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

export type ArbitrationRole = 'user' | 'assistant';

/** 多轮追问里的一条消息；assistant 消息带 note / model 供结果卡使用。 */
export interface ArbitrationMessage {
  role: ArbitrationRole;
  text: string;
  note?: string;
  model?: string;
}

/**
 * 一句字幕的临时对话。
 *
 * 只存在内存：`key` 由媒体 + 起止时间组成，切走再切回还能接着聊；时间或 A/B
 * 被外部改写后 `isFreshThread()` 判假，界面提示重置。
 */
export interface ArbitrationThread {
  key: string;
  mediaId: string;
  start: number;
  end: number;
  textA: string;
  textB: string;
  /** 尚未发送的输入框内容（切句也保留）。 */
  draft: string;
  messages: ArbitrationMessage[];
  updatedAt: number;
}

export const MAX_HINT_CHARS = 400;
export const MAX_HISTORY_ROUNDS = 6;
export const MAX_HISTORY_MESSAGE_CHARS = 260;
export const MAX_HISTORY_CHARS = 400;

/** 单次判定的来源：首次 / 用户追加追问 / 清空历史后重判 / 自动判定。 */
export type ArbitrationRequestMode = 'initial' | 'followup' | 'rejudge' | 'auto';

export interface ArbitrationRequestPlan {
  /** 本次请求要带的追问历史；`rejudge` / `auto` / `initial` 永远为空。 */
  history: Array<{ role: ArbitrationRole; text: string }>;
  /** 输入框里的线索；`auto` 恒为空。 */
  hint: string;
  /** 成功回来后是否从空历史重建（clean rejudge 的核心）。 */
  resetThread: boolean;
  /** 成功回来后是否把本次 hint 记成一条用户气泡。 */
  recordHint: boolean;
}

/**
 * 把一次点击翻译成「请求带什么 + 回来后线程怎么变」。
 *
 * 用户报障（2026-11-20）：多轮追问后点「重新判定」，旧追问与 AI 回复仍被塞进
 * `history`，模型继续引用上一轮的错误结论。所以 `rejudge` 必须**丢掉 messages**
 * 里的所有旧问答，只保留 A/B、前后文与输入框里这一次新写的线索；`followup`
 * 才是唯一会携带历史的路径，而且只有输入框非空时才会追加。
 */
export function planArbitrationRequest(opts: {
  mode: ArbitrationRequestMode;
  draft: string;
  messages: ArbitrationMessage[];
}): ArbitrationRequestPlan {
  const draft = String(opts.draft || '').trim().slice(0, MAX_HINT_CHARS);
  const messages = Array.isArray(opts.messages) ? opts.messages : [];
  if (opts.mode === 'auto') {
    return { history: [], hint: '', resetThread: true, recordHint: false };
  }
  if (opts.mode === 'followup') {
    return {
      history: historyForRequest(messages),
      hint: draft,
      resetThread: false,
      recordHint: Boolean(draft),
    };
  }
  // rejudge 与 initial 都是干净起点：不携带任何旧追问 / 旧 AI 回复。
  // 输入框里当前写着的线索仍算「本次材料」，所以允许随请求发送；
  // 输入框为空时 hint 就是空串（截图里那次重判正是这种情况）。
  return { history: [], hint: draft, resetThread: true, recordHint: Boolean(draft) };
}

/** 线程里是否已经有追问（用户气泡，或不止第一条 AI 结果）。 */
export function hasFollowUpHistory(messages: ArbitrationMessage[]): boolean {
  if (messages.some((item) => item.role === 'user')) return true;
  return messages.filter((item) => item.role === 'assistant').length > 1;
}

/** 「重新判定」按钮在已有追问时明确提示会清空历史。 */
export function rejudgeButtonLabel(hasHistory: boolean): string {
  return hasHistory ? '清空追问并重判' : '重新判定';
}

/** 最后一条用户追问的位置；没有追问时返回 -1。 */
export function lastUserPosition(messages: ArbitrationMessage[]): number {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].role === 'user') return i;
  }
  return -1;
}

