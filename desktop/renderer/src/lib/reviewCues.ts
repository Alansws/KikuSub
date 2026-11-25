/**
 * 核对台里「当前时间 → 哪条字幕 / 画面该显示哪几行」的纯计算。
 *
 * 从 `views/ReviewView.svelte` 抽出（红线 11：大文件只许变短）。这里不读
 * 组件状态、不碰 DOM，只接收 cues / 时间 / 轨道，返回下标与行数组，方便
 * `node --test` 直接加载，也让二分查找只有一份实现。
 */

import type { Cue, TrackMode } from './api';

/**
 * 时间落在哪条 cue 里；没有就 -1。
 *
 * **边界口径与核对台一致**：`time === cue.end` 不算命中（二分里走 `time >= end`
 * 右移）。这一点和 `selection.ts` 的 `cueIndexAtTime`（`<= end` 算命中）不同，
 * 两者分别服务「播放头逐帧判定」与「点在句尾也算这句」的场景，不能互换。
 */
export function cueIndexAtTimeExclusive(cues: readonly Cue[], time: number): number {
  let lo = 0;
  let hi = cues.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const cue = cues[mid];
    if (time < cue.start) hi = mid - 1;
    else if (time >= cue.end) lo = mid + 1;
    else return mid;
  }
  return -1;
}

/** 一条 cue 里的硬换行拆成多行，空行丢掉。画面叠加层与表格共用。 */
export function captionTextLines(text: string): string[] {
  return String(text || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
}

/**
 * 表格里一行只能放一行文字（虚拟列表固定行高），多行 cue 用「 / 」分隔显示，
 * 不再让 newline 被 nowrap 压成一个空格——两种语言粘在一起看起来像识别错误。
 * 完整原文仍在检查器文本框里按原样编辑。
 */
export function cueDisplayText(text: string): string {
  return captionTextLines(text).join(' / ');
}

/**
 * 画面字幕：当前时间对应的一整块 cue（双语同区间算一块），按当前轨道拼行。
 *
 * - `source`：只显示原文；
 * - `target`：只显示译文，译文缺失时退回原文，绝不在画面上留空行；
 * - `both`：原文在上、译文在下，译文缺失时只留原文。
 *
 * 只收 `text.trim()` 非空的源 cue：整块都是空文本时画面不显示任何行。
 */
export function captionLinesAt(
  cues: readonly Cue[],
  time: number,
  track: TrackMode,
  translationAt: (index: number) => string,
): string[] {
  if (!cues.length) return [];
  const hit = cueIndexAtTimeExclusive(cues, time);
  if (hit < 0) return [];

  const key = `${cues[hit].start}:${cues[hit].end}`;
  let first = hit;
  while (first >= 0 && `${cues[first].start}:${cues[first].end}` === key) first -= 1;

  const indices: number[] = [];
  for (let k = first + 1; k < cues.length; k += 1) {
    if (`${cues[k].start}:${cues[k].end}` !== key) break;
    if (cues[k].text.trim()) indices.push(k);
  }

  const lines: string[] = [];
  for (const index of indices) {
    const sourceLines = captionTextLines(cues[index].text);
    const targetLines = captionTextLines(translationAt(index));
    if (track === 'target') {
      lines.push(...(targetLines.length ? targetLines : sourceLines));
    } else if (track === 'both') {
      lines.push(...sourceLines);
      if (targetLines.length) lines.push(...targetLines);
    } else {
      lines.push(...sourceLines);
    }
  }
  return lines;
}
