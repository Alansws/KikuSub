<script lang="ts">
  /**
   * 核对台视频下方的「播放走带」行 + 「时间轴工具」行。
   *
   * 2026-11-24 从 `ReviewView.svelte` 纯搬运（Phase 0，视觉零变化）：
   * 那个文件有行数预算（只许变短），而这两行是完整的小界面单元，状态全在
   * ReviewView 里，这里只读 props + 回调。
   *
   * 两条契约不能动（red line 6）：
   * - 进度条复用 `click-to-seek` 的同一个擦洗器（`onTrackDown/Move/Up` 由父组件给），
   *   禁止在这里另起一套 seek；
   * - 缩放步进 `duration/69` 由 `lib/timelineView.ts` 决定，这里只调 `onZoomAt`。
   */
  import Icon from '../Icon.svelte';
  import SelectionBar from '../SelectionBar.svelte';
  import { formatDuration, tc } from '../../lib/time';

  let {
    playing = false,
    time = 0,
    duration = 0,
    progressPct = 0,
    fps = null,
    rate = 1,
    trackDrag = false,
    zoomX = 1,
    sliderValue = 0,
    follow = true,
    selection = null,
    laneSelection = [],
    rangeBusy = false,
    focusTitle = '',
    ontogglePlay,
    onresetRate,
    onTrackDown,
    onTrackMove,
    onTrackUp,
    onZoomAt,
    onZoomSlider,
    onFit,
    onFocusPlayhead,
    onToggleFollow,
    onDelete,
    onTranscribe,
    onFocusSelection,
    onSendSelection,
    onSeekSelection,
    onClearLane,
    onClearSelection,
  }: {
    playing?: boolean;
    time?: number;
    duration?: number;
    progressPct?: number;
    fps?: number | null;
    rate?: number;
    trackDrag?: boolean;
    zoomX?: number;
    sliderValue?: number;
    follow?: boolean;
    selection?: { start: number; end: number } | null;
    laneSelection?: string[];
    rangeBusy?: boolean;
    focusTitle?: string;
    ontogglePlay: () => void;
    onresetRate: () => void;
    onTrackDown: (e: PointerEvent) => void;
    onTrackMove: (e: PointerEvent) => void;
    onTrackUp: (e: PointerEvent) => void;
    onZoomAt: (time: number, factor: number) => void;
    onZoomSlider: (e: Event) => void;
    onFit: () => void;
    onFocusPlayhead: () => void;
    onToggleFollow: () => void;
    onDelete: () => void;
    onTranscribe: () => void;
    onFocusSelection: () => void;
    onSendSelection: () => void;
    onSeekSelection: () => void;
    onClearLane: () => void;
    onClearSelection: () => void;
  } = $props();
</script>

