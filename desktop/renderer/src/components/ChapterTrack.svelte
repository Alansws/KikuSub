<script lang="ts">
  /**
   * 章节旗标 / 区间色条（时间轴顶部覆盖层）。
   *
   * 三件事：
   * 1. 把当前视窗内的标记画在刻度区上面，单击旗标跳到章节起点；
   * 2. 区间章节两端可拖：旗标拖过 4px 改起点，右端抓手上拖动改终点
   *    （单击旗标仍然是跳转——4px 阈值是「单击 vs 拖」的唯一判据）；
   * 3. 拖到左右缘时视窗自己继续平移（与播放头擦洗同一套 `createScrubPan`），
   *    否则放大后 14 分钟的区间根本够不到端点。
   *
   * 契约（不能破）：顶部 17px 刻度条是专属擦洗区。本覆盖层整体
   * `pointer-events: none`，只有旗标与右端抓手例外；它们都在刻度条**下方**
   * 的 6px 色条里，不会吃掉刻度擦洗。
   *
   * 定位用百分比而不是像素：视窗缩放/平移时不需要重算 DOM 宽度，跟 canvas 里
   * 画的刻度天然对齐。
   */
  import Icon from './Icon.svelte';
  import type { ChapterMark } from '../lib/api';
  import { chapters, updateMark } from '../lib/chapters.svelte';
  import { clampEdgeTime, edgeBounds, roundMs } from '../lib/chapterEdge';
  import { span as draftSpan } from '../lib/chapterDraft';
  import { createScrubPan } from '../lib/scrub';
  import { play } from '../lib/store.svelte';
  import { tcShort } from '../lib/time';
  import { clampTimelineView } from '../lib/timelineView';

  type TrackItem = { mark: ChapterMark; start: number; end: number };
  type DragEdge = 'start' | 'end';

  interface MarkDrag {
    id: string;
    edge: DragEdge;
    /** 拖动中的区间（秒）：提交前只在这里变，不污染 `chapters.marks`。 */
    start: number;
    end: number;
    lo: number;
    hi: number;
  }

  let {
    marks = [],
    duration = 0,
    viewStart = 0,
    viewSpan = 1,
    rulerH = 17,
    onseek = (_id: string, _start: number) => {},
    onview = null,
  }: {
    marks: ChapterMark[];
    duration: number;
    viewStart: number;
    viewSpan: number;
    /** 顶部刻度条高度：色条贴在它的下沿，才不会被刻度文字盖住。 */
    rulerH?: number;
    onseek?: (id: string, start: number) => void;
    /** 端点拖到边缘时把视窗移到某个起点（`null` = 不支持，此时不自动平移）。 */
    onview?: ((start: number) => void) | null;
  } = $props();

  let trackEl = $state<HTMLDivElement | null>(null);
  let drag = $state<MarkDrag | null>(null);
  /** 旗标按下但还没拖过阈值：松手仍按「单击跳转」处理。 */
  let press: { id: string; downX: number } | null = null;
  /** 拖完松手后浏览器还会补一个 click：吞掉它，别再跳一次。 */
  let quietClick = false;
  let raf = 0;

  /** 单击 vs 拖动：与核对台框选同一个阈值。 */
  const CLICK_SLOP = 4;

  const pct = (t: number) => ((t - viewStart) / (viewSpan || 1)) * 100;

  /** 展示用区间：结束时间取自己声明的 end，没有就取下一个标记起点（或片尾）。 */
  const items = $derived.by((): TrackItem[] => {
    const ordered = [...marks].sort((a, b) => a.start - b.start);
    return ordered.map((mark, index) => {
      const next = ordered[index + 1]?.start ?? duration;
      const end = mark.end !== null ? Math.min(mark.end, next) : next;
      return { mark, start: mark.start, end: Math.max(mark.start, end) };
    });
  });

  /** 只渲染视窗附近（左右各留半屏），整片几百个标记时不至于塞满 DOM。 */
  const visible = $derived(
    items.filter(
      (item) =>
        item.end >= viewStart - viewSpan * 0.5 && item.start <= viewStart + viewSpan * 1.5,
    ),
  );

  /** 章节草稿的预览区间：待定的那一端跟着播放头走（与章节面板读同一个 `span()`）。 */
  const draftRange = $derived(draftSpan(chapters.draft, play.time));

  const liveStart = (item: TrackItem) => (drag && drag.id === item.mark.id ? drag.start : item.start);
  const liveEnd = (item: TrackItem) => (drag && drag.id === item.mark.id ? drag.end : item.end);

  function tc(seconds: number): string {
    const total = Math.max(0, seconds);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = Math.floor(total % 60);
    const mm = String(m).padStart(2, '0');
    const ss = String(s).padStart(2, '0');
    return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  }

  function nextStartFor(id: string): number {
    const index = items.findIndex((item) => item.mark.id === id);
    return items[index + 1]?.start ?? duration;
  }

  function timeAtX(clientX: number): number {
    const rect = trackEl?.getBoundingClientRect();
    if (!rect || !(rect.width > 0)) return viewStart;
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    return viewStart + ratio * viewSpan;
  }

  /** 端点拖到边缘后的自动平移：与播放头擦洗同一套推进器。 */
  const pan = createScrubPan({
    isDragging: () => Boolean(drag),
    getRect: () => trackEl?.getBoundingClientRect() ?? null,
    getView: () => ({ start: viewStart, span: viewSpan }),
    getDuration: () => duration,
    // minSpan 直接给当前跨度：这里只夹起点，不改变缩放
    clampStart: (start, span) => clampTimelineView(start, span, duration, span).start,
    setView: (start) => onview?.(start),
    advance: (delta) => {
      if (!drag || !onview) return;
      applyTime((drag.edge === 'start' ? drag.start : drag.end) + delta);
    },
  });

  function loop() {
    raf = 0;
    if (!drag) return;
    pan.step();
    raf = requestAnimationFrame(loop);
  }

  function startLoop() {
    if (!raf) raf = requestAnimationFrame(loop);
  }

  function stopLoop() {
    if (raf) {
      cancelAnimationFrame(raf);
      raf = 0;
    }
    pan.reset();
  }

  function applyTime(t: number) {
    if (!drag) return;
    const next = roundMs(clampEdgeTime(t, drag));
    if (drag.edge === 'start') drag.start = next;
    else drag.end = next;
  }

  function beginDrag(item: TrackItem, edge: DragEdge, clientX: number) {
    if (item.mark.end === null) return;
    const bounds = edgeBounds({
      edge,
      start: item.start,
      end: item.end,
      nextStart: nextStartFor(item.mark.id),
      duration,
    });
    drag = {
      id: item.mark.id,
      edge,
      start: item.start,
      end: item.end,
      lo: bounds.lo,
      hi: bounds.hi,
    };
    pan.arm(clientX);
    pan.move(clientX);
    startLoop();
  }

  function onFlagDown(e: PointerEvent, item: TrackItem) {
    if (e.button !== 0) return;
    // 不吃掉这个事件的话，按住旗标拖动会同时触发波形擦洗 / 框选
    e.stopPropagation();
    e.preventDefault();
    try {
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    } catch {
      /* 合成事件可能拿不到 pointerId */
    }
    quietClick = false;
    press = item.mark.end === null ? null : { id: item.mark.id, downX: e.clientX };
    if (item.mark.end !== null) pan.arm(e.clientX);
  }

  function onFlagMove(e: PointerEvent, item: TrackItem) {
    if (drag) {
      pan.move(e.clientX);
      applyTime(timeAtX(e.clientX));
      return;
    }
    if (!press || press.id !== item.mark.id) return;
    if (Math.abs(e.clientX - press.downX) < CLICK_SLOP) return;
    beginDrag(item, 'start', e.clientX);
    applyTime(timeAtX(e.clientX));
  }

  function onFlagUp() {
    press = null;
    if (drag) void commitDrag();
  }

  function onGripDown(e: PointerEvent, item: TrackItem) {
    if (e.button !== 0 || item.mark.end === null) return;
    e.stopPropagation();
    e.preventDefault();
    try {
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    } catch {
      /* ignore */
    }
    quietClick = true;
    beginDrag(item, 'end', e.clientX);
    applyTime(timeAtX(e.clientX));
  }

  function onGripMove(e: PointerEvent) {
    if (!drag) return;
    pan.move(e.clientX);
    applyTime(timeAtX(e.clientX));
  }

  function onPointerCancel() {
    drag = null;
    press = null;
    stopLoop();
    quietClick = false;
  }

  /** 松手提交：一步历史（`updateMark` 只记一条），没改动就不写。 */
  async function commitDrag() {
    const finished = drag;
    drag = null;
    press = null;
    stopLoop();
    if (!finished) return;
    quietClick = true;
    setTimeout(() => {
      quietClick = false;
    }, 0);
    const mark = marks.find((item) => item.id === finished.id);
    if (!mark || mark.end === null) return;
    const start = roundMs(finished.start);
    const end = roundMs(finished.end);
    if (start === roundMs(mark.start) && end === roundMs(mark.end)) return;
    await updateMark(finished.id, { start, end }, '调整章节时间');
  }

  function tooltip(item: TrackItem): string {
    const kind = item.mark.end === null ? '时刻点' : '章节';
    const dragHint = item.mark.end === null ? '' : ' · 拖动改起点';
    return `${item.mark.title || '未命名'}（${kind} ${tc(item.start)} → ${tc(item.end)}）· 单击跳转${dragHint}`;
  }
