/**
 * 核对台「工作现场」：波形包络的进程内缓存 + 每部影片的视窗/播放头快照。
 *
 * 两个问题一起解决，但它们**不是**同一层：
 *
 * 1. **切换软件内页面就丢包络**。`App.svelte` 用 `{#key app.view}` 重建视图，
 *    切去润色页再回来时 ReviewView 的 `peaks` 是空的，先白一帧再重新请求；
 *    同一段波形反复拉三次。这里放一个按「媒体 + 视窗 + 采样点数」索引的小 LRU，
 *    挂载后同步命中，不闪、不重复请求。只存内存，进程退出即丢（波形是派生数据，
 *    没有跨重启保留的价值）。
 *
 * 2. **切换影片 / 重启就丢现场**。用户核对到第 137 条，点去转写页再回来，
 *    视窗回到了全片、播放头回到了 0。这里按媒体**文件路径**（不是 media id：
 *    重启后 id 会变）持久化 `{cueIndex, cueTime, playhead, viewStart, span, selection}`
 *    到 localStorage，最近 50 部，LRU 淘汰。
 *
 * **恢复优先级**：外部入口（双引擎复核 / 质检面板 / 报告页点时间码）是显式跳转，
 * 它比「上次停在哪」新，必须赢。`markExplicitJump(path)` 在跳转发起时记一笔，
 * 核对台在恢复前用 `takeExplicitJump(path)` 消费它——显式跳转优先，且只影响这一次。
 *
 * 恢复时序由视图层负责（播放头要等 `loadedmetadata`，缩放/选区要等 duration），
 * 这里只给纯函数：`planViewportRestore()` 负责合法 clamp，越界/损坏一律安全降级。
 */

import type { Cue } from './api';

export interface ReviewViewport {
  /** 当前选中的字幕下标（恢复时若越界，用 cueTime 找最近的一条）。 */
  cueIndex: number;
  /** 选中字幕的起点（秒）：字幕表变了以后仍能找回同一句。 */
  cueTime: number;
  /** 播放头（秒）。 */
  playhead: number;
  /** 视窗起点（秒），等价于时间轴的 scrollLeft。 */
  viewStart: number;
  /** 视窗跨度（秒），等价于缩放级别。 */
  span: number;
  /** 时间选区；没有就是 null。 */
  selection: { start: number; end: number } | null;
  /** 写盘时间（ms），只用于 LRU 与调试。 */
  updatedAt: number;
}

/** 只记最近 50 部影片；超出的按最久未更新淘汰。 */
export const MAX_VIEWPORTS = 50;
/** 波形缓存最多保留多少个视窗；放大/平移产生的组合很多，必须封顶。 */
export const MAX_PEAK_ENTRIES = 48;

const STORAGE_KEY = 'kikusub.reviewViewports';
/** 旧版只记一个全局播放头的键；升级后读一次做迁移，之后不再写。 */
const LEGACY_PLAYHEAD_KEY = 'kikusub.lastPosition';
const STORE_VERSION = 1;

interface ViewportStore {
  version: number;
  entries: Record<string, ReviewViewport>;
}

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null; // 隐私模式 / 沙箱里访问 localStorage 会抛
  }
}

function finite(value: unknown, fallback = 0): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function readStore(): ViewportStore {
  const empty: ViewportStore = { version: STORE_VERSION, entries: {} };
  const store = storage();
  if (!store) return empty;
  try {
    const raw = JSON.parse(store.getItem(STORAGE_KEY) || 'null');
    if (!raw || typeof raw !== 'object' || !raw.entries || typeof raw.entries !== 'object') {
      return empty;
    }
    const entries: Record<string, ReviewViewport> = {};
    for (const [path, value] of Object.entries(raw.entries as Record<string, unknown>)) {
      const normalized = normalizeViewport(value);
      if (path && normalized) entries[path] = normalized;
    }
    return { version: STORE_VERSION, entries };
  } catch {
    // 手改坏 / 旧格式：当作没有，不要让它把核对台卡住
    return empty;
  }
}

