<script lang="ts">
  /**
   * 核对台的波形 / 字幕轨道画布。
   *
   * 2026-11-24 从 `ReviewView.svelte` 纯搬运（Phase 0，视觉零变化）。
   * 这里是**纯展示 + 事件转发**：所有命中判定、拖拽状态机、擦洗器、缩放与
   * 选区 clamp 仍然在 `ReviewView` 里，本组件不持有任何交互状态。
   *
   * 两条契约因此原封不动（red line 6）：
   * - 单击 `pointerdown` 先进入 pending，移动 > `CLICK_SLOP=4px` 才算框选的判定
   *   在父组件的 `onWavePointerDown/Move/Up` 里；
   * - 顶部刻度条 `RULER_H` 与播放头两侧 `PLAYHEAD_GRAB` 是专属擦洗区。
   *
   * 画布与容器节点通过 `onwrap` / `oncanvas` 交回父组件：绘制（`draw()`）、
   * 尺寸测量与像素换算都要读它们，组件内不再留一份引用。
   */
  import Icon from '../Icon.svelte';
  import ChapterTrack from '../ChapterTrack.svelte';
  import { tcShort } from '../../lib/time';
  import type { ChapterMark } from '../../lib/api';

  let {
    height = 80,
    cursor = 'crosshair',
    dragging = false,
    marks = [],
    duration = 0,
    viewStart = 0,
    viewSpan = 1,
    rulerH = 17,
    playTime = 0,
    playheadX = 0,
    waveW = 0,
    selectionLeft = null,
    selectionWidth = 0,
    cueTip = null,
    loadingPeaks = false,
    hasPeaks = false,
    onwrap,
    oncanvas,
    onpointerdown,
    onpointermove,
    onpointerup,
    onpointerleave,
    onwheel,
    oncontextmenu,
    ondblclick,
    onseekmark,
    onview,
    onselectionresize,
    onfocusplayhead,
    onresizedown,
    onresizemove,
    onresizeup,
  }: {
    height?: number;
    cursor?: string;
    dragging?: boolean;
    marks?: ChapterMark[];
    duration?: number;
    viewStart?: number;
    viewSpan?: number;
    rulerH?: number;
    playTime?: number;
    playheadX?: number;
    waveW?: number;
    selectionLeft?: number | null;
    selectionWidth?: number;
    cueTip?: { x: number; label: string } | null;
    loadingPeaks?: boolean;
    hasPeaks?: boolean;
    onwrap?: (node: HTMLDivElement) => void;
    oncanvas?: (node: HTMLCanvasElement) => void;
    onpointerdown: (e: PointerEvent) => void;
    onpointermove: (e: PointerEvent) => void;
    onpointerup: (e: PointerEvent) => void;
    onpointerleave: (e: PointerEvent) => void;
    onwheel: (e: WheelEvent) => void;
    oncontextmenu: (e: MouseEvent) => void;
    ondblclick: (e: MouseEvent) => void;
    onseekmark: (id: string, start: number) => void;
    onview?: ((start: number) => void) | null;
    onselectionresize: (edge: 'l' | 'r', e: PointerEvent) => void;
    onfocusplayhead: () => void;
    onresizedown: (e: PointerEvent) => void;
    onresizemove: (e: PointerEvent) => void;
    onresizeup: (e: PointerEvent) => void;
  } = $props();

  let wrapEl = $state<HTMLDivElement | null>(null);
  let canvasEl = $state<HTMLCanvasElement | null>(null);

  $effect(() => {
    if (wrapEl) onwrap?.(wrapEl);
  });
  $effect(() => {
    if (canvasEl) oncanvas?.(canvasEl);
  });

  const outside = $derived(playTime < viewStart - 0.02 || playTime > viewStart + viewSpan + 0.02);
  const rightSide = $derived(playTime > viewStart);
  const flagShift = $derived(
    playheadX < 26 ? '0' : playheadX > waveW - 26 ? '-100%' : '-50%',
  );

  // 双击 = 以点击处为中心放大到 1/5 跨度（1.5–10s）。坐标换算与 setView 都在父组件，
  // 这里只把原始事件转回去。
</script>

<div
  class="wave-wrap"
  bind:this={wrapEl}
  role="group"
  aria-label="波形时间轴与字幕轨道"
  style="height:{height}px;cursor:{cursor}"
  {onpointerdown}
  {onpointermove}
  {onpointerup}
  {onpointerleave}
  {onwheel}
  {oncontextmenu}
  ondblclick={ondblclick}
  class:dragging
