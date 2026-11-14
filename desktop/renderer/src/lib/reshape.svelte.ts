/**
 * 断句重排页的状态。
 *
 * 一个页面两种做法，共用一个粘贴入口：
 * - ``rewrite``（整份重写）：提示词不要求 1:1，粘回来的**整份 SRT** 覆盖当前段；
 * - ``ops``（只改几处）：沿用 ``structure.svelte.ts`` 的 ops 预览与原子应用。
 *
 * 三条不变量：
 * - 时间码就是模型给的那些（服务端只体检、不改数），这里不做任何时间推算；
 * - 覆盖锚点是原稿的**条目索引区间**：分段一旦定下就冻结，之后每段按
 *   「前面已覆盖段的条数差」平移，不随表格条数变化而重切；
 * - 每段各自留一份草稿，切段不丢；覆盖后清空并推进到下一段。
 *
 * 注意「别在 $effect 里自读自写 state」：``ensureReshapePlan()`` 与
 * ``ensurePromptInfo()`` 都可能被页面的 effect 调用，所以两者都只写不读自己写的
 * 那几项（计划锚点与提示词缓存放模块变量，不放 $state）。
 */

import {
  api,
  type Cue,
  type ReshapeDiagnostics,
  type ReshapeNote,
  type ReshapePromptPayload,
} from './api';
import { needsSegments, planSegments, type AiSegment, type SegmentOptions } from './aiSegments';
import { dual, refreshAltReview } from './dualReview.svelte';
import { promptSelectedId } from './promptStore.svelte';
import { applyCueSnapshot, app, loadTranslations, scheduleDraftSave, toast } from './store.svelte';

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

export interface AppliedMark {
  at: number;
  /** 这一段覆盖后表格条数的变化量；用来平移后面各段的索引。 */
  delta: number;
}

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
  text: '',
  pasteOpen: false,
  prompt: null as ReshapePromptPayload | null,
  loadingPrompt: false,
  parsing: false,
  applying: false,
  errors: [] as string[],
});

/** 分段计划的锚点：只有换片 / 换做法 / 换源 / 第二版变化时才重切。 */
let planAnchor = '';
/** 提示词元信息缓存：刻意不放 $state，避免 effect 自读自写。 */
let infoCache: { key: string; payload: ReshapePromptPayload } | null = null;

export function resetReshape() {
  reshape.drafts = {};
  reshape.applied = {};
  reshape.text = '';
  reshape.pasteOpen = false;
  reshape.prompt = null;
  reshape.errors = [];
  reshape.segmentIndex = 0;
  planAnchor = '';
  infoCache = null;
}

export function segmentKey(segment: AiSegment): string {
  return `${segment.from}-${segment.to}`;
}

/** 当前段：长片用分段表，短片把整片当成唯一一段，后面所有逻辑只有一条路径。 */
export function currentSegment(): AiSegment | null {
  if (!app.cues.length) return null;
  if (reshape.longMode && reshape.segments.length) {
    const index = Math.min(reshape.segmentIndex, reshape.segments.length - 1);
    return reshape.segments[index] ?? null;
  }
  const first = app.cues[0];
  const last = app.cues[app.cues.length - 1];
  return { from: 1, to: app.cues.length, start: first.start, end: last.end, count: app.cues.length };
}

export function activeKey(): string {
  const segment = currentSegment();
  return segment ? segmentKey(segment) : '';
}

export function activeDraft(): ReshapeDraftState | null {
  const key = activeKey();
  return key ? (reshape.drafts[key] ?? null) : null;
}

/**
 * 定下分段计划（只切一次，之后冻结）。
 *
 * 只写不读：调用方是 $effect 时，读回刚写的 ``segments`` 会让 Svelte 一直重跑到
 * ``effect_update_depth_exceeded``（润色页踩过一次）。
 */
export function ensureReshapePlan() {
  const anchor = `${app.media?.id ?? ''}|${reshape.mode}|${reshape.source}|${dual.count}|${app.cues.length ? 1 : 0}`;
  if (anchor === planAnchor) return;
  planAnchor = anchor;
  if (reshape.mode !== 'rewrite' || !dual.exists) {
    reshape.longMode = false;
    reshape.segments = [];
    reshape.segmentIndex = 0;
    return;
  }
  const longMode = needsSegments(app.cues, dual.cues, SEGMENT_OPTIONS);
  const segments = longMode ? planSegments(app.cues, dual.cues, SEGMENT_OPTIONS) : [];
  reshape.longMode = longMode;
  reshape.segments = segments;
  reshape.segmentIndex = Math.min(reshape.segmentIndex, Math.max(0, segments.length - 1));
}

/** 强制重新分段（换片、重新导入字幕后由页面按钮触发）。 */
export function replanReshapeSegments() {
  planAnchor = '';
  ensureReshapePlan();
}

/**
 * 段在**当前表**里的索引区间。
 *
 * 前面每覆盖一段，本条数可能变化；分段计划冻结在原稿的编号上，所以后面各段
 * 要按已覆盖段的条数差平移——这样既不会因为你改过一段就把第二段切错，
 * 也不会让段轨的「1–141」自己跳数字。
 */
export function currentRangeFor(segment: AiSegment): { from: number; to: number } {
  let shift = 0;
  for (const item of reshape.segments) {
    if (item.from >= segment.from) break;
    const mark = reshape.applied[segmentKey(item)];
    if (mark) shift += mark.delta;
  }
  return { from: segment.from + shift, to: segment.to + shift };
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
  planAnchor = '';
}

export function setSource(source: ReshapeSource) {
  if (reshape.source === source) return;
  reshape.source = source;
  reshape.errors = [];
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
 */
export async function ensurePromptInfo(force = false): Promise<ReshapePromptPayload | null> {
  if (reshape.mode !== 'rewrite' || !app.connected || !app.cues.length) return null;
  if (reshape.source === 'dual' && !dual.exists) {
    reshape.prompt = null;
    return null;
  }
  const segment = currentSegment();
  if (!segment) return null;
  const range = reshape.longMode ? currentRangeFor(segment) : { from: 1, to: app.cues.length };
  const key = `${promptCategory()}|${range.from}-${range.to}|${activeTemplateId()}|${app.cuesRevision}`;
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
  const raw = (text ?? reshape.text).trim();
  if (!raw) {
    toast('先把模型返回的字幕粘进来', 'warn');
    return false;
  }
  const segment = currentSegment();
  if (!segment) return false;
  const range = reshape.longMode ? currentRangeFor(segment) : { from: 1, to: app.cues.length };
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
    scheduleDraftSave();
    // 条数变了译文轨会被服务端丢弃；第二版的对齐也会变，两处都跟界面同步一次。
    void loadTranslations();
    void refreshAltReview();
    const replace = res.replace;
    reshape.applied = {
      ...reshape.applied,
      [key]: { at: Date.now(), delta: replace.inserted - replace.replaced },
    };
    const nextDrafts = { ...reshape.drafts };
    delete nextDrafts[key];
    // 其它段的草稿是针对「覆盖前」的表格解析的，指纹已经变了：留着只会 409。
    const droppedOthers = Object.keys(nextDrafts).length;
    reshape.drafts = nextDrafts;
    toast(
      `已覆盖第 ${replace.from}–${replace.to} 条：${replace.replaced} 条 → ${replace.inserted} 条（⌘Z 可整批撤回）`,
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
        (item, position) => position > reshape.segmentIndex && !reshape.applied[segmentKey(item)],
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
  return Object.keys(reshape.applied).length;
}
