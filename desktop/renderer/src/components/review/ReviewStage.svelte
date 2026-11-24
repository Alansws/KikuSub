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
    stageHeight = 0,
    maxStageHeight = 0,
    proxyLabel = '',
    resolution = '',
    fps = 0,
    bDiff = null as number | null,
    ondragbar,
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
    /** 监看舞台高度（0 = 用 16:9 的自然高度）；可拖高，见下方 splitter。 */
    stageHeight?: number;
    /** 拖高的上限（窗口可用高度的一半），由父组件按视口算。 */
    maxStageHeight?: number;
    proxyLabel?: string;
    resolution?: string;
    fps?: number;
    /** B 稿（另一引擎）差异条数；null = 没有 B 稿。 */
    bDiff?: number | null;
    ondragbar?: (height: number) => void;
  } = $props();

  let videoEl = $state<HTMLVideoElement | null>(null);

  $effect(() => {
    if (videoEl) onvideo?.(videoEl);
  });
</script>

<div class="stage">
  <div
    class="player"
    style={stageHeight
      ? `--stage-h:${stageHeight}px;height:${stageHeight}px;width:auto;max-height:none`
      : ''}
  >
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

  <!-- 监看区底部的媒体状态条（28px）：代理 / 分辨率 / 帧率 / B 稿差异。
       状态不再压在画面四角上——那样既挡字幕，又在窄窗口盖住人脸。 -->
  <div class="pinfo">
    <span class="pi-dot" class:ready={Boolean(proxyLabel.includes('就绪'))}></span>
    <span>{proxyLabel || '原始画面'}</span>
    {#if resolution}
      <span class="pi-sep">·</span>
      <span>{resolution}</span>
    {/if}
    {#if fps > 0}
      <span class="pi-sep">·</span>
      <span>{fps.toFixed(3)} fps</span>
    {/if}
    <span class="pi-grow"></span>
    {#if bDiff !== null}
      <span class="pi-b">B 稿 {bDiff} 处差异</span>
    {/if}
  </div>

  <!-- 可拖的高度分隔条：向下拉 = 画面变高、时间轴与表格让位。
       双击回到默认（16:9 自然高度）。 -->
  <button
    class="splitter"
    aria-label="调整监看区高度（双击还原）"
    title="拖动调整监看区高度 · 双击还原"
    onpointerdown={(e) => {
      e.preventDefault();
      const startY = e.clientY;
      const startH = e.currentTarget.parentElement?.querySelector('.player')?.clientHeight ?? 0;
      const el = e.currentTarget as HTMLElement;
      el.setPointerCapture(e.pointerId);
      const move = (ev: PointerEvent) => {
        const next = startH + (ev.clientY - startY);
        ondragbar?.(Math.max(160, Math.min(maxStageHeight || 720, next)));
      };
      const up = () => {
        el.removeEventListener('pointermove', move);
        el.removeEventListener('pointerup', up);
        el.removeEventListener('pointercancel', up);
      };
      el.addEventListener('pointermove', move);
      el.addEventListener('pointerup', up);
      el.addEventListener('pointercancel', up);
    }}
    ondblclick={() => ondragbar?.(0)}
  ></button>
</div>

<style>
  /* 画面固定在 640×360 的 16:9 框里（窗口更窄时等比缩），只留阴影，不要光晕 */
  /* 监看舞台：全宽暗底（2026-11-24 Phase 2）。
     原来是一块亮灰底上漂着 640×360 的黑圆角卡片，读起来像「嵌在网页里的播放器」；
     改成通栏暗底之后画面是唯一亮点，边框与圆角都收掉（阴影也不再需要）。
     颜色走令牌：--stage-bg 在亮/暗两套主题里各自接近纯黑，保证画面边缘不发灰。 */
  .stage {
    display: flex;
    flex-direction: column;
    background: var(--stage-bg);
  }
  .player {
    position: relative;
    /* 高度自适应真 16:9：宽由容器定、高由 aspect-ratio 定；
       拖高时高度由内联 style 覆盖，宽度仍然按 16:9 反推（见下）。
       禁止水平拉伸或 overflow 裁剪上下画面（object-fit: contain 保底）。 */
    /* 默认高度同时受三件事约束：容器宽、16:9、以及「给下面留出空间」的窗口比例。
       拖高时内联 height 覆盖这一条（见 .player[style]）。 */
    width: auto;
    height: var(--stage-natural, auto);
    max-width: 100%;
    max-height: var(--stage-cap, 46vh);
    aspect-ratio: 16 / 9;
    margin: 0 auto;
    background: #000;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  /* 用户拖过高度：按内联高度铺满，宽度仍由 16:9 换算，绝不横向拉伸 */
  .player[style*='height'] {
    height: var(--stage-h, auto);
    max-height: none;
    width: auto;
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

  /* 媒体状态条：28px 暗色，压在画面下方而不是四角 */
  .pinfo {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 28px;
    flex: 0 0 28px;
    padding: 0 var(--sp-3);
    font-size: 11.5px;
    line-height: 16px;
    color: var(--stage-ink);
    background: var(--stage-bar);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: hidden;
  }
  .pi-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    flex: 0 0 5px;
    background: var(--stage-ink-dim);
  }
  .pi-dot.ready {
    background: var(--success);
  }
  .pi-sep {
    color: var(--stage-ink-dim);
  }
  .pi-grow {
    flex: 1;
  }
  .pi-b {
    color: var(--stage-ink);
    opacity: 0.82;
  }

  /* 高度分隔条：6px 命中区 + 1px 视觉线；hover / 拖动时亮起来 */
  .splitter {
    appearance: none;
    display: block;
    width: 100%;
    height: 6px;
    margin: 0;
    padding: 0;
    border: 0;
    background: transparent;
    cursor: ns-resize;
    position: relative;
    flex: 0 0 6px;
  }
  .splitter::after {
    content: '';
    position: absolute;
    left: 0;
    right: 0;
    top: 2px;
    height: 1px;
    background: var(--stage-line);
  }
  .splitter:hover::after,
  .splitter:focus-visible::after {
    background: var(--accent);
  }
  .splitter:focus-visible {
    outline: none;
  }
</style>
