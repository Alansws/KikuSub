/**
 * 设置页「AI 与技能 → AI 优化」的状态与动作。
 *
 * 从 `views/SettingsView.svelte` 搬出来（那边原来 700 行的 <script> 混着四个域的状态）。
 * 放在模块级而不是组件里，切换页签不会清空已加载的配置、也不会重复请求；
 * 组件只负责展示与把事件转发进来。
 */
import { api } from '../api';
import { toast } from '../store.svelte';

export type AiConfig = Awaited<ReturnType<typeof api.getAiConfig>>;

export const aiState = $state({
  cfg: null as AiConfig | null,
  loading: false,
  /** 本机加密是否可用（正常恒为 true）。 */
  keyReady: true,
  hasKey: false,
  /** 有密文但解不开，需要重填。 */
  keyBroken: false,
  /** 更早版本用钥匙串存的，本版本读不了。 */
  keyLegacy: false,
  /** 输入框里的新 Key（空字符串 = 没在改）。 */
  keyInput: '',
  saving: false,
  testing: false,
  testMsg: '',
  /** 高级参数展开时才有意义的“已保存”提示 */
  savedAt: 0,
});

export async function loadAiConfig() {
  aiState.loading = true;
  try {
    aiState.cfg = await api.getAiConfig();
  } catch {
    aiState.cfg = null;
  } finally {
    aiState.loading = false;
  }
  await refreshAiKey();
}

export async function refreshAiKey() {
  try {
    const status = await window.kikusub?.aiKey?.status?.();
    aiState.keyReady = status?.available !== false;
    aiState.hasKey = Boolean(status?.has);
    aiState.keyBroken = Boolean(status?.broken);
    aiState.keyLegacy = Boolean(status?.legacy);
  } catch {
    aiState.keyReady = false;
    aiState.hasKey = false;
    aiState.keyBroken = false;
    aiState.keyLegacy = false;
  }
}

export async function patchAi(patch: Parameters<typeof api.patchAiConfig>[0]): Promise<boolean> {
  try {
    aiState.cfg = await api.patchAiConfig(patch);
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  }
}

export async function toggleAi() {
  if (!aiState.cfg) return;
  const next = !aiState.cfg.enabled;
  if (await patchAi({ enabled: next })) {
    toast(next ? 'AI 优化已启用' : 'AI 优化已关闭');
  }
}

/** 保存服务地址 / 模型 / 三个分块参数（高级参数面板也走这里）。 */
export async function saveAiEndpoint(quiet = false): Promise<boolean> {
  if (!aiState.cfg || aiState.saving) return false;
  aiState.saving = true;
  try {
    const ok = await patchAi({
      base_url: aiState.cfg.base_url.trim(),
      model: aiState.cfg.model.trim(),
      chunk_cues: Number(aiState.cfg.chunk_cues) || 200,
      translate_chunk_cues: Number(aiState.cfg.translate_chunk_cues) || 120,
      context_cues: Number(aiState.cfg.context_cues) || 0,
    });
    if (ok) {
      aiState.savedAt = Date.now();
      // 输入框失焦时静默保存（macOS 设置面板的习惯），显式点「保存」才提示
      if (!quiet) toast('AI 配置已保存');
    }
    return ok;
  } finally {
    aiState.saving = false;
  }
}

export async function saveAiKey() {
  const text = aiState.keyInput.trim();
  if (!text) return;
  try {
    const res = await window.kikusub.aiKey.set(text);
    if (!res?.ok) {
      toast('保存失败：应用数据目录不可写', 'error');
      return;
    }
    aiState.keyBroken = false;
    aiState.keyInput = '';
    await refreshAiKey();
    toast('API Key 已加密保存');
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

export async function clearAiKey() {
  try {
    await window.kikusub.aiKey.clear();
    await refreshAiKey();
    aiState.keyBroken = false;
    aiState.testMsg = '';
    toast('已清除 API Key');
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

export async function testAiConnection() {
  if (!aiState.cfg || aiState.testing) return;
  aiState.testing = true;
  aiState.testMsg = '';
  try {
    const key = await window.kikusub.aiKey.get();
    if (!key) {
      aiState.testMsg = '还没有保存 API Key';
      return;
    }
    const res = await api.testAi({ base_url: aiState.cfg.base_url, model: aiState.cfg.model }, key);
    aiState.testMsg = `连接正常 · ${res.latency_ms}ms · ${res.host}`;
  } catch (err) {
    aiState.testMsg = `连接失败：${(err as Error).message}`;
  } finally {
    aiState.testing = false;
  }
}

/** 高级参数面板上的「当前值」摘要：折叠着也能看见现在是多少。 */
export function advancedParamsSummary(): string {
  const cfg = aiState.cfg;
  if (!cfg) return '';
  return `每块 ${cfg.chunk_cues} · 翻译 ${cfg.translate_chunk_cues} · 上下文 ${cfg.context_cues}`;
}
