/**
 * 核对台「第一次打开这部片」的默认现场（纯函数 + 一个进程内标记）。
 *
 * 解决两个默认态问题（2026-11-21，Step 3）：
 *
 * 1. **长片打开时是全片 1.0×、播放头停在 0**。整部片压进两三百像素的波形里，
 *    什么也看不清；播放头停在片头，片头常常是黑场 / 淡入，用户看到的第一眼就是
 *    一块黑 + 一条挤成一根线的波形。有本机现场快照时走 `reviewViewport` 恢复，
 *    没有快照时按这里给的默认现场：**聚焦第 1 条字幕、默认约 50× 视野**。
 * 2. **已挂译文轨时默认只显示原文**。核对台的主要用户是日语学习者 / 生肉，
 *    有译文就该两行一起看。本次启动只在第一次真正满足「有译文轨 + 当前是原文」
 *    时生效一次，之后绝不覆盖用户自己的选择（`app.track` 仍写
 *    `localStorage['kikusub.track']`）。
 *
 * 纯函数只回「计划」，夹紧 / seek 由组件按自己的时机执行（播放头要等
 * `loadedmetadata`，缩放要等 `duration`）。
 */

/** 默认视野倍率：`duration / 50` 秒的窗口（2 小时片约 144 秒，和「聚焦」69× 同量级）。 */
export const INITIAL_VIEW_ZOOM = 50;

/**
 * 默认视野的下限（秒）。短片（十几秒的测试片 / 单个片段）除以 50 会得到
 * 0.3 秒这种不实用的窗口，所以给一个「看得见上下文」的下限。
 */
export const MIN_INITIAL_SPAN = 2;

/** 第 1 条字幕放在窗口偏左的位置，左边留约 1/4 的上下文。 */
const LEAD_RATIO = 0.25;

/**
 * 短片（≤ 60 秒）不缩：样片、片段、测试片本来就是几十秒，
 * 全片视图一眼看得完，放大反而是「看不到全貌」。
 * 50× 视野解决的是长片被压成一根线的问题。
 */
export const SHORT_FILM_SECONDS = 60;

/** 播放头落在开头这个范围里就不打扰用户（与 `planViewportRestore` 同口径）。 */
const NEAR_ZERO = 0.2;

export interface InitialReviewView {
  /** 默认选中第 1 条字幕。 */
  cueIndex: number;
  /** 要 seek 到的位置；null 表示本来就该待在 0，不必动播放头。 */
  seekTo: number | null;
  /** 视窗起点（秒）。 */
  viewStart: number;
  /** 视窗跨度（秒）。 */
  span: number;
}

/**
 * 没有本机现场快照时的默认现场：选中第 1 条字幕 + `duration / 50` 的视野。
 *
 * 返回 null 表示「没有可用的默认态」（还没有字幕 / 还没有时长），调用方不要动
 * 任何状态——保持全片视图比跳到错误位置更安全。
 */
export function planInitialReviewView(
  duration: number,
  cues: { start: number; end: number }[],
  minSpan: number,
): InitialReviewView | null {
  const d = Number.isFinite(duration) ? Math.max(0, duration) : 0;
  if (d <= 0 || !cues.length) return null;

  const first = cues[0];
  const start = Number.isFinite(first.start) ? Math.max(0, Math.min(first.start, d)) : 0;
  const maxSpan = Math.max(1, d); // span=0 的时间轴是无意义的
  const floor = Math.max(minSpan, MIN_INITIAL_SPAN);
  const span =
    d <= SHORT_FILM_SECONDS
      ? maxSpan
      : Math.min(maxSpan, Math.max(floor, d / INITIAL_VIEW_ZOOM));
  const viewStart = Math.max(0, Math.min(start - span * LEAD_RATIO, maxSpan - span));

  return {
    cueIndex: 0,
    seekTo: start > NEAR_ZERO ? start : null,
    viewStart,
    span,
  };
}

// ---------------------------------------------------------------------------
// 「有译文轨就默认双语」只在本次启动生效一次
// ---------------------------------------------------------------------------

/**
 * 进程内标记，不落盘。
 *
 * 落盘会让「用户明确选回原文」变成一次性设置（下次启动又被翻成双语）；
 * 完全不记又会在每次换片 / 切页回来时再翻一次，用户选了原文又被改回去。
 * 所以本次启动只问一次：第一次「有译文轨且当前是原文」时翻成双语，之后不管。
 */
let translationDefaultClaimed = false;

/** 取走「本次启动还没用过双语默认」这个名额；已用过返回 false。 */
export function claimTranslationDefault(): boolean {
  if (translationDefaultClaimed) return false;
  translationDefaultClaimed = true;
  return true;
}

/** 仅供测试：把名额还回去。 */
export function resetTranslationDefault(): void {
  translationDefaultClaimed = false;
}
