/**
 * 断句重排的分段坐标系（纯函数，无 $state / 无网络）。
 *
 * 为什么单独一个模块：这份坐标系是整页的安全边界，必须能被 `node --test` 直接钉死
 * （`desktop/test/reshapePlan.test.mjs`），不能只靠手点。`reshape.svelte.ts` 只留状态壳。
 *
 * 三条不变量（改之前先读 `docs/contracts/ai-proposal.md` §3.7.6）：
 *
 * 1. **计划只锚在原稿上**：`segments` 用的是「定计划那一刻的 1 基条号」。覆盖某段之后
 *    表里条数会变，后面各段靠 `shiftFor()` 按已覆盖段的 `delta` 平移——所以计划一旦
 *    定下就不能重切，重切等于换了一套坐标系，在途的草稿全部失配。
 * 2. **段的身份是原稿起条号**（`segmentKey()`），不是展示区间 `"from-to"`：覆盖之后
 *    展示区间会漂，用漂过的区间当 key 会让勾选、草稿、进度全部失配（2026-11-15 用户
 *    报障的根因之一）。
 * 3. **冻结键不含 source / 条数 / B 条数**：单源双源只决定提示词里带不带 B，不决定
 *    工作单元；条数变化正是要冻结的东西。`planKey()` 由调用方拼好传进来，这里只校验
 *    它长什么样，避免各处各拼一份。
 *
 * 还有一件事这里刻意不做：**不替用户「修」计划**。计划失效时只标 `stale`，由人决定
 * 重新切段还是恢复上一版——静默重切正是这个 bug 的原始形态。
 */

import type { Cue, ReshapeDiagnostics, ReshapeNote } from './api';
import type { AiSegment } from './aiSegments';

/** 一段覆盖完成后的记账；后续各段的平移全靠 `delta`。 */
export interface AppliedMark {
  /** 覆盖时间（毫秒），提示与排序用。 */
  at: number;
  /** 这一段覆盖后条数的变化量（`inserted - replaced`）。 */
  delta: number;
  /** 覆盖前被换掉的原稿区间（1 基，含两端）。 */
  wasFrom: number;
  wasTo: number;
  /** 覆盖后这一段在当前表里实际占的区间（1 基，含两端）。 */
  atFrom: number;
  atTo: number;
}

/** 一次「粘贴 → 预检」的结果，按段存放。 */
export interface ReshapeDraftState {
  cues: Cue[];
  notes: ReshapeNote[];
  diagnostics: ReshapeDiagnostics;
  /** 1-based 行号 → 行内提示（重叠 / 偏长 / 越界…）。 */
  issues: Record<number, string>;
  digest: string;
  /** 解析时用掉的当前表索引区间（应用时原样回传，服务端按它切片）。 */
  range: { from: number; to: number; full: boolean };
}

/** 一份冻结的分段计划。 */
export interface ReshapePlan {
  /** 单调递增的版本号；快照与提示词记录都拿它做钥匙。 */
  id: number;
  /** 冻结键：媒体身份 | 做法 | 第二版身份 | 有没有稿（见 `planKey()`）。 */
  key: string;
  longMode: boolean;
  /** 原稿坐标的分段；`longMode` 为 false 时是空数组（整片即一段）。 */
  segments: AiSegment[];
  /** 定计划时原稿的条数。 */
  baseTotal: number;
  /** 定计划时的 `app.cuesRevision`，外部改动侦测的基准。 */
  baseRevision: number;
  /** 为什么定了这份计划（横幅要说清是哪一变造成的）。 */
  reason: string;
}

/**
 * 一份计划连同它的进度快照。
 *
 * `revision` 是恢复的前提：原稿在快照之后被改过，里面的 `applied` 坐标就已经是旧表
 * 上的，硬恢复等于拿错位下标去覆盖——宁可恢复不了。
 */
export interface PlanSnapshot {
  at: number;
  revision: number;
  total: number;
  reason: string;
  plan: ReshapePlan;
  applied: Record<string, AppliedMark>;
  drafts: Record<string, ReshapeDraftState>;
}

/** 冻结键：只有这四样能决定「换一套坐标系」。 */
export function planKey(parts: {
  mediaId: string;
  mode: string;
  altId: number | string;
  hasCues: boolean;
}): string {
  return [parts.mediaId, parts.mode, parts.altId, parts.hasCues ? 1 : 0].join('|');
}

/**
 * 段的身份 = 原稿起条号。
 *
 * 不用 `"from-to"`：覆盖前一段之后条数会变，展示区间会漂；漂过的 key 会让「已覆盖
 * 2/3 段」这种假进度出现，也会让在途草稿读不出来。
 */
export function segmentKey(segment: AiSegment): string {
  return String(segment.from);
}

