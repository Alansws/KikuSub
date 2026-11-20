/**
 * 断句重排页的状态。
 *
 * 一个页面两种做法，共用一个粘贴入口：
 * - ``rewrite``（整份重写）：提示词不要求 1:1，粘回来的**整份 SRT** 覆盖当前段；
 * - ``ops``（只改几处）：沿用 ``structure.svelte.ts`` 的 ops 预览与原子应用。
 *
 * 五条不变量：
 * - 时间码就是模型给的那些（服务端只体检、不改数），这里不做任何时间推算；
 * - 覆盖锚点是原稿的**条目索引区间**：分段计划一旦定下就冻结，之后每段按
 *   「前面已覆盖段的条数差」平移，不随表格条数变化而重切；
 * - **冻结键不含 `source`**：单源/双源只决定提示词里带不带 B，不决定工作单元。
 *   2026-11-15 用户报障的根因就是把 `source` 混进了冻结键——点一下「单源」再切回来，
 *   整页对着**已经覆盖过两段的表**重切成 3 段，在途的第三段草稿再也粘不回去；
 * - **已开工就不再静默重切**：原稿/第二版/字幕真的变了，只挂「计划失效」横幅，
 *   由人决定重新切段还是恢复上一版（`restoreReshapePlan()`）；
 * - 每段各自留一份草稿，切段不丢；覆盖后清空并推进到下一段。
 *
 * 注意「别在 $effect 里自读自写 state」：``ensureReshapePlan()`` 与
 * ``ensurePromptInfo()`` 都可能被页面的 effect 调用，所以两者都只写不读自己写的
 * 那几项（计划身份与提示词缓存放模块变量，不放 $state）。视图侧再用 `untrack()`
 * 把调用包起来，避免把内部读到的 state 变成 effect 的依赖。
 */

import { api, type ReshapePromptPayload } from './api';
import { needsSegments, planSegments, type AiSegment, type SegmentOptions } from './aiSegments';
import { clipSpan, isFullClip } from './clipRange';
import {
  DEFAULT_BATCH_SIZE,
  clampRange,
  nextBatch,
  previousBatch,
  rangeCount,
  resizeBatch,
  type CueSpan,
} from './cueBatch';
import { dual, refreshAltReview } from './dualReview.svelte';
import { promptSelectedId } from './promptStore.svelte';
import {
  appliedCount as countApplied,
  clampIndex,
  expectedTotal,
  markFor,
  planKey as buildPlanKey,
  rangeFor,
  remapApplied,
  segmentKey,
  undoCandidate,
  type AppliedMark,
  type PlanSnapshot,
  type ReshapeDraftState,
  type ReshapePlan,
} from './reshapePlan';
import {
  applyCueSnapshot,
  app,
  exporter,
  loadTranslations,
  scheduleDraftSave,
  toast,
} from './store.svelte';

export {
  segmentKey,
  type AppliedMark,
  type PlanSnapshot,
  type ReshapeDraftState,
  type ReshapePlan,
} from './reshapePlan';

export type ReshapeMode = 'rewrite' | 'ops';
export type ReshapeSource = 'single' | 'dual';

/**
 * 长片分段阈值比润色宽：整份重写不要求逐条回显，600 条 / 6 万字一次吃得下。
 * 超过才切成 150 条一段——分段是兜底，不是常规路径。
 */
const SEGMENT_OPTIONS: SegmentOptions = {
  targetCues: 150,
  toleranceCues: 20,
  toleranceSeconds: 120,
  maxCues: 600,
  maxChars: 60_000,
};

/** 计划历史留几份：够退回「刚才那套分段」，又不至于让横幅变成历史课本。 */
const PLAN_HISTORY = 5;