function writeStore(store: ViewportStore): void {
  const target = storage();
  if (!target) return;
  try {
    target.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    /* 配额满 / 不可写：只影响下次恢复，不影响当前编辑 */
  }
}

/** 把任意来源（localStorage / IPC）的现场数据洗成合法值；坏数据返回 null。 */
export function normalizeViewport(raw: unknown): ReviewViewport | null {
  if (!raw || typeof raw !== 'object') return null;
  const value = raw as Record<string, unknown>;
  const playhead = Math.max(0, finite(value.playhead));
  const viewStart = Math.max(0, finite(value.viewStart));
  const span = Math.max(0, finite(value.span));
  const cueIndex = Math.trunc(finite(value.cueIndex, -1));
  const cueTime = Math.max(0, finite(value.cueTime));
  let selection: { start: number; end: number } | null = null;
  const rawSelection = value.selection as Record<string, unknown> | null | undefined;
  if (rawSelection && typeof rawSelection === 'object') {
    const a = finite(rawSelection.start, Number.NaN);
    const b = finite(rawSelection.end, Number.NaN);
    if (Number.isFinite(a) && Number.isFinite(b)) {
      const start = Math.max(0, Math.min(a, b));
      const end = Math.max(start, Math.max(a, b));
      if (end - start > 0.001) selection = { start, end };
    }
  }
  // 字段全空 = 从没记录过（或整份坏掉）：当作没有现场
  if (!playhead && !span && !viewStart && cueIndex < 0 && !selection) return null;
  return {
    cueIndex,
    cueTime,
    playhead,
    viewStart,
    span,
    selection,
    updatedAt: Math.max(0, finite(value.updatedAt)),
  };
}

/** 读出某部影片的现场；没有（或损坏）返回 null。 */
export function readViewport(path: string): ReviewViewport | null {
  if (!path) return null;
  const store = readStore();
  return store.entries[path] ?? null;
}

/**
 * 恢复用读取：没有新格式快照时退回旧版「上次播放头」，避免升级后丢现场。
 * 旧格式只有播放头，视窗交给调用方保持当前值（`span` 为 0）。
 */
export function readViewportForRestore(path: string): ReviewViewport | null {
  const snapshot = readViewport(path);
  if (snapshot) return snapshot;
  const legacy = legacyPlayhead(path);
  if (legacy <= 0.2) return null;
  return {
    cueIndex: -1,
    cueTime: 0,
    playhead: legacy,
    viewStart: 0,
    span: 0,
    selection: null,
    updatedAt: 0,
  };
}

/**
 * 把核对台当前状态收成一份可落盘的现场快照（不含 `updatedAt`）。
 *
 * 纯函数：cue 起点从 cues 里取，其余值由调用方给。放在这里是为了让
 * `ReviewView.svelte` 只保留接线，也让「cueIndex 越界时 cueTime 退 0」
 * 的口径与恢复端共用一份。
 */
export function snapshotOf(
  cues: readonly Cue[],
  selected: number,
  playhead: number,
  viewStart: number,
  span: number,
  selection: { start: number; end: number } | null,
): Omit<ReviewViewport, 'updatedAt'> {
  const cue = cues[selected];
  return {
    cueIndex: selected,
    cueTime: cue?.start ?? 0,
    playhead,
    viewStart,
    span,
    selection: selection ? { start: selection.start, end: selection.end } : null,
  };
}

/**
 * 记下现场并写盘。同一份内容重复写会被跳过（核对台每 2 秒调一次）。
 * 返回是否真的写入。
 */
export function rememberViewport(
  path: string,
  snapshot: Omit<ReviewViewport, 'updatedAt'>,
): boolean {
  if (!path) return false;
  const next = normalizeViewport({ ...snapshot, updatedAt: Date.now() });
  if (!next) return false;
  const store = readStore();
  const previous = store.entries[path];
  // 位置没变就跳过：否则播放头静止时每 2 秒都会全量写一次 localStorage
  if (previous && sameSnapshot(previous, next)) return false;
  store.entries[path] = next;
  pruneStore(store);
  writeStore(store);
  return true;
}

