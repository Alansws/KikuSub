<script lang="ts">
  /**
   * 设置：引擎与模型、运行环境、日志诊断、工作流偏好。
   *
   * 引擎卡片完全由服务端 `core/engines.py` 的注册表驱动：以后加引擎只改后端，
   * 这里自动多一张卡（语种、体积、安装状态、下载按钮都不用在 UI 里写死）。
   */
  import Icon from '../components/Icon.svelte';
  import { api, logEvent, type EngineInfo } from '../lib/api';
  import {
    app,
    downloadEngine,
    loadSettings,
    setTheme,
    settings,
    toast,
    toggleEngine,
    updateSettings,
  } from '../lib/store.svelte';
  import { formatBytes } from '../lib/time';

  type Diag = Awaited<ReturnType<typeof api.diagnostics>>;

  let diag = $state<Diag | null>(null);
  let diagLoading = $state(false);
  let copying = $state('');
  let wavePreset = $state(Number(localStorage.getItem('kikusub.waveHeight') || 148));
  let changingModels = $state(false);
  let changingExport = $state(false);
  let cleaningLogs = $state(false);
  let wasConnected = false;

  // 内核重启（改模型目录 / 崩溃恢复）后重新拉设置，否则路径与安装状态还是旧的。
  $effect(() => {
    if (!app.connected) {
      wasConnected = false;
      return;
    }
    if (wasConnected) return;
    wasConnected = true;
    void loadSettings(true);
    void loadDiag();
  });

  const engines = $derived(settings.data?.engines ?? []);
  const enabledCount = $derived(engines.filter((e) => e.enabled).length);
  const installedCount = $derived(engines.filter((e) => e.installed).length);
  const autoProxy = $derived(settings.data?.settings.auto_proxy ?? true);
  const exportDir = $derived(
    settings.data?.paths.export_dir || diag?.paths.export_dir || app.config?.export_dir || '',
  );
  const exportDirIsCustom = $derived(Boolean(settings.data?.settings.export_dir));
  const downloading = $derived(settings.download);

  async function loadDiag() {
    diagLoading = true;
    try {
      diag = await api.diagnostics(300);
    } catch (err) {
      toast(`诊断信息读取失败：${(err as Error).message}`, 'warn');
    } finally {
      diagLoading = false;
    }
  }

  async function copy(text: string, tag: string) {
    try {
      if (window.kikusub.writeClipboard) {
        await window.kikusub.writeClipboard(text);
      } else {
        await navigator.clipboard.writeText(text);
      }
      copying = tag;
      setTimeout(() => (copying = ''), 1600);
      toast('已复制到剪贴板');
    } catch (err) {
      toast(`复制失败：${(err as Error).message}`, 'error');
    }
  }

  async function copyLogs() {
    try {
      const data = await api.diagnosticsLog(400);
      if (!data.text) {
        toast('日志还是空的：先跑一次转写再试', 'warn');
        return;
      }
      await copy(data.text, 'log');
    } catch (err) {
      toast((err as Error).message, 'error');
    }
  }

  async function copyDiagnostics() {
    try {
      const payload = diag ?? (await api.diagnostics(300));
      const summary = {
      runtime: payload.runtime,
      paths: payload.paths,
      ffmpeg: payload.ffmpeg,
      settings: payload.settings,
      engines: payload.engines.map((e) => ({
        key: e.key,
        installed: e.installed,
        enabled: e.enabled,
        size_bytes: e.size_bytes,
      })),
      recent_problems: payload.recent_problems,
      log_tail: payload.log_tail,
    };
      await copy(JSON.stringify(summary, null, 2), 'diag');
    } catch (err) {
      toast(`诊断信息读取失败：${(err as Error).message}`, 'error');
    }
  }

  function openPath(path: string) {
    if (!path) return;
    void window.kikusub.openPath(path);
  }

  function reveal(path: string) {
    if (path) window.kikusub.revealInFinder(path);
  }

  function statusText(engine: EngineInfo) {
    if (engine.installed) return `已安装 · ${formatBytes(engine.size_bytes)}`;
    return `未下载 · ${engine.approx_label}`;
  }

  function downloadState(key: string) {
    return downloading && downloading.key === key ? downloading : null;
  }

  async function onDownload(engine: EngineInfo) {
    await downloadEngine(engine.key);
  }

  async function onToggle(engine: EngineInfo) {
    await toggleEngine(engine.key, !engine.enabled);
  }

  async function onAutoProxy() {
    await updateSettings({ auto_proxy: !autoProxy });
  }

  async function cleanOldLogs() {
    if (cleaningLogs) return;
    if (
      !window.confirm(
        '清理所有轮转日志备份（kikusub.log.1 / main.log.1 等）。\n\n正在写入的日志会保留，只删除过期或超量的旧文件。',
      )
    ) {
      return;
    }
    cleaningLogs = true;
    try {
      const result = await api.cleanLogs();
      if (result.removed > 0) {
        toast(`已清理 ${result.removed} 个旧日志，释放 ${formatBytes(result.freed)}`);
      } else {
        toast('没有需要清理的旧日志');
      }
      logEvent('info', 'logs-clean', `removed=${result.removed} freed=${result.freed}`);
      await loadDiag();
    } catch (err) {
      toast(`清理失败：${(err as Error).message}`, 'error');
    } finally {
      cleaningLogs = false;
    }
  }

  async function changeExportDir() {
    if (changingExport) return;
    let picked = '';
    try {
      picked = (await window.kikusub.pickDirectory({
        title: '选择字幕默认导出文件夹',
        defaultPath: exportDir,
      })) || '';
    } catch (err) {
      toast((err as Error).message, 'error');
      return;
    }
    if (!picked) return;
    const current = (exportDir || '').replace(/\/+$/, '');
    if (picked.replace(/\/+$/, '') === current) return;
    changingExport = true;
    try {
      await updateSettings({ export_dir: picked });
      logEvent('info', 'export-dir-change', picked);
      await loadDiag();
    } finally {
      changingExport = false;
    }
  }

  async function resetExportDir() {
    if (changingExport) return;
    if (!window.confirm('恢复为默认导出文件夹（运行数据目录）？\n\n已经导出的字幕不会被移动或删除。')) {
      return;
    }
    changingExport = true;
    try {
      await updateSettings({ export_dir: '' });
      logEvent('info', 'export-dir-reset', '');
      await loadDiag();
    } finally {
      changingExport = false;
    }
  }

  async function changeModelsDir() {
    if (changingModels) return;
    if (app.job?.status === 'running') {
      toast('任务进行中，先等它结束或打断后再切换模型目录', 'warn');
      return;
    }
    let picked = '';
    try {
      picked = (await window.kikusub.pickModelsDir()) || '';
    } catch (err) {
      toast((err as Error).message, 'error');
      return;
    }
    if (!picked) return;
    const current = (diag?.paths.models_dir ?? settings.data?.paths.models_dir ?? '').replace(/\/+$/, '');
    if (picked.replace(/\/+$/, '') === current) return;
    const sessionWarning = app.media
      ? '\n\n注意：切换会重启内核，当前会话的媒体、字幕与撤回记录会清空；请先导出 SRT。'
      : '';
    const ok = window.confirm(
      `将模型目录切换到：\n${picked}\n\n` +
        '已下载的模型不会自动搬迁，需要重新下载或手动复制。' +
        sessionWarning +
        '\n\n确定继续吗？',
    );
    if (!ok) return;

    // 先挂好「内核重启完成」的监听，再触发重启，避免 ready 比调用返回更早。
    const ready = new Promise<void>((resolve) => {
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        off();
        resolve();
      };
      const off = window.kikusub.onSidecarReady(() => finish());
      setTimeout(finish, 30000);
    });

    changingModels = true;
    try {
      await window.kikusub.setModelsDir(picked);
      toast('模型目录已切换，正在重启内核…');
      logEvent('info', 'models-dir-change', picked);
      await ready;
      await loadSettings(true);
      await loadDiag();
      toast('内核已重启，新的模型目录已生效');
    } catch (err) {
      toast(`切换失败：${(err as Error).message}`, 'error');
      logEvent('error', 'models-dir-change-failed', picked, String(err));
    } finally {
      changingModels = false;
    }
  }