export const reshape = $state({
  mode: 'rewrite' as ReshapeMode,
  source: 'single' as ReshapeSource,
  longMode: false,
  segments: [] as AiSegment[],
  segmentIndex: 0,
  /** 段 key → 已解析待覆盖的新稿。 */
  drafts: {} as Record<string, ReshapeDraftState>,
  /** 段 key → 已覆盖标记；段轨据此打勾。 */
  applied: {} as Record<string, AppliedMark>,
  /** 当前冻结的分段计划（坐标系本体）。 */
  plan: null as ReshapePlan | null,
  /** 可以恢复的历史计划，最新在前。 */
  plans: [] as PlanSnapshot[],
  /** 计划是否已经被「原稿/第二版变了」废掉（此时不许复制提示词、不许覆盖）。 */
  stale: false,
  staleReason: '',
  text: '',
  pasteOpen: false,
  prompt: null as ReshapePromptPayload | null,
  loadingPrompt: false,
  parsing: false,
  applying: false,
  errors: [] as string[],
  /** 本次处理批次（处理范围之内的条号子范围）；默认等于整个处理范围。 */
  batchFrom: 1,
  batchTo: 0,
  batchManual: false,
  batchSize: DEFAULT_BATCH_SIZE,
});

/** 计划版本号：只在 buildPlan 里自增，模块级、不进 $state。 */
let planCounter = 0;
/** 我们自己最后一次动作之后的 `app.cuesRevision`；不等就是「别人改过」。 */
let expectedRevision = 0;
/** 上一次同步过的媒体 id：只有换片才整页重置（进页不再清进度）。 */
let reshapeMediaId: string | null = null;
/** 提示词元信息缓存：刻意不放 $state，避免 effect 自读自写。 */
let infoCache: { key: string; payload: ReshapePromptPayload } | null = null;
/** 定计划时用的处理范围 / 批次身份；变化说明换了坐标系，不能静默沿用。 */
let scopeKeyAtPlan = '';

/** 处理范围命中的全片区间（与润色 / 翻译 / 导出共用 `exporter.clip`）。 */
export function reshapeScopeSpan(): CueSpan {
  return { ...clipSpan(app.cues, exporter.clip) };
}

/** 本次处理批次：默认等于处理范围；手动批次永远夹在范围内。 */
export function reshapeBatchSpan(): CueSpan {
  const span = reshapeScopeSpan();
  if (span.count <= 0) return { from: 0, to: 0, count: 0 };
  if (!reshape.batchManual) return { ...span };
  const range = clampRange({ from: reshape.batchFrom, to: reshape.batchTo }, span);
  return { ...range, count: rangeCount(range) };
}

/** 当前真正会替换的全片区间。 */
export function reshapeRange(): CueSpan {
  return reshapeBatchSpan();
}

/** 范围身份：只含时间范围与手动批次，不含条数（条数变化是覆盖的结果）。 */
function planScopeKey(): string {
  const scope = exporter.clip;
  const clip = isFullClip(scope)
    ? 'full'
    : `${scope.start.toFixed(2)}-${scope.end.toFixed(2)}-${scope.label}`;
  const batch = reshape.batchManual
    ? `${reshape.batchFrom}-${reshape.batchTo}`
    : 'auto';
  return `${clip}|${batch}`;
}

/** 设置手动批次（夹进处理范围）；换批时清空粘贴框。 */
export function setReshapeBatch(from: number, to: number) {
  const span = reshapeScopeSpan();
  if (span.count <= 0) return;
  const range = clampRange({ from, to }, span);
  reshape.batchManual = true;
  reshape.batchFrom = range.from;
  reshape.batchTo = range.to;
  reshape.text = '';
  reshape.pasteOpen = false;
  reshape.errors = [];
}

/** 上一批 / 下一批（按每批 N 条）。 */
export function stepReshapeBatch(direction: 1 | -1) {
  const span = reshapeScopeSpan();
  if (span.count <= 0) return;
  const current = reshapeBatchSpan();
  const next = direction > 0
    ? nextBatch(current, span, reshape.batchSize)
    : previousBatch(current, span, reshape.batchSize);
  setReshapeBatch(next.from, next.to);
}

