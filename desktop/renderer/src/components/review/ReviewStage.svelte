<script lang="ts">
  /**
   * 核对台的视频监看区：画面 + 字幕叠加 + 代理提示。
   *
   * 2026-11-24 从 `ReviewView.svelte` 纯搬运（Phase 0，视觉零变化）。
   * `<video>` 的生命周期、`theatre` 擦洗、首帧探测与布局恢复都还在父组件：
   * 这里只把节点交回去（`onvideo`），并把所有原生事件原样转发。
   *
   * `{@attach bindVideo}` 的挂载 / 卸载语义不能改：`bindVideo` 返回的清理函数
   * 负责 detach，视频节点换掉时必须走到它。
   */
  import ProxyGate from '../ProxyGate.svelte';

  let {
    src = '',
    captionLines = [],
    gate = null,
    proxyReason = '',
    onvideo,
    attach,
    onerror,
    onloadedmetadata,
    onloadeddata,
    onstartproxy,
    onimportproxy,
  }: {
    src?: string;
    captionLines?: string[];
    gate?: unknown;
    proxyReason?: string;
    onvideo?: (node: HTMLVideoElement) => void;
    attach: (node: HTMLVideoElement) => void | (() => void) | { destroy(): void };
    onerror: (el: HTMLVideoElement, e: Event) => void;
    onloadedmetadata: (el: HTMLVideoElement, e: Event) => void;
    onloadeddata: (el: HTMLVideoElement, e: Event) => void;
    onstartproxy: () => void;
    onimportproxy: () => void;
  } = $props();

  let videoEl = $state<HTMLVideoElement | null>(null);

  $effect(() => {
    if (videoEl) onvideo?.(videoEl);
  });
</script>

<div class="player">
  {#if src}
    <video
      {@attach attach}
      bind:this={videoEl}
      {src}
      preload="auto"
      playsinline
      onerror={(e) => videoEl && onerror(videoEl, e)}
      onloadedmetadata={(e) => videoEl && onloadedmetadata(videoEl, e)}
      onloadeddata={(e) => videoEl && onloadeddata(videoEl, e)}
    ></video>
  {:else}
    <div class="empty">还没有导入媒体</div>
  {/if}

  {#if captionLines.length}
    <div class="caption">
      {#each captionLines as line, i (i)}
        <span>{line}</span>
      {/each}
    </div>
  {/if}

  <!-- 代理闸门只负责「压下画面」的提示层；状态机在 lib/videoFallback.ts -->
  <ProxyGate
    state={gate as never}
    reason={proxyReason}
    onstart={onstartproxy}
    onimport={onimportproxy}
  />
</div>

<style>
  /* 画面固定在 640×360 的 16:9 框里（窗口更窄时等比缩），只留阴影，不要光晕 */
  .player {
    position: relative;
    width: min(640px, 100%);
    aspect-ratio: 16 / 9;
    margin: 0 auto;
    background: #000;
    border-radius: 10px;
    overflow: hidden;
    box-shadow: var(--shadow-video);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  :global(html[data-theme='dark']) .player {
    box-shadow: var(--shadow-video), 0 0 0 1px rgba(236, 241, 250, 0.06);
  }
  video {
    width: 100%;
    height: 100%;
    object-fit: contain;
    background: #000;
    display: block;
  }
  .empty {
    color: rgba(255, 255, 255, 0.5);
    font-size: 12.5px;
  }

  .caption {
    position: absolute;
    left: 50%;
    bottom: 14px;
    transform: translateX(-50%);
    max-width: 84%;
    background: var(--caption-bg);
    backdrop-filter: blur(6px);
    color: #fff;
    /* 与表格、检查器同一条字幕字体角色：主题换的是「字幕」，不是「界面」 */
    font-family: var(--font-cue);
    font-size: 14px;
    line-height: 1.5;
    padding: 5px 13px;
    border-radius: 4px;
    text-align: center;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
    pointer-events: none;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .caption span {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
