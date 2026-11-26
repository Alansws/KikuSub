/**
 * 「AI 补译」的单句草稿状态：请求 → 草稿 → 采纳。
 *
 * 只服务核对台的检查器（双语 / 译文模式下的「这一条还没有译文 / 原文改过了」）。
 * 不写轨、不进历史：结果只是输入框里的一段草稿，用户看过（可改）点「采纳」才走
 * 既有 `updateTranslation()`（一步历史，可 ⌘Z）。
 *
 * 用**单句判定模型**（`ai_arbitrate_*`）而不是翻译页的全局模型：这类片源云端会拒，
 * 本地那份已经为逐句复核加载着；请求也只带相邻几行，不会把整片塞进去。
 *
 * 状态放这里而不是 `store.svelte.ts`：后者有行数预算（只许变短）。
 */
import { api } from './api';
import { app, toast, updateTranslation } from './store.svelte';

export const cueTranslate = $state({
  /** 草稿对应的条下标；-1 = 没有草稿。 */
  index: -1,
  busy: false,
  /** 阶段文案（准备本地模型 / 正在翻）。 */
  stage: '',
  text: '',
  model: '',
  error: '',
});

let inflight: AbortController | null = null;

export function clearCueTranslate() {
  inflight?.abort();
  inflight = null;
  cueTranslate.index = -1;
  cueTranslate.busy = false;
  cueTranslate.stage = '';
  cueTranslate.text = '';
  cueTranslate.model = '';
  cueTranslate.error = '';
}

/** 本机 LM Studio 首次补译前校准一次上下文档位（与逐句判定共用同一条策略）。 */
async function prepareLocalModel(cfg: Awaited<ReturnType<typeof api.getAiConfig>>) {
  if (!cfg.arbitrate_loopback) return;
  try {
    const status = await api.localModelStatus();
    if (!status.available) return;
    if (status.loaded && status.context_length === cfg.local_context) return;
    cueTranslate.stage = `正在按 ${cfg.local_context} 准备本地模型…`;
    await api.loadLocalModel(cfg.local_context);
  } catch {
    // 档位准备失败不该挡住补译：让 chat 请求自己报错，界面会显示原因。
  }
}

/**
 * 请求第 index 条的 AI 草稿。成功返回译文（并写进 `cueTranslate.text`），
 * 失败返回 null 并把原因写进 `cueTranslate.error`。
 */
export async function requestCueTranslation(index: number, lang: string): Promise<string | null> {
  if (cueTranslate.busy) return null;
  const cue = app.cues[index];
  if (!cue || !cue.text.trim()) {
    cueTranslate.error = '这一句原文是空的，没有可翻译的内容';
    return null;
  }
  cueTranslate.index = index;
  cueTranslate.busy = true;
  cueTranslate.stage = '';
  cueTranslate.text = '';
  cueTranslate.error = '';
  const snapshot = cue.text;
  const mediaId = app.media?.id ?? '';
  const controller = new AbortController();
  inflight = controller;
  try {
    const cfg = await api.getAiConfig();
    if (!cfg.enabled) {
      cueTranslate.error = 'AI 优化未启用：到「设置 → AI 优化」打开它';
      return null;
    }
    const override = Boolean(cfg.arbitrate_base_url || cfg.arbitrate_model);
    const keyOptional = override ? cfg.arbitrate_key_optional : cfg.key_optional;
    const globalKey = (await window.kikusub?.aiKey?.get?.('global')) || '';
    const arbitrateKey = override
      ? (await window.kikusub?.aiKey?.get?.('arbitrate')) || ''
      : '';
    const effectiveKey = override ? arbitrateKey || globalKey : globalKey;
    if (!effectiveKey && !keyOptional) {
      cueTranslate.error = override
        ? '单句判定模型还没有配置 Key：到「设置 → AI 优化 → 单句判定模型覆盖」填写'
        : '还没有配置 API Key：到「设置 → AI 优化」填写（本地模型可留空）';
      return null;
    }
    if (override && cfg.arbitrate_loopback) await prepareLocalModel(cfg);
    if (controller.signal.aborted) return null;
    cueTranslate.stage = '正在翻这一句…';
    const result = await api.translateCue(
      { index, lang },
      { globalKey, arbitrateKey, useArbitrate: override, signal: controller.signal },
    );
    // 期间换了片 / 改了选中的那一句：结果作废，别把 A 句的译文填进 B 句。
    if (app.media?.id !== mediaId || app.cues[index]?.text !== snapshot) {
      cueTranslate.error = '这一句在翻译期间被改动了，结果已丢弃；请重试';
      return null;
    }
    cueTranslate.text = result.text;
    cueTranslate.model = result.model;
    return result.text;
  } catch (err) {
    cueTranslate.error = (err as Error).message || 'AI 补译失败';
    return null;
  } finally {
    cueTranslate.busy = false;
    cueTranslate.stage = '';
    if (inflight === controller) inflight = null;
  }
}

/** 采纳当前输入框里的译文（`text` 允许用户改过）；成功返回是否落轨。 */
export async function acceptCueTranslation(index: number, text: string): Promise<boolean> {
  if (!text.trim()) return false;
  cueTranslate.busy = true;
  try {
    await updateTranslation(index, text);
    clearCueTranslate();
    toast('已采纳这一句的译文');
    return true;
  } finally {
    cueTranslate.busy = false;
  }
}
