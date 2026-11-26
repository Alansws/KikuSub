/**
 * 章节区间端点拖动的纯数学（端点能被拖到哪、落库前怎么取整）。
 *
 * 与服务端 `core/chapters.py` 的归一化口径保持一致，用户拖的时候看到的就是
 * 保存后的结果：
 * - 起点夹进 `[0, 终点 - 最短长度]`；
 * - 终点夹进 `[起点 + 最短长度, 下一条标记的起点 / 片尾]`（防重叠：后一个标记
 *   一开始，前一个必须结束）。
 *
 * 零导入：`node --test` 直接加载 `.ts`（同 `lib/scrub.ts`）。
 */


/** 章节最短长度（秒）：与 `lib/chapterDraft.ts` 同一口径。 */
export const MIN_MARK_SPAN = 0.2;

export type MarkEdge = 'start' | 'end';

export interface EdgeInput {
  edge: MarkEdge;
  /** 拖动前的区间（秒）。 */
  start: number;
  end: number;
  /** 下一条标记的起点；没有下一条就传片尾。 */
  nextStart: number;
  /** 媒体时长；未知时传 0。 */
  duration: number;
}

/** 这一端能被拖到的范围（秒）。 */
export function edgeBounds(input: EdgeInput): { lo: number; hi: number } {
  const duration = input.duration > 0 ? input.duration : Number.POSITIVE_INFINITY;
  if (input.edge === 'start') {
    return { lo: 0, hi: Math.max(0, Math.min(input.end - MIN_MARK_SPAN, duration)) };
  }
  const lo = Math.max(0, input.start + MIN_MARK_SPAN);
  // nextStart 为 0 表示「没有下一条标记」：上限交给片尾（未知时长时就是无穷）
  const limit = input.nextStart > 0 ? input.nextStart : duration;
  return { lo, hi: Math.max(lo, Math.min(limit, duration)) };
}

/** 把拖到的时间夹进范围。 */
export function clampEdgeTime(time: number, bounds: { lo: number; hi: number }): number {
  if (!Number.isFinite(time)) return bounds.lo;
  return Math.max(bounds.lo, Math.min(bounds.hi, time));
}

/** 落库前的毫秒取整（与 `addRangeChapter` / 服务端一致）。 */
export function roundMs(t: number): number {
  return Math.round(t * 1000) / 1000;
}
