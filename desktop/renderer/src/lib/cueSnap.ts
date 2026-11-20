/**
 * 底部字幕轨道拖拽的磁吸（纯函数）。
 *
 * 只处理「字幕块拖动」：吸附播放头与邻句边缘，参考线由调用方绘制。
 * 不碰单击跳转 / 4px 框选 / 播放头擦洗 / 进度条——那些路径根本不会调用这里。
 */

import type { Cue } from './api';

/** 抓取半径（像素）。换算成秒后还会被 `MAX_SNAP_SECONDS` 封顶。 */
export const SNAP_PX = 7;
export const MIN_SNAP_SECONDS = 0.02;
export const MAX_SNAP_SECONDS = 0.12;
/** 与切割 / 拖动夹紧一致的最短字幕。 */
const MIN_CUE_LENGTH = 0.05;

export interface SnapResult {
  start: number;
  end: number;
  /** 命中的参考线时间；没有吸附为 null。 */
  guide: number | null;
}

const round3 = (value: number) => Math.round(value * 1000) / 1000;

/**
 * 像素抓取半径 → 秒。
 *
 * 全片视图下 7px 可能是十几秒，必须封顶 120ms；放大到 69× 时也不至于吸附过远。
 * 波形宽度 / 视窗无效时返回一个保守值。
 */
export function snapThreshold(waveW: number, viewSpan: number): number {
  if (!(waveW > 0) || !(viewSpan > 0)) return 0.05;
  const pxPerSec = waveW / viewSpan;
  const seconds = SNAP_PX / Math.max(pxPerSec, 1e-6);
  return Math.max(MIN_SNAP_SECONDS, Math.min(MAX_SNAP_SECONDS, seconds));
}

/**
 * 吸附候选：播放头 + 0 / 片尾 + 所有**未被拖动**字幕的起止。
 * 去重并排序；被拖动的下标必须排除，否则会吸到自己。
 */
export function collectSnapTargets(
  cues: readonly Pick<Cue, 'start' | 'end'>[],
  excludeIndices: readonly number[],
  playhead: number,
  duration: number,
): number[] {
  const exclude = new Set(excludeIndices);
  const values = new Set<number>();
  const push = (value: number) => {
    if (Number.isFinite(value) && value >= 0) values.add(round3(value));
  };
  push(playhead);
  push(0);
  if (duration > 0) push(duration);
  cues.forEach((cue, index) => {
    if (exclude.has(index)) return;
    push(cue.start);
    push(cue.end);
  });
  return [...values].sort((a, b) => a - b);
}

function nearest(
  edge: number,
  targets: readonly number[],
  threshold: number,
  activeGuide: number | null,
): number | null {
  if (!targets.length) return null;
  // 已经有参考线时扩大一点回滞半径，避免在阈值边缘来回跳。
  if (activeGuide !== null && Math.abs(edge - activeGuide) <= threshold * 1.4) {
    return activeGuide;
  }
  let best: number | null = null;
  let bestDelta = Number.POSITIVE_INFINITY;
  for (const target of targets) {
    const delta = Math.abs(edge - target);
    if (delta <= threshold && delta < bestDelta) {
      best = target;
      bestDelta = delta;
    }
  }
  return best;
}

function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

/**
 * 对一次拖动结果做吸附。
 *
 * - `move`：比较起点 / 终点到候选的距离，整体平移（保持时长）；
 * - `start` / `end`：只吸被拖的那一端；
 * - clamp 之后若边缘不再等于候选，参考线丢弃（不画一条骗人的线）。
 */
export function snapCueTimes(
  base: { start: number; end: number },
  edge: 'move' | 'start' | 'end',
  targets: readonly number[],
  threshold: number,
  max: number,
  activeGuide: number | null = null,
  enabled = true,
): SnapResult {
  const fallback = { start: base.start, end: base.end, guide: null as number | null };
  if (!enabled || !targets.length || !(threshold > 0)) return fallback;

  if (edge === 'move') {
    const dur = base.end - base.start;
    const startTarget = nearest(base.start, targets, threshold, activeGuide);
    const endTarget = nearest(base.end, targets, threshold, activeGuide);
    let delta = 0;
    let guide: number | null = null;
    if (startTarget !== null && (endTarget === null || Math.abs(startTarget - base.start) <= Math.abs(endTarget - base.end))) {
      delta = startTarget - base.start;
      guide = startTarget;
    } else if (endTarget !== null) {
      delta = endTarget - base.end;
      guide = endTarget;
    }
    if (guide === null) return fallback;
    const upper = max > 0 ? Math.max(0, max - dur) : Number.POSITIVE_INFINITY;
    const start = round3(clamp(base.start + delta, 0, upper));
    const end = round3(start + dur);
    const snappedTo = round3(guide);
    return {
      start,
      end,
      guide: Math.abs(start - snappedTo) < 1e-6 || Math.abs(end - snappedTo) < 1e-6 ? snappedTo : null,
    };
  }

  if (edge === 'start') {
    const target = nearest(base.start, targets, threshold, activeGuide);
    if (target === null) return fallback;
    const upper = base.end - MIN_CUE_LENGTH;
    const start = round3(clamp(target, 0, upper));
    const snappedTo = round3(target);
    return { start, end: base.end, guide: Math.abs(start - snappedTo) < 1e-6 ? snappedTo : null };
  }

  const target = nearest(base.end, targets, threshold, activeGuide);
  if (target === null) return fallback;
  const lower = base.start + MIN_CUE_LENGTH;
  const upper = max > 0 ? max : Number.POSITIVE_INFINITY;
  const end = round3(clamp(target, lower, upper));
  const snappedTo = round3(target);
  return { start: base.start, end, guide: Math.abs(end - snappedTo) < 1e-6 ? snappedTo : null };
}