export function clampIndex(index: number, length: number): number {
  if (length <= 0) return 0;
  return Math.min(Math.max(0, Math.floor(index)), length - 1);
}

/**
 * 这一段在原稿坐标里之前，已经因为覆盖而多出来（或少了）多少条。
 *
 * 只看 `from` 严格小于本段起点的那些段：自己的 delta 不能用在自己身上。
 */
export function shiftFor(
  applied: Record<string, AppliedMark>,
  plan: ReshapePlan | null,
  segment: AiSegment,
): number {
  if (!plan) return 0;
  let shift = 0;
  for (const item of plan.segments) {
    if (item.from >= segment.from) break;
    const mark = applied[segmentKey(item)];
    if (mark) shift += mark.delta;
  }
  return shift;
}

/** 段在当前表里的索引区间（平移之后）。 */
export function rangeFor(
  applied: Record<string, AppliedMark>,
  plan: ReshapePlan | null,
  segment: AiSegment,
): { from: number; to: number } {
  const shift = shiftFor(applied, plan, segment);
  return { from: segment.from + shift, to: segment.to + shift };
}

/** 段轨上已覆盖的段数；只数**当前计划里**真的存在的那几段（不数僵尸 key）。 */
export function appliedCount(
  applied: Record<string, AppliedMark>,
  plan: ReshapePlan | null,
): number {
  if (!plan) return 0;
  // 短片（整片即一段）的段 key 恒为 "1"：覆盖后条数会变，起条号不会。
  if (!plan.longMode) return applied['1'] ? 1 : 0;
  return plan.segments.filter((item) => Boolean(applied[segmentKey(item)])).length;
}

/** 按「原稿 + 各段 delta」推算现在的表应当多少条；对不上就是被别处改过。 */
export function expectedTotal(
  plan: ReshapePlan | null,
  applied: Record<string, AppliedMark>,
): number {
  if (!plan) return 0;
  let total = plan.baseTotal;
  for (const key of Object.keys(applied)) total += applied[key].delta;
  return total;
}

/** 把服务端的 `replace` 回执变成一条记账。 */
export function markFor(
  replace: { from: number; to: number; replaced: number; inserted: number },
  at: number,
): AppliedMark {
  return {
    at,
    delta: replace.inserted - replace.replaced,
    wasFrom: replace.from,
    wasTo: replace.to,
    atFrom: replace.from,
    atTo: replace.from + Math.max(0, replace.inserted) - 1,
  };
}

/**
 * 重新分段后，把旧的覆盖标记按「覆盖后实际占的区间」挪到新计划里。
 *
 * 只有当已覆盖区域**完整落在**某一段里才算继续 done；跨了边界说明新切法把成果切开了，
 * 这一段得重做——宁可让用户重跑，也不能留一个位置错掉的勾。
 */
export function remapApplied(
  segments: AiSegment[],
  applied: Record<string, AppliedMark>,
): Record<string, AppliedMark> {
  const next: Record<string, AppliedMark> = {};
  for (const mark of Object.values(applied)) {
    const host = segments.find((item) => item.from <= mark.atFrom && item.to >= mark.atTo);
    if (!host) continue;
    next[segmentKey(host)] = mark;
  }
  return next;
}

const COVER_RE = /覆盖第\s*(\d+)\s*[–—-]\s*(\d+)\s*条/;

/**
 * ⌘Z 撤掉的是不是我们自己做的那次覆盖。
 *
 * 依据是 `redo_label`（服务端 `const up, redo_label = 刚被撤回那一步的 label`）：
 * 标签里带着被换掉的原稿区间，和 `AppliedMark.wasFrom/wasTo` 一一对应。返回段 key，
 * 认不出来就返回 null（交给「计划失效」横幅，绝不瞎猜）。
 *
 * 「整份覆盖」的标签不带区间，只有唯一一段时才没有歧义。
 */
export function undoCandidate(
  label: string,
  applied: Record<string, AppliedMark>,
): string | null {
  const keys = Object.keys(applied);
  if (!keys.length) return null;
  if (!String(label || '').includes('断句重排')) return null;
  const hit = COVER_RE.exec(label);
  if (hit) {
    const from = Number(hit[1]);
    const to = Number(hit[2]);
    const matched = keys.filter(
      (key) => applied[key].wasFrom === from && applied[key].wasTo === to,
    );
    return matched.length === 1 ? matched[0] : null;
  }
  return keys.length === 1 ? keys[0] : null;
}

/** 两份分段是不是同一套坐标（只比边界，不比 start/end，时间不影响切法）。 */
export function sameSegments(a: AiSegment[], b: AiSegment[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((item, index) => item.from === b[index].from && item.to === b[index].to);
}