/** 「每批 N 条」预设：从当前批次起点重切。 */
export function setReshapeBatchSize(size: number) {
  reshape.batchSize = Math.max(1, Math.min(5000, Math.floor(size) || DEFAULT_BATCH_SIZE));
  const span = reshapeScopeSpan();
  if (span.count <= 0) return;
  const current = reshapeBatchSpan();
  const resized = resizeBatch(
    { from: reshape.batchManual ? current.from : span.from, to: current.to },
    span,
    reshape.batchSize,
  );
  setReshapeBatch(resized.from, resized.to);
}

/** 回到整个处理范围。 */
export function resetReshapeBatch() {
  const span = reshapeScopeSpan();
  reshape.batchManual = false;
  reshape.batchFrom = span.from;
  reshape.batchTo = span.to;
  reshape.text = '';
  reshape.pasteOpen = false;
}

/** 当前的冻结键：媒体身份 | 做法 | 第二版身份 | 有没有稿。 */
export function planKey(): string {
  return buildPlanKey({
    mediaId: app.media?.id ?? '',
    mode: reshape.mode,
    // 用「哪一份 B」（生成时间）而不是「B 有几条」：条数不代表换了参考稿。
    altId: dual.exists ? dual.createdAt : 0,
    hasCues: app.cues.length > 0,
  });
}

export function resetReshape() {
  reshape.drafts = {};
  reshape.applied = {};
  reshape.plan = null;
  reshape.plans = [];
  reshape.stale = false;
  reshape.staleReason = '';
  reshape.text = '';
  reshape.pasteOpen = false;
  reshape.prompt = null;
  reshape.errors = [];
  reshape.longMode = false;
  reshape.segments = [];
  reshape.segmentIndex = 0;
  reshape.batchManual = false;
  reshape.batchFrom = 1;
  reshape.batchTo = 0;
  infoCache = null;
  scopeKeyAtPlan = '';
  expectedRevision = app.cuesRevision;
}

/**
 * 只在**换片**时重置整页。
 *
 * 原来这条判断写在视图的 `$effect` 里无条件执行，而切视图会销毁重建组件
 * （`App.svelte` 的 `{#if app.view === 'reshape'}`），于是「复制提示词 → 去核对台
 * 看一眼 → 回来」也会把分段计划、已覆盖勾选和在途草稿全部清掉，再对着已经改过的表
 * 重切一遍。返回 true 表示这次真的换了片。
 */
export function syncReshapeMedia(): boolean {
  const id = app.media?.id ?? '';
  if (reshapeMediaId === id) return false;
  reshapeMediaId = id;
  resetReshape();
  return true;
}

/** 当前段：长片用分段表，短片把整片当成唯一一段，后面所有逻辑只有一条路径。 */
export function currentSegment(): AiSegment | null {
  if (!app.cues.length) return null;
  if (reshape.longMode && reshape.segments.length) {
    const index = clampIndex(reshape.segmentIndex, reshape.segments.length);
    return reshape.segments[index] ?? null;
  }
  const range = reshapeRange();
  if (range.count <= 0 || range.to > app.cues.length) return null;
  const first = app.cues[range.from - 1];
  const last = app.cues[range.to - 1];
  return { from: range.from, to: range.to, start: first.start, end: last.end, count: range.count };
}

export function activeKey(): string {
  const segment = currentSegment();
  return segment ? segmentKey(segment) : '';
}

export function activeDraft(): ReshapeDraftState | null {
  const key = activeKey();
  return key ? (reshape.drafts[key] ?? null) : null;
}

function clearPlan() {
  reshape.plan = null;
  reshape.longMode = false;
  reshape.segments = [];
  reshape.segmentIndex = 0;
  reshape.stale = false;
  reshape.staleReason = '';
}

/**
 * 定下一份新计划。**所有会换坐标系的东西都收在这一个函数里**，
 * 调用点只有 `ensureReshapePlan()`（自动、未开工）与 `replanReshapeSegments()`
 * （人工、二次确认后）。
 */
