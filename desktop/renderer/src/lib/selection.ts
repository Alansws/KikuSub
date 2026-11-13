/**
 * 选区 → 字幕下标的纯函数（段三从 ReviewView 抽出来）。
 *
 * 为什么抽出来：`ReviewView.svelte` 有行数预算（只许变短），而这两个函数是纯的、
 * 和界面无关；同时「另一引擎复核」的批量入口也要用同一套口径——两处各写一份
 * 就会出现「删除选中的」和「复核选中的」覆盖范围不一致。
 *
 * 字幕用 `${start}:${end}` 作键（与轨道块、合并逻辑一致）；时间改了键就变了，
 * 这是刻意的：改了时间的字幕不该再被当成原来那块。
 */

import type { Cue } from './api';

export function laneKey(cue: Cue): string {
  return `${cue.start}:${cue.end}`;
}

/** ⌘ 多选：有就移除、没有就追加（返回新数组，调用方负责赋值）。 */
export function toggleLaneSelection(keys: string[], key: string): string[] {
  return keys.includes(key) ? keys.filter((item) => item !== key) : [...keys, key];
}

/**
 * ⌘ 单击一次之后的选中集合。
 *
 * 关键点：**没做过多选时，基准是"当前这一句"**——用户已经单击选中了第 3 句，
 * 再 ⌘ 点第 4 句，期望是 {3,4}，而不是"只有 4"。早期实现只从空集合起算，
 * 于是 ⌘ 点第二句只得到 1 条、工具条不出现（2026-11-14 实测反馈）。
 *
 * 返回 `kept` 表示刚点的那一块是否仍在集合里（取消选中时不能让当前行留在外面）。
 * 集合不允许变成空：取消到空时保留刚点的那块，因为总要有一句是"当前句"。
 */
export function stepSelection(
  keys: string[],
  anchorKey: string,
  clickedKey: string,
): { keys: string[]; kept: boolean } {
  const base = keys.length ? keys : anchorKey ? [anchorKey] : [];
  const next = toggleLaneSelection(base, clickedKey);
  if (!next.length) return { keys: [clickedKey], kept: true };
  return { keys: next, kept: next.includes(clickedKey) };
}

/** 时间点落在哪条字幕里（不含"回退到当前选中"的兜底）。 */
export function cueIndexAtTime(cues: Cue[], time: number): number {
  for (let i = 0; i < cues.length; i += 1) {
    if (cues[i].start <= time && time <= cues[i].end) return i;
  }
  return -1;
}

/** 按轨道块的键找下标（⌘ 多选用的就是键）。 */
export function indicesForLaneKeys(cues: Cue[], keys: string[]): number[] {
  if (!keys.length) return [];
  const wanted = new Set(keys);
  const out: number[] = [];
  cues.forEach((cue, index) => {
    if (wanted.has(laneKey(cue))) out.push(index);
  });
  return out;
}

/** 时间区间里的字幕下标（框选后右键合并、复核选区都用它）。 */
export function indicesInRange(cues: Cue[], start: number, end: number): number[] {
  const out: number[] = [];
  cues.forEach((cue, index) => {
    if (cue.start < end && cue.end > start) out.push(index);
  });
  return out;
}