</script>

{#if visible.length}
  <div class="chapter-track" bind:this={trackEl} style="top:{rulerH}px" aria-label="章节标记">
    {#if draftRange && draftRange.end - draftRange.start > 0.001}
      <div
        class="draft-band"
        style="left:{pct(draftRange.start)}%;width:{Math.max(0.3, pct(draftRange.end) - pct(draftRange.start))}%"
        aria-hidden="true"
      ></div>
    {/if}
    <div class="band">
      {#each visible as item (item.mark.id)}
        <span
          class="range"
          class:point={item.mark.end === null}
          class:dragging={drag?.id === item.mark.id}
          style="left:{pct(liveStart(item))}%;width:{Math.max(
            0.12,
            pct(liveEnd(item)) - pct(liveStart(item)),
          )}%"
        >
          {#if item.mark.end !== null}
            <span
              class="grip r"
              role="presentation"
              title="拖动调整章节结束时间"
              onpointerdown={(e) => onGripDown(e, item)}
              onpointermove={onGripMove}
              onpointerup={onFlagUp}
              onpointercancel={onPointerCancel}
            ></span>
          {/if}
        </span>
      {/each}
    </div>
    {#each visible as item (item.mark.id)}
      <button
        class="flag"
        class:point={item.mark.end === null}
        class:active={drag?.id === item.mark.id}
        style="left:{pct(liveStart(item))}%"
        title={tooltip(item)}
        aria-label={tooltip(item)}
        onpointerdown={(e) => onFlagDown(e, item)}
        onpointermove={(e) => onFlagMove(e, item)}
        onpointerup={onFlagUp}
        onpointercancel={onPointerCancel}
        onclick={(e) => {
          e.stopPropagation();
          if (quietClick) {
            quietClick = false;
            return;
          }
          onseek(item.mark.id, liveStart(item));
        }}
      >
        <i></i>
        <span class="flag-label">{item.mark.title || tc(item.start)}</span>
      </button>
    {/each}
    {#if drag}
      <div
        class="drag-tip"
        style="left:{pct(drag.edge === 'start' ? drag.start : drag.end)}%"
        aria-hidden="true"
      >
        {tcShort(drag.edge === 'start' ? drag.start : drag.end)}
      </div>
    {/if}
  </div>
{/if}

<style>
  .chapter-track {
    position: absolute;
    left: 0;
    right: 0;
    height: 17px;
    /* 刻度擦洗属于 canvas：覆盖层整体不吃指针，只有旗标 / 右端抓手例外 */
    pointer-events: none;
    z-index: 3;
  }

  .band {
    position: absolute;
    inset: 0 0 auto 0;
    height: 6px;
  }

  .range {
    position: absolute;
    top: 0;
    height: 6px;
    border-radius: 2px;
    background: var(--accent);
    /* 底部一条深色边：与波形上方的字幕淡蓝区分开，不会读成「播放进度」 */
    box-shadow: inset 0 -1px 0 rgba(0, 0, 0, 0.28);
  }

  .range.point {
    /* 时刻点没有自己的区间：只留一个方块标记，避免看起来像一大段章节 */
    width: 6px !important;
    height: 6px;
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.28);
  }

  .range.dragging {
    box-shadow:
      inset 0 -1px 0 rgba(0, 0, 0, 0.28),
      0 0 0 1px var(--accent);
  }

  /*
   * 右端抓手：只有区间章节有。
   * 色条本身只有 6px 高，命中区做到了 12×12（向下多借 6px 波形区），
   * 视觉仍是一条 2px 的深色竖线，不会把色条撑高。
   */
  .grip {
    position: absolute;
    top: 0;
    right: -6px;
    width: 12px;
    height: 12px;
    pointer-events: auto;
    cursor: ew-resize;
    touch-action: none;
  }

  .grip::after {
    content: '';
    position: absolute;
    top: 0;
    left: 5px;
    width: 2px;
    height: 6px;
    border-radius: 1px;
    background: rgba(0, 0, 0, 0.32);
  }

  .grip:hover::after {
    background: rgba(0, 0, 0, 0.6);
  }

  .flag {
    position: absolute;
    top: 0;
    width: 10px;
    height: 15px;
    padding: 0;
    border: 0;
    background: transparent;
    transform: translateX(-2px);
    cursor: pointer;
    pointer-events: auto;
    touch-action: none;
  }

  .flag:not(.point) {
    cursor: grab;
  }

  .flag.active {
    cursor: grabbing;
  }

  .flag i {
    position: absolute;
    left: 2px;
    top: 6px;
    width: 2px;
    height: 11px;
    background: var(--accent);
    border-radius: 1px;
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.12);
  }

  .flag.point i {
    top: 6px;
    width: 6px;
    height: 6px;
    border-radius: 1px;
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.28);
  }

  .flag:hover i {
    box-shadow: 0 0 0 1px var(--separator);
  }

  .flag-label {
    position: absolute;
    left: 7px;
    top: 1px;
    max-width: 160px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-size: 10px;
    line-height: 13px;
    padding: 0 var(--sp-1);
    border-radius: 3px;
    color: var(--on-accent);
    background: var(--accent);
    opacity: 0;
    transition: opacity 90ms ease;
    pointer-events: none;
  }

  .flag:hover .flag-label,
  .flag:focus-visible .flag-label {
    opacity: 1;
  }

  .drag-tip {
    position: absolute;
    top: 8px;
    transform: translateX(-50%);
    padding: 0 var(--sp-1);
    height: 15px;
    line-height: 15px;
    border-radius: 3px;
    background: var(--accent);
    color: var(--on-accent);
    font-size: 10px;
    font-variant-numeric: tabular-nums;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    white-space: nowrap;
    pointer-events: none;
    z-index: 2;
  }
</style>