function buildPlan(reason: string) {
  // 手动选定局部范围 / 批次时，它就是这一轮的工作单元：不再叠加自动智能分段
  // （否则段轨会把用户刚选的 1–151 又锁回 150 条一段，和页面 1 同一条红线）。
  const scope = reshapeRange();
  const local = scope.count > 0 && (scope.from > 1 || scope.to < app.cues.length);
  const canSegment = dual.exists && !local;
  const longMode = canSegment && needsSegments(app.cues, dual.cues, SEGMENT_OPTIONS);
  const segments = longMode ? planSegments(app.cues, dual.cues, SEGMENT_OPTIONS) : [];
  const plan: ReshapePlan = {
    id: (planCounter += 1),
    key: planKey(),
    longMode,
    segments,
    singleKey: String(scope.count > 0 ? scope.from : 1),
    baseTotal: app.cues.length,
    baseRevision: app.cuesRevision,
    reason,
  };
  reshape.plan = plan;
  reshape.longMode = longMode;
  reshape.segments = segments;
  reshape.segmentIndex = clampIndex(reshape.segmentIndex, segments.length);
  reshape.stale = false;
  reshape.staleReason = '';
  // 旧坐标系的进度全部作废：草稿的 range 与 digest 都是旧表上的，留着只会 409。
  reshape.applied = {};
  reshape.drafts = {};
  infoCache = null;
  scopeKeyAtPlan = planScopeKey();
  expectedRevision = app.cuesRevision;
}

/**
 * 把当前计划连同进度压进历史栈（恢复用）。
 *
 * `revision` / `total` 记的是**进度账最后一次对齐时**的表（`expectedRevision`），
 * 不是此刻的表：失效横幅就是在「此刻的表已经变了」时弹出来的，如果按此刻存档，
 * 恢复校验会误判成「表没变过」，把旧坐标的 delta 搬到新表上——差一两条的平移错误
 * 比报错难查得多。
 */
function snapshotPlan(reason: string) {
  const plan = reshape.plan;
  if (!plan) return;
  const snap: PlanSnapshot = {
    at: Date.now(),
    revision: expectedRevision,
    total: expectedTotal(plan, reshape.applied),
    reason,
    plan: { ...plan, segments: [...plan.segments] },
    applied: { ...reshape.applied },
    drafts: { ...reshape.drafts },
  };
  reshape.plans = [snap, ...reshape.plans].slice(0, PLAN_HISTORY);
}

/** 这份快照还能不能安全恢复：表必须还是它记账时那一张（revision + 条数双检）。 */
function snapshotRestorable(snap: PlanSnapshot): boolean {
  return snap.revision === app.cuesRevision && snap.total === app.cues.length;
}

/** 横幅上「恢复上一版分段」该恢复的那一份；没有可安全恢复的返回 null。 */
export function latestRestorablePlan(): PlanSnapshot | null {
  return reshape.plans.find(snapshotRestorable) ?? null;
}

/** 计划失效：只挂标记并留一份快照，绝不静默重切。 */
function markStale(reason: string) {
  if (reshape.stale) return;
  snapshotPlan('计划失效前的分段');
  reshape.stale = true;
  reshape.staleReason = reason;
}

/** 冻结键变了，说清是哪一变造成的（横幅上要写人话）。 */
function describeKeyChange(plan: ReshapePlan, key: string): string {
  const [media, , alt, has] = key.split('|');
  const [wasMedia, , wasAlt] = plan.key.split('|');
  if (has !== '1') return '字幕被清空了';
  if (media !== wasMedia) return '换了媒体';
  if (alt !== wasAlt) return '第二版换了（重新导入或删掉了第二版）';
  if (plan.reason !== '') return '字幕被重新导入或重新转写过';
  return '原稿变了';
}

/**
 * ⌘Z 撤掉的正是我们自己做的那次覆盖：把标记一起回退，状态同步回退。
 *
 * 判据有两条，缺一不可：
 * - `redo_label` 是断句重排的标签，且区间与某一段 `wasFrom/wasTo` 对得上；
 * - 按「原稿 + 其余各段 delta」推算的条数，正好等于撤回后的表条数。
 * 第二条是防呆：用户可能在被撤回的那一步之后又在别处改过，条数对不上就绝不猜。
 */