/** 丢掉一部影片的现场（文件被删除 / 用户显式重置）。 */
export function forgetViewport(path: string): void {
  if (!path) return;
  const store = readStore();
  if (!store.entries[path]) return;
  delete store.entries[path];
  writeStore(store);
}

function sameSnapshot(a: ReviewViewport, b: ReviewViewport): boolean {
  return (
    Math.abs(a.playhead - b.playhead) < 0.05 &&
    Math.abs(a.viewStart - b.viewStart) < 0.01 &&
    Math.abs(a.span - b.span) < 0.01 &&
    a.cueIndex === b.cueIndex &&
    selectionKey(a.selection) === selectionKey(b.selection)
  );
}

function selectionKey(sel: ReviewViewport['selection']): string {
  return sel ? `${sel.start.toFixed(2)}:${sel.end.toFixed(2)}` : '';
}

function pruneStore(store: ViewportStore): void {
  const paths = Object.keys(store.entries);
  if (paths.length <= MAX_VIEWPORTS) return;
  paths
    .sort((a, b) => store.entries[a].updatedAt - store.entries[b].updatedAt)
    .slice(0, paths.length - MAX_VIEWPORTS)
    .forEach((path) => delete store.entries[path]);
}

/** 旧版「上次播放头」：升级到现场快照时读一次，不覆盖已有快照。 */
export function legacyPlayhead(path: string): number {
  const store = storage();
  if (!store || !path) return 0;
  try {
    const raw = JSON.parse(store.getItem(LEGACY_PLAYHEAD_KEY) || 'null');
    if (raw && raw.path === path && Number.isFinite(Number(raw.time))) {
      return Math.max(0, Number(raw.time));
    }
  } catch {
    /* 忽略损坏的记录 */
  }
  return 0;
}

// ---------------------------------------------------------------------------
// 显式跳转优先
// ---------------------------------------------------------------------------

/**
 * 最近一次显式跳转的目标媒体路径；空串表示没有待消费的显式跳转。
 *
 * 不用布尔值：从别的页面点时间码跳过来之后，用户可能在核对台里再切一次片，
 * 那次切换不该被上一次的显式跳转影响。
 */
let pendingExplicitPath = '';

/** 外部入口发起跳转时调用（必须早于核对台恢复）。 */
export function markExplicitJump(path = ''): void {
  pendingExplicitPath = path;
}

/** 恢复前消费显式跳转：命中返回 true，调用方应跳过历史恢复。 */
export function takeExplicitJump(path: string): boolean {
  if (!pendingExplicitPath) return false;
  const hit = !path || pendingExplicitPath === path;
  if (hit) pendingExplicitPath = '';
  return hit;
}

/** 仅供测试 / 换会话时清空。 */
export function resetExplicitJump(): void {
  pendingExplicitPath = '';
}

// ---------------------------------------------------------------------------
// 恢复计划（纯函数）
// ---------------------------------------------------------------------------

export interface RestorePlan {
  cueIndex: number;
  /** 恢复后是否要 seek；播放头本来就在 0 附近就不打扰用户。 */
  seekTo: number | null;
  viewStart: number;
  span: number;
  selection: { start: number; end: number } | null;
}

/**
 * 把一份历史现场洗成「可以照着恢复」的计划。
 *
 * - 视窗按 `duration` 夹紧（与 `timelineView.clampTimelineView` 同口径）；
 * - 选区夹进 `[0, duration]`，非法（倒序/零长）一律丢弃；
 * - 播放头夹进片长，落在开头 0.2 秒内视为没有恢复过；
 * - `span <= 0`（旧版只存过播放头）时返回 `span: 0`，调用方保持当前视窗。
 *
 * 返回 null 表示「没有可恢复的东西」，调用方不要动任何状态。
 */
