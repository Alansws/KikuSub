/**
 * 单句 AI 判定的状态机（含多轮追问的临时会话缓存与浮窗开关）。
 *
 * 结果只存在当前会话内存里：它是一次「第三版建议」，采用后才通过 `updateCue()`
 * 进入字幕与统一历史。判定失败/取消不会碰字幕、质检或提案文件。
 *
 * 与 `secondOpinion.svelte.ts` 的分工：那边负责 A/B 两版引擎复核，这里负责把
 * A/B、上下文、听音线索与追问记录送给 AI 拿第三版；两者都只读结果，采用都要用户点。
 *
 * 对话按「媒体 + 起止时间」缓存：切到别的句子再切回来，之前磨到一半的对话还在。
 * 时间或 A/B 被外部改写时线程判旧（界面提示重置），绝不把旧结论当新句子的答案。
 */

import { api, type AiConfig } from './api';
import { alternativeText, currentEngineKey } from './secondOpinion.svelte';
import {
  MAX_HINT_CHARS,
  contextFor,
  cueThreadKey,
  hasThreadResult,
  isFreshRecord,
  isFreshThread,
  lastUserPosition,
  latestAssistant,
  planArbitrationRequest,
  truncateFromUser,
  type ArbitrationMessage,
  type ArbitrationRecord,
  type ArbitrationRequestMode,
  type ArbitrationThread,
} from './arbitration';
import { app, toast, updateCue } from './store.svelte';

const MAX_THREADS = 60;
const MAX_THREAD_MESSAGES = 30;

export const arbitration = $state({
  records: {} as Record<number, ArbitrationRecord>,
  /** 「媒体 + 起止时间」→ 临时对话；只在内存，切换句子不丢。 */
  threads: {} as Record<string, ArbitrationThread>,
  /** 同一时间只允许判定一句；切换选中不会中断在途请求。 */
  runningIndex: -1,
  /** 运行中的阶段文案（准备本地模型 / 判定中）。 */
  stage: '',
  errors: {} as Record<number, string>,
  config: null as AiConfig | null,
  configLoading: false,
  configError: '',
  hasGlobalKey: false,
  hasArbKey: false,
  /** 多轮对话浮窗：固定在打开时那一句，不随选中跳动。 */
  dialogOpen: false,
  dialogIndex: -1,
});

let inflight: AbortController | null = null;
let configLoaded = false;
/** 自动判定去重：同一媒体 + 同一句 + 同一 B 文本只自动跑一次。 */
const autoTried = new Set<string>();

export function takeAutoArbitrationKey(key: string): boolean {
  if (autoTried.has(key)) return false;
  autoTried.add(key);
  // 长片里最多也就几百条字幕，给一个上限防止跨媒体无界增长。
  if (autoTried.size > 2000) {
    const oldest = autoTried.values().next().value;
    if (oldest) autoTried.delete(oldest);
  }
  return true;
}

/** 覆盖只在 base_url / model 任一非空时生效；空则整组跟随全局。 */
export function usesArbitrateOverride(cfg: AiConfig | null): boolean {
  return Boolean(cfg && (cfg.arbitrate_base_url || cfg.arbitrate_model));
}

export function arbitrateModelName(cfg: AiConfig | null): string {
  if (!cfg) return '';
  return usesArbitrateOverride(cfg)
    ? cfg.arbitrate_model || cfg.model
    : cfg.model;
}

/** 当前句的主语种（ja / zh）；注册表没有时按日语处理。 */
export function arbitrationLang(): string {
  const key = currentEngineKey();
  const engine = app.config?.engines?.find((item) => item.key === key);
  return engine?.languages?.[0] || 'ja';
}

export async function loadArbitrationConfig(force = false): Promise<AiConfig | null> {
  if (!force && configLoaded && arbitration.config) return arbitration.config;
  arbitration.configLoading = true;
  arbitration.configError = '';
  try {
    const cfg = await api.getAiConfig();
    arbitration.config = cfg;
    configLoaded = true;
    const status = window.kikusub?.aiKey?.status;
    const [globalKey, arbKey] = await Promise.all([
      status ? status('global').catch(() => null) : null,
      status ? status('arbitrate').catch(() => null) : null,
    ]);
    arbitration.hasGlobalKey = Boolean(globalKey?.has);
    arbitration.hasArbKey = Boolean(arbKey?.has);
    return cfg;
  } catch (err) {
    arbitration.config = null;
    configLoaded = false;
    arbitration.configError = (err as Error).message || '读取 AI 配置失败';
    return null;
  } finally {
    arbitration.configLoading = false;
  }
}

