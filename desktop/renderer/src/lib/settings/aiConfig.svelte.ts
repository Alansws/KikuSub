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
  /** 单句判定覆盖 Key 的独立输入与状态。 */
  arbKeyInput: '',
  arbHasKey: false,
  arbKeyBroken: false,
  arbKeyLegacy: false,
  saving: false,
  testing: false,
  testMsg: '',
  arbTesting: false,
  arbTestMsg: '',
  /** 高级参数展开时才有意义的“已保存”提示 */
  savedAt: 0,
  /** 本机 LM Studio 探测 / 重载状态。 */
  localModel: {
    loading: false,
    checked: false,
    available: false,
    loaded: false,
    contextLength: null as number | null,
    maxContext: null as number | null,
    error: '',
    loadingModel: false,
    message: '',
  },
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
  if (aiState.cfg?.arbitrate_loopback) void loadLocalModelStatus();
}

export async function refreshAiKey() {
  try {
    const status = await window.kikusub?.aiKey?.status?.('global');
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
  try {
    const status = await window.kikusub?.aiKey?.status?.('arbitrate');
    aiState.arbHasKey = Boolean(status?.has);
    aiState.arbKeyBroken = Boolean(status?.broken);
    aiState.arbKeyLegacy = Boolean(status?.legacy);
  } catch {
    aiState.arbHasKey = false;
    aiState.arbKeyBroken = false;
    aiState.arbKeyLegacy = false;
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
      arbitrate_base_url: aiState.cfg.arbitrate_base_url.trim(),
      arbitrate_model: aiState.cfg.arbitrate_model.trim(),
      local_context: aiState.cfg.local_context,
      auto_arbitrate: aiState.cfg.auto_arbitrate,
    });
    if (ok) {
      aiState.savedAt = Date.now();
      // 地址 / 模型可能刚切到本机 LM Studio：重新探测一次档位状态。
      aiState.localModel.checked = false;
      if (aiState.cfg?.arbitrate_loopback) void loadLocalModelStatus();
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

export async function testAiConnection(scope: 'global' | 'arbitrate' = 'global') {
  if (!aiState.cfg) return;
  const testing = scope === 'arbitrate' ? 'arbTesting' : 'testing';
  const message = scope === 'arbitrate' ? 'arbTestMsg' : 'testMsg';
  if (aiState[testing]) return;
  aiState[testing] = true;
  aiState[message] = '';
  try {
    const key = await window.kikusub.aiKey.get(scope);
    const cfg = aiState.cfg;
    const baseUrl =
      scope === 'arbitrate' ? cfg.arbitrate_base_url || cfg.base_url : cfg.base_url;
    const model = scope === 'arbitrate' ? cfg.arbitrate_model || cfg.model : cfg.model;
    const res = await api.testAi({ base_url: baseUrl, model }, key || '');
    aiState[message] = `连接正常 · ${res.latency_ms}ms · ${res.host}`;
  } catch (err) {
    aiState[message] = `连接失败：${(err as Error).message}`;
  } finally {
    aiState[testing] = false;
  }
}

/** 保存单句判定覆盖 Key（与全局 Key 分开加密存放）。 */
export async function saveArbKey() {
  const text = aiState.arbKeyInput.trim();
  if (!text) return;
  try {
    const res = await window.kikusub.aiKey.set(text, 'arbitrate');
    if (!res?.ok) {
      toast('保存失败：应用数据目录不可写', 'error');
      return;
    }
    aiState.arbKeyBroken = false;
    aiState.arbKeyInput = '';
    await refreshAiKey();
    toast('单句判定 Key 已加密保存');
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

export async function clearArbKey() {
  try {
    await window.kikusub.aiKey.clear('arbitrate');
    await refreshAiKey();
    aiState.arbKeyBroken = false;
    aiState.arbTestMsg = '';
    toast('已清除单句判定 Key');
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

export async function loadLocalModelStatus(force = false): Promise<void> {
  const cfg = aiState.cfg;
  if (!cfg?.arbitrate_loopback) {
    aiState.localModel = {
      loading: false,
      checked: true,
      available: false,
      loaded: false,
      contextLength: null,
      maxContext: null,
      error: '',
      loadingModel: false,
      message: '',
    };
    return;
  }
  if (aiState.localModel.loading) return;
  if (!force && aiState.localModel.checked) return;
  aiState.localModel.loading = true;
  try {
    const status = await api.localModelStatus();
    aiState.localModel.checked = true;
    aiState.localModel.available = status.available;
    aiState.localModel.loaded = Boolean(status.loaded);
    aiState.localModel.contextLength = status.context_length ?? null;
    aiState.localModel.maxContext = status.max_context_length ?? null;
    aiState.localModel.error = status.error || '';
  } catch (err) {
    aiState.localModel.checked = true;
    aiState.localModel.available = false;
    aiState.localModel.error = (err as Error).message;
  } finally {
    aiState.localModel.loading = false;
  }
}

export async function setLocalContext(context: number) {
  if (!aiState.cfg) return;
  const ok = await patchAi({ local_context: context });
  if (ok) aiState.localModel.message = '档位已保存；点「加载 / 重载本地模型」后生效';
}

export async function toggleAutoArbitrate() {
  if (!aiState.cfg) return;
  const next = !aiState.cfg.auto_arbitrate;
  if (await patchAi({ auto_arbitrate: next })) {
    toast(next ? '已开启：两版不一致时自动 AI 判定' : '已关闭自动 AI 判定');
  }
}

export async function reloadLocalModel(): Promise<void> {
  if (!aiState.cfg || aiState.localModel.loadingModel) return;
  aiState.localModel.loadingModel = true;
  aiState.localModel.message = '';
  try {
    const result = await api.loadLocalModel(aiState.cfg.local_context);
    aiState.localModel.message = result.reloaded
      ? `已重载到 ${result.context_length}（${result.load_time_seconds ?? '—'}s）`
      : `已在该档位（${result.context_length}）`;
    await loadLocalModelStatus(true);
  } catch (err) {
    aiState.localModel.message = `加载失败：${(err as Error).message}`;
  } finally {
    aiState.localModel.loadingModel = false;
  }
}

/** 高级参数面板上的「当前值」摘要：折叠着也能看见现在是多少。 */
export function advancedParamsSummary(): string {
  const cfg = aiState.cfg;
  if (!cfg) return '';
  return `每块 ${cfg.chunk_cues} · 翻译 ${cfg.translate_chunk_cues} · 上下文 ${cfg.context_cues}`;
}
