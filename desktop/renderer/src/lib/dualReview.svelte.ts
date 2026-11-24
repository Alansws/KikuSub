/**
 * 双引擎复核的前端状态。
 *
 * 第二版仍是只读参考：页面只做对齐展示，加上三种写回（整列覆盖、单句采用 B、
 * 丢弃）。**单句采用不新增写接口**：它把 B 那一行的文本走 `updateCue()` 写回核对台
 * （统一 50 步历史、带 label、⌘Z 一次撤回），所以永远不会出现两套可编辑字幕。
 * 对齐与 diff **每次都由服务端按当前两份字幕现算**，这里只缓存结果——用户在
 * 核对台改一句后切回来，重新拉一次就是最新的。
 */

import { api, type Cue, type DualRow, type DualStats } from './api';
import { app, applyCueSnapshot, scheduleDraftSave, toast, updateCue } from './store.svelte';

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
  /**
   * 忽略标点与空格（默认开）：只有标点 / 空白不同的行由服务端判为一致，
   * 不再计入「~ 文本不同」与侧栏徽标。关掉就回到逐字严格比对。
   */
  ignorePunct: true,
  /** 正在「采用 B」的那条 A 下标；-1 = 空闲。防连点压出两步历史。 */
  adopting: -1,
  /**
   * 差异排序（默认按时间）。`ratio-asc` = 相似度最低的排最前：专名被听错、
   * 整句幻觉这类差异的相似度往往接近 0，混在时间序里根本看不见
   * （实测 `だーてん` vs `当店、魔族` 的 ratio 就是 0.000）。
   * 只在「只看差异」的思路下有意义，但也允许在全量视图里用。
   */
  sort: 'time' as 'time' | 'ratio-asc',
  /**
   * 刚从对照表点走的那一行（`a-b` 索引）。回来后高亮它，让用户一眼看到
   * 「刚才看的就是这一句」；B 版换了就没有意义了，重新拉取时清掉。
   */
  anchor: '',
  /** 进入页面时接管的媒体 id：换片后自动重拉。 */
  mediaId: '',
});

/** 第二版是不是导入稿（没有转写参数、没有 job_id）。 */
export function altIsImported(): boolean {
  return dual.source?.kind === 'import';
}

/** 引擎 key → 用户看到的名称（注册表里找不到时退回 key；导入稿额外标注）。 */
export function altEngineLabel(): string {
  const key = dual.engine;
  const base = key
    ? app.config?.engines.find((engine) => engine.key === key)?.label ?? key
    : '';
  if (altIsImported()) return base ? `${base}（导入）` : '导入稿';
  return base || '第二引擎';
}

export function altParamsLabel(): string {
  if (altIsImported()) return '导入稿 · 无转写参数';
  const entries = Object.entries(dual.params ?? {});
  if (!entries.length) return '默认参数';
  return entries
    .slice(0, 4)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(' · ');
}

/**
 * 认领「这是哪一份 B」：媒体 id + 生成时间。
 * 换了人，之前点过的那一行就作废（横幅高亮不能挂到新表的同号行上）。
 */
function adoptAltIdentity(createdAt: number) {
  const nextMedia = app.media?.id ?? '';
  const nextCreatedAt = createdAt ?? 0;
  if (dual.mediaId !== nextMedia || dual.createdAt !== nextCreatedAt) dual.anchor = '';
  dual.createdAt = nextCreatedAt;
  dual.mediaId = nextMedia;
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
  dual.anchor = '';
  dual.mediaId = app.media?.id ?? '';
}

