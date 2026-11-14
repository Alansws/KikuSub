/**
 * 双引擎复核的前端状态。
 *
 * 第二版是只读参考：页面只做对齐展示与两种兜底操作（丢弃 / 整列覆盖）。
 * 对齐与 diff **每次都由服务端按当前两份字幕现算**，这里只缓存结果——用户在
 * 核对台改一句后切回来，重新拉一次就是最新的。
 */

import { api, type Cue, type DualRow, type DualStats } from './api';
import { app, applyCueSnapshot, scheduleDraftSave, toast } from './store.svelte';

export const dual = $state({
  exists: false,
  engine: '',
  count: 0,
  cues: [] as Cue[],
  source: {} as Record<string, any>,
  params: {} as Record<string, unknown>,
  createdAt: 0,
  rows: [] as DualRow[],
  stats: null as DualStats | null,
  loading: false,
  replacing: false,
  error: '',
  /** 只看差异（= / ~ / + / − 里只留 ~ + −）。 */
  onlyDiff: true,
  /** 进入页面时接管的媒体 id：换片后自动重拉。 */
  mediaId: '',
});

/** 引擎 key → 用户看到的名称（注册表里找不到时退回 key）。 */
export function altEngineLabel(): string {
  const key = dual.engine;
  if (!key) return '第二引擎';
  return app.config?.engines.find((engine) => engine.key === key)?.label ?? key;
}

export function altParamsLabel(): string {
  const entries = Object.entries(dual.params ?? {});
  if (!entries.length) return '默认参数';
  return entries
    .slice(0, 4)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(' · ');
}

export function resetAltReview() {
  dual.exists = false;
  dual.engine = '';
  dual.count = 0;
  dual.cues = [];
  dual.source = {};
  dual.params = {};
  dual.createdAt = 0;
  dual.rows = [];
  dual.stats = null;
  dual.error = '';
  dual.mediaId = app.media?.id ?? '';
}

/** 拉摘要 + 统计（徽标只需要这个）。 */
export async function refreshAltReview() {
  if (!app.connected) return;
  dual.loading = true;
  dual.error = '';
  try {
    const data = await api.getAltReview(false);
    dual.exists = data.exists;
    dual.engine = data.engine;
    dual.count = data.count;
    dual.cues = data.cues ?? [];
    dual.source = data.source ?? {};
    dual.params = data.params ?? {};
    dual.createdAt = data.created_at ?? 0;
    dual.stats = data.stats ?? null;
    dual.mediaId = app.media?.id ?? '';
    if (!data.exists) dual.rows = [];
  } catch (err) {
    dual.error = (err as Error).message;
  } finally {
    dual.loading = false;
  }
}

/** 拉对齐行（进入双引擎复核页时调用）。 */
export async function loadAltDiff() {
  if (!app.connected) return;
  if (!dual.exists && dual.mediaId === (app.media?.id ?? '')) {
    // 还没拉过摘要：先拉一次；有第二版再继续拉 diff
    await refreshAltReview();
    if (!dual.exists) return;
  }
  dual.loading = true;
  dual.error = '';
  try {
    const data = await api.getAltReview(true);
    dual.exists = data.exists;
    dual.engine = data.engine;
    dual.count = data.count;
    dual.cues = data.cues ?? [];
    dual.source = data.source ?? {};
    dual.params = data.params ?? {};
    dual.createdAt = data.created_at ?? 0;
    dual.rows = data.rows ?? [];
    dual.stats = data.stats ?? null;
    dual.mediaId = app.media?.id ?? '';
  } catch (err) {
    dual.error = (err as Error).message;
  } finally {
    dual.loading = false;
  }
}

export async function deleteAltReview() {
  try {
    await api.deleteAltReview();
    resetAltReview();
    toast('已删除第二版字幕（核对台未改动）');
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  }
}

export async function replacePrimaryWithAlt(clearAlt = true) {
  if (dual.replacing) return false;
  if (!dual.exists) {
    toast('还没有第二版字幕', 'warn');
    return false;
  }
  dual.replacing = true;
  try {
    const res = await api.replacePrimaryWithAlt(clearAlt);
    applyCueSnapshot(res);
    scheduleDraftSave();
    if (clearAlt) resetAltReview();
    else await refreshAltReview();
    toast(`已用第二版覆盖核对台（${res.replaced} 条，⌘Z 可一次撤回）`);
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  } finally {
    dual.replacing = false;
  }
}
