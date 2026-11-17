/**
 * 核对台的时间精修动作：入点 / 出点 / 切割 / 试听。
 *
 * 从 `App.svelte` 的快捷键直接调用；全部复用 store 的既有动作：
 * - `updateCue()` → 服务端一步历史；
 * - `splitCueAt()` → 服务端切割、两段保留完整原文；
 * - `previewRange()` → 播到句末由 `tick()` 自动暂停。
 */

import { app, play, previewRange, splitCueAt, toast, updateCue } from './store.svelte';
import { alignCueEnd, alignCueStart, canSplitAt, MIN_CUE_LENGTH } from './cueEdit';

function selectedCue() {
  return app.cues[play.selected] ?? null;
}

function mediaDuration(): number {
  return play.duration || app.media?.duration || 0;
}

/** 当前字幕入点对齐播放头。 */
export async function alignSelectedCueStart(): Promise<void> {
  const cue = selectedCue();
  if (!cue) {
    toast('先选中一条字幕', 'warn');
    return;
  }
  const result = alignCueStart(cue, play.time, mediaDuration());
  if (!result.ok) {
    toast(result.reason, 'warn');
    return;
  }
  if (Math.abs(result.time - cue.start) < 1e-6) return;
  await updateCue(play.selected, { start: result.time });
}

/** 当前字幕出点对齐播放头。 */
export async function alignSelectedCueEnd(): Promise<void> {
  const cue = selectedCue();
  if (!cue) {
    toast('先选中一条字幕', 'warn');
    return;
  }
  const result = alignCueEnd(cue, play.time, mediaDuration());
  if (!result.ok) {
    toast(result.reason, 'warn');
    return;
  }
  if (Math.abs(result.time - cue.end) < 1e-6) return;
  await updateCue(play.selected, { end: result.time });
}

/** 在播放头切割当前字幕；与右键切割共用 0.05 秒边距。 */
export async function splitSelectedAtPlayhead(): Promise<void> {
  const cue = selectedCue();
  if (!cue) {
    toast('先选中一条字幕', 'warn');
    return;
  }
  if (!canSplitAt(cue, play.time)) {
    toast('播放头不在当前字幕内（或太靠近两端），无法切割', 'warn');
    return;
  }
  await splitCueAt(play.selected, play.time);
}

/** 试听当前字幕：从入点播到出点，由 `previewRange` 的 stopAt 自动停。 */
export function auditionSelectedCue(): void {
  const cue = selectedCue();
  if (!cue) {
    toast('先选中一条字幕', 'warn');
    return;
  }
  if (cue.end - cue.start < MIN_CUE_LENGTH) {
    toast('这条字幕太短，无法试听', 'warn');
    return;
  }
  previewRange(cue.start, cue.end);
}
