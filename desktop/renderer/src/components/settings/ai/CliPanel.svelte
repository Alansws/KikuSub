<script lang="ts">
  /**
   * 命令行工具：把 app 内的 kikusub 软链到 ~/.local/bin，并给出 PATH 引导。
   *
   * 为什么放在「AI 与技能」页：CLI 是 Agent 技能的执行入口——技能说「用
   * kikusub cues 读证据 / kikusub propose 提交提案」，没有这个软链就只能写
   * .app 里的绝对路径。两者必须挨着，用户才不会只装一半。
   */
  import { onMount } from 'svelte';
  import Icon from '../../Icon.svelte';
  import { toast } from '../../../lib/store.svelte';
  import {
    cliState,
    cliStatusLabel,
    cliStatusOk,
    installCli,
    loadCli,
    uninstallCli,
  } from '../../../lib/settings/cli.svelte';

  const status = $derived(cliStatusLabel(cliState.info));
  const ok = $derived(cliStatusOk(cliState.info));
  const hint = $derived(cliState.info?.hint ?? null);
  const showHint = $derived(Boolean(cliState.info?.installed && !cliState.info?.inPath));

  onMount(() => {
    void loadCli();
  });

  async function copyHint() {
    if (!hint) return;
    try {
      const done = await window.kikusub.writeClipboard(hint.command);
      toast(done ? '已复制；贴进终端执行后重开终端' : '复制失败，请手动选中命令', done ? 'info' : 'warn');
    } catch (err) {
      toast((err as Error).message, 'error');
    }
  }

  function install() {
    void installCli();
  }
</script>

<div class="set-group">
  <div class="set-row">
    <div class="set-row-main">
      <span class="set-row-title">命令位置</span>
      <span class="set-row-desc">
        外部 Agent 用 <code>kikusub project / cues / cue / listen / propose</code> 读工程、提交审阅提案；
        它只提交提案，应用仍由你在界面里点。
      </span>
    </div>
    <div class="set-row-ctl grow">
      <span class="set-path" title={cliState.info?.linkPath ?? ''}>
        {cliState.info?.linkPath || '~/.local/bin/kikusub'}
      </span>
      <span class="cli-state" class:ok>{status}</span>
      <button class="btn sm" onclick={install} disabled={cliState.busy}>
        {cliState.busy ? '安装中…' : cliState.info?.installed ? '重新安装' : '安装命令'}
      </button>
      {#if cliState.info?.installed}
        <button class="btn sm ghost" onclick={() => void uninstallCli()} disabled={cliState.busy}>
          移除
        </button>
      {/if}
      <button class="btn sm ghost" onclick={() => void loadCli()} disabled={cliState.busy}>刷新</button>
    </div>
  </div>

  {#if cliState.info?.conflict}
    <div class="set-row">
      <div class="set-row-main">
        <span class="set-row-desc warn">{cliState.info.error}</span>
      </div>
    </div>
  {/if}

  {#if showHint && hint}
    <div class="set-row">
      <div class="set-row-main">
        <span class="set-row-title">PATH 还没包含 ~/.local/bin</span>
        <span class="set-row-desc">
          macOS 默认不把该目录放进 PATH。执行下面这条命令（写入 <code>~/.zshrc</code>）后重开终端；
          有的 Agent 不读 .zshrc，必要时在它的环境里显式加 <code>~/.local/bin</code>。
        </span>
      </div>
      <div class="set-row-ctl grow">
        <code class="cli-cmd">{hint.command}</code>
        <button class="btn sm ghost" onclick={() => void copyHint()}>复制命令</button>
      </div>
    </div>
  {/if}

  <div class="set-row">
    <div class="set-row-main">
      <span class="set-row-title">兜底路径</span>
      <span class="set-row-desc">
        没装软链或 PATH 不可用时，直接用
        <code>{cliState.info?.target || '/Applications/KikuSub.app/Contents/Resources/bin/kikusub'}</code>
        也能运行。
      </span>
    </div>
  </div>
</div>

<div class="note-box">
  <span class="note-icon"><Icon name="doc" size={13} /></span>
  <span>
    运行中的 App 会把端口/token 写到 <code>outputs/runtime.json</code>（0600）；CLI 只读它，
    不会猜路径、不会新建会话。<b>提案提交后界面会在 2 秒内提示并刷新</b>，不需要重启或手动切页。
  </span>
</div>

<style>
  code {
    font-size: 11px;
    padding: 0 var(--sp-1);
    border-radius: 4px;
    background: var(--surface-2);
  }
  .cli-state {
    font-size: var(--fs-label);
    color: var(--warn);
    white-space: nowrap;
  }
  .cli-state.ok {
    color: var(--success);
  }
  .cli-cmd {
    max-width: 420px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    user-select: all;
  }
  .warn {
    color: var(--warn);
  }
</style>
