/**
 * 第二引擎复核的纯函数（P1-1 段二）。
 *
 * 这里只做「选中哪些条 → 发什么 payload」，不碰状态与网络：
 * 服务端会再用同一套规则夹窗口（`core.second_opinion.clamp_window`），
 * 前端传 `prev_end` / `next_start` 是为了让服务端知道相邻字幕在哪。
 */

import type { Cue } from './api';

/** 一次最多复核多少条；与 `core.second_opinion.MAX_WINDOWS` 保持一致。 */
export const MAX_BATCH = 40;

export interface CompareRange {
  index: number;
  start: number;
  end: number;
  prev_end?: number;
  next_start?: number;
}

/**
 * 两个日语引擎互为「另一引擎」；当前是其他引擎时默认用 qwen。
 *
 * 只做 `pickReviewEngine()` 的兜底：用户选过的引擎优先。语种不同的引擎不会进
 * 候选（`sharesLanguage()`），所以这里的兜底不会把中文引擎送进日语复核。
 */
export function otherEngineKey(current: string): string {
  return current === 'qwen' ? 'whisper' : 'qwen';
}

/** 一比一送复核的引擎选项（注册表提供能力与安装态，这里只做纯逻辑）。 */
export interface ReviewEngineChoice {
  key: string;
  label: string;
  /** 设置里启用：停用的引擎不在复核下拉里可选。 */
  enabled: boolean;
  /** 权重已下载：没下载的引擎跑不了，选项里置灰。 */
  installed: boolean;
}

/**
 * 选出「另一引擎」。
 *
 * 用户选过且仍然可用就尊重用户；否则退回两引擎互斥的默认（当前是 Qwen 就用
 * Whisper，反之亦然）；再不行取注册表顺序里第一个已就绪的。返回空串表示
 * 没有可用的复核引擎，界面据此禁用按钮并给出原因。
 */
export function pickReviewEngine(
  choices: ReviewEngineChoice[],
  current: string,
  preferred = '',
): string {
  const ready = choices.filter((item) => item.enabled && item.installed && item.key !== current);
  if (!ready.length) return '';
  if (preferred && ready.some((item) => item.key === preferred)) return preferred;
  const fallback = otherEngineKey(current);
  return ready.find((item) => item.key === fallback)?.key ?? ready[0].key;
}

/**
 * 两个引擎能不能复核同一句：至少要共享一种语种。
 *
 * 用中文引擎去复核日语字幕只会拿到乱码般的文本，用户还会以为「另一引擎更差」。
 * 语种未知（旧注册表 / 导入稿）时不限制，交给 `reviewable` 能力位把关。
 */
export function sharesLanguage(a?: string[], b?: string[]): boolean {
  if (!a?.length || !b?.length) return true;
  const known = new Set(a);
  return b.some((language) => known.has(language));
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
