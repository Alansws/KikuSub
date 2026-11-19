<script lang="ts">
  /**
   * 轻量「复制」按钮：写系统剪贴板并给出短暂反馈。
   *
   * 复核卡 / AI 判定卡 / 多轮对话里的台词都允许鼠标选中复制；这个按钮只是
   * 让「整句带走」不必依赖精确拖选。剪贴板走 preload 的 `writeClipboard`，
   * 无 preload 的截图环境回退到 `navigator.clipboard`。
   */
  import { onDestroy } from 'svelte';
  import Icon from './Icon.svelte';

  let {
    text,
    compact = false,
    title = '复制这段文本到剪贴板',
  }: { text: string; compact?: boolean; title?: string } = $props();

  let state = $state<'idle' | 'copied' | 'failed'>('idle');
  let timer: ReturnType<typeof setTimeout> | null = null;

  function clearTimer() {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  }

  async function copy() {
    const value = String(text ?? '');
    if (!value) return;
    try {
      if (window.kikusub?.writeClipboard) {
        const ok = await window.kikusub.writeClipboard(value);
        if (ok === false) throw new Error('剪贴板写入失败');
      } else if (navigator.clipboard) {
        await navigator.clipboard.writeText(value);
      } else {
        throw new Error('当前环境没有剪贴板');
      }
      state = 'copied';
    } catch {
      state = 'failed';
    }
    clearTimer();
    timer = setTimeout(() => {
      state = 'idle';
      timer = null;
    }, 1500);
  }

  onDestroy(clearTimer);
</script>

<button
  class="copy"
  class:compact
  type="button"
  onclick={copy}
  disabled={!text}
  title={state === 'copied'
    ? '已复制'
    : state === 'failed'
      ? '复制失败，可手动划选文本后按 ⌘C'
      : title}
  aria-label={state === 'copied' ? '已复制' : title}
>
  <Icon name={state === 'copied' ? 'check' : 'copy'} size={compact ? 10 : 11} />
  <span>{state === 'copied' ? '已复制' : state === 'failed' ? '复制失败' : '复制'}</span>
</button>

<style>
  .copy {
    appearance: none;
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    gap: 3px;
    height: 22px;
    padding: 0 7px;
    border: 1px solid var(--line-2);
    border-radius: 6px;
    background: transparent;
    color: var(--ink-2);
    font: inherit;
    font-size: 11px;
    line-height: 1;
    white-space: nowrap;
    cursor: pointer;
    user-select: none;
    transition:
      color var(--dur-fast) var(--ease),
      border-color var(--dur-fast) var(--ease),
      background var(--dur-fast) var(--ease);
  }
  .copy:hover:not(:disabled) {
    color: var(--accent-hover);
    border-color: var(--accent-line);
    background: var(--accent-soft);
  }
  .copy:focus-visible {
    outline: 2px solid var(--accent-ring);
    outline-offset: 2px;
  }
  .copy:disabled {
    opacity: 0.55;
    cursor: default;
  }
  .copy.compact {
    height: 21px;
    font-size: 10.5px;
  }
</style>