</script>

<div class="settings">
  <div class="head">
    <div>
      <h1>设置</h1>
      <p class="sub">引擎与模型、运行环境、日志诊断与工作流偏好。</p>
    </div>
    <div class="head-meta">
      <span>{installedCount} / {engines.length} 个引擎已就绪</span>
      <span>·</span>
      <span>{enabledCount} 个已启用</span>
    </div>
  </div>

  <!-- 引擎 -->
  <section class="sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">引擎与模型</div>
        <div class="sec-desc">
          模型按需下载。启用的引擎会出现在顶部切换栏；第一次转写前至少启用一个。
        </div>
      </div>
      <button class="btn ghost" onclick={() => loadSettings(true)} title="重新检测安装状态">
        <Icon name="undo" size={11} />重新检测
      </button>
    </div>

    {#if settings.loading && !settings.data}
      <div class="loading">正在读取引擎配置…</div>
    {:else if settings.error}
      <div class="error-box">
        <Icon name="warn" size={13} />
        读取失败：{settings.error}
        <button class="btn tiny" onclick={() => loadSettings(true)}>重试</button>
      </div>
    {:else}
      <div class="engines">
        {#each engines as engine (engine.key)}
          {@const dl = downloadState(engine.key)}
          <div class="engine" class:off={!engine.enabled}>
            <div class="eng-top">
              <div class="eng-name">
                <span class="dot" class:ready={engine.installed}></span>
                <b>{engine.label}</b>
                <span class="eng-purpose">{engine.purpose}</span>
              </div>
              <label class="enable" title={engine.enabled ? '在顶部切换栏中隐藏' : '显示在顶部切换栏'}>
                <span>{engine.enabled ? '已启用' : '已停用'}</span>
                <button
                  class="switch"
                  class:on={engine.enabled}
                  role="switch"
                  aria-checked={engine.enabled}
                  onclick={() => onToggle(engine)}
                >
                  <span class="knob"></span>
                </button>
              </label>
            </div>

            <p class="eng-desc">{engine.description}</p>

            <div class="meta">
              <span class="pill">
                <Icon name="wave" size={10} />{engine.languages.join(' / ')}
              </span>
              <span class="pill">{engine.installed ? formatBytes(engine.size_bytes) : engine.approx_label}</span>
              <span class="pill">建议内存 {engine.min_ram_gb} GB</span>
              <span class="pill mono" title={engine.hf_repo}>{engine.hf_repo.split('/').pop()}</span>
              <span class="status" class:ok={engine.installed} class:missing={!engine.installed}>
                {statusText(engine)}
              </span>
            </div>

            {#if engine.notes}
              <div class="notes">{engine.notes}</div>
            {/if}

            <div class="eng-actions">
              {#if engine.installed}
                <button class="btn" onclick={() => openPath(engine.model_dir)}>
                  <Icon name="folder" size={11} />打开模型目录
                </button>
                <button
                  class="btn ghost"
                  onclick={() => onDownload(engine)}
                  disabled={Boolean(downloading && downloading.status === 'running')}
                  title="检查权重是否完整，缺文件时自动补齐"
                >
                  校验 / 补齐
                </button>
              {:else}
                <button
                  class="btn primary"
                  onclick={() => onDownload(engine)}
                  disabled={!engine.downloadable || Boolean(downloading && downloading.status === 'running')}
                >
                  <Icon name="export" size={11} />
                  {engine.downloadable ? '下载模型' : '需手动安装'}
                </button>
              {/if}
              <button class="btn ghost" onclick={() => reveal(engine.model_dir)}>
                在访达中显示
              </button>
              <span class="path mono" title={engine.model_dir}>{engine.model_dir}</span>
            </div>

            {#if dl}
              <div class="dl">
                <div class="dl-top">
                  <span>{dl.stage}</span>
                  <b>{dl.percent}%</b>
                </div>
                <div class="bar" class:error={dl.status === 'error'}>
                  <i style="width:{Math.max(2, dl.percent)}%"></i>
                </div>
              </div>
            {/if}
          </div>
        {/each}
      </div>

      {#if enabledCount === 0}
        <div class="warn-box">
          <Icon name="warn" size={13} />
          当前没有启用任何引擎——转写页会无法开始。至少打开一个开关。
        </div>
      {/if}
      <p class="footnote">
        增加新引擎只需在后端 <code>core/engines.py</code> 注册一条；这张列表会自动出现，
        不用改界面。当前模型目录：<span class="mono">{settings.data?.paths.models_dir ?? '—'}</span>
        （可在「运行环境」里更改）。
      </p>
    {/if}
  </section>

  <!-- 运行环境 -->
  <section class="sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">运行环境</div>
        <div class="sec-desc">
          字幕默认写到「导出文件夹」，可改成你常用的位置；日志、质检与代理缓存留在运行数据目录。
        </div>
      </div>
    </div>
    <div class="grid">
      <div class="kv"><span>加速设备</span><b>{diag?.runtime.device ?? app.config?.device ?? '—'}</b></div>
      <div class="kv"><span>应用版本</span><b>v{diag?.runtime.version ?? app.config?.version ?? '—'}</b></div>
      <div class="kv"><span>Python</span><b>{diag?.runtime.python ?? '—'}</b></div>
      <div class="kv"><span>打包运行</span><b>{diag?.runtime.frozen ? '是' : '否（源码模式）'}</b></div>
      <div class="kv wide">
        <span>ffmpeg</span>
        <b class="mono" title={diag?.ffmpeg.version ?? ''}>
          {diag?.ffmpeg.path || '未找到（导入会失败）'}
        </b>
      </div>
      {#if diag}
        <div class="kv wide">
          <span>导出文件夹</span>
          <b class="mono" title={exportDir}>{exportDir}</b>
          <button class="btn tiny ghost" onclick={() => openPath(exportDir)}>打开</button>
          <button class="btn tiny" onclick={changeExportDir} disabled={changingExport}>
            {changingExport ? '切换中…' : '更改…'}
          </button>
          {#if exportDirIsCustom}
            <button class="btn tiny ghost" onclick={resetExportDir} disabled={changingExport}>
              恢复默认
            </button>
          {/if}
        </div>
        <div class="kv wide">
          <span>运行数据目录</span>
          <b class="mono">{diag.paths.output_dir}</b>
          <button class="btn tiny ghost" onclick={() => openPath(diag!.paths.output_dir)}>打开</button>
        </div>
        <div class="kv wide">
          <span>模型目录</span>
          <b class="mono" title={diag.paths.models_dir}>{diag.paths.models_dir}</b>
          <button class="btn tiny ghost" onclick={changeModelsDir} disabled={changingModels}>
            {changingModels ? '切换中…' : '更改…'}
          </button>
          <button class="btn tiny ghost" onclick={() => openPath(diag!.paths.models_dir)}>打开</button>
        </div>
        <div class="kv wide">
          <span>设置文件</span>
          <b class="mono">{diag.paths.settings_path}</b>
          <button class="btn tiny ghost" onclick={() => reveal(diag!.paths.settings_path)}>显示</button>
        </div>
      {/if}
    </div>
  </section>

  <!-- 日志与诊断 -->
  <section class="sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">日志与诊断</div>
        <div class="sec-desc">
          遇到问题先点「复制诊断信息」，它包含版本、目录、引擎状态与最近日志，发给我就能定位。
        </div>
      </div>
      <button class="btn ghost" onclick={loadDiag} disabled={diagLoading}>
        <Icon name="undo" size={11} />{diagLoading ? '读取中…' : '刷新'}
      </button>
    </div>

    <div class="log-row">
      <span class="mono log-path" title={diag?.log_path ?? ''}>{diag?.log_path ?? '—'}</span>
      <button class="btn" onclick={() => diag && openPath(diag.paths.log_dir)}>
        <Icon name="folder" size={11} />打开日志目录
      </button>
      <button class="btn" onclick={copyLogs}>
        <Icon name="doc" size={11} />{copying === 'log' ? '已复制' : '复制最近日志'}
      </button>
      <button class="btn" onclick={cleanOldLogs} disabled={cleaningLogs}>
        <Icon name="undo" size={11} />{cleaningLogs ? '清理中…' : '清理旧日志'}
      </button>
      <button class="btn primary" onclick={copyDiagnostics}>
        <Icon name="export" size={11} />{copying === 'diag' ? '已复制' : '复制诊断信息'}
      </button>
    </div>

    {#if diag}
      <div class="log-meta">
        <span>日志：{diag.log_exists ? '已写入' : '尚未生成'}</span>
        <span>最近问题：{diag.recent_problems.length} 条</span>
        <span>模型目录：{diag.paths.models_dir}</span>
      </div>
      {#if diag.recent_problems.length}
        <pre class="log-tail">{diag.recent_problems.join('\n')}</pre>
      {:else}
        <div class="empty-log">最近日志里没有 ERROR / WARNING。</div>
      {/if}
      <details class="tail">
        <summary>查看最近日志原文（{diag.log_tail.split('\n').filter(Boolean).length} 行）</summary>
        <pre class="log-tail">{diag.log_tail || '（空）'}</pre>
      </details>
    {/if}
  </section>

  <!-- 工作流 -->
  <section class="sec">
    <div class="sec-head">
      <div>
        <div class="sec-title">工作流与外观</div>
        <div class="sec-desc">这些偏好只影响当前这台机器。</div>
      </div>
    </div>

    <div class="pref">
      <div>
        <b>导入 MKV / HEVC 时自动压制 480p 监看代理</b>
        <span>关闭后不会后台转码，但 Chromium 可能放不出画面（可手动在转写/报告里处理）。</span>
      </div>
      <button
        class="switch"
        class:on={autoProxy}
        role="switch"
        aria-checked={autoProxy}
        onclick={onAutoProxy}
      >
        <span class="knob"></span>
      </button>
    </div>

    <div class="pref">
      <div>
        <b>外观</b>
        <span>跟随你的阅读习惯；工具栏月亮按钮也可以快速切换。</span>
      </div>
      <div class="seg">
        <button class:on={app.theme === 'light'} onclick={() => setTheme('light')}>浅色</button>
        <button class:on={app.theme === 'dark'} onclick={() => setTheme('dark')}>深色</button>
      </div>
    </div>

    <div class="pref">
      <div>
        <b>波形高度</b>
        <span>核对台波形底部可以直接拖动调整；这里给出三个预设。</span>
      </div>
      <div class="seg">
        {#each [120, 148, 200] as h (h)}
          <button
            class:on={wavePreset === h}
            onclick={() => {
              wavePreset = h;
              localStorage.setItem('kikusub.waveHeight', String(h));
              toast('已保存，回到核对台生效');
            }}>{h}px</button>
        {/each}
      </div>
    </div>
  </section>

  <div class="about">
    KikuSub · 本地优先的日语字幕工作台。所有音视频与模型都在本机处理，不上传。
  </div>
</div>

<style>
  .settings {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 22px 28px 40px;
  }
  .settings > * {
    max-width: 940px;
  }

  .head {
    display: flex;
    align-items: flex-start;
    gap: 16px;
    margin-bottom: 20px;
  }
  .head h1 {
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.02em;
    margin: 0 0 4px;
  }
  .sub {
    margin: 0;
    font-size: 12.5px;
    color: var(--text-2);
  }
  .head-meta {
    margin-left: auto;
    display: flex;
    gap: 6px;
    font-size: 11px;
    color: var(--text-3);
    padding-top: 4px;
    font-variant-numeric: tabular-nums;
  }

  .sec {
    border-top: 1px solid var(--separator-soft);
    padding: 18px 0 6px;
  }
  .sec-head {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    margin-bottom: 12px;
  }
  .sec-title {
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 3px;
  }
  .sec-desc {
    font-size: 11.5px;
    color: var(--text-3);
    line-height: 1.5;
    max-width: 640px;
  }
  .sec-head > .btn {
    margin-left: auto;
    flex: 0 0 auto;
  }

  .engines {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .engine {
    border: 1px solid var(--separator-soft);
    border-radius: 10px;
    padding: 13px 15px 12px;
    background: var(--bg-content);
    transition: opacity 160ms var(--ease), border-color 160ms var(--ease);
  }
  .engine.off {
    opacity: 0.72;
  }
  .eng-top {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .eng-name {
    display: flex;
    align-items: baseline;
    gap: 8px;
    min-width: 0;
  }
  .eng-name b {
    font-size: 13.5px;
    font-weight: 600;
  }
  .eng-purpose {
    font-size: 11px;
    color: var(--text-3);
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--text-3);
    flex: 0 0 7px;
  }
  .dot.ready {
    background: #30d158;
  }

  .enable {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 11px;
    color: var(--text-3);
    flex: 0 0 auto;
  }

  .eng-desc {
    margin: 7px 0 8px;
    font-size: 12.5px;
    color: var(--text-2);
    line-height: 1.5;
  }

  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    align-items: center;
  }
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    height: 19px;
    padding: 0 7px;
    border-radius: 9px;
    background: var(--fill);
    color: var(--text-2);
    font-size: 10.5px;
    font-variant-numeric: tabular-nums;
  }
  .pill.mono {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    max-width: 260px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .status {
    margin-left: auto;
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }
  .status.ok {
    color: #1c7c36;
  }
  .status.missing {
    color: #b26a00;
  }
  html[data-theme='dark'] .status.ok {
    color: #4cd964;
  }
  html[data-theme='dark'] .status.missing {
    color: #ffb340;
  }

  .notes {
    margin-top: 7px;
    font-size: 11px;
    color: var(--text-3);
    line-height: 1.5;
  }

  .eng-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 10px;
  }
  .path {
    font-size: 10.5px;
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  .dl {
    margin-top: 9px;
  }
  .dl-top {
    display: flex;
    justify-content: space-between;
    font-size: 10.5px;
    color: var(--text-2);
    margin-bottom: 4px;
    font-variant-numeric: tabular-nums;
  }
  .bar {
    height: 4px;
    border-radius: 2px;
    background: var(--fill-strong);
    overflow: hidden;
  }
  .bar i {
    display: block;
    height: 100%;
    background: var(--accent);
    transition: width 300ms var(--ease);
  }
  .bar.error i {
    background: #ff453a;
  }

  .switch {
    appearance: none;
    width: 30px;
    height: 18px;
    border-radius: 9px;
    border: 0;
    background: var(--fill-strong);
    position: relative;
    padding: 0;
    transition: background 160ms var(--ease);
    flex: 0 0 30px;
  }
  .switch .knob {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
    transition: transform 160ms var(--ease);
  }
  .switch.on {
    background: var(--accent);
  }
  .switch.on .knob {
    transform: translateX(12px);
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0 22px;
    border: 1px solid var(--separator-soft);
    border-radius: 10px;
    padding: 9px 14px;
  }
  .kv {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 6px 0;
    border-bottom: 1px solid var(--separator-soft);
    font-size: 12px;
    min-width: 0;
  }
  .kv.wide {
    grid-column: 1 / -1;
  }
  .kv > span {
    color: var(--text-3);
    flex: 0 0 76px;
  }
  .kv > b {
    font-weight: 500;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .kv > b.mono {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 10.5px;
  }
  .kv .btn {
    margin-left: auto;
    flex: 0 0 auto;
  }

  .log-row {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .log-path {
    flex: 1 1 320px;
    min-width: 0;
    font-size: 10.5px;
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .log-meta {
    display: flex;
    gap: 14px;
    font-size: 10.5px;
    color: var(--text-3);
    margin-top: 9px;
    flex-wrap: wrap;
  }
  .log-tail {
    margin: 8px 0 0;
    max-height: 180px;
    overflow: auto;
    background: var(--fill);
    border-radius: 8px;
    padding: 9px 11px;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 10.5px;
    line-height: 1.55;
    color: var(--text-2);
    user-select: text;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .empty-log {
    margin-top: 9px;
    font-size: 11px;
    color: var(--text-3);
  }
  .tail {
    margin-top: 8px;
  }
  .tail summary {
    font-size: 11px;
    color: var(--text-3);
    cursor: default;
    list-style: none;
  }
  .tail summary::-webkit-details-marker {
    display: none;
  }
  .tail summary:hover {
    color: var(--text-2);
  }

  .pref {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 11px 0;
    border-bottom: 1px solid var(--separator-soft);
  }
  .pref:last-child {
    border-bottom: 0;
  }
  .pref > div:first-child {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .pref b {
    font-size: 12.5px;
    font-weight: 500;
  }
  .pref span {
    font-size: 11px;
    color: var(--text-3);
    line-height: 1.45;
  }

  .warn-box,
  .error-box {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11.5px;
    color: #b26a00;
    background: rgba(255, 159, 10, 0.12);
    border-radius: 8px;
    padding: 8px 10px;
    margin-top: 10px;
  }
  .error-box {
    color: #c0392b;
    background: rgba(255, 69, 58, 0.1);
  }
  .error-box .btn {
    margin-left: auto;
  }
  .loading {
    font-size: 12px;
    color: var(--text-3);
    padding: 16px 2px;
  }
  .footnote {
    font-size: 10.5px;
    color: var(--text-3);
    line-height: 1.6;
    margin: 10px 0 0;
  }
  code {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    background: var(--fill);
    border-radius: 4px;
    padding: 0 4px;
  }
  .about {
    margin-top: 26px;
    padding-top: 14px;
    border-top: 1px solid var(--separator-soft);
    font-size: 10.5px;
    color: var(--text-3);
    text-align: center;
  }

  .seg {
    display: inline-flex;
    background: var(--fill);
    border-radius: 6px;
    padding: 1px;
    flex: 0 0 auto;
  }
  .seg button {
    appearance: none;
    border: 0;
    background: transparent;
    font: inherit;
    font-size: 11px;
    height: 22px;
    padding: 0 9px;
    border-radius: 5px;
    color: var(--text-2);
  }
  .seg button.on {
    background: var(--bg-content);
    color: var(--text);
    box-shadow: 0 0.5px 1.5px rgba(0, 0, 0, 0.12);
  }
  .tiny {
    height: 20px;
    font-size: 10.5px;
    padding: 0 6px;
  }
</style>
