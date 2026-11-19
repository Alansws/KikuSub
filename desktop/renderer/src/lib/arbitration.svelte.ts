/**
 * 单句 AI 判定的状态机。
 *
 * 结果只存在当前会话内存里：它是一次「第三版建议」，采用后才通过 `updateCue()`
 * 进入字幕与统一历史。判定失败/取消不会碰字幕、质检或提案文件。
 *
 * 与 `secondOpinion.svelte.ts` 的分工：那边负责 A/B 两版引擎复核，这里负责把
 * A/B 与前后文送给 AI 拿第三版；两者都只读结果，采用都要用户点。
 */

import { api, type AiConfig } from './api';
import { alternativeText, currentEngineKey } from './secondOpinion.svelte';
import {
  contextFor,
  isFreshRecord,
  type ArbitrationRecord,
} from './arbitration';
import { app, toast, updateCue } from './store.svelte';

export const arbitration = $state({
  records: {} as Record<number, ArbitrationRecord>,
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

export async function runArbitration(index: number): Promise<void> {
  if (arbitration.runningIndex >= 0) {
    toast('AI 正在判定另一句，等它完成或取消后再试', 'warn');
    return;
  }
  const cue = app.cues[index];
  const textB = alternativeText(index);
  if (!cue) return;
  if (!textB.trim()) {
    toast('先用另一引擎复核这一句，出两版后再让 AI 判定', 'warn');
    return;
  }
  if (!cue.text.trim() && !textB.trim()) return;
  if (cue.text.trim() === textB.trim()) {
    toast('两版一致，不需要 AI 判定');
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

  const mediaId = app.media?.id || '';
  const snapshot = { start: cue.start, end: cue.end, textA: cue.text };
  const context = contextFor(app.cues, index);
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
      },
      {
        globalKey,
        arbitrateKey,
        useArbitrate: override,
        signal: controller.signal,
      },
    );
    // 换片 / 改句都可能在请求期间发生：结果只归发起时那条快照。
    if (app.media?.id !== mediaId) return;
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

/** 取消只是中断前端请求；服务端那条短请求会自行结束，结果被丢弃。 */
export function cancelArbitration(): void {
  inflight?.abort();
  inflight = null;
  arbitration.runningIndex = -1;
  arbitration.stage = '';
}

export function dismissArbitration(index: number): void {
  delete arbitration.records[index];
  delete arbitration.errors[index];
  if (arbitration.runningIndex === index) cancelArbitration();
}

export async function adoptArbitration(index: number): Promise<void> {
  const record = arbitrationRecord(index);
  if (!record) return;
  await updateCue(index, { text: record.text });
  delete arbitration.records[index];
  toast('已采用 AI 判定（可撤销）');
}

/** 仅开发截图：灌一份假的第三版结果，避免为看卡片真加载本地模型。 */
export function applyDevArbitration(seed: {
  index?: number;
  text?: string;
  note?: string;
  model?: string;
}): void {
  const index = Number(seed?.index ?? 0);
  const cue = app.cues[index];
  if (!cue) return;
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
}
