/**
 * 字幕剪贴板的纯逻辑：复制什么、粘到哪里、会不会和邻句打架。
 *
 * 这里不 import 任何东西，`node --test` 可以直接加载（和 `punctuation.ts` 一样）。
 * 需要 store / 网络的接线在 `cueClipboard.svelte.ts`，UI 只读这里算出来的结果。
 */

/** 一句字幕在剪贴板里的样子。 */
export interface CueClip {
  /** 原文（多行也原样保留）。 */
  text: string;
  /** 原句时长（秒）。粘贴时按这个长度铺开。 */
  duration: number;
  /** lang -> 该语种的译文与生成时的原文快照。 */
  translations: Record<string, CueClipTranslation>;
  /** 来源句起点，仅用于提示，不参与粘贴计算。 */
  sourceStart: number;
}

export interface CueClipTranslation {
  text: string;
  /**
   * 生成这句译文时的原文快照。
   *
   * 必须原样带到新句：原来过期的译文（base ≠ 当前原文）在新句上也应当继续
   * 显示为「需要同步」，不能因为粘贴一次就伪装成已同步。
   */
  base: string;
}

export interface CueSpan {
  start: number;
  end: number;
}

export interface PastePlan {
  start: number;
  end: number;
  /** 新句插进 `cues` 的下标（按 start 排序的位置）。 */
  index: number;
  /** 与现有字幕的最大重叠秒数；0 表示没有重叠。 */
  overlapSeconds: number;
  /** 与多少条现有字幕重叠。 */
  overlapCount: number;
  /** 是否因为片尾不够长而缩短了结束时间。 */
  clamped: boolean;
}

export type PastePlanResult =
  | { ok: true; plan: PastePlan }
  | { ok: false; reason: string };

/** 最短字幕：与插入空字幕、切割的最小间隔保持一致。 */
export const MIN_CUE_LENGTH = 0.05;

const round3 = (value: number) => Math.round(value * 1000) / 1000;

/**
 * 计算「把剪贴板里这句贴到 at」的时间与下标。
 *
 * 规则（2026-11-17 用户确认）：
 * - 起点就是播放头，不居中；
 * - 长度沿用复制句，不按邻句自动裁切；
 * - 只有片尾不够长时才把 end 收到片尾；
 * - 与邻句重叠不拒绝，只把重叠量报回去给 UI 提示（绝不自动改邻句）。
 */
export function planCuePaste(input: {
  at: number;
  length: number;
  cues: readonly CueSpan[];
  /** 媒体总时长；0 / 缺省表示未知，不做片尾 clamp。 */
  mediaDuration?: number;
}): PastePlanResult {
  if (!Number.isFinite(input.at) || !Number.isFinite(input.length)) {
    return { ok: false, reason: '播放头位置无效，无法粘贴' };
  }
  if (input.length < MIN_CUE_LENGTH) {
    return { ok: false, reason: '这句字幕太短，无法粘贴' };
  }

  const media = Number(input.mediaDuration ?? 0);
  let start = round3(Math.max(0, input.at));
  let end = round3(start + input.length);
  let clamped = false;

  if (media > 0) {
    if (start >= media - MIN_CUE_LENGTH) {
      return { ok: false, reason: '播放头太靠近片尾，放不下这条字幕' };
    }
    if (end > media) {
      end = round3(media);
      clamped = true;
    }
  }
  if (end - start < MIN_CUE_LENGTH) {
    return { ok: false, reason: '播放头太靠近片尾，放不下这条字幕' };
  }

  // 插在「第一条起点严格晚于新句起点」的前面；与现有插入空字幕的口径一致。
  const index = input.cues.findIndex((cue) => cue.start > start + 0.0005);
  const insertAt = index < 0 ? input.cues.length : index;

  let overlapSeconds = 0;
  let overlapCount = 0;
  for (const cue of input.cues) {
    const overlap = Math.min(end, cue.end) - Math.max(start, cue.start);
    if (overlap > 0.001) {
      overlapCount += 1;
      overlapSeconds = Math.max(overlapSeconds, overlap);
    }
  }

  return {
    ok: true,
    plan: {
      start,
      end,
      index: insertAt,
      overlapSeconds: round3(overlapSeconds),
      overlapCount,
      clamped,
    },
  };
}

/** 剪贴板里的一句，压成一行给检查器 / toast 用。 */
export function clipSummary(clip: CueClip, max = 18): string {
  const text = clip.text.replace(/\s+/g, ' ').trim();
  const shown = text.length > max ? `${text.slice(0, max)}…` : text;
  const hasTranslation = Object.values(clip.translations).some((item) => item.text.trim());
  const suffix = hasTranslation ? ' · 含译文' : '';
  return `「${shown}」· ${clip.duration.toFixed(2)}s${suffix}`;
}
