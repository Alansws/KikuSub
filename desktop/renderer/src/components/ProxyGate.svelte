<script lang="ts">
  /**
   * 黑屏画面里的代理入口：只有画面真的出不来时才出现。
   *
   * 压制过程中的进度**不在这里显示**（百分比和进度条都留给顶部工具栏的蓝色 chip）：
   * 这里只保留提示文案和按钮，失败/取消后按钮会随 `state` 回到可点击的「压制代理」。
   */
  import Icon from './Icon.svelte';
  import {
    proxyReasonLabel,
    type VideoGateState,
  } from '../lib/videoFallback';

  let {
    state,
    reason = '',
    onstart,
    onimport,
  }: {
    state: VideoGateState;
    reason?: string;
    onstart: () => void;
    onimport: () => void;
  } = $props();

  const busy = $derived(state === 'proxy-busy');
</script>

{#if state !== 'none'}
  <div class="gate" role="group" aria-label="视频画面无法播放">
    <div class="gate-card" class:busy>
      <span class="gate-icon" aria-hidden="true"><Icon name="warn" size={18} /></span>
      {#if state === 'proxy-unavailable'}
        <b>代理已就绪，但画面仍无法播放</b>
        <span class="gate-body">
          代理文件可能已损坏，或它的编码同样不受支持。重新导入一份可播放的代理。
        </span>
        <div class="gate-actions">
          <button class="gate-btn primary" onclick={onimport}>重新导入代理</button>
        </div>
      {:else}
        <b>无法显示这个视频的画面</b>
        <span class="gate-body">
          {proxyReasonLabel(reason)}。压一份 480p 监看代理后，就能在核对台正常预览和拖动。
        </span>
        <div class="gate-actions">
          <button
            class="gate-btn primary"
            onclick={onstart}
            disabled={busy}
            aria-busy={busy}
          >
            {busy ? '正在压制…' : '压制代理'}
          </button>
          {#if !busy}
            <button class="gate-btn quiet" onclick={onimport}>导入已有代理</button>
          {/if}
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  /* 画面本身是黑的：不再盖一层遮罩，只把卡片放在正中，避免误伤仍在播放的帧。
     容器不接指针事件，按钮自己接，画面其它区域保持可交互。 */
  .gate {
    position: absolute;
    inset: 0;
    z-index: 2;
    display: grid;
    place-items: center;
    padding: 14px;
    pointer-events: none;
  }

  .gate-card {
    pointer-events: auto;
    width: min(400px, 90%);
    padding: var(--sp-4) var(--sp-5) 15px;
    border-radius: 10px;
    border: 1px solid rgba(255, 255, 255, 0.14);
    background: rgba(16, 18, 22, 0.84);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
    color: #fff;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 6px;
  }

  .gate-icon {
    color: rgba(255, 205, 120, 0.95);
    line-height: 1;
    margin-bottom: 1px;
  }

  b {
    font-size: 13.5px;
    font-weight: 600;
    line-height: 1.35;
  }

  .gate-body {
    font-size: 12.5px;
    line-height: 1.55;
    color: rgba(255, 255, 255, 0.68);
  }

  .gate-actions {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 7px;
    margin-top: 7px;
  }

  .gate-btn {
    appearance: none;
    font: inherit;
    cursor: default;
    border-radius: 6px;
    height: 29px;
    padding: 0 15px;
    font-size: 12.5px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition:
      background-color 140ms ease,
      border-color 140ms ease,
      color 140ms ease;
  }

  .gate-btn.primary {
    border: 1px solid transparent;
    background: var(--accent);
    color: var(--on-accent);
    font-weight: 500;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
  }
  .gate-btn.primary:hover:not(:disabled) {
    background: var(--accent-hover);
  }
  .gate-btn.primary:disabled {
    background: rgba(255, 255, 255, 0.14);
    border-color: transparent;
    color: rgba(255, 255, 255, 0.6);
    box-shadow: none;
  }

  .gate-btn.quiet {
    border: 0;
    background: transparent;
    color: rgba(255, 255, 255, 0.62);
    height: 22px;
    padding: 0 6px;
    font-size: 12px;
  }
  .gate-btn.quiet:hover {
    color: #fff;
    background: rgba(255, 255, 255, 0.07);
  }
</style>
