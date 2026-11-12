<script lang="ts">
  /**
   * 本地模型配置：首次启动向导的第二步，也可以从设置页随时打开。
   *
   * 设计约束：
   * - **默认不强制下载**：所有引擎（Anime Whisper / Qwen3-ASR / OmniVoice）都可勾选，
   *   也可以「稍后再说」。系统语音和已有模型不受影响。
   * - **一键配置 = 顺序下载所选**：转写引擎走 `/api/engines/{key}/download` 的单槽任务，
   *   OmniVoice 走自己的后台下载线程；两者都轮询状态，进度只展示当前这一项。
   * - 已安装的项不重复下载；OmniVoice 依赖缺失时（打包漏了 omnivoice）会禁用并提示。
   */
  import { formatBytes } from '../lib/time';
  import {
    app,
    loadSettings,
    loadTtsVoices,
    refreshConfig,
  } from '../lib/store.svelte';
  import { api } from '../lib/api';

  let { ondone }: { ondone: () => void } = $props();

  interface SetupItem {
    key: string;
    kind: 'asr' | 'tts';
    label: string;
    description: string;
    notes: string;
    sizeLabel: string;
    approxBytes: number;
    installed: boolean;
    sizeBytes: number;
    packageMissing: boolean;
    recommended: boolean;
  }

  let items = $state<SetupItem[]>([]);
  let selected = $state<Record<string, boolean>>({});
  let loading = $state(true);
  let loaded = false;
  let loadError = $state('');
  let running = $state(false);
  let activeKey = $state('');
  let percent = $state(0);
  let stage = $state('');
  let error = $state('');

  const selectedItems = $derived(
    items.filter((item) => selected[item.key] && !item.installed && !item.packageMissing),
  );
  const selectedCount = $derived(selectedItems.length);
  const selectedBytes = $derived(selectedItems.reduce((sum, item) => sum + item.approxBytes, 0));
  const activeItem = $derived(items.find((item) => item.key === activeKey) ?? null);

  $effect(() => {
    if (!app.connected || loaded) return;
    loaded = true;
    void load();
  });

  // 内核一直没连上时别让用户对着空卡片：20 秒后给可重试的错误。
  $effect(() => {
    if (app.connected) return;
    const timer = setTimeout(() => {
      if (!app.connected && loading) {
        loading = false;
        loadError = '转写内核还没有连接上。请检查日志，或稍后重试。';
      }
    }, 20_000);
    return () => clearTimeout(timer);
  });

  async function load() {
    loading = true;
    loadError = '';
    try {
      const [config, voices] = await Promise.all([api.getSettings(), api.ttsVoices()]);
      const next: SetupItem[] = config.engines.map((engine) => ({
        key: engine.key,
        kind: 'asr' as const,
        label: engine.label,
        description: engine.description,
        notes: engine.notes,
        sizeLabel: engine.approx_label,
        approxBytes: engine.approx_bytes,
        installed: engine.installed,
        sizeBytes: engine.size_bytes,
        packageMissing: false,
        recommended: engine.key === 'whisper',
      }));
      const ttsEngine = voices.engine;
      next.push({
        key: 'omnivoice',
        kind: 'tts',
        label: 'OmniVoice 音色克隆',
        description:
          '从视频里的任意一句切出 3–10 秒参考音频，用本地零样本克隆按角色声线朗读日文。',
        notes: '可选功能；首次合成才加载权重，空闲 5 分钟自动卸载。不下载也能用系统语音。',
        sizeLabel: ttsEngine.approx_label || '约 3.3 GB',
        approxBytes: 3.3 * 1024 ** 3,
        installed: ttsEngine.installed,
        sizeBytes: 0,
        packageMissing: !ttsEngine.package_installed,
        recommended: false,
      });
      items = next;
      selected = Object.fromEntries(
        next.map((item) => [item.key, item.recommended && !item.installed && !item.packageMissing]),
      );
    } catch (err) {
      loadError = `读取模型配置失败：${(err as Error).message}`;
    } finally {
      loading = false;
    }
  }

  function toggle(key: string) {
    if (running) return;
    selected[key] = !selected[key];
  }

  function sizeText(item: SetupItem): string {
    if (item.installed) return item.sizeBytes > 0 ? formatBytes(item.sizeBytes) : '已安装';
    return item.sizeLabel;
  }

  async function waitAsrDownload(key: string) {
    const job = await api.downloadEngine(key);
    for (;;) {
      const snap = await api.getJob(job.id);
      percent = Math.max(percent, snap.percent ?? 0);
      if (snap.stage) stage = snap.stage;
      if (snap.status === 'done') {
        percent = 100;
        return;
      }
      if (snap.status === 'error') throw new Error(snap.error || '下载失败');
      if (snap.status === 'cancelled') throw new Error('下载已取消');
      await new Promise((resolve) => setTimeout(resolve, 700));
    }
  }

  async function waitTtsDownload() {
    const first = await api.downloadTtsModel();
    percent = Math.max(percent, first.percent ?? 0);
    if (first.stage) stage = first.stage;
    for (;;) {
      const status = await api.ttsModelStatus();
      percent = Math.max(percent, status.percent ?? 0);
      if (status.stage) stage = status.stage;
      if (status.status === 'done' || status.installed) {
        percent = 100;
        return;
      }
      if (status.status === 'error') throw new Error(status.error || '下载失败');
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }

  async function run() {
    if (running || loading) return;
    const todo = [...selectedItems];
    if (!todo.length) {
      ondone();
      return;
    }
    running = true;
    error = '';
    try {
      for (const item of todo) {
        activeKey = item.key;
        percent = 0;
        stage = item.kind === 'tts' ? '准备下载 OmniVoice…' : '准备下载模型…';
        if (item.kind === 'tts') await waitTtsDownload();
        else await waitAsrDownload(item.key);
        item.installed = true;
      }
      stage = '全部完成';
      await Promise.allSettled([refreshConfig(), loadSettings(true), loadTtsVoices()]);
      ondone();
    } catch (err) {
      error = `${activeItem?.label ?? '模型'} 下载失败：${(err as Error).message}`;
    } finally {
      running = false;
      activeKey = '';
    }
  }
</script>

<div class="setup-overlay">
  <div class="setup-card">
    <div class="logo">KikuSub</div>
    <h1>配置本地模型</h1>
    <p class="lead">
      按需勾选要下载的模型。转写引擎负责识别人声；OmniVoice 只用于克隆音色。
      不选任何一项也能启动——系统语音（Kyoko 等）和已安装的模型照常可用。
    </p>

    {#if loading}
      <div class="loading">
        <span class="spinner"></span>
        正在读取模型状态…
      </div>
    {:else if loadError}
      <div class="error-box">
        读取失败：{loadError}
        <button class="btn tiny" onclick={load}>重试</button>
      </div>
    {:else}
      <div class="engine-list">
        {#each items as item (item.key)}
          <label
            class="engine-row"
            class:disabled={item.installed || item.packageMissing}
            class:active={running && activeKey === item.key}
          >
            <input
              type="checkbox"
              checked={selected[item.key] ?? false}
              disabled={running || item.installed || item.packageMissing}
              onchange={() => toggle(item.key)}
            />
            <div class="engine-main">
              <div class="engine-title">
                <b>{item.label}</b>
                {#if item.recommended && !item.installed}
                  <span class="tag rec">推荐</span>
                {/if}
                {#if item.key === 'omnivoice'}
                  <span class="tag opt">可选</span>
                {/if}
                {#if item.installed}
                  <span class="tag ok">已安装</span>
                {/if}
                {#if item.packageMissing}
                  <span class="tag bad">依赖缺失</span>
                {/if}
              </div>
              <div class="engine-desc">{item.description}</div>
              {#if item.notes}
                <div class="engine-note">{item.notes}</div>
              {/if}
            </div>
            <div class="engine-size">{sizeText(item)}</div>
          </label>
        {/each}
      </div>
    {/if}

    {#if running}
      <div class="download">
        <div class="download-top">
          <span>{activeItem?.label ?? '准备中'} · {stage}</span>
          <b>{percent}%</b>
        </div>
        <div class="bar"><div style="width:{percent}%"></div></div>
      </div>
    {/if}

    {#if error}
      <div class="error-box">{error}</div>
    {/if}

    <div class="summary">
      {#if selectedCount}
        已选 {selectedCount} 项 · {formatBytes(selectedBytes)}
      {:else}
        未选择任何要下载的模型
      {/if}
    </div>

    <div class="actions">
      <button class="btn ghost" onclick={ondone} disabled={running}>稍后再说</button>
      <button
        class="btn primary"
        onclick={run}
        disabled={running || loading || Boolean(loadError) || !app.connected}
      >
        {running ? '正在配置…' : selectedCount ? '一键配置所选' : '完成'}
      </button>
    </div>

    <div class="fine">
      模型只在本机使用，不会上传。之后可在「设置 → 引擎与模型」里重新配置。
    </div>
  </div>
</div>

<style>
  .setup-overlay {
    position: fixed;
    inset: 0;
    z-index: 320;
    display: grid;
    place-items: center;
    padding: var(--sp-8);
    background: var(--bg-content);
    -webkit-app-region: drag;
    overflow-y: auto;
  }
  .setup-card {
    width: min(660px, 100%);
    background: var(--bg-content);
    border: 1px solid var(--separator);
    border-radius: 12px;
    box-shadow: var(--shadow-pop);
    padding: 26px 28px var(--sp-5);
    -webkit-app-region: no-drag;
  }
  .logo {
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.08em;
    color: var(--accent);
    text-transform: uppercase;
  }
  h1 {
    margin: var(--sp-2) 0 7px;
    font-size: 21px;
    font-weight: 600;
    letter-spacing: -0.02em;
  }
  .lead {
    margin: 0 0 var(--sp-4);
    font-size: 12.5px;
    line-height: 1.6;
    color: var(--text-2);
  }
  .loading {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 22px var(--sp-1);
    font-size: 12.5px;
    color: var(--text-3);
  }
  .spinner {
    width: 13px;
    height: 13px;
    border-radius: 50%;
    border: 2px solid var(--separator);
    border-top-color: var(--accent);
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  .engine-list {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .engine-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 11px var(--sp-3);
    border: 1px solid var(--separator);
    border-radius: 8px;
    background: var(--fill);
    cursor: pointer;
    transition:
      border-color 120ms ease,
      background 120ms ease;
  }
  .engine-row:hover {
    border-color: var(--accent-line);
  }
  .engine-row.active {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .engine-row.disabled {
    cursor: default;
    opacity: 0.72;
  }
  .engine-row input {
    margin-top: 2px;
    width: 14px;
    height: 14px;
    accent-color: var(--control-on);
    flex: 0 0 auto;
  }
  .engine-main {
    flex: 1;
    min-width: 0;
  }
  .engine-title {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .engine-title b {
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
  }
  .tag {
    height: 17px;
    padding: 0 5px;
    border-radius: 3px;
    font-size: 10.5px;
    line-height: 17px;
    color: var(--text-3);
    background: var(--fill-strong);
  }
  .tag.rec {
    color: var(--accent);
    background: var(--accent-soft);
  }
  .tag.ok {
    color: var(--success);
    background: var(--success-soft);
  }
  .tag.bad {
    color: var(--danger);
    background: var(--danger-soft);
  }
  .engine-desc {
    margin-top: 3px;
    font-size: 12px;
    line-height: 1.55;
    color: var(--text-2);
  }
  .engine-note {
    margin-top: 3px;
    font-size: 11px;
    line-height: 1.5;
    color: var(--text-3);
  }
  .engine-size {
    flex: 0 0 auto;
    padding-left: var(--sp-2);
    font-size: 11.5px;
    color: var(--text-3);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .download {
    margin-top: var(--sp-3);
  }
  .download-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    font-size: 11.5px;
    color: var(--text-3);
    margin-bottom: 5px;
  }
  .download-top b {
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }
  .bar {
    height: 4px;
    border-radius: 2px;
    background: var(--fill-strong);
    overflow: hidden;
  }
  .bar > div {
    height: 100%;
    background: var(--accent);
    transition: width 240ms ease;
  }
  .error-box {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    margin-top: var(--sp-3);
    padding: var(--sp-2) 10px;
    border-radius: 8px;
    font-size: 12px;
    line-height: 1.5;
    color: var(--danger);
    background: var(--danger-soft);
  }
  .summary {
    margin-top: 14px;
    font-size: 12px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--sp-2);
    margin-top: var(--sp-3);
  }
  .actions .btn {
    height: 30px;
    padding: 0 14px;
  }
  .actions .btn.ghost {
    color: var(--text-2);
  }
  .fine {
    margin-top: var(--sp-3);
    font-size: 11px;
    line-height: 1.5;
    color: var(--text-3);
    text-align: right;
  }
</style>