function rewindUndoneApply(): boolean {
  const plan = reshape.plan;
  if (!plan) return false;
  const key = undoCandidate(String(app.redoLabel ?? ''), reshape.applied);
  if (!key) return false;
  const mark = reshape.applied[key];
  if (!mark) return false;
  if (expectedTotal(plan, reshape.applied) - mark.delta !== app.cues.length) return false;
  const next = { ...reshape.applied };
  delete next[key];
  reshape.applied = next;
  expectedRevision = app.cuesRevision;
  toast(`已同步撤回第 ${mark.wasFrom}–${mark.wasTo} 条那次覆盖：段轨标记一并退回，可以直接重做这一段`);
  return true;
}

/**
 * 原稿在别处被改过 / 被 ⌘Z 过：要么同步回退，要么挂失效横幅。
 *
 * 返回 true 表示检测到了漂移。**任何情况下都不会拿脏 delta 继续平移。**
 */
function detectDrift(): boolean {
  if (app.cuesRevision === expectedRevision) return false;
  if (rewindUndoneApply()) return false;
  if (countApplied(reshape.applied, reshape.plan) === 0) {
    // 还没开始覆盖：无所谓，直接按当前稿重切。
    buildPlan('原稿在别处改过，按当前稿重新分段');
    return true;
  }
  markStale(
    '原稿在别处被改过（⌘Z、核对台编辑，或重新导入／转写了字幕）：原先的分段区间已经对不上现在这张表',
  );
  return true;
}

/**
 * 定下 / 核对分段计划。可以在 effect 里反复调用，幂等。
 *
 * 只写不读：调用方是 $effect 时，读回刚写的 ``segments`` 会让 Svelte 一直重跑到
 * ``effect_update_depth_exceeded``（润色页踩过一次）。
 */
export function ensureReshapePlan() {
  if (reshape.mode !== 'rewrite' || !app.cues.length) {
    if (reshape.plan || reshape.longMode || reshape.segments.length) clearPlan();
    return;
  }
  const key = planKey();
  const plan = reshape.plan;
  if (plan && plan.key === key) {
    if (planScopeKey() !== scopeKeyAtPlan) {
      // 处理范围 / 手动批次变了：坐标系的含义变了。没覆盖过就按新范围重定；
      // 已覆盖过则挂失效横幅（绝不拿旧区间继续覆盖）。
      // 范围一变，旧计划的快照也失去意义（恢复了也套不到新范围上）。
      reshape.plans = [];
      if (countApplied(reshape.applied, plan) > 0) {
        reshape.stale = true;
        reshape.staleReason =
          '处理范围或本次批次变了：原先的分段区间对应的是旧范围，不能再沿用';
        return;
      }
      const hadDrafts = Object.keys(reshape.drafts).length > 0;
      buildPlan('处理范围变了，按当前范围重新定计划');
      if (hadDrafts) {
        toast('处理范围变了：未覆盖的新稿已作废，需要按新范围重新粘贴', 'warn');
      }
      return;
    }
    void detectDrift();
    return;
  }
  if (plan && countApplied(reshape.applied, plan) > 0) {
    markStale(describeKeyChange(plan, key));
    return;
  }
  buildPlan(plan ? '原稿或第二版变了，重新分段' : '进页');
}

/** 现在能不能把旧计划的覆盖标记按区间挪进新计划（原稿没被外部改过才行）。 */
export function canKeepProgress(): boolean {
  return app.cuesRevision === expectedRevision;
}

/** 人工重新分段（必须由界面的二次确认触发；失败时把快照压栈，可恢复）。 */
export function replanReshapeSegments({ keepProgress = false } = {}): boolean {
  if (!app.cues.length || reshape.mode !== 'rewrite') return false;
  const hadProgress = countApplied(reshape.applied, reshape.plan) > 0;
  if (hadProgress) snapshotPlan('重新分段前');
  const previous = reshape.applied;
  buildPlan('手动重新分段');
  if (keepProgress && hadProgress) {
    reshape.applied = remapApplied(reshape.segments, previous);
  }
  return true;
}