<div class="transport">
  <button
    class="playbtn"
    onclick={ontogglePlay}
    title="播放 / 暂停（空格）"
    aria-label={playing ? '暂停' : '播放'}
  >
    <Icon name={playing ? 'pause' : 'play'} size={11} />
  </button>
  <span
    class="tp-time"
    title={fps ? `${fps.toFixed(3)} fps` : '未探测到帧率，逐帧按 30fps 步进'}
  >
    {tc(time)}
  </span>
  {#if rate !== 1}
    <button class="mini-text tp-rate" onclick={onresetRate} title="恢复 1×（⇧2）">{rate}×</button>
  {/if}
  <div
    class="tp-track"
    class:dragging={trackDrag}
    role="slider"
    tabindex="-1"
    aria-label="播放进度"
    aria-valuemin="0"
    aria-valuemax={duration}
    aria-valuenow={time}
    onpointerdown={onTrackDown}
    onpointermove={onTrackMove}
    onpointerup={onTrackUp}
    onpointercancel={onTrackUp}
    title="拖动逐帧预览画面"
  >
    <div class="tp-rail">
      <div class="tp-fill" style="width:{progressPct}%"></div>
    </div>
    <div class="tp-knob" style="left:{progressPct}%"></div>
  </div>
  <span class="tp-dur">{formatDuration(duration)}</span>

  <!-- 缩放 / 全景 / 聚焦 / 跟随（2026-11-24 Phase 2：与播放行合并成一条 34px）。
       润色 / 导出在顶栏，代理与原文 / 译文轨的导入删除在「⋯」里。 -->
  <div class="tl-sep"></div>
  <div class="zoom-group">
    <button class="zbtn" onclick={() => onZoomAt(time, 1.5)} title="缩小波形" aria-label="缩小波形">
      <Icon name="minus" size={12} />
    </button>
    <input
      class="zoom-slider"
      type="range"
      min="0"
      max="100"
      step="1"
      value={sliderValue}
      style="--zoom-pct:{sliderValue}%"
      oninput={onZoomSlider}
      title="波形缩放"
      aria-label="波形缩放"
    />
    <button
      class="zbtn"
      onclick={() => onZoomAt(time, 1 / 1.5)}
      title="放大波形（滚轮 / 捏合同效）"
      aria-label="放大波形"
    >
      <Icon name="plus" size={12} />
    </button>
    <span class="zoom-x">{zoomX >= 10 ? Math.round(zoomX) : zoomX.toFixed(1)}×</span>
  </div>
  <button class="mini-text" onclick={onFit} title="显示全片">全景</button>
  <button class="mini-text" onclick={onFocusPlayhead} title="聚焦到播放头并放大">聚焦</button>
  <div class="grow"></div>
  <button
    class="follow-pill"
    class:on={follow}
    aria-pressed={follow}
    onclick={onToggleFollow}
    title={follow
      ? '跟随中：播放与跳转时保持播放头在视窗内；缩放/平移不会关闭它'
      : '开启后，播放或跳转字幕时波形会跟随播放头'}
  >
    <i></i>{follow ? '跟随中' : '跟随'}
  </button>

  <SelectionBar
    {selection}
    {laneSelection}
    {rangeBusy}
    onDelete={onDelete}
    onTranscribe={onTranscribe}
    onFocus={onFocusSelection}
    onSendSelection={onSendSelection}
    onSeekSelection={onSeekSelection}
    onClearLane={onClearLane}
    onClearSelection={onClearSelection}
  />
</div>

<style>
  /* 单行走带条 34px（2026-11-24 Phase 2）：左 = 播放 + 等宽时间码 + 进度 + 时长，
     右 = 缩放 / 全景 / 聚焦 / 跟随。原来拆两行（32 + 30 + 间距）白吃掉 35px 垂直高度。 */
  .transport {
    position: relative;
    display: flex;
    align-items: center;
    gap: 9px;
    height: 34px;
    flex: 0 0 34px;
    margin-top: 6px;
    padding: 0 26px;
  }
  .playbtn {
    width: 24px;
    height: 24px;
    flex: 0 0 24px;
    padding: 0;
    border-radius: 50%;
    border: 1px solid var(--line);
    background: var(--raise);
    color: var(--ink);
    display: grid;
    place-items: center;
    cursor: default;
    transition: border-color var(--dur) var(--ease), color var(--dur) var(--ease);
  }
  .playbtn:hover {
    border-color: var(--accent-line);
    color: var(--accent);
  }
  .tp-time {
    font-size: 12px;
    line-height: 16px;
    font-variant-numeric: tabular-nums;
    color: var(--text);
    font-family: var(--font-mono);
    letter-spacing: -0.01em;
    white-space: nowrap;
    min-width: 84px;
  }
  .tp-dur {
    font-size: 12px;
    line-height: 16px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    font-family: var(--font-mono);
    min-width: 38px;
    text-align: right;
  }
  .tp-rate {
    height: 18px;
    padding: 0 var(--sp-1);
    color: var(--accent);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }
  .tp-track {
    flex: 1;
    height: 16px; /* 比视觉轨道高：4px 的细线根本捏不住 */
    position: relative;
    cursor: pointer;
    touch-action: none;
    display: flex;
    align-items: center;
  }
  .tp-track::before {
    /* 悬停时给一条淡淡的底，提示这里可拖动 */
    content: '';
    position: absolute;
    inset: -2px -4px;
    border-radius: 4px;
    background: transparent;
    transition: background 120ms var(--ease);
  }
  .tp-track:hover::before,
  .tp-track.dragging::before {
    background: var(--accent-soft);
  }
  .tp-rail {
    position: relative;
    width: 100%;
    height: 3px;
    border-radius: 2px;
    background: var(--line);
    transition: height var(--dur-fast) var(--ease);
  }
  .tp-track:hover .tp-rail,
  .tp-track.dragging .tp-rail {
    height: 5px;
  }
  .tp-fill {
    position: absolute;
    inset: 0 auto 0 0;
    border-radius: 2px;
    background: var(--accent);
  }
  .tp-knob {
    position: absolute;
    top: 50%;
    width: 9px;
    height: 9px;
    margin-left: -4.5px;
    border-radius: 50%;
    background: var(--raise);
    border: 1px solid var(--accent);
    box-shadow: 0 1px 2px rgba(27, 39, 64, 0.18);
    transform: translateY(-50%);
    transition: transform var(--dur-fast) var(--ease);
  }
  .tp-track:hover .tp-knob,
  .tp-track.dragging .tp-knob {
    transform: translateY(-50%) scale(1.18);
  }

  /* 时间线第二行：只放时间轴工具 */
  /* 播放行与缩放行之间的竖分隔线：比一整行高度便宜得多 */
  .tl-sep {
    width: 1px;
    height: 14px;
    flex: 0 0 1px;
    background: var(--separator);
  }
  .zoom-group {
    display: flex;
    align-items: center;
    gap: var(--sp-1);
  }
  .zbtn {
    width: 20px;
    height: 20px;
    padding: 0;
    border: 0;
    border-radius: 4px;
    background: transparent;
    color: var(--ink-2);
    font-size: 14px;
    line-height: 1;
    display: grid;
    place-items: center;
    cursor: default;
    transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
  }
  .zbtn:hover {
    background: var(--line-2);
    color: var(--ink);
  }
  .zoom-slider {
    appearance: none;
    width: 64px;
    height: 14px;
    background: transparent;
    cursor: default;
  }
  /* 和播放进度同一种滑块语言：已选段实心 accent + 实心拇指 */
  .zoom-slider::-webkit-slider-runnable-track {
    height: 4px;
    border-radius: 2px;
    background: linear-gradient(
      to right,
      var(--accent) var(--zoom-pct, 0%),
      var(--line) var(--zoom-pct, 0%)
    );
  }
  .zoom-slider::-webkit-slider-thumb {
    appearance: none;
    width: 10px;
    height: 10px;
    margin-top: -3px;
    border-radius: 50%;
    background: var(--accent);
    border: 0;
    box-shadow: 0 1px 2px rgba(27, 39, 64, 0.28);
  }
  .zoom-slider:hover::-webkit-slider-thumb {
    box-shadow: 0 0 0 3px var(--accent-soft);
  }
  .zoom-x {
    font-size: 12px;
    line-height: 16px;
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
    min-width: 32px;
    text-align: right;
    font-family: var(--font-mono);
  }
  .mini-text {
    height: 24px;
    padding: 0 7px;
    border: 0;
    border-radius: 4px;
    background: transparent;
    color: var(--ink-2);
    font: inherit;
    font-size: 12px;
    cursor: default;
    transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
  }
  .mini-text:hover {
    background: var(--line-2);
    color: var(--ink);
  }
  .grow {
    flex: 1;
  }
  .follow-pill {
    height: 24px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 0 var(--sp-2);
    border: 0;
    border-radius: 4px;
    background: transparent;
    color: var(--ink-2);
    font: inherit;
    font-size: 12px;
    font-weight: 500;
    cursor: default;
  }
  .follow-pill i {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--ink-3);
  }
  .follow-pill.on {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .follow-pill.on i {
    background: var(--accent);
  }
  .follow-pill:hover {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .tl-spacer {
    flex: 1;
  }
</style>
