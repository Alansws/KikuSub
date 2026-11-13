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
