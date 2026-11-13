/**
 * 第二引擎复核的纯函数（P1-1 段二）。
 *
 * 这里只做「选中哪些条 → 发什么 payload」，不碰状态与网络：
 * 服务端会再用同一套规则夹窗口（`core.second_opinion.clamp_window`），
 * 前端传 `prev_end` / `next_start` 是为了让服务端知道相邻字幕在哪。
 */

import type { Cue } from './api';

export interface CompareRange {
  index: number;
  start: number;
  end: number;
  prev_end?: number;
  next_start?: number;
}

/** 日语两个引擎互为「另一引擎」；当前是其他引擎时默认用 qwen。 */
export function otherEngineKey(current: string): string {
  return current === 'qwen' ? 'whisper' : 'qwen';
}

/**
 * 把选中的字幕下标转成复核区间。
 *
 * 邻句边界取**时间上的前一条/后一条**，不是下标 ±1：时间轴可能被导入的字幕打乱顺序，
 * 按下标取会把不相邻的句子当成邻居，窗口就夹错了。
 */
export function buildRanges(cues: Cue[], indices: number[]): CompareRange[] {
  const unique = [...new Set(indices)].filter((i) => i >= 0 && i < cues.length).sort((a, b) => a - b);
  return unique.map((index) => {
    const cue = cues[index];
    let prevEnd: number | undefined;
    let nextStart: number | undefined;
    for (let i = 0; i < cues.length; i += 1) {
      if (i === index) continue;
      const other = cues[i];
      if (other.end <= cue.start + 1e-6) {
        prevEnd = prevEnd === undefined ? other.end : Math.max(prevEnd, other.end);
      }
      if (other.start >= cue.end - 1e-6) {
        nextStart = nextStart === undefined ? other.start : Math.min(nextStart, other.start);
      }
    }
    const range: CompareRange = { index, start: cue.start, end: cue.end };
    if (prevEnd !== undefined) range.prev_end = prevEnd;
    if (nextStart !== undefined) range.next_start = nextStart;
    return range;
  });
}

/** 按时间找质检条目对应的字幕下标；`miss` 组那种没有字幕的区间返回 -1。 */
export function cueIndexForRange(
  cues: Cue[],
  start: number,
  end: number,
  tolerance = 0.08,
): number {
  let best = -1;
  let bestOverlap = 0;
  for (let i = 0; i < cues.length; i += 1) {
    const cue = cues[i];
    const overlap = Math.min(cue.end, end) - Math.max(cue.start, start);
    const closeStart = Math.abs(cue.start - start) <= tolerance;
    if (closeStart && overlap > bestOverlap) {
      best = i;
      bestOverlap = overlap;
    } else if (overlap > bestOverlap && overlap >= (cue.end - cue.start) * 0.5) {
      best = i;
      bestOverlap = overlap;
    }
  }
  return best;
}
