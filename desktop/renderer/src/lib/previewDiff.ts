/**
 * AI 预览用的纯排版函数（无 DOM、无网络）。
 *
 * 只服务界面：断句重排的「原稿 ↔ 新稿」对照、双源下 A 行对应的 B 段。
 * **不参与应用与 digest**——真正写回核对台仍走服务端的 `replace_range()` /
 * `apply_polish()`，这里算错了最多是预览难看，不会改错字幕。
 */

import type { Cue } from './api';

export interface PreviewRow {
  start: number;
  end: number;
  /** 原稿在这一行里的下标（0 基，按传入数组）。 */
  oldIndexes: number[];
  /** 新稿在这一行里的下标（0 基）。为空 = 这一行原稿被删了。 */
  newIndexes: number[];
  kind: 'same' | 'diff' | 'old' | 'new';
}

export interface BRef {
  /** 对齐到的 B 段起止（0 基，含两端）。 */
  first: number;
  last: number;
  /** 去掉分隔符的拼接文本（润色页的 B 参考列用）。 */
  text: string;
  /** 逐条文本（断句重排预览按行显示）。 */
  lines: string[];
}

const EPS = 0.001;

function overlap(a: Cue, b: Cue): number {
  return Math.min(a.end, b.end) - Math.max(a.start, b.start);
}

function textOf(cues: Cue[], indexes: number[], separator: string): string {
  return indexes.map((index) => cues[index]?.text ?? '').join(separator);
}

function span(cues: Cue[], indexes: number[]): { start: number; end: number } {
  let start = Number.POSITIVE_INFINITY;
  let end = Number.NEGATIVE_INFINITY;
  for (const index of indexes) {
    const cue = cues[index];
    if (!cue) continue;
    start = Math.min(start, cue.start);
    end = Math.max(end, cue.end);
  }
  if (!Number.isFinite(start) || !Number.isFinite(end)) return { start: 0, end: 0 };
  return { start, end };
}

/**
 * 把两份字幕按**时间重叠**对齐成行。
 *
 * 不复用双引擎复核的服务端对齐：那里的契约是「1:1，绝不合并」；断句重排
 * 恰恰会把 2 条并成 1 条、把 1 条拆成 2 条，界面需要把重叠的整组放在同一行，
 * 否则「合并」会被读成「删了后半句」。
 */
export function alignPreviewRows(oldCues: Cue[], newCues?: Cue[] | null): PreviewRow[] {
  if (!newCues || !newCues.length) {
    return oldCues.map((cue, index) => ({
      start: cue.start,
      end: cue.end,
      oldIndexes: [index],
      newIndexes: [],
      kind: 'same',
    }));
  }

  const rows: PreviewRow[] = [];
  let i = 0;
  let j = 0;

  while (i < oldCues.length || j < newCues.length) {
    const oldCue = oldCues[i];
    const newCue = newCues[j];

    if (oldCue && newCue) {
      if (overlap(oldCue, newCue) > EPS) {
        const olds = [i];
        const news = [j];
        // 先向两侧扩张，直到没有新条目与这一组重叠。用不动点循环处理
        // 「2 条并成 1 条」和「1 条拆成 2 条」互相牵动的情况。
        let grew = true;
        while (grew) {
          grew = false;
          while (i + 1 < oldCues.length) {
            const next = oldCues[i + 1];
            if (!news.some((index) => overlap(next, newCues[index]) > EPS)) break;
            i += 1;
            olds.push(i);
            grew = true;
          }
          while (j + 1 < newCues.length) {
            const next = newCues[j + 1];
            if (!olds.some((index) => overlap(oldCues[index], next) > EPS)) break;
            j += 1;
            news.push(j);
            grew = true;
          }
        }

        const before = textOf(oldCues, olds, '\n').trim();
        const after = textOf(newCues, news, '\n').trim();
        const merged = span(oldCues, olds);
        const incoming = span(newCues, news);
        rows.push({
          start: Math.min(merged.start, incoming.start),
          end: Math.max(merged.end, incoming.end),
          oldIndexes: olds,
          newIndexes: news,
          kind: before === after ? 'same' : 'diff',
        });
        i += 1;
        j += 1;
        continue;
      }

      if (oldCue.end <= newCue.start) {
        rows.push({
          start: oldCue.start,
          end: oldCue.end,
          oldIndexes: [i],
          newIndexes: [],
          kind: 'old',
        });
        i += 1;
        continue;
      }

      rows.push({
        start: newCue.start,
        end: newCue.end,
        oldIndexes: [],
        newIndexes: [j],
        kind: 'new',
      });
      j += 1;
      continue;
    }

    if (oldCue) {
      rows.push({
        start: oldCue.start,
        end: oldCue.end,
        oldIndexes: [i],
        newIndexes: [],
        kind: 'old',
      });
      i += 1;
    } else if (newCue) {
      rows.push({
        start: newCue.start,
        end: newCue.end,
        oldIndexes: [],
        newIndexes: [j],
        kind: 'new',
      });
      j += 1;
    }
  }

  return rows;
}

/**
 * 每条 A 对应的 B 段（按时间重叠，0 基）。
 *
 * 与润色页原实现一致：只取真正与这条 A 重叠的 B，不把相邻句混进参考列。
 * 另外返回逐条文本，断句重排预览要按行显示 B 原文。
 */
export function bRefsFor(aCues: Cue[], bCues: Cue[]): (BRef | null)[] {
  const refs: (BRef | null)[] = [];
  let cursor = 0;

  for (const cue of aCues) {
    while (cursor < bCues.length && bCues[cursor].end <= cue.start + EPS) cursor += 1;
    let first = -1;
    let last = -1;
    const lines: string[] = [];
    let index = cursor;
    while (index < bCues.length && bCues[index].start < cue.end - EPS) {
      if (overlap(cue, bCues[index]) > EPS) {
        if (first < 0) first = index;
        last = index;
        lines.push(bCues[index].text);
      }
      index += 1;
    }
    refs.push(first >= 0 ? { first, last, text: lines.join(''), lines } : null);
  }

  return refs;
}