/** 当前句仍有效的第三版结果；A/B/时间/媒体任一变化都返回 null。 */
export function arbitrationRecord(index: number): ArbitrationRecord | null {
  const record = arbitration.records[index];
  const fresh = isFreshRecord(
    record,
    app.cues[index],
    alternativeText(index),
    app.media?.id || '',
  );
  return fresh ? record : null;
}

export function hasArbitration(index: number): boolean {
  return arbitrationRecord(index) !== null;
}

function threadForCue(index: number): ArbitrationThread | null {
  const cue = app.cues[index];
  if (!cue) return null;
  return arbitration.threads[cueThreadKey(app.media?.id || '', cue)] ?? null;
}

/** 当前句仍有效的对话线程；时间 / A / B 被外部改写后返回 null。 */
export function arbitrationThread(index: number): ArbitrationThread | null {
  const thread = threadForCue(index);
  const cue = app.cues[index];
  if (!thread || !cue) return null;
  return isFreshThread(thread, cue, alternativeText(index), app.media?.id || '')
    ? thread
    : null;
}

/** 有历史结果、但对不上当前句：界面提示「已失效」并提供重置。 */
export function arbitrationThreadStale(index: number): boolean {
  const thread = threadForCue(index);
  if (!thread || !thread.messages.length) return false;
  return arbitrationThread(index) === null;
}

export function arbitrationDraft(index: number): string {
  return arbitrationThread(index)?.draft ?? threadForCue(index)?.draft ?? '';
}

export function arbitrationMessages(index: number): ArbitrationMessage[] {
  // 失效的线程也把旧消息留给浮窗展示（只读提示重置），否则「失效」等于内容凭空消失。
  return (arbitrationThread(index) ?? threadForCue(index))?.messages ?? [];
}

export function arbitrationHasResult(index: number): boolean {
  return hasThreadResult(arbitrationThread(index));
}

function pruneThreads(): void {
  const entries = Object.entries(arbitration.threads);
  if (entries.length <= MAX_THREADS) return;
  entries.sort((a, b) => (a[1].updatedAt || 0) - (b[1].updatedAt || 0));
  for (const [key] of entries.slice(0, entries.length - MAX_THREADS)) {
    delete arbitration.threads[key];
  }
}

function ensureThread(index: number): ArbitrationThread | null {
  const cue = app.cues[index];
  if (!cue) return null;
  const mediaId = app.media?.id || '';
  const key = cueThreadKey(mediaId, cue);
  const textB = alternativeText(index);
  let thread = arbitration.threads[key];
  if (!thread) {
    thread = {
      key,
      mediaId,
      start: cue.start,
      end: cue.end,
      textA: cue.text,
      textB,
      draft: '',
      messages: [],
      updatedAt: Date.now(),
    };
    arbitration.threads[key] = thread;
    pruneThreads();
  } else if (!thread.messages.length) {
    // 还没产生结果的空线程：文本 / 时间变了就静默刷新，别让用户看到「已失效」。
    thread.start = cue.start;
    thread.end = cue.end;
    thread.textA = cue.text;
    thread.textB = textB;
    thread.updatedAt = Date.now();
  }
  return thread;
}

export function setArbitrationDraft(index: number, text: string): void {
  const thread = ensureThread(index);
  if (thread) thread.draft = String(text || '').slice(0, MAX_HINT_CHARS);
}

/** 清掉这一句的临时对话与结果；不影响字幕与统一历史。 */
export function resetArbitrationThread(index: number): void {
  const cue = app.cues[index];
  if (!cue) return;
  const key = cueThreadKey(app.media?.id || '', cue);
  delete arbitration.threads[key];
  delete arbitration.records[index];
  delete arbitration.errors[index];
  if (arbitration.runningIndex === index) cancelArbitration();
}

export function openArbitrationDialog(index: number): void {
  if (!app.cues[index]) return;
  arbitration.dialogIndex = index;
  arbitration.dialogOpen = true;
}

export function closeArbitrationDialog(): void {
  arbitration.dialogOpen = false;
}

