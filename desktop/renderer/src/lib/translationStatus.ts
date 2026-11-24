/**
 * 译文轨的两种「不可信」状态，必须分开数：
 *
 * - **待译**：这一条还没有译文（空串）——局部转写新加进来的句子；
 * - **原文已改**：有译文，但它是对着旧原文翻的，需要人看一眼。
 *
 * 混成一个 stale 会让用户看到「N 条待更新」却找不到哪一条真要改（2026-11-25
 * 用户报障）。只动句读的改动在服务端写 base 时已经对齐，不会进这里。
 *
 * 纯函数 + 零运行时 import（`node --test` 直接加载），单测在
 * `desktop/test/translation-status.test.mjs`。
 */
import type { Cue, TranslationTrack } from './api';

export interface PendingCounts {
  gap: number;
  stale: number;
}

/** 这一条有译文、但原文已经改过（空译文算待译，不算过期）。 */
export function cueIsStale(
  track: TranslationTrack | undefined,
  index: number,
  cues: ReadonlyArray<Cue>,
): boolean {
  if (!track) return false;
  if (!track.texts[index]) return false;
  const base = track.base ?? [];
  if (index >= base.length) return true;
  return base[index] !== (cues[index]?.text ?? '');
}

export function countPending(
  track: TranslationTrack | undefined,
  cues: ReadonlyArray<Cue>,
): PendingCounts {
  const out: PendingCounts = { gap: 0, stale: 0 };
  if (!track) return out;
  for (let i = 0; i < cues.length; i += 1) {
    if (!track.texts[i]) out.gap += 1;
    else if (cueIsStale(track, i, cues)) out.stale += 1;
  }
  return out;
}
