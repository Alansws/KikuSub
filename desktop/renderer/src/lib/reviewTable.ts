/**
 * 字幕表的虚拟列表口径（纯计算，无 Svelte 依赖）。
 *
 * 2026-11-24 从 `ReviewView.svelte` 抽出来（界面原生化 Phase 2 前置）：那个文件有
 * 行数预算（红线 11，只许变短），而这次要给表格加状态列、还要调行高——**先抽、再改**。
 *
 * 为什么是「固定行高」而不是自动测量：双语是固定双行高，TTS 朗读条 / 长句换行都
 * 不能改变行高，否则绝对定位的虚拟滚动会算错偏移（开发文档 §6.3.2 踩过）。
 * 所以行高必须是这里算出来的一个确定值，任何需要更高行的地方去改 `ROW_H`，
 * 不要在渲染里插一段自动测量。
 */

/** 单行高（原文 / 译文 单语种模式）。双语 = 2×。 */
export const ROW_H = 30;

/** 可视区上下各多渲染几行，滚动时不会露白。 */
export const OVERSCAN = 7;

/** 还没有测量到可视高度时的兜底，避免首帧只渲染几行。 */
export const FALLBACK_VIEW_H = 400;

/** 行高只取决于显示模式：双语是固定双行。 */
export function rowHeightFor(track: string): number {
  return track === 'both' ? ROW_H * 2 : ROW_H;
}

/**
 * `Math.max(0, NaN)` 还是 NaN —— 从未测量过的 `clientHeight` / 刚挂载的
 * `scrollTop` 都可能给 NaN，一旦漏进去，整个窗口计算会算出 NaN 行号、
 * 渲染出 0 行。所以统一在入口处兜住。
 */
function safe(value: number): number {
  return Number.isFinite(value) ? Math.max(0, value) : 0;
}

export interface VirtualWindow {
  start: number;
  end: number;
  /** 顶部占位高度（已滚过的行），保留绝对偏移。 */
  padTop: number;
  /** 底部占位高度（还没滚到的行）。 */
  padBottom: number;
}

/**
 * 当前该渲染哪一段。
 *
 * 纯函数：同样的 (scrollTop, viewH, total, rowH) 永远给同样的窗口，
 * 因此可以在单测里断言，不依赖 DOM。
 */
export function virtualWindow(opts: {
  scrollTop: number;
  viewH: number;
  total: number;
  rowH: number;
  overscan?: number;
}): VirtualWindow {
  const { scrollTop, viewH, total, rowH } = opts;
  const overscan = opts.overscan ?? OVERSCAN;
  const h = Math.max(1, rowH);
  const start = Math.max(0, Math.floor(safe(scrollTop) / h) - overscan);
  const end = Math.min(
    Math.max(0, total),
    start + Math.ceil((viewH || FALLBACK_VIEW_H) / h) + overscan * 2,
  );
  return {
    start,
    end,
    padTop: start * h,
    padBottom: Math.max(0, (total - end) * h),
  };
}

/**
 * 把第 `index` 行滚进视野时的目标 `scrollTop`。
 *
 * 行为口径（2026-11-21 起）：已经在可视区中间就不动，避免播放时每句都抖一下；
 * 需要滚时把目标行放在可视区约 40% 处，让上下文还在上面。
 * 返回 `null` = 不用滚。
 */
export function revealScrollTop(opts: {
  index: number;
  scrollTop: number;
  viewH: number;
  rowH: number;
}): number | null {
  const { index, scrollTop, viewH, rowH } = opts;
  const h = Math.max(1, rowH);
  const top = index * h;
  const viewTop = safe(scrollTop);
  const viewBottom = viewTop + viewH;
  if (top >= viewTop + h * 2 && top + h <= viewBottom - h * 2) return null;
  const above = Math.max(1, Math.floor((viewH * 0.4) / h));
  return Math.max(0, (index - above) * h);
}