/**
 * 首次判定前把本机 LM Studio 的 context 校准到设置档位。
 *
 * 只在 loopback LM Studio 上执行；同一 base/model/档位在一次应用生命周期里只
 * 检查一次。模型已在该档位时是纯 no-op；未加载或档位不同才走一次 unload/load。
 * 返回 false 表示取消或模型不可用（调用方应停止本次判定）。
 */
async function prepareLocalModel(cfg: AiConfig, signal: AbortSignal): Promise<boolean> {
  try {
    // 每次判定前只做一次轻量 status 探测；只有档位不符 / 模型未加载才重载。
    // 这样 JIT 在 TTL 后按 LM Studio 默认档位重新加载时，也能在下一次判定前
    // 自动校准回设置的 2048，而不是每个请求都盲目重载 27B。
    const status = await api.localModelStatus();
    if (signal.aborted) return false;
    if (!status.available) return true; // 不是 LM Studio / 未运行：交给 chat 请求报错
    if (status.loaded && status.context_length === cfg.local_context) return true;
    arbitration.stage = `正在按 ${cfg.local_context} 准备本地模型…`;
    await api.loadLocalModel(cfg.local_context);
    if (signal.aborted) return false;
    return true;
  } catch (err) {
    const index = arbitration.runningIndex;
    if (index >= 0) arbitration.errors[index] = (err as Error).message;
    return false;
  }
}

export interface ArbitrationRunOptions {
  mode?: ArbitrationRequestMode;
}

/**
 * 发起一次判定。
 *
 * 四种来源必须彻底分开：
 * - `initial`：首次判定，绝不携带旧问答；
 * - `followup`：用户点「发送追问」，只有输入框非空才会追加并携带当前历史；
 * - `rejudge`：清空历史后重判，请求体里的 `history` 恒为空，输入框里当前写着的
 *   新线索可作为本次 hint（为空时 hint 就是空串）；
 * - `auto`：设置里的自动判定，永远不读草稿、不带历史。
 */