>
  <canvas bind:this={canvasEl}></canvas>
  <ChapterTrack {marks} {duration} {viewStart} {viewSpan} {rulerH} onseek={onseekmark} {onview} />

  {#if cueTip}
    <div class="cue-tip" style="left:{cueTip.x}px">{cueTip.label}</div>
  {/if}

  {#if selectionLeft !== null}
    <div class="sel" style="left:{selectionLeft}px;width:{Math.max(1, selectionWidth)}px">
      <div class="sel-handle l" onpointerdown={(e) => onselectionresize('l', e)}></div>
      <div class="sel-handle r" onpointerdown={(e) => onselectionresize('r', e)}></div>
    </div>
  {/if}

  {#if outside}
    <button
      class="ph-off"
      class:right={rightSide}
      onclick={onfocusplayhead}
      onpointerdown={(e) => e.stopPropagation()}
      title="播放头在视窗外"
    >
      <Icon name={rightSide ? 'chevron-right' : 'chevron-left'} size={11} />
    </button>
  {:else}
    <div class="ph" style="left:{Math.max(0, Math.min(waveW, playheadX))}px">
      <div class="ph-flag" style="transform:translateX({flagShift})">{tcShort(playTime)}</div>
    </div>
  {/if}

  {#if loadingPeaks && !hasPeaks}
    <div class="wave-loading">正在解码波形…</div>
  {/if}

  <div
    class="wave-resize"
    onpointerdown={onresizedown}
    onpointermove={onresizemove}
    onpointerup={onresizeup}
    onpointercancel={onresizeup}
    title="拖动调整波形高度"
  ></div>
</div>

<style>
  /* 时间轴是通栏的，不再包在圆角里：圆角在浅色下会露出四角的一小块画布，
     看起来像「时间轴被裁掉了一点」。 */
  .wave-wrap {
    position: relative;
    background: transparent;
    overflow: hidden;
    touch-action: none;
    /* 具体光标由脚本按命中区域切换（刻度/播放头/字幕块/波形） */
    cursor: crosshair;
  }
  canvas {
    display: block;
    width: 100%;
    height: 100%;
  }

  .cue-tip {
    position: absolute;
    bottom: 26px;
    transform: translateX(-50%);
    background: var(--accent);
    color: var(--on-accent);
    font-size: var(--fs-mono);
    line-height: 15px;
    height: 15px;
    padding: 0 5px;
    border-radius: 3px;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    pointer-events: none;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.22);
    z-index: 3;
  }

  .wave-resize {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: 6px;
    cursor: ns-resize;
    touch-action: none;
  }
  .wave-resize::after {
    content: '';
    position: absolute;
    left: 50%;
    bottom: 2px;
    width: 34px;
    height: 2px;
    margin-left: -17px;
    border-radius: 1px;
    background: var(--separator);
  }
  .wave-resize:hover {
    background: var(--accent-soft);
  }
  .wave-resize:hover::after {
    background: var(--accent);
  }

  .sel {
    position: absolute;
    top: 17px;
    bottom: 0;
    background: color-mix(in srgb, var(--accent) 8%, transparent);
    border-left: 1px solid var(--accent);
    border-right: 1px solid var(--accent);
    pointer-events: none;
  }
  .sel-handle {
    position: absolute;
    top: 0;
    /* 留出底部字幕轨道：选区的把手不能挡住字幕块的左右端拖动 */
    bottom: 23px;
    width: 8px;
    pointer-events: auto;
    cursor: ew-resize;
  }
  .sel-handle.l {
    left: -4px;
  }
  .sel-handle.r {
    right: -4px;
  }

  .ph {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 1.5px;
    background: var(--accent);
    pointer-events: none;
    will-change: left;
  }
  .ph-off {
    position: absolute;
    top: 21px;
    width: 15px;
    height: 15px;
    padding: 0;
    border: 0;
    border-radius: 4px;
    background: var(--accent-soft);
    color: var(--accent);
    display: grid;
    place-items: center;
    left: 3px;
    z-index: 2;
  }
  .ph-off.right {
    left: auto;
    right: 3px;
  }
  .ph-off:hover {
    background: var(--accent);
    color: var(--on-accent);
  }
  .ph-flag {
    position: absolute;
    top: 1px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--accent);
    color: var(--on-accent);
    font-size: var(--fs-mono);
    line-height: 14px;
    padding: 0 var(--sp-1);
    height: 14px;
    border-radius: 3px;
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    white-space: nowrap;
  }

  .wave-loading {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    font-size: 11.5px;
    color: var(--text-3);
    background: color-mix(in srgb, var(--canvas) 78%, transparent);
  }
</style>
