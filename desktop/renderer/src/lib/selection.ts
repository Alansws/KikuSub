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

/** 删除目标：轨道多选优先，没有多选才删当前行。 */
export function deleteTargets(cues: Cue[], laneKeys: string[], selected: number): number[] {
  const fromLane = indicesForLaneKeys(cues, laneKeys);
  if (fromLane.length) return fromLane;
  return selected >= 0 && selected < cues.length ? [selected] : [];
}

/** 时间区间里的字幕下标（框选后右键合并、复核选区都用它）。 */
export function indicesInRange(cues: Cue[], start: number, end: number): number[] {
  const out: number[] = [];
  cues.forEach((cue, index) => {
    if (cue.start < end && cue.end > start) out.push(index);
  });
  return out;
}

export interface CueBlock {
  key: string;
  start: number;
  end: number;
  indices: number[];
}

/**
 * 底部字幕轨道上 x 处的字幕块。
 * 双语 SRT 的日/中两行共享同一区间，必须作为一块整体移动；这里返回整块的下标。
 * 嵌套块取像素宽度更小的那块（内层优先）。
 */
export function cueBlockAtX(
  cues: Cue[],
  x: number,
  xOf: (time: number) => number,
): CueBlock | null {
  const seen = new Set<string>();
  let bestKey = '';
  let bestSpan = Number.POSITIVE_INFINITY;
  for (const cue of cues) {
    const key = laneKey(cue);
    if (seen.has(key)) continue;
    seen.add(key);
    const x0 = xOf(cue.start);
    const x1 = xOf(cue.end);
    if (x < x0 - 1 || x > x1 + 1) continue;
    const span = x1 - x0;
    if (span < bestSpan) {
      bestSpan = span;
      bestKey = key;
    }
  }
  if (!bestKey) return null;
  const indices: number[] = [];
  cues.forEach((cue, index) => {
    if (laneKey(cue) === bestKey) indices.push(index);
  });
  if (!indices.length) return null;
  const first = cues[indices[0]];
  return { key: bestKey, start: first.start, end: first.end, indices };
}

export interface CueRangeSelection {
  indices: number[];
  keys: string[];
  start: number;
  end: number;
}

/**
 * ⇧ 连选（文件系统那套）：锚点行到目标行之间（含两端）整块选中，
 * 同时给出「首块起点 → 末块终点」的时间选区，供用户在音轨上微调后再同步。
 *
 * 下标按表格行算，所以双语/三语同区间的多行会被整块覆盖；keys 去重，
 * 同一块只算一次。锚点应当是上一次普通单击 / ⌘ 单击的那一行。
 */
export function rangeSelection(
  cues: Cue[],
  anchor: number,
  target: number,
): CueRangeSelection | null {
  if (!cues.length) return null;
  const lo = Math.max(0, Math.min(anchor, target));
  const hi = Math.min(cues.length - 1, Math.max(anchor, target));
  const indices: number[] = [];
  const keys = new Set<string>();
  let start = Number.POSITIVE_INFINITY;
  let end = Number.NEGATIVE_INFINITY;
  for (let i = lo; i <= hi; i += 1) {
    const cue = cues[i];
    if (!cue) continue;
    indices.push(i);
    keys.add(laneKey(cue));
    start = Math.min(start, cue.start);
    end = Math.max(end, cue.end);
  }
  if (!indices.length || !Number.isFinite(start) || !Number.isFinite(end)) return null;
  return { indices, keys: [...keys], start, end };
}

/** 时间选区内与字幕轨重叠的块键（拖选区手柄时让「已选 N 块」跟着走）。 */
export function keysInRange(cues: Cue[], start: number, end: number): string[] {
  const keys = new Set<string>();
  for (const cue of cues) {
    if (cue.start < end && cue.end > start) keys.add(laneKey(cue));
  }
  return [...keys];
}

export interface CueDragSpec {
  start: number;
  end: number;
  edge: 'move' | 'start' | 'end';
  anchorT: number;
}

/**
 * 拖字幕块 / 拖两端的落点：只算时间，不碰状态。
 * 块整体平移按「抓取时的相对位置」保持时长；两端各自夹在 0.05 秒以上，
 * 并限制在影片时长内。结果按毫秒取整，避免浮点尾巴写进 SRT。
 */
export function cueDragTimes(
  drag: CueDragSpec,
  t: number,
  max: number,
): { start: number; end: number } {
  const minDur = 0.05;
  let start = drag.start;
  let end = drag.end;
  if (drag.edge === 'move') {
    const dur = drag.end - drag.start;
    start = Math.max(0, Math.min(Math.max(0, max - dur), drag.start + (t - drag.anchorT)));
    end = start + dur;
  } else if (drag.edge === 'start') {
    start = Math.max(0, Math.min(drag.end - minDur, t));
  } else {
    end = Math.min(max, Math.max(drag.start + minDur, t));
  }
  return {
    start: Math.round(start * 1000) / 1000,
    end: Math.round(end * 1000) / 1000,
  };
}