export async function runArbitration(
  index: number,
  options: ArbitrationRunOptions = {},
): Promise<void> {
  if (arbitration.runningIndex >= 0) {
    toast('AI 正在判定另一句，等它完成或取消后再试', 'warn');
    return;
  }
  const mode = options.mode ?? 'initial';
  const cue = app.cues[index];
  if (!cue) return;
  const textB = alternativeText(index);
  const mediaId = app.media?.id || '';
  let thread = ensureThread(index);
  // 外部改写了时间 / A / B：旧问答不再可信。自动判定等非 UI 路径可能绕过
  // 「失效」提示，这里从新快照重开一条，避免把旧答案混进新请求。
  if (thread && thread.messages.length && !isFreshThread(thread, cue, textB, mediaId)) {
    delete arbitration.threads[thread.key];
    thread = ensureThread(index);
  }
  const plan = planArbitrationRequest({
    mode,
    draft: thread?.draft ?? '',
    messages: thread?.messages ?? [],
  });
  const hint = plan.hint;
  const history = plan.history;
  if (mode === 'followup' && !hint) {
    toast('先在输入框里写下要追问的线索，再点「发送追问」', 'warn');
    return;
  }
  const context = contextFor(app.cues, index);
  const hasContext = context.before.length > 0 || context.after.length > 0;
  // 不再拦「B 为空 / 两版一致」：音量太小、B 引擎没识别、手动新建的空字幕块，
  // 只要有文本、线索、追问或上下文之一，就允许 AI 还原。
  if (!cue.text.trim() && !textB.trim() && !hint && !history.length && !hasContext) {
    toast('没有可发送的材料：先输入文本或补一条听音线索', 'warn');
    return;
  }

  const cfg = await loadArbitrationConfig(true);
  if (!cfg) {
    arbitration.errors[index] = arbitration.configError || '读取 AI 配置失败';
    return;
  }
  if (!cfg.enabled) {
    arbitration.errors[index] = 'AI 优化未启用：到「设置 → AI 优化」打开它';
    return;
  }
  if (!cfg.base_url || !cfg.model) {
    arbitration.errors[index] = '还没有配置 AI 服务：到「设置 → AI 优化」填写地址与模型';
    return;
  }

  const override = usesArbitrateOverride(cfg);
  const keyOptional = override ? cfg.arbitrate_key_optional : cfg.key_optional;
  const globalKey = (await window.kikusub?.aiKey?.get?.('global')) || '';
  const arbitrateKey = override
    ? (await window.kikusub?.aiKey?.get?.('arbitrate')) || ''
    : '';
  const effectiveKey = override ? arbitrateKey || globalKey : globalKey;
  if (!effectiveKey && !keyOptional) {
    arbitration.errors[index] = override
      ? '单句判定模型还没有配置 Key：到「设置 → AI 优化 → 单句判定模型覆盖」填写'
      : '还没有配置 API Key：到「设置 → AI 优化」填写（本地模型可留空）';
    return;
  }

  const snapshot = { start: cue.start, end: cue.end, textA: cue.text };
  const controller = new AbortController();
  inflight = controller;
  arbitration.runningIndex = index;
  arbitration.stage = '';
  delete arbitration.errors[index];
  try {
    // 只在本机 LM Studio 上做一次「档位准备」：JIT 的默认 context 可能不是
    // 设置里的档位；这里在**首次判定前**校准一次，而不是每个请求都重载。
    if (cfg.arbitrate_loopback) {
      const prepared = await prepareLocalModel(cfg, controller.signal);
      if (!prepared) return;
    }
    if (controller.signal.aborted) return;
    arbitration.stage = '';
    const result = await api.arbitrateAi(
      {
        text_a: cue.text,
        text_b: textB,
        before: context.before,
        after: context.after,
        lang: arbitrationLang(),
        hint,
        history,
      },
      {
        globalKey,
        arbitrateKey,
        useArbitrate: override,
        signal: controller.signal,
      },
    );
    // 换片 / 改句 / 改 A / 改 B 都可能在请求期间发生：结果只归发起时那条快照。
    const current = app.cues[index];
    if (app.media?.id !== mediaId) return;
    if (
      !current ||
      Math.abs(current.start - snapshot.start) > 1e-6 ||
      Math.abs(current.end - snapshot.end) > 1e-6 ||
      current.text !== snapshot.textA ||
      alternativeText(index) !== textB
    ) {
      arbitration.errors[index] = '这一句在判定期间被改动了，结果已丢弃；请重试';
      return;
    }
    const liveThread = ensureThread(index);
    if (liveThread) {
      const nextMessages = plan.resetThread ? [] : liveThread.messages.slice();
      if (plan.recordHint && hint) nextMessages.push({ role: 'user', text: hint });
      nextMessages.push({
        role: 'assistant',
        text: result.text,
        note: result.note,
        model: result.model,
      });
      if (nextMessages.length > MAX_THREAD_MESSAGES) {
        nextMessages.splice(0, nextMessages.length - MAX_THREAD_MESSAGES);
      }
      liveThread.messages = nextMessages;
      liveThread.textA = snapshot.textA;
      liveThread.textB = textB;
      if (plan.recordHint) liveThread.draft = '';
      liveThread.updatedAt = Date.now();
    }
    arbitration.records[index] = {
      ...snapshot,
      textB,
      text: result.text,
      note: result.note,
      model: result.model,
      mediaId,
    };
  } catch (err) {
    if (controller.signal.aborted) return;
    arbitration.errors[index] = (err as Error).message || 'AI 判定失败';
  } finally {
    if (inflight === controller) inflight = null;
    if (arbitration.runningIndex === index) arbitration.runningIndex = -1;
    arbitration.stage = '';
  }
}

/**
 * 「发送追问」：只有输入框非空且用户明确点这个动作时才追加。
 *
 * 与 `rejudgeArbitration` 分开，避免用户点「重新判定」时把上一轮的追问继续带进去。
 */
export function sendArbitrationFollowUp(index: number): void {
  if (!arbitrationDraft(index).trim()) {
    toast('先在输入框里写下要追问的线索，再点「发送追问」', 'warn');
    return;
  }
  void runArbitration(index, { mode: 'followup' });
}

/** 「重新判定」：清空历史问答，按原始 A/B + 上下文发起全新请求。 */
export function rejudgeArbitration(index: number): void {
  void runArbitration(index, { mode: 'rejudge' });
}

/** 取消只是中断前端请求；服务端那条短请求会自行结束，结果被丢弃。 */
export function cancelArbitration(): void {
  inflight?.abort();
  inflight = null;
  arbitration.runningIndex = -1;
  arbitration.stage = '';
}

