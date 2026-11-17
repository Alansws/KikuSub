/**
 * 时间轴视窗（起点 + 跨度）的纯数学。
 *
 * 从 `ReviewView.svelte` 抽出：缩放、平移、聚焦 69×、全片适应的边界规则都在这里，
 * 组件只负责把结果写回 `viewStart / viewSpan`。这样「duration/69」和视窗 clamp
 * 只有一份实现，红线 6 的既有口径不会因为加功能而分叉。
 */

export interface TimelineView {
  start: number;
  span: number;
}

export interface TimelineFitState {
  view: TimelineView;
  saved: TimelineView | null;
  fitted: boolean;
}

/** 把视窗夹进 `[0, duration - span]`；媒体未就绪时用当前跨度兜底。 */
export function clampTimelineView(
  start: number,
  span: number,
  duration: number,
  minSpan: number,
): TimelineView {
  const d = duration || span;
  const s = Math.max(minSpan, Math.min(span, d || minSpan));
  const a = Math.max(0, Math.min(start, Math.max(0, d - s)));
  return { start: a, span: s };
}

/** 以 `at` 为中心缩放：保持该时间点在屏幕上的相对位置。 */
export function zoomTimelineView(
  view: TimelineView,
  at: number,
  factor: number,
  duration: number,
  minSpan: number,
): TimelineView {
  const nextSpan = Math.max(minSpan, Math.min(duration || view.span, view.span * factor));
  const ratio = (at - view.start) / (view.span || 1);
  return clampTimelineView(at - ratio * nextSpan, nextSpan, duration, minSpan);
}

/**
 * 聚焦跨度：媒体就绪时固定 `duration / zoom`（默认 69×），
 * 未就绪时才退回 2–12 秒。禁止改成会随当前缩放叠加的公式。
 */
export function focusTimelineSpan(
  duration: number,
  viewSpan: number,
  minSpan: number,
  zoom: number,
): number {
  if (duration > 0) return Math.max(minSpan, duration / zoom);
  return Math.max(2, Math.min(12, viewSpan / 6 || 6));
}

/** 缩放滑杆值（0=全景，100=最深）→ 视窗跨度。 */
export function sliderToSpan(value: number, duration: number, minSpan: number): number {
  const d = duration || 60;
  const min = Math.max(minSpan, Math.min(1.2, d / 400));
  return d * Math.pow(min / d, value / 100);
}

/** 视窗跨度 → 缩放滑杆值。 */
export function spanToSlider(span: number, duration: number, minSpan: number): number {
  const d = duration || 60;
  const min = Math.max(minSpan, Math.min(1.2, d / 400));
  const safe = Math.max(min, span);
  const v = (Math.log(safe / d) / Math.log(min / d)) * 100;
  return Math.max(0, Math.min(100, v));
}

/**
 * 跳转 / 播放时把播放头带回视窗。
 *
 * 跟随关闭、媒体未就绪、播放头已经在视窗内时都不动；从右侧出去就从左侧 15%
 * 处回来，反之亦然，缩放比例保持不变。
 */
export function revealTimelineView(
  view: TimelineView,
  time: number,
  duration: number,
  minSpan: number,
  follow: boolean,
): TimelineView {
  if (!follow || !(view.span > 0) || !(duration > 0)) return view;
  if (time >= view.start && time <= view.start + view.span) return view;
  const anchor = time > view.start + view.span ? 0.85 : 0.15;
  return clampTimelineView(time - view.span * anchor, view.span, duration, minSpan);
}

/** 全片适应。 */
export function fitTimelineView(
  duration: number,
  viewSpan: number,
  minSpan: number,
): TimelineView {
  return clampTimelineView(0, duration || viewSpan, duration, minSpan);
}
