/**
 * 单句 AI 判定的纯函数：上下文、结果分类、失效判断。
 *
 * 状态与网络在 `arbitration.svelte.ts`，UI 在 `ArbitrationCard.svelte`；这里保持
 * 零依赖，`node --test` 可以直接加载。
 */

import type { Cue } from './api';

export interface ArbitrationRecord {
  /** 判定时的句子时间与两版文本快照；任何一项变了，结果就不再可信。 */
  start: number;
  end: number;
  textA: string;
  textB: string;
  text: string;
  note: string;
  model: string;
  mediaId: string;
}

export interface ArbitrationContext {
  before: string[];
  after: string[];
}

/**
 * 前后文取「按时间排序后，当前句之外的相邻 3 句」。
 *
 * 刻意不按 `end <= cue.start` / `start >= cue.end` 过滤：核对台的转写选区会带
 * padStart/padEnd，邻句与当前句可能轻微重叠；用重叠条件会在边缘漏掉邻句。
 * 这里先按 start 排序（同 start 保持原顺序），找到当前句的位置，再取前后各 3 条。
 */
export function contextFor(cues: Cue[], index: number, radius = 3): ArbitrationContext {
  const current = cues[index];
  if (!current) return { before: [], after: [] };
  const ordered = cues
    .map((cue, i) => ({ cue, i }))
    .sort((a, b) => a.cue.start - b.cue.start || a.i - b.i);
  const pos = ordered.findIndex((entry) => entry.i === index);
  if (pos < 0) return { before: [], after: [] };
  const clean = (items: Array<{ cue: Cue }>) =>
    items
      .map((entry) => entry.cue.text.trim())
      .filter(Boolean)
      .map((text) => text.slice(0, 200));
  return {
    before: clean(ordered.slice(Math.max(0, pos - radius), pos)),
    after: clean(ordered.slice(pos + 1, pos + 1 + radius)),
  };
}

export type ArbitrationMatch = 'a' | 'b' | 'third';

/** 第三版与 A/B 的关系：用于徽章与「是否给采用按钮」。 */
export function classifyText(textA: string, textB: string, text: string): ArbitrationMatch {
  const picked = text.trim();
  if (picked && picked === textA.trim()) return 'a';
  if (picked && picked === textB.trim()) return 'b';
  return 'third';
}

/** 与 A 相同时没有可采用的改动；与 B 相同也保留按钮，并标明同 B 版。 */
export function canAdopt(match: ArbitrationMatch): boolean {
  return match !== 'a';
}

export function adoptLabel(match: ArbitrationMatch): string {
  return match === 'b' ? '采用（同 B 版）' : '采用 AI 版';
}

/** 结果是否仍对应当前句、当前 A/B 与当前媒体。 */
export function isFreshRecord(
  record: ArbitrationRecord | null | undefined,
  cue: Cue | null | undefined,
  textB: string,
  mediaId: string,
): boolean {
  if (!record || !cue) return false;
  if (record.mediaId !== mediaId) return false;
  return (
    Math.abs(record.start - cue.start) <= 1e-6 &&
    Math.abs(record.end - cue.end) <= 1e-6 &&
    record.textA === cue.text &&
    record.textB === textB
  );
}