/** 把线程里最后一条 AI 结果同步回右侧结果卡；没有 AI 回复时清掉旧卡。 */
function syncRecordFromThread(index: number, thread: ArbitrationThread): void {
  const last = latestAssistant(thread);
  if (!last) {
    delete arbitration.records[index];
    return;
  }
  arbitration.records[index] = {
    start: thread.start,
    end: thread.end,
    textA: thread.textA,
    textB: thread.textB,
    text: last.text,
    note: last.note || '',
    model: last.model || '',
    mediaId: thread.mediaId,
  };
}

/** 至少有一条可撤回的用户追问。 */
export function canUndoArbitrationFollowUp(index: number): boolean {
  return lastUserPosition(threadForCue(index)?.messages ?? []) >= 0;
}

/**
 * 从某条用户追问开始撤销：截断这条追问与它之后的 AI 回复，不重新请求模型。
 *
 * 截断后如果还剩更早的 AI 回复，右侧结果卡同步回那一条；如果一条不剩，
 * 结果卡也清空。返回实际删掉的消息条数，供 UI/测试判断。
 */
export function undoArbitrationFrom(index: number, position: number): number {
  const thread = threadForCue(index);
  if (!thread) return 0;
  const next = truncateFromUser(thread.messages, position);
  const removed = thread.messages.length - next.length;
  if (removed <= 0) return 0;
  if (arbitration.runningIndex === index) cancelArbitration();
  thread.messages = next;
  thread.updatedAt = Date.now();
  delete arbitration.errors[index];
  syncRecordFromThread(index, thread);
  return removed;
}

/** 底部「↩ 撤回上一轮追问」：找到最后一条用户气泡，从它开始截断。 */
export function undoLastArbitrationFollowUp(index: number): number {
  const thread = threadForCue(index);
  if (!thread) return 0;
  return undoArbitrationFrom(index, lastUserPosition(thread.messages));
}

export function dismissArbitration(index: number): void {
  delete arbitration.records[index];
  delete arbitration.errors[index];
  if (arbitration.runningIndex === index) cancelArbitration();
}

/** 采用任意一轮 AI 回复；仍走 `updateCue()`，统一历史里一步可退。 */
export async function adoptArbitrationMessage(
  index: number,
  message: ArbitrationMessage,
): Promise<void> {
  const text = String(message.text || '').trim();
  if (message.role !== 'assistant' || !text) return;
  await updateCue(index, { text });
  // 采用后 A 变成 AI 文本；把线程快照同步过去，否则下一次追问会立刻判失效。
  // 用当前字幕的真实文本而不是消息文本：服务端归一化 / 失败刷新时口径一致。
  const adopted = app.cues[index]?.text ?? text;
  const thread = ensureThread(index);
  if (thread) {
    thread.textA = adopted;
    thread.updatedAt = Date.now();
  }
  delete arbitration.records[index];
  toast('已采用 AI 判定（可撤销）');
}

export async function adoptArbitration(index: number): Promise<void> {
  const record = arbitrationRecord(index);
  if (!record) return;
  await adoptArbitrationMessage(index, {
    role: 'assistant',
    text: record.text,
    note: record.note,
    model: record.model,
  });
}

/** 仅开发截图：灌一份假的第三版结果 / 对话，避免为看卡片真加载本地模型。 */
export function applyDevArbitration(seed: {
  index?: number;
  text?: string;
  note?: string;
  model?: string;
  hint?: string;
  history?: Array<{ role: 'user' | 'assistant'; text: string; note?: string; model?: string }>;
  dialogOpen?: boolean;
}): void {
  const index = Number(seed?.index ?? 0);
  const cue = app.cues[index];
  if (!cue) return;
  const thread = ensureThread(index);
  if (thread) {
    thread.messages = (seed.history ?? []).map((item) => ({
      role: item.role,
      text: String(item.text || ''),
      note: item.note,
      model: item.model,
    }));
    thread.messages.push({
      role: 'assistant',
      text: String(seed?.text ?? cue.text),
      note: String(seed?.note ?? ''),
      model: String(seed?.model ?? 'dev-model'),
    });
    thread.draft = String(seed?.hint ?? '');
    thread.updatedAt = Date.now();
  }
  arbitration.records[index] = {
    start: cue.start,
    end: cue.end,
    textA: cue.text,
    textB: alternativeText(index) || '',
    text: String(seed?.text ?? cue.text),
    note: String(seed?.note ?? ''),
    model: String(seed?.model ?? 'dev-model'),
    mediaId: app.media?.id || '',
  };
  if (seed?.dialogOpen) openArbitrationDialog(index);
}