/** 拉摘要 + 统计（徽标只需要这个）。 */
export async function refreshAltReview() {
  if (!app.connected) return;
  dual.loading = true;
  dual.error = '';
  try {
    const data = await api.getAltReview(false, dual.ignorePunct);
    dual.exists = data.exists;
    dual.engine = data.engine;
    dual.count = data.count;
    dual.cues = data.cues ?? [];
    dual.source = data.source ?? {};
    dual.params = data.params ?? {};
    dual.stats = data.stats ?? null;
    adoptAltIdentity(data.created_at ?? 0);
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
    const data = await api.getAltReview(true, dual.ignorePunct);
    dual.exists = data.exists;
    dual.engine = data.engine;
    dual.count = data.count;
    dual.cues = data.cues ?? [];
    dual.source = data.source ?? {};
    dual.params = data.params ?? {};
    dual.rows = data.rows ?? [];
    dual.stats = data.stats ?? null;
    adoptAltIdentity(data.created_at ?? 0);
  } catch (err) {
    dual.error = (err as Error).message;
  } finally {
    dual.loading = false;
  }
}

/**
 * 导入一份已经做好的字幕作为第二版。
 *
 * 与「换引擎再整片转一次」写的是同一个 `AltReview`：边车按媒体身份落盘、切媒体
 * 自动恢复、实时 diff、双源润色 / 断句重排参考、整列覆盖全部复用；核对台不动。
 */
export async function importAltReview(): Promise<boolean> {
  const dir = app.config?.export_dir || app.config?.output_dir || '';
  const file = await window.kikusub.pickSubtitle(dir, '选择第二版字幕');
  if (!file) return false;
  if (
    dual.exists &&
    !window.confirm(
      `导入会替换当前第二版（${altEngineLabel()} · ${dual.count} 条）。\n\n核对台不会改动，这一步也不进撤销历史。继续？`,
    )
  ) {
    return false;
  }
  dual.loading = true;
  dual.error = '';
  try {
    const res = await api.importAltReview(file);
    await refreshAltReview();
    await loadAltDiff();
    const name = file.split('/').pop() || file;
    if (res.warning) {
      toast(`已导入第二版 ${res.count} 条；${res.warning}`, 'warn');
    } else {
      toast(`已导入第二版 ${res.count} 条（${name}）`);
    }
    return true;
  } catch (err) {
    toast(`导入第二版失败：${(err as Error).message}`, 'error');
    return false;
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

/**
 * 切换「忽略标点与空格」并重拉 diff。
 *
 * 过滤在服务端做（`core/dual_review.build_review`），所以必须重拉而不是本地过滤：
 * 本地过滤只能隐掉行，改不了「~ 文本不同」与徽标的口径。
 */
export async function setIgnorePunct(value: boolean) {
  if (dual.ignorePunct === value) return;
  dual.ignorePunct = value;
  await loadAltDiff();
}

/**
 * 切换对照表的排序。纯前端视图状态，不重拉、不改服务端的对齐结果。
 *
 * 排序只影响**行的呈现顺序**，不影响 `a_indices` / `b_indices` 与「采用 B」的
 * 写回目标——那一行仍然指回核对台原来那条。
 */
export function setDualSort(value: 'time' | 'ratio-asc') {
  if (dual.sort === value) return;
  dual.sort = value;
}

/**
 * 单句「采用 B」：把 B 这一行的文本写回核对台的同一条字幕。
 *
 * 只换文本，**不动时间轴**——B 的时间和 A 是两套断句，混着改会让时间码悄悄漂移；
 * 需要 B 的时间就整列覆盖（或回核对台手改）。
 * 走的仍是 `updateCue()`：一步统一历史、带 label、⌘Z 一次撤回。
 */
export async function adoptAltText(index: number, text: string): Promise<boolean> {
  if (dual.adopting >= 0) return false;
  const cue = app.cues[index];
  if (!cue) {
    toast('这一句在核对台已经不存在了，刷新对照再试', 'warn');
    return false;
  }
  if (!text.trim()) {
    toast('B 这一行是空的，没有可采用的文本', 'warn');
    return false;
  }
  if (cue.text === text) return false;
  dual.adopting = index;
  try {
    await updateCue(index, { text }, `采用第二版：第 ${index + 1} 条`);
    return true;
  } finally {
    dual.adopting = -1;
  }
}