/** 恢复一份历史计划（含已覆盖标记与草稿）。原稿在快照之后被改过就拒绝。 */
export function restoreReshapePlan(at: number): boolean {
  const snap = reshape.plans.find((item) => item.at === at);
  if (!snap) return false;
  if (!snapshotRestorable(snap)) {
    toast(
      '原稿在存这份分段之后又变过（条数或编辑历史对不上），它的区间已经不能套在现在这张表上，不能直接恢复',
      'warn',
    );
    return false;
  }
  const plan: ReshapePlan = { ...snap.plan, segments: [...snap.plan.segments] };
  reshape.plan = plan;
  reshape.segments = plan.segments;
  reshape.longMode = plan.longMode;
  reshape.segmentIndex = clampIndex(reshape.segmentIndex, plan.segments.length);
  reshape.applied = { ...snap.applied };
  reshape.drafts = { ...snap.drafts };
  reshape.plans = reshape.plans.filter((item) => item.at !== at);
  reshape.stale = false;
  reshape.staleReason = '';
  infoCache = null;
  scopeKeyAtPlan = planScopeKey();
  expectedRevision = app.cuesRevision;
  toast('已恢复上一版分段：之前复制出去的提示词可以粘回原来的段');
  return true;
}

/**
 * 段在**当前表**里的索引区间。
 *
 * 前面每覆盖一段，本条数可能变化；分段计划冻结在原稿的编号上，所以后面各段
 * 要按已覆盖段的条数差平移——这样既不会因为你改过一段就把第二段切错，
 * 也不会让段轨的「1–141」自己跳数字。
 */
export function currentRangeFor(segment: AiSegment): { from: number; to: number } {
  return rangeFor(reshape.applied, reshape.plan, segment);
}

export function setMode(mode: ReshapeMode) {
  if (reshape.mode === mode) return;
  reshape.mode = mode;
  reshape.text = '';
  reshape.pasteOpen = false;
  reshape.errors = [];
  reshape.longMode = false;
  reshape.segments = [];
  reshape.segmentIndex = 0;
  reshape.stale = false;
  reshape.staleReason = '';
  reshape.plan = null;
  // 计划会在下一个 effect 里按当前稿重定；进度仍保留（同一种做法内切模式本来也没进度可言）。
}

/**
 * 单源 / 双源：**只换提示词里带不带 B**。
 *
 * 这里不碰 `plan` / `segments` / `applied` / `drafts` / `segmentIndex`——工作单元与
 * 进度必须原地不动。曾经因为冻结键里含 `source`，这一行切换就把整页重切了。
 */
export function setSource(source: ReshapeSource) {
  if (reshape.source === source) return;
  reshape.source = source;
  reshape.errors = [];
  reshape.prompt = null;
  infoCache = null;
}

export function setSegment(index: number) {
  if (index === reshape.segmentIndex) return;
  reshape.segmentIndex = index;
  // 粘贴框只有一份：换段时必须清掉，否则会把上一段的回复贴到这一段。
  reshape.text = '';
  reshape.pasteOpen = false;
}

export function promptCategory(): 'reshape_single' | 'reshape_dual' {
  return reshape.source === 'dual' ? 'reshape_dual' : 'reshape_single';
}

function activeTemplateId(): string {
  return promptSelectedId(promptCategory());
}

/**
 * 取当前段 / 当前源 / 当前模板的提示词元信息。
 *
 * 复制与「约 4.2k 字」都读同一份结果：复制的就是界面上写的那一份。
 * 计划失效时直接返回空——这时候给出的区间是旧表的，复制出去只会得到一份贴不对的稿。
 */
