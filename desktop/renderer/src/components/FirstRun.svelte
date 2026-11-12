<script lang="ts">
  /**
   * 首次启动向导。
   *
   * 真实用户拿到的是一个空目录：models/ 不存在、settings.json 不存在。模型有
   * 3–4 GB，不能默认替用户决定放哪儿，所以第一件事是选模型目录。选完后主进程
   * 才拉起 sidecar，并把 KIKUSUB_MODELS_DIR 指过去——设置页、下载任务、引擎
   * 安装检测都自然沿用同一个目录。
   */
  import Icon from './Icon.svelte';
  import EngineSetup from './EngineSetup.svelte';

  let {
    defaultDir,
    currentDir,
    dataDir,
    ffmpeg,
    ondone,
  }: {
    defaultDir: string;
    currentDir: string;
    dataDir: string;
    ffmpeg: string;
    ondone: () => void;
  } = $props();

  let picked = $state('');
  const chosen = $derived(picked || currentDir || defaultDir);
  let busy = $state(false);
  let error = $state('');
  /** 第二步：选完目录、主进程开始拉 sidecar 后，再让用户勾选要下载的模型。 */
  let step = $state<'dir' | 'engines'>('dir');

  async function pick() {
    error = '';
    try {
      const dir = await window.kikusub.pickModelsDir();
      if (dir) picked = dir;
    } catch (err) {
      error = (err as Error).message;
    }
  }

  async function start() {
    if (busy) return;
    error = '';
    busy = true;
    try {
      await window.kikusub.completeSetup(chosen);
      // 不立刻 ondone：先进入模型配置，sidecar 会在后台启动。
      step = 'engines';
    } catch (err) {
      error = (err as Error).message || '无法使用这个目录';
    } finally {
      busy = false;
    }
  }
</script>

{#if step === 'engines'}
  <EngineSetup ondone={ondone} />
{:else}
<div class="setup-overlay">
  <div class="setup-card">
    <div class="logo">KikuSub</div>
    <h1>欢迎使用 KikuSub</h1>
    <p class="lead">
      转写模型体积较大（每个约 3–4 GB）。请先选择模型的保存位置，下一步再选择要下载哪些
      模型（包括可选的 OmniVoice 音色克隆）；以后也可以在「设置 → 引擎与模型」里更改。
    </p>

    <div class="path-box">
      <div class="path-head">
        <span>模型目录</span>
        <button class="btn tiny" onclick={pick} disabled={busy}>选择其他位置…</button>
      </div>
      <div class="path mono" title={chosen}>{chosen}</div>
      <div class="path-note">数据与输出目录：<span class="mono">{dataDir}</span></div>
    </div>

    {#if !ffmpeg}
      <div class="warn">
        <Icon name="warn" size={13} />
        没有检测到 ffmpeg。导入视频前需要先安装它（推荐 <code>brew install ffmpeg</code>），
        否则抽取音轨会失败。
      </div>
    {/if}

    {#if error}
      <div class="error">{error}</div>
    {/if}

    <div class="actions">
      <button class="btn primary" onclick={start} disabled={busy}>
        {busy ? '正在准备…' : '使用此位置并继续'}
      </button>
    </div>

    <div class="fine">模型只在本机使用，不会上传。第一次转写前可在设置页按需下载。</div>
  </div>
</div>
{/if}

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
  }
  .setup-card {
    width: min(560px, 100%);
    background: var(--bg-content);
    border: 1px solid var(--separator);
    border-radius: 12px;
    box-shadow: var(--shadow-pop);
    padding: 28px 30px 22px;
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
    margin: var(--sp-2) 0 var(--sp-2);
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.02em;
  }
  .lead {
    margin: 0 0 18px;
    font-size: 12.5px;
    line-height: 1.6;
    color: var(--text-2);
  }
  .path-box {
    border: 1px solid var(--separator);
    border-radius: 8px;
    padding: 11px var(--sp-3);
    background: var(--fill);
  }
  .path-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    font-size: 12px;
    color: var(--text-3);
  }
  .path {
    margin-top: 7px;
    font-size: 12px;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .path-note {
    margin-top: 6px;
    font-size: 12px;
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mono {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 12px;
    user-select: text;
  }
  .warn,
  .error {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    margin-top: var(--sp-3);
    padding: var(--sp-2) 10px;
    border-radius: 8px;
    font-size: 12px;
    line-height: 1.5;
  }
  .warn {
    color: var(--warn);
    background: var(--warn-soft);
  }
  .error {
    color: var(--danger);
    background: var(--danger-soft);
  }
  code {
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    background: var(--fill-strong);
    border-radius: 4px;
    padding: 0 var(--sp-1);
  }
  .actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--sp-2);
    margin-top: var(--sp-5);
  }
  .actions .btn {
    height: 30px;
    padding: 0 14px;
  }
  .fine {
    margin-top: 14px;
    font-size: 12px;
    color: var(--text-3);
    text-align: right;
  }
  .tiny {
    height: 20px;
    font-size: 12px;
    padding: 0 7px;
  }
</style>
