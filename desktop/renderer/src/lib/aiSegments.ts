/**
 * 长片双源润色的智能分段（纯函数，无 DOM / 无网络）。
 *
 * 外部网页模型一次吃不下「A 全量 + B 全量」时，按 A 的条数切段：以目标条数为
 * 基准，在前后容差内找 **A/B 相邻句之间静音间隙最大** 的边界，避免在对话中间
 * 断开。每段仍保留 A 的真实全局序号，粘贴回来按序号区间回填，零时间戳冲突。
 */

import type { Cue } from './api';

export interface AiSegment {
  /** 1 基、含两端（与用户看到的「第 k~m 条」一致）。 */
  from: number;
  to: number;
  /** 该段 A 的时间范围（秒），用于界面显示与提示词前缀。 */
  start: number;
  end: number;
  count: number;
}

export interface SegmentOptions {
  /** 目标每段 A 条数，默认 150。 */
  targetCues?: number;
  /** 前后容差（条数），默认 20。 */
  toleranceCues?: number;
  /** 前后容差（秒），默认 120。 */
  toleranceSeconds?: number;
  /** 判定「长片」的总条数阈值（A+B），默认 300。 */
  maxCues?: number;
  /** 判定「长片」的总字符阈值（A+B），默认 120000。 */
  maxChars?: number;
}

const DEFAULTS = {
  targetCues: 150,
  toleranceCues: 20,
  toleranceSeconds: 120,
  maxCues: 300,
  maxChars: 120_000,
};

function opts(options: SegmentOptions) {
  return { ...DEFAULTS, ...options };
}

/** A+B 是否已经大到不该一次整片复制（超过任一阈值）。 */
export function needsSegments(
  cuesA: Cue[],
  cuesB: Cue[] = [],
  options: SegmentOptions = {},
): boolean {
  const o = opts(options);
  if (cuesA.length + cuesB.length > o.maxCues) return true;
  const chars =
    cuesA.reduce((n, cue) => n + (cue.text?.length ?? 0), 0) +
    cuesB.reduce((n, cue) => n + (cue.text?.length ?? 0), 0);
  return chars > o.maxChars;
}

/** 边界处的静音分：越大越适合断开。 */
function boundaryScore(cuesA: Cue[], cuesB: Cue[], index: number): number {
  const prev = cuesA[index - 1];
  const next = cuesA[index];
  if (!prev || !next) return Number.NEGATIVE_INFINITY;
  const at = (prev.end + next.start) / 2;
  const gapA = Math.max(0, next.start - prev.end);

  // B 的时间轴与 A 不完全一致：找跨过边界时间点的相邻两条 B，取它们之间的间隙。
  let gapB = 0;
  if (cuesB.length) {
    let before: Cue | null = null;
    let after: Cue | null = null;
    for (const cue of cuesB) {
      if (cue.end <= at) before = cue;
      else if (!after && cue.start >= at) after = cue;
    }
    if (before && after) gapB = Math.max(0, after.start - before.end);
    else if (before) gapB = Math.max(0, at - before.end);
    else if (after) gapB = Math.max(0, after.start - at);
  }
  // 两边都安静最好；至少一边有停顿也可以接受。
  return gapA + gapB * 0.7;
}

/**
 * 把 A 切成若干段。返回值始终覆盖 `1..cuesA.length`，不重叠、不遗漏。
 * A 为空或不超过目标条数时返回一段（或空数组）。
 */
export function planSegments(
  cuesA: Cue[],
  cuesB: Cue[] = [],
  options: SegmentOptions = {},
): AiSegment[] {
  const o = opts(options);
  const total = cuesA.length;
  if (total === 0) return [];
  const target = Math.max(1, Math.floor(o.targetCues));
  const segments: AiSegment[] = [];
  let from = 1;

  while (from <= total) {
    const remaining = total - from + 1;
    if (remaining <= target + o.toleranceCues) {
      segments.push(makeSegment(cuesA, from, total));
      break;
    }
    const ideal = from + target; // 下一段的起点（1 基）
    const lo = Math.max(from + 1, ideal - o.toleranceCues);
    const hi = Math.min(total, ideal + o.toleranceCues);
    let best = ideal;
    let bestScore = Number.NEGATIVE_INFINITY;
    for (let boundary = lo; boundary <= hi; boundary += 1) {
      // 边界过于贴近段首/段尾都不合适
      if (boundary - from < Math.floor(target / 3)) continue;
      if (total - boundary < Math.floor(target / 3)) continue;
      const score = boundaryScore(cuesA, cuesB, boundary);
      if (score > bestScore) {
        bestScore = score;
        best = boundary;
      }
    }
    segments.push(makeSegment(cuesA, from, best));
    from = best + 1;
  }
  return segments;
}

function makeSegment(cuesA: Cue[], from: number, to: number): AiSegment {
  return {
    from,
    to,
    start: cuesA[from - 1]?.start ?? 0,
    end: cuesA[to - 1]?.end ?? 0,
    count: to - from + 1,
  };
}