export async function ensurePromptInfo(force = false): Promise<ReshapePromptPayload | null> {
  if (reshape.mode !== 'rewrite' || !app.connected || !app.cues.length) return null;
  if (reshape.stale) {
    // 失效由页面上的横幅解释，这里不再往红条里堆一条重复的错误。
    reshape.prompt = null;
    return null;
  }
  if (reshape.source === 'dual' && !dual.exists) {
    reshape.prompt = null;
    return null;
  }
  const segment = currentSegment();
  if (!segment) return null;
  const range = reshape.longMode
    ? currentRangeFor(segment)
    : { from: segment.from, to: segment.to };
  const key = `${reshape.plan?.id ?? 0}|${promptCategory()}|${range.from}-${range.to}|${activeTemplateId()}|${app.cuesRevision}`;
  if (!force && infoCache?.key === key) return infoCache.payload;
  reshape.loadingPrompt = true;
  try {
    const payload = await api.getReshapePrompt(
      reshape.source,
      range.from,
      range.to,
      activeTemplateId(),
    );
    infoCache = { key, payload };
    reshape.prompt = payload;
    reshape.errors = [];
    return payload;
  } catch (err) {
    infoCache = null;
    reshape.prompt = null;
    reshape.errors = [(err as Error).message];
    return null;
  } finally {
    reshape.loadingPrompt = false;
  }
}

async function writeClipboard(text: string) {
  if (window.kikusub?.writeClipboard) {
    await window.kikusub.writeClipboard(text);
  } else if (navigator.clipboard) {
    await navigator.clipboard.writeText(text);
  }
}

export async function copyReshapePrompt(): Promise<boolean> {
  const payload = await ensurePromptInfo(true);
  if (!payload) {
    toast(reshape.errors[0] || '拿不到提示词：先导入字幕', 'warn');
    return false;
  }
  try {
    await writeClipboard(payload.prompt);
  } catch (err) {
    toast(`复制失败：${(err as Error).message}`, 'error');
    return false;
  }
  reshape.pasteOpen = true;
  reshape.text = '';
  toast(
    `已复制「${payload.template_name}」：${payload.count} 条字幕，${(payload.chars / 1000).toFixed(1)}k 字符`,
  );
  return true;
}

export function openPaste() {
  reshape.pasteOpen = true;
}

export function closePaste() {
  reshape.pasteOpen = false;
}

export async function parseReshapeText(text?: string): Promise<boolean> {
  if (reshape.parsing) return false;
  if (reshape.stale) {
    toast('分段计划已失效：先点「重新定计划」，再粘这一段的稿', 'warn');
    return false;
  }
  const raw = (text ?? reshape.text).trim();
  if (!raw) {
    toast('先把模型返回的字幕粘进来', 'warn');
    return false;
  }
  const segment = currentSegment();
  if (!segment) return false;
  const range = reshape.longMode
    ? currentRangeFor(segment)
    : { from: segment.from, to: segment.to };
  reshape.parsing = true;
  try {
    const draft = await api.parseReshape(raw, range.from, range.to);
    const issues: Record<number, string> = {};
    for (const issue of draft.diagnostics.issues) issues[issue.index] = issue.label;
    reshape.drafts[segmentKey(segment)] = {
      cues: draft.cues,
      notes: draft.notes,
      diagnostics: draft.diagnostics,
      issues,
      digest: draft.digest,
      range: { from: draft.range.from, to: draft.range.to, full: draft.range.full },
    };
    reshape.errors = [];
    reshape.text = '';
    reshape.pasteOpen = false;
    toast(
      `已解析 ${draft.diagnostics.count} 条（原 ${draft.diagnostics.count_before} 条），扫一眼再覆盖`,
    );
    return true;
  } catch (err) {
    const message = (err as Error).message;
    reshape.errors = [message];
    toast(message, 'error');
    return false;
  } finally {
    reshape.parsing = false;
  }
}

export function updateDraftCue(index: number, text: string) {
  const key = activeKey();
  const draft = key ? reshape.drafts[key] : null;
  if (!draft) return;
  const cues = draft.cues.map((cue, position) =>
    position === index - 1 ? { ...cue, text } : cue,
  );
  reshape.drafts[key] = { ...draft, cues };
}