/**
 * 从某条用户追问开始截断：这条追问与它之后的 AI 回复一起撤掉。
 *
 * 只在前端内存里改数组，不重新请求模型；调用方把截断后的最后一条 AI 结果
 * 同步回右侧结果卡即可。传错位置（不是 user）时原样返回，调用方用长度差判断。
 */
export function truncateFromUser(
  messages: ArbitrationMessage[],
  position: number,
): ArbitrationMessage[] {
  if (!Number.isInteger(position) || position < 0 || position >= messages.length) {
    return messages.slice();
  }
  if (messages[position].role !== 'user') return messages.slice();
  return messages.slice(0, position);
}

export function cueThreadKey(mediaId: string, cue: Pick<Cue, 'start' | 'end'>): string {
  return `${mediaId || ''}|${cue.start.toFixed(3)}|${cue.end.toFixed(3)}`;
}

export function isFreshThread(
  thread: ArbitrationThread | null | undefined,
  cue: Cue | null | undefined,
  textB: string,
  mediaId: string,
): boolean {
  if (!thread || !cue) return false;
  if (thread.mediaId !== mediaId) return false;
  return (
    Math.abs(thread.start - cue.start) <= 1e-6 &&
    Math.abs(thread.end - cue.end) <= 1e-6 &&
    thread.textA === cue.text &&
    thread.textB === textB
  );
}

export function latestAssistant(
  thread: ArbitrationThread | null | undefined,
): ArbitrationMessage | null {
  if (!thread) return null;
  for (let i = thread.messages.length - 1; i >= 0; i -= 1) {
    if (thread.messages[i].role === 'assistant') return thread.messages[i];
  }
  return null;
}

export function hasThreadResult(thread: ArbitrationThread | null | undefined): boolean {
  return latestAssistant(thread) !== null;
}

/**
 * 取最近 6 轮、总字符预算内的追问记录。
 *
 * 与后端 `core/ai_arbitrate._clean_history()` 同口径：先丢最旧的整轮，仍超才
 * 截断最旧的一条。后端会再裁一次，这里先裁是为了让请求体本身就小。
 */
export function historyForRequest(
  messages: ArbitrationMessage[],
): Array<{ role: ArbitrationRole; text: string }> {
  const cleaned = messages
    .filter((item) => item.role === 'user' || item.role === 'assistant')
    .map((item) => ({
      role: item.role,
      text: String(item.text || '').trim().slice(0, MAX_HISTORY_MESSAGE_CHARS),
    }))
    .filter((item) => item.text)
    .slice(-MAX_HISTORY_ROUNDS * 2);
  const chars = () => cleaned.reduce((sum, item) => sum + item.text.length + 4, 0);
  // 从最旧的一条开始丢，保留最近连续对话；开头落在 AI 行也允许（首轮可能没有线索）。
  while (cleaned.length && chars() > MAX_HISTORY_CHARS) cleaned.shift();
  if (cleaned.length && chars() > MAX_HISTORY_CHARS) {
    const overflow = chars() - MAX_HISTORY_CHARS;
    const first = cleaned[0];
    first.text = first.text.slice(0, Math.max(0, first.text.length - overflow)).trim();
    if (!first.text) cleaned.shift();
  }
  return cleaned;
}

/** 按钮文案按当前材料自适应；不改变实际发送内容。 */
export function arbitrationButtonLabel(opts: {
  textA: string;
  textB: string;
  hint: string;
  hasRecord: boolean;
}): string {
  const a = opts.textA.trim();
  const b = opts.textB.trim();
  const hint = opts.hint.trim();
  // 已有结果时按钮是「重新判定」而不是「追问」：追问走独立的发送按钮，
  // 否则同一颗按钮会在两种语义之间漂移，正是旧 bug 的来源。
  if (opts.hasRecord) return '重新判定';
  if (a && b) {
    if (a === b) return '让 AI 复核';
    return '让 AI 判定';
  }
  if (a || b) return hint ? '根据线索辅助修正' : '让 AI 辅助修正';
  return hint ? '根据线索推断' : '根据上下文与线索推断';
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