export function planViewportRestore(
  raw: ReviewViewport | null,
  duration: number,
  minSpan: number,
  opts: { explicit?: boolean } = {},
): RestorePlan | null {
  if (opts.explicit) return null; // 显式跳转优先：历史现场这次不参与
  const snapshot = raw ? normalizeViewport(raw) : null;
  if (!snapshot) return null;

  const d = Math.max(0, finite(duration));
  const playhead = d > 0 ? Math.min(snapshot.playhead, d) : snapshot.playhead;
  let selection: { start: number; end: number } | null = null;
  if (snapshot.selection) {
    const start = Math.max(0, d > 0 ? Math.min(snapshot.selection.start, d) : snapshot.selection.start);
    const end = Math.max(0, d > 0 ? Math.min(snapshot.selection.end, d) : snapshot.selection.end);
    if (end - start > 0.001) selection = { start, end };
  }

  let viewStart = 0;
  let clampedSpan = 0;
  if (snapshot.span > 0 && d > 0) {
    clampedSpan = Math.max(minSpan, Math.min(snapshot.span, d));
    viewStart = Math.max(0, Math.min(snapshot.viewStart, d - clampedSpan));
  }

  return {
    cueIndex: snapshot.cueIndex,
    seekTo: playhead > 0.2 ? playhead : null,
    viewStart,
    span: clampedSpan,
    selection,
  };
}

/**
 * 恢复「当前选中哪一条」。
 *
 * 字幕表可能已经被重新转写 / 导入替换过，下标不再对应同一句，所以先看下标是否
 * 还指向同一时间（±0.5s），对不上就按 `cueTime` 找最近的一条；都没有就保持原样。
 */
export function resolveCueIndex(
  cues: { start: number; end: number }[],
  snapshot: { cueIndex: number; cueTime: number } | null,
): number | null {
  if (!cues.length || !snapshot) return null;
  const exact = snapshot.cueIndex;
  if (exact >= 0 && exact < cues.length) {
    const cue = cues[exact];
    if (Math.abs(cue.start - snapshot.cueTime) <= 0.5) return exact;
  }
  let best = -1;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (let i = 0; i < cues.length; i += 1) {
    const distance = Math.abs(cues[i].start - snapshot.cueTime);
    if (distance < bestDistance) {
      best = i;
      bestDistance = distance;
    }
  }
  return best >= 0 ? best : null;
}

// ---------------------------------------------------------------------------
// 波形包络缓存（仅内存）
// ---------------------------------------------------------------------------

const peakCache = new Map<string, number[]>();

/**
 * 波形缓存键：媒体 + 视窗 + 采样点数。
 *
 * 采样点数进键是必须的：视窗宽度变了（窗口缩放 / 波形高度拖动）以后，
 * 分辨率不同的包络直接复用会画成锯齿。
 */
export function peakCacheKey(
  mediaId: string,
  from: number,
  span: number,
  bins: number,
): string {
  return [
    mediaId,
    Math.max(0, from).toFixed(3),
    Math.max(0, span).toFixed(3),
    Math.max(1, Math.round(bins)),
  ].join('|');
}

/** 取缓存（LRU：命中即移到队尾）；没有返回 null。 */
export function cachedPeaks(key: string): number[] | null {
  const hit = peakCache.get(key);
  if (!hit) return null;
  peakCache.delete(key);
  peakCache.set(key, hit);
  return hit;
}

/** 写入缓存并淘汰最久未用的条目。空包络也缓存：静音段不该反复请求。 */
export function storePeaks(key: string, peaks: readonly number[]): void {
  if (!key) return;
  peakCache.delete(key);
  peakCache.set(key, Array.from(peaks));
  while (peakCache.size > MAX_PEAK_ENTRIES) {
    const oldest = peakCache.keys().next().value;
    if (oldest === undefined) break;
    peakCache.delete(oldest);
  }
}

/** 丢掉某个媒体的全部包络（文件被替换 / 代理重建后旧数据不可信）。 */
export function forgetPeaks(mediaId: string): void {
  const prefix = `${mediaId}|`;
  for (const key of [...peakCache.keys()]) {
    if (key.startsWith(prefix)) peakCache.delete(key);
  }
}

/** 仅供测试：清空内存缓存。 */
export function clearPeakCache(): void {
  peakCache.clear();
}

/** 仅供测试：清空 localStorage 里的全部现场。 */
export function clearViewportStore(): void {
  const store = storage();
  if (!store) return;
  try {
    store.removeItem(STORAGE_KEY);
  } catch {
    /* 忽略 */
  }
}