export function removeDraftCue(index: number) {
  const key = activeKey();
  const draft = key ? reshape.drafts[key] : null;
  if (!draft) return;
  const cues = draft.cues.filter((_, position) => position !== index - 1);
  // 删行之后后面所有行号前移：旧的行内标记已经对不上，只保留不带行号的摘要。
  const notes = draft.notes.filter(
    (note) => note.level === 'plain' && !note.text.startsWith('只覆盖'),
  );
  reshape.drafts[key] = { ...draft, cues, issues: {}, notes };
}

export function discardDraft() {
  const key = activeKey();
  if (!key || !reshape.drafts[key]) return;
  const next = { ...reshape.drafts };
  delete next[key];
  reshape.drafts = next;
  toast('已丢弃这段新稿');
}

/** 覆盖当前段；成功后自动推进到下一段还没覆盖的段。 */
export async function applyReshapeDraft(): Promise<boolean> {
  if (reshape.applying) return false;
  if (reshape.stale) {
    toast('分段计划已失效：先点「重新定计划」，否则会按错位的区间覆盖', 'warn');
    return false;
  }
  const segment = currentSegment();
  const key = activeKey();
  const draft = key ? reshape.drafts[key] : null;
  if (!segment || !draft || !draft.cues.length) return false;
  reshape.applying = true;
  try {
    const res = await api.applyReshape({
      cues: draft.cues,
      from_index: draft.range.from,
      to_index: draft.range.full ? null : draft.range.to,
      digest: draft.digest,
      label: '',
    });
    applyCueSnapshot(res);
    // 先同步把账记平，再去刷新别的：中间有 await，effect 会跑一轮漂移检测。
    const replace = res.replace;
    const mark = markFor(replace, Date.now());
    reshape.applied = { ...reshape.applied, [key]: mark };
    const nextDrafts = { ...reshape.drafts };
    delete nextDrafts[key];
    // 其它段的草稿是针对「覆盖前」的表格解析的，指纹已经变了：留着只会 409。
    const droppedOthers = Object.keys(nextDrafts).length;
    reshape.drafts = nextDrafts;
    expectedRevision = app.cuesRevision;
    scheduleDraftSave();
    // 条数变了：范围外译文会跟着平移（服务端保证），第二版对齐也要刷新。
    void loadTranslations();
    void refreshAltReview();
    const shifted = replace.shifted_translations ?? [];
    const aligned = shifted.length
      ? `；${shifted.join(' / ')} 译文轨已保持对齐（范围外头部 / 尾部随条数平移）`
      : '';
    toast(
      `已覆盖第 ${replace.from}–${replace.to} 条：${replace.replaced} 条 → ${replace.inserted} 条（⌘Z 可整批撤回）${aligned}`,
    );
    if (replace.dropped_translations.length) {
      toast(
        `条数变了，已清空 ${replace.dropped_translations.join(' / ')} 译文轨（⌘Z 可退回）`,
        'warn',
      );
    }
    if (droppedOthers) {
      toast('表格条数变了：其它段未覆盖的新稿已作废，需要重新粘贴', 'warn');
    }
    if (reshape.longMode) {
      const next = reshape.segments.findIndex(
        (item, position) =>
          position > reshape.segmentIndex && !reshape.applied[segmentKey(item)],
      );
      if (next >= 0) setSegment(next);
    }
    reshape.pasteOpen = false;
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  } finally {
    reshape.applying = false;
  }
}

/** 段轨状态：'done' 已覆盖 / 'ready' 有待覆盖的新稿 / 'todo' 还没开始。 */
export function segmentState(segment: AiSegment): 'done' | 'ready' | 'todo' {
  const key = segmentKey(segment);
  if (reshape.applied[key]) return 'done';
  if (reshape.drafts[key]) return 'ready';
  return 'todo';
}

export function appliedCount(): number {
  return countApplied(reshape.applied, reshape.plan);
}
