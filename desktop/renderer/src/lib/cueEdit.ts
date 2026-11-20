/**
 * 字幕时间点的纯校验（入点 / 出点 / 切割）。
 *
 * 从 `ReviewView.svelte` 与右键菜单抽出：键盘切割和右键切割必须共用同一个 0.05 秒
 * 边距，否则同一个播放头位置会出现「右键能切、快捷键不能切」。
 */

import type { Cue } from './api';

/** 与切割接口、拖动夹紧保持一致的最短字幕。 */
export const MIN_CUE_LENGTH = 0.05;

/** 在 `time` 处能把这条字幕切开吗（两端各留 0.05 秒）。 */
export function canSplitAt(cue: Pick<Cue, 'start' | 'end'>, time: number): boolean {
  return time > cue.start + MIN_CUE_LENGTH && time < cue.end - MIN_CUE_LENGTH;
}

export type TimeAlignResult =
  | { ok: true; time: number }
  | { ok: false; reason: string };

function clampToMedia(time: number, duration: number): number {
  const lower = Math.max(0, time);
  return duration > 0 ? Math.min(lower, duration) : lower;
}

/** 入点对齐播放头：不能压到出点（至少留 0.05 秒）。 */
export function alignCueStart(
  cue: Pick<Cue, 'start' | 'end'>,
  time: number,
  duration: number,
): TimeAlignResult {
  const t = clampToMedia(time, duration);
  if (t >= cue.end - MIN_CUE_LENGTH) {
    return { ok: false, reason: '播放头太靠近出点，不能作为入点' };
  }
  return { ok: true, time: Math.round(t * 1000) / 1000 };
}

/** 出点对齐播放头：不能压到入点（至少留 0.05 秒）。 */
export function alignCueEnd(
  cue: Pick<Cue, 'start' | 'end'>,
  time: number,
  duration: number,
): TimeAlignResult {
  const t = clampToMedia(time, duration);
  if (t <= cue.start + MIN_CUE_LENGTH) {
    return { ok: false, reason: '播放头太靠近入点，不能作为出点' };
  }
  return { ok: true, time: Math.round(t * 1000) / 1000 };
}
