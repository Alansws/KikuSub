/**
 * 应用状态与动作。
 *
 * 放在 `.svelte.ts` 里用 runes，组件只负责渲染 —— 这样「握手 → 载入 → 转写 → 报告」
 * 这条链路只有一份实现，不会散落在各个组件里。
 */

import {
  api,
  logEvent,
  setEndpoint,
  type AiProposal,
  type AppSettings,
  type Cue,
  type EngineInfo,
  type JobSnapshot,
  type MediaInfo,
  type ParamSpec,
  type ReportData,
  type SettingsPayload,
  type TrackMode,
  type TranslationTrack,
} from './api';

export type View = 'import' | 'transcribe' | 'review' | 'ai' | 'report' | 'settings';

export interface AppConfig {
  version: string;
  device: string;
  models_dir: string;
  output_dir: string;
  export_dir: string;
  settings_path?: string;
  formats: string[];
  engines: EngineInfo[];
  settings?: AppSettings;
  legacy_ui: boolean;
}

export const app = $state({
  // 连接
  connected: false,
  connecting: true,
  sidecarPid: 0,

  // 界面
  view: 'import' as View,
  theme: 'light' as 'light' | 'dark',
  inspectorOpen: true,
  /** 当前识别引擎；工具栏切换时同步，核对台局部重转与质检补录都读它。 */
  engine: 'whisper',
  /** 质检「补录」正在等哪一条：局部转写完成后自动把它标为 filled。 */
  qaFillId: '' as string,

  // 数据
  config: null as AppConfig | null,
  settings: null as AppSettings | null,
  media: null as MediaInfo | null,
  cues: [] as Cue[],
  canUndo: false,
  canRedo: false,
  /** 核对台显示哪条轨：原文 / 译文 / 双语（双语 = 每行两行文字） */
  track: ((typeof localStorage !== 'undefined' && localStorage.getItem('kikusub.track')) ||
    'source') as TrackMode,
  trackLang: ((typeof localStorage !== 'undefined' && localStorage.getItem('kikusub.trackLang')) ||
    'zh-Hans') as string,
  /** lang -> 译文轨（含 stale 下标） */
  translations: {} as Record<string, TranslationTrack>,
  report: null as ReportData | null,
  /** 最近一次转写自动落盘的字幕路径；转写页/详情页据此提供「打开导出文件夹」。 */
  lastSavedPath: '' as string,
  /** 最近一次从核对台导出的交付文件；侧栏与详情页共用。 */
  lastExportPath: '' as string,

  // 任务
  job: null as JobSnapshot | null,
  jobKind: '' as '' | 'transcribe' | 'proxy',
  /** 本次转写的意图：整片还是某个区间，决定完成后的落点与提示。 */
  jobMeta: null as null | {
    scope: 'full' | 'range';
    apply: 'replace' | 'append' | 'replace_range';
    start: number;
    end: number;
    label: string;
  },

  /** 从核对台「填入转写」带过去的区间；nonce 变一次，转写页就填一次。 */
  slice: null as null | { start: string; end: string; nonce: number },

  // 提示
  toast: '',
  toastKind: 'info' as 'info' | 'warn' | 'error',
  busy: false,
});

/** 播放状态。核对屏与检查器共享：播放头位置、是否在播、当前选中行。 */
export const play = $state({
  time: 0,
  playing: false,
  selected: 0,
  duration: 0,
  /** 每次「请求跳到某处」自增，核对屏据此真正设置 video.currentTime。 */
  seekNonce: 0,
  /** 请求把波形视窗聚焦到某个区间（质检定位 / 选区聚焦）。 */
  focus: null as { start: number; end: number; nonce: number } | null,
  /** 只播一段（选中句 / 组合区），到 end 自动停。 */
  stopAt: 0,
  /** 跳转后是否立即播放（试听）。由核对屏消费后复位。 */
  playAfterSeek: false,
});

/** 跳到某个时间点。所有「定位」入口都走这里，视频与播放头才不会各走各的。 */
export function seekTo(time: number, opts: { stopAt?: number; play?: boolean } = {}) {
  play.time = Math.max(0, time);
  play.stopAt = opts.stopAt ?? 0;
  play.playAfterSeek = Boolean(opts.play);
  play.seekNonce += 1;
}

/** 聚焦并框选一个时间区间（不自动播放）。 */
export function focusRange(start: number, end: number) {
  const s = Math.max(0, Math.min(start, end));
  const e = Math.max(s + 0.05, Math.max(start, end));
  play.focus = { start: s, end: e, nonce: (play.focus?.nonce ?? 0) + 1 };
  seekTo(s);
}

/** 试听某一句：从 start 播到 end。 */
export function previewRange(start: number, end: number) {
  seekTo(start + 0.02, { stopAt: end, play: true });
}

/** 调参状态：schema 来自 /api/params，values 按引擎分开存并落 localStorage。 */
export const tuning = $state({
  schema: null as { key: string; groups: { group: string; params: ParamSpec[] }[]; defaults: Record<string, number | boolean> }[] | null,
  values: {} as Record<string, Record<string, number | boolean>>,
  presets: [] as { name: string; engine: string | null }[],
  activePreset: '',
  loading: false,
});

/** 设置页 / 引擎配置。 */
export const settings = $state({
  data: null as SettingsPayload | null,
  loading: false,
  error: '',
  download: null as null | {
    key: string;
    label: string;
    percent: number;
    stage: string;
    status: 'running' | 'done' | 'error';
  },
});

/** 质检队列（浮标面板用）。 */
export const qa = $state({
  open: false,
  payload: null as Record<string, any> | null,
  loading: false,
});

/**
 * 核对工作草稿（临时全量保存）。
 *
 * 与「导出」是两件事：草稿写在运行数据目录的 `{stem}.autosave_draft.srt`，
 * 只在核对期间防丢；导出写的是设置里的交付目录。编辑后会自动暂存，按钮只是
 * 让用户不等待防抖、立刻把当前全量写盘并得到确认。
 */
export const reviewDraft = $state({
  exists: false,
  path: '',
  count: 0,
  saved_at: 0,
  saving: false,
  restoring: false,
});

let toastTimer: number | undefined;

// 核对草稿的防抖/串行写入状态（saveDraft / scheduleDraftSave 共用）
let draftTimer: number | undefined;
let draftInFlight: Promise<void> | null = null;
let draftAgain = false;
// 读取草稿状态的请求序号：避免较早发出的 GET 在保存完成之后才回来，把新状态盖掉
let draftInfoSeq = 0;

/** 旧内核的提示语带 ✅⚠️🔎 这类 emoji；桌面端视觉规范是零 emoji。 */
const EMOJI_RE = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/gu;

function plain(message: string): string {
  return String(message ?? '')
    .replace(EMOJI_RE, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

export function toast(message: string, kind: 'info' | 'warn' | 'error' = 'info') {
  app.toast = plain(message);
  app.toastKind = kind;
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    app.toast = '';
  }, kind === 'error' ? 6000 : 3200);
}

// ---------------------------------------------------------------------------
// 启动
// ---------------------------------------------------------------------------

export async function boot(port: number, token: string) {
  setEndpoint(port, token);
  app.connecting = true;
  try {
    app.config = await api.config();
    app.settings = app.config.settings ?? null;
    app.connected = true;
    logEvent('info', 'app-boot', `version=${app.config.version} device=${app.config.device}`, {
      engines: app.config.engines.map((e) => `${e.key}:${e.enabled ? 'on' : 'off'}:${e.installed ? 'ready' : 'missing'}`),
      settings: app.config.settings,
    });
    await loadTuning();
    // 设备探测在 sidecar 的后台预热线程里；先让界面出来，再补一次配置
    scheduleDeviceRefresh();
    // 恢复上次外观（main.ts 在挂载前已同步应用过一次，这里只补齐状态）
    const saved = localStorage.getItem('kikusub.theme');
    if (saved === 'dark' || saved === 'light') setTheme(saved);
    else setTheme(app.theme);
    // 双击文件/拖到 Dock 启动时，open-file 可能早于内核就绪；这里补做导入。
    const pending = pendingMediaPath;
    pendingMediaPath = '';
    if (pending) await openMedia(pending);
  } catch (err) {
    app.connected = false;
    toast(`连接内核失败：${(err as Error).message}`, 'error');
  } finally {
    app.connecting = false;
  }
}

let deviceTimer: number | undefined;
let deviceTries = 0;

function scheduleDeviceRefresh() {
  clearTimeout(deviceTimer);
  deviceTries = 0;
  const tick = async () => {
    deviceTries += 1;
    if (!app.connected) return;
    if (app.config?.device === 'unknown' && deviceTries <= 6) {
      await refreshConfig().catch(() => {});
      deviceTimer = window.setTimeout(tick, 1500);
    }
  };
  deviceTimer = window.setTimeout(tick, 1500);
}

/** 重新拉取 /api/config：设备名、引擎启用状态、最近设置都以服务端为准。 */
export async function refreshConfig() {
  try {
    app.config = await api.config();
    app.settings = app.config.settings ?? app.settings;
  } catch (err) {
    logEvent('warn', 'config-refresh', String(err));
  }
}

export function markSidecarDown() {
  const wasConnected = app.connected;
  app.connected = false;
  // 已连上过 → 显示“正在重启”，等下一次 ready；从未连上 → 直接显示“内核未连接”，
  // 避免启动就失败时一直转圈。
  app.connecting = wasConnected;
  // sidecar 的 SessionStore 是进程内的：内核一重启，媒体绑定、字幕表与撤回栈
  // 就全没了。继续显示旧界面只会让后续操作对着空会话报错，所以这里同步清空。
  const hadSession = Boolean(app.media || app.cues.length);
  app.media = null;
  app.cues = [];
  app.canUndo = false;
  app.canRedo = false;
  app.report = null;
  app.lastSavedPath = '';
  app.lastExportPath = '';
  app.job = null;
  app.jobMeta = null;
  app.jobKind = '';
  app.qaFillId = '';
  play.time = 0;
  play.playing = false;
  play.selected = 0;
  play.stopAt = 0;
  play.focus = null;
  qa.payload = null;
  qa.open = false;
  reviewDraft.exists = false;
  reviewDraft.path = '';
  reviewDraft.count = 0;
  reviewDraft.saved_at = 0;
  reviewDraft.saving = false;
  reviewDraft.restoring = false;
  clearTimeout(draftTimer);
  draftAgain = false;
  // 只有原本在工作区里才跳回导入；改模型目录时用户通常停在设置页，不要把他弹走。
  if (hadSession) setView('import');
  // 内核重启后设置页必须重新拉一次：模型目录/设备/引擎状态都可能变了。
  settings.data = null;
  settings.loading = true;
  toast(
    hadSession
      ? '内核已断开，当前会话已重置；重启后请重新导入媒体'
      : '内核已断开，正在自动重启…',
    'warn',
  );
}

export function setTheme(theme: 'light' | 'dark') {
  app.theme = theme;
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('kikusub.theme', theme);
  // 原生 vibrancy / 红绿灯区域跟随应用主题，否则深色模式下侧栏会透成浅色。
  window.kikusub?.setTheme?.(theme);
}

export function toggleTheme() {
  setTheme(app.theme === 'dark' ? 'light' : 'dark');
}

export function setView(view: View) {
  app.view = view;
  // 检查器只属于「核对」屏（已确认的设计决定）
  app.inspectorOpen = view === 'review';
}

// ---------------------------------------------------------------------------
// 媒体
// ---------------------------------------------------------------------------

/**
 * 开发用：把主进程注入的「媒体 + 字幕」灌进当前会话。
 *
 * 必须在渲染进程里做——会话是 cookie 认的，主进程发的请求是另一个会话。
 * 打包后 `getDevSeed()` 恒为 null，这段不会执行。
 */
export async function applyDevSeed(seed: { mediaPath: string; cues?: Cue[] }) {
  if (!seed?.mediaPath) return;
  try {
    // 走真实的 openMedia 路径（含代理压制任务），这样截图/联调覆盖的是产品代码本身
    await openMedia(seed.mediaPath);
    if (seed.cues?.length) {
      await api.replaceCues(seed.cues);
      await refreshCues();
    }
    setView('review');
  } catch (err) {
    toast(`种子注入失败：${(err as Error).message}`, 'error');
  }
}

const SUBTITLE_EXTS = ['.srt', '.vtt'];

/** 内核未就绪时双击/拖入的媒体：握手完成后自动补导入，不丢用户的操作。 */
let pendingMediaPath = '';

export async function openMedia(path: string) {
  if (!app.connected) {
    pendingMediaPath = path;
    toast('正在启动内核，完成后会自动导入这个文件…');
    return;
  }
  // 换片前取消上一部片还没落地的草稿写入，避免把旧字幕写到新媒体的草稿名下
  clearTimeout(draftTimer);
  draftAgain = false;
  // 提案是按片生成的：换了片就不能让上一部片的 diff 继续留在界面上
  resetAi();
  const lower = path.toLowerCase();
  if (SUBTITLE_EXTS.some((ext) => lower.endsWith(ext))) {
    await openSubtitle(path);
    return;
  }
  app.busy = true;
  try {
    const info = await api.importMedia(path);
    app.media = info;
    await api.bindSession(info.id);
    app.view = 'review';
    app.inspectorOpen = true;
    app.report = null;
    app.lastSavedPath = '';
    app.lastExportPath = '';
    app.job = null;
    app.jobMeta = null;
    app.qaFillId = '';
    await refreshCues();
    await refreshQa();
    await refreshDraftInfo();
    // 换片后播放头必须归零，否则会带着上一部的进度落地
    play.time = 0;
    play.selected = 0;
    play.focus = null;

    // 历史结果直接接上：有字幕就进核对，没有就停在转写
    if (!app.cues.length) {
      app.view = 'transcribe';
      app.inspectorOpen = false;
    }

    logEvent('info', 'media-import', `${info.name} | ${info.duration.toFixed(2)}s | ${info.video_codec}/${info.audio_codec}`, {
      path: info.path,
      id: info.id,
      needs_proxy: info.needs_proxy,
      proxy_ready: info.proxy_ready,
      size: info.size,
    });

    // MKV / HEVC 在 Chromium 里放不出来：后台压代理，不挡用户操作
    if (info.needs_proxy && (app.settings?.auto_proxy ?? true)) {
      startProxyJob(info.id);
    }
  } catch (err) {
    toast(`导入失败：${(err as Error).message}`, 'error');
  } finally {
    app.busy = false;
  }
}

/** 导入字幕：只换核对基线，不动当前媒体与画面。 */
export async function openSubtitle(path: string) {
  // 导入是“换基线”，不是一次编辑：取消还在排队的自动暂存，避免立刻覆盖旧草稿，
  // 让用户仍有机会从「恢复上次暂存」取回导入前的内容。
  clearTimeout(draftTimer);
  draftAgain = false;
  app.busy = true;
  try {
    logEvent('info', 'subtitle-import', path);
    const res = await api.importCues(path);
    app.cues = res.cues;
    app.canUndo = res.can_undo;
    app.canRedo = res.can_redo;
    setView('review');
    app.inspectorOpen = true;
    play.selected = 0;
    play.time = 0;
    play.focus = null;
    // 只读草稿状态，方便用户发现上一次的暂存；不要自动覆盖它。
    await refreshDraftInfo();
    toast(`已导入字幕 ${res.count} 条（可按 ⌘Z 撤回）`);
  } catch (err) {
    toast(`导入字幕失败：${(err as Error).message}`, 'error');
  } finally {
    app.busy = false;
  }
}

async function startProxyJob(mediaId: string) {
  try {
    const job = await api.createProxyJob(mediaId);
    toast('正在后台压制 480p 监看代理…');
    watchJob(job, 'proxy');
  } catch {
    // 已有任务在跑时 409，属正常：代理不是关键路径
  }
}

// ---------------------------------------------------------------------------
// 字幕
// ---------------------------------------------------------------------------

export async function refreshMedia() {
  if (!app.media) return;
  try {
    app.media = await api.getMedia(app.media.id);
  } catch {
    /* 媒体被移走时忽略 */
  }
}

export async function refreshCues() {
  try {
    const data = await api.getCues();
    app.cues = data.cues;
    app.canUndo = data.can_undo;
    app.canRedo = data.can_redo;
  } catch {
    /* 会话未绑定媒体时忽略 */
  }
}

export async function undo() {
  try {
    const data = await api.undo();
    app.cues = data.cues;
    app.canUndo = data.can_undo;
    app.canRedo = data.can_redo;
    scheduleDraftSave();
    toast('已撤回');
  } catch (err) {
    toast((err as Error).message, 'warn');
  }
}

export async function redo() {
  try {
    const data = await api.redo();
    app.cues = data.cues;
    app.canUndo = data.can_undo;
    app.canRedo = data.can_redo;
    scheduleDraftSave();
    toast('已重做');
  } catch (err) {
    toast((err as Error).message, 'warn');
  }
}

export async function updateCue(index: number, patch: Partial<Cue>) {
  try {
    const data = await api.patchCue(index, patch);
    app.cues = data.cues;
    app.canUndo = data.can_undo;
    app.canRedo = data.can_redo;
    scheduleDraftSave();
  } catch (err) {
    toast((err as Error).message, 'error');
    await refreshCues();
  }
}

export async function deleteCue(index: number) {
  try {
    const data = await api.deleteCue(index);
    app.cues = data.cues;
    app.canUndo = data.can_undo;
    app.canRedo = data.can_redo;
    scheduleDraftSave();
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

/**
 * 一次提交多条时间戳修改。
 *
 * 双语字幕的日/中两行共享同一个 (start, end)，在波形上拖动字幕块时它们必须
 * 一起移动；如果逐条 PATCH，撤回栈会被拆成好几步，用户按一次 ⌘Z 只回退一行。
 * 这里走整表替换（服务端只压一次历史），索引与文本都不变。
 */
export async function applyCueTimes(changes: { index: number; start: number; end: number }[]) {
  if (!changes.length) return;
  try {
    const next = app.cues.map((c) => ({ start: c.start, end: c.end, text: c.text }));
    for (const ch of changes) {
      const target = next[ch.index];
      if (target) {
        target.start = ch.start;
        target.end = ch.end;
      }
    }
    const data = await api.replaceCues(next);
    app.cues = data.cues;
    app.canUndo = data.can_undo;
    app.canRedo = data.can_redo;
    scheduleDraftSave();
  } catch (err) {
    toast((err as Error).message, 'error');
    await refreshCues();
  }
}

// ---------------------------------------------------------------------------
// 核对草稿（临时全量保存）与导出
// ---------------------------------------------------------------------------

function applyDraftInfo(info: {
  exists: boolean;
  path: string;
  count: number;
  saved_at: number;
}) {
  reviewDraft.exists = info.exists;
  reviewDraft.path = info.path;
  reviewDraft.count = info.count;
  reviewDraft.saved_at = info.saved_at;
}

/** 读取当前媒体的草稿状态（是否存在、多少条、最后写入时间）。 */
export async function refreshDraftInfo() {
  if (!app.connected) return;
  const seq = ++draftInfoSeq;
  try {
    const info = await api.getDraft();
    if (seq === draftInfoSeq) applyDraftInfo(info);
  } catch {
    // 草稿状态是辅助信息：媒体尚未绑定或服务端版本较旧时静默失败
  }
}

/**
 * 编辑成功后延迟暂存。
 *
 * 旧 Gradio 核对台每次改表格都会写 `*.autosave_draft.srt`；桌面版也保持同样的
 * 兜底节奏，但用 0.9 秒防抖，避免拖一次字幕块就发一串请求。
 */
export function scheduleDraftSave(delay = 900) {
  if (!app.connected || !app.cues.length) return;
  clearTimeout(draftTimer);
  draftTimer = window.setTimeout(() => {
    void saveDraft({ silent: true });
  }, delay);
}

/**
 * 立即把核对台的**全部**字幕写进工作草稿。
 *
 * `silent` 用于自动暂存：失败不弹 toast，避免打断正在进行的核对；手动点击时
 * 必须给出明确反馈。草稿路径由服务端按媒体主干名决定，绝不覆盖导出交付文件。
 */
export async function saveDraft(opts: { silent?: boolean } = {}) {
  if (!app.connected) {
    if (!opts.silent) toast('内核还没连接，暂时无法暂存', 'warn');
    return;
  }
  if (!app.cues.length) {
    if (!opts.silent) toast('当前没有可暂存的字幕', 'warn');
    return;
  }
  clearTimeout(draftTimer);
  if (draftInFlight) {
    // 上一次写入还在路上：标记一下，等它落地后再补一次最新快照
    draftAgain = true;
    return;
  }
  reviewDraft.saving = true;
  draftInFlight = (async () => {
    try {
      const info = await api.saveDraft();
      draftInfoSeq += 1;
      applyDraftInfo(info);
      if (!opts.silent) {
        toast(`已暂存 ${info.count} 条到工作草稿（不覆盖导出文件）`);
      }
    } catch (err) {
      if (!opts.silent) toast(`暂存失败：${(err as Error).message}`, 'error');
    } finally {
      reviewDraft.saving = false;
      draftInFlight = null;
    }
  })();
  await draftInFlight;
  if (draftAgain) {
    draftAgain = false;
    scheduleDraftSave(0);
  }
}

/** 用工作草稿覆盖核对台；服务端会压一次撤回栈，⌘Z 一步退回。 */
export async function restoreDraft() {
  if (!reviewDraft.exists || reviewDraft.restoring) return;
  reviewDraft.restoring = true;
  try {
    const res = await api.restoreDraft();
    app.cues = res.cues;
    app.canUndo = res.can_undo;
    app.canRedo = res.can_redo;
    setView('review');
    app.inspectorOpen = true;
    if (play.selected >= app.cues.length) {
      play.selected = Math.max(0, app.cues.length - 1);
    }
    play.focus = null;
    await refreshDraftInfo();
    toast(`已恢复暂存草稿：${res.count} 条（⌘Z 可撤回）`);
  } catch (err) {
    toast(`恢复暂存失败：${(err as Error).message}`, 'error');
  } finally {
    reviewDraft.restoring = false;
  }
}

/**
 * 把核对台当前时间轴导出成交付文件（写进设置里的导出文件夹）。
 *
 * 侧栏与「详情与导出」共用这一个入口：即使没有任务报告（例如重开应用后手动
 * 导入了字幕），也能从核对台直接交付，不再被“没有任务”卡住。
 */
export async function exportCues(
  format: 'SRT' | 'VTT' | 'TXT' = 'SRT',
  opts: { track?: TrackMode; lang?: string } = {},
) {
  if (!app.cues.length) {
    toast('当前没有可导出的字幕', 'warn');
    return null;
  }
  try {
    const res = await api.exportCues(format, opts);
    app.lastExportPath = res.path;
    logEvent('info', 'export', `${format} | ${res.count} 条`, { path: res.path });
    const label = res.track === 'both' ? '双语' : res.track === 'target' ? '译文' : '原文';
    const skipped = res.skipped ? `，跳过 ${res.skipped} 条空译文` : '';
    toast(`已导出${label} ${format}：${res.path.split('/').pop()}（${res.count} 条${skipped}）`);
    return res;
  } catch (err) {
    toast((err as Error).message, 'error');
    return null;
  }
}

// ---------------------------------------------------------------------------
// 转写
// ---------------------------------------------------------------------------

export interface TranscribeOptions {
  engine: string;
  outputFormat: string;
  startText: string;
  endText: string;
  absoluteTimeline: boolean;
  /** 结果如何进入核对台。整片默认覆盖，区间默认追加。 */
  apply?: 'replace' | 'append' | 'replace_range';
}

function optimisticJob(stage: string): JobSnapshot {
  return {
    id: '',
    kind: 'transcribe',
    status: 'queued',
    ratio: 0,
    percent: 0,
    stage,
    error: '',
    created_at: Date.now() / 1000,
    started_at: 0,
    finished_at: 0,
    elapsed: 0,
    result: null,
  };
}

function engineEnabled(key: string): boolean {
  const fromSettings = app.settings?.enabled_engines;
  if (Array.isArray(fromSettings)) return fromSettings.includes(key);
  return app.config?.engines.some((e) => e.key === key && e.enabled) ?? true;
}

export async function startTranscribe(
  opts: TranscribeOptions,
  parseTime: (s: string) => number | null,
) {
  if (!app.media) {
    toast('请先导入媒体', 'warn');
    return;
  }
  if (!engineEnabled(opts.engine)) {
    toast('这个引擎已停用：到「设置 → 引擎与模型」里重新启用', 'warn');
    return;
  }
  const start = parseTime(opts.startText);
  const end = parseTime(opts.endText);
  if (start !== null && end !== null && end <= start) {
    toast('结束时间必须大于起始时间', 'warn');
    return;
  }
  // 「全片」按钮会把 0 与完整时长填进两个输入框；那仍然算整片覆盖，
  // 不能因为「填了时间」就误判成区间追加。
  const duration = app.media.duration || 0;
  const coversFull =
    (start === null || start <= 0.001) && (end === null || end >= duration - 0.5);
  const isRange = !coversFull;
  const apply = opts.apply ?? (isRange ? 'append' : 'replace');

  // 乐观态：请求本身可能因为服务端首次预热而慢一拍，
  // 但用户必须在 300ms 内看到反馈（规划 §5 指标 6）
  app.jobKind = 'transcribe';
  app.jobMeta = {
    scope: isRange ? 'range' : 'full',
    apply,
    start: start ?? 0,
    end: end ?? app.media.duration,
    label: isRange ? `${start ?? 0}s – ${end ?? '片尾'}` : '整片',
  };
  app.job = optimisticJob('正在启动内核…');
  logEvent('info', 'transcribe-start', `${opts.engine} | ${isRange ? 'range' : 'full'} | ${apply}`, {
    start,
    end,
    output_format: opts.outputFormat,
    absolute_timeline: opts.absoluteTimeline,
    params: { ...(tuning.values[opts.engine] ?? {}) },
  });

  try {
    const job = await api.createTranscribeJob({
      media_id: app.media.id,
      engine: opts.engine,
      output_format: opts.outputFormat,
      start,
      end,
      keep_absolute_timeline: opts.absoluteTimeline,
      apply,
      // 参数键就是 core.params 的规格键，服务端负责补默认 / 夹区间
      params: tuning.values[opts.engine] ?? {},
    });
    watchJob(job, 'transcribe');
  } catch (err) {
    app.job = null;
    app.jobMeta = null;
    toast((err as Error).message, 'error');
  }
}

/**
 * 局部转写：核对台的「重转此句 / 转写选区」都走这里。
 *
 * 与整片转写共用同一个任务队列（单槽），但完成后**只替换该区间内的字幕**，
 * 自动定位回起点，并把质检队列刷新到最新——不会把用户已经核对过的整张表冲掉。
 */
export async function transcribeRange(args: {
  start: number;
  end: number;
  engine: string;
  label?: string;
  padStart?: number;
  padEnd?: number;
  /** 区间不得越过这个绝对时间（质检补录用 gap 边界兜底，避免切进下一句）。 */
  clampStart?: number;
  clampEnd?: number;
  apply?: 'replace_range' | 'append';
}) {
  if (!app.media) {
    toast('请先导入媒体', 'warn');
    return;
  }
  const duration = app.media.duration || 0;
  const startFloor = Math.max(0, Number(args.clampStart ?? 0));
  const endCeil = args.clampEnd != null ? Number(args.clampEnd) : (duration || args.end);
  const start = Math.max(startFloor, args.start - (args.padStart ?? 0.12));
  const end = Math.min(endCeil, args.end + (args.padEnd ?? 0.25));
  if (end - start < 0.2) {
    toast('选区太短，至少需要 0.2 秒', 'warn');
    return;
  }

  if (!engineEnabled(args.engine)) {
    toast('这个引擎已停用：到「设置 → 引擎与模型」里重新启用', 'warn');
    return;
  }
  const apply = args.apply ?? 'replace_range';
  app.jobKind = 'transcribe';
  app.jobMeta = {
    scope: 'range',
    apply,
    start,
    end,
    label: args.label ?? `${start.toFixed(2)}s – ${end.toFixed(2)}s`,
  };
  app.job = optimisticJob('正在识别选区…');
  logEvent('info', 'transcribe-range', `${args.engine} | ${start.toFixed(2)}-${end.toFixed(2)} | ${apply}`, {
    label: args.label,
    params: { ...(tuning.values[args.engine] ?? {}) },
  });

  try {
    const job = await api.createTranscribeJob({
      media_id: app.media.id,
      engine: args.engine,
      start,
      end,
      keep_absolute_timeline: true,
      apply,
      params: tuning.values[args.engine] ?? {},
    });
    watchJob(job, 'transcribe');
  } catch (err) {
    app.job = null;
    app.jobMeta = null;
    toast((err as Error).message, 'error');
  }
}

export async function cancelJob() {
  // 乐观态还没有 job id（请求在途），此时没有可取消的东西
  if (!app.job?.id) return;
  try {
    await api.cancelJob(app.job.id);
    toast('已发送打断指令', 'warn');
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

function watchJob(initial: JobSnapshot, kind: 'transcribe' | 'proxy') {
  app.job = initial;
  app.jobKind = kind;

  api.streamJob(
    initial.id,
    async (ev) => {
      if (ev.job) app.job = ev.job;
      if (ev.type === 'progress' && kind === 'transcribe' && app.job) {
        app.job = {
          ...app.job,
          percent: ev.job_percent ?? Math.round((ev.ratio ?? 0) * 100),
          stage: ev.stage || app.job.stage,
        };
      }
      if (ev.type === 'done') {
        await onJobDone(ev.job!, kind);
      }
      if (ev.type === 'error') {
        // 质检补录失败不能把该条算成已处理
        app.qaFillId = '';
        toast(`处理失败：${ev.message || ''}`, 'error');
        logEvent('error', 'job-failed', `${kind} ${ev.job?.id ?? ''}`, ev.message);
      }
      if (ev.type === 'cancelled') {
        app.qaFillId = '';
        toast('任务已取消', 'warn');
        logEvent('warn', 'job-cancelled', `${kind} ${ev.job?.id ?? ''}`);
      }
      if (ev.type === 'done') {
        logEvent('info', 'job-done', `${kind} ${ev.job?.id ?? ''}`, {
          cue_count: ev.job?.result?.cue_count,
          applied: ev.job?.result?.applied,
          elapsed: ev.job?.elapsed,
        });
      }
    },
    () => {
      /* 连接关闭：终态已在 done/error 里处理过 */
    },
  );
}

async function onJobDone(job: JobSnapshot, kind: 'transcribe' | 'proxy') {
  if (kind === 'proxy') {
    // 刷新 media.proxy_ready —— 核对屏的 <video src> 由它派生，
    // 一变就会自动切到代理流，用户不用手动重开
    await refreshMedia();
    toast('480p 监看代理已就绪，画面已切换');
    return;
  }

  const meta = app.jobMeta;
  app.lastSavedPath = String(job.result?.out_path ?? '') || app.lastSavedPath;
  await refreshCues();
  await refreshQa();
  // 整片/区间转写都会改写核对表：写一份最新草稿，防丢
  scheduleDraftSave(0);

  if (meta?.scope === 'range') {
    // 局部转写：停在核对屏原处，把播放头放回选区起点，让用户立刻试听结果
    const added = Number(job.result?.added ?? 0);
    const removed = Number(job.result?.removed ?? 0);
    const total = app.cues.length;
    seekTo(Math.max(0, meta.start), { play: false });
    focusRange(meta.start, meta.end);
    // 转写页的区间任务也是一次正式转写：报告要切到这次结果，才能与质检
    // 队列对得上。只有核对台的单句/选区修正才保留旧报告。
    if (meta.apply !== 'replace_range') {
      try {
        app.report = await api.getReport(job.id);
      } catch {
        /* 报告不是关键路径 */
      }
    }
    const fillId = app.qaFillId;
    if (fillId) {
      // 质检「补录」：转写成功后才允许把该条标成已处理（失败不得算完成）
      app.qaFillId = '';
      await qaAction({ id: fillId, action: 'mark', status: 'done', resolution: 'filled' });
    }
    const saved = app.lastSavedPath ? '，已自动保存到导出文件夹' : '';
    if (added && removed) {
      toast(`局部转写完成：替换 ${removed} 条、新增 ${added} 条，时间轴共 ${total} 条${saved}`);
    } else if (removed) {
      toast(`局部转写完成：更新该区间 ${removed} 条，时间轴共 ${total} 条${saved}`);
    } else if (added) {
      toast(`局部转写完成：新增 ${added} 条，时间轴共 ${total} 条${saved}`);
    } else {
      toast(`局部转写完成：该区间已有相同字幕，时间轴共 ${total} 条${saved}`);
    }
    return;
  }

  try {
    app.report = await api.getReport(job.id);
  } catch {
    app.report = null;
  }
  const cues = app.cues.length;
  toast(`转写完成：${cues} 条字幕${app.lastSavedPath ? '，已自动保存到导出文件夹' : ''}`);
  if (cues > 0) {
    setView('review');
  }
}

// ---------------------------------------------------------------------------
// 报告
// ---------------------------------------------------------------------------

export async function loadReport(opts: { silent?: boolean } = {}) {
  try {
    app.report = await api.getReport();
  } catch (err) {
    // 没有任务报告是正常空态（例如重开应用后手动导入字幕）：
    // 自动进入详情页时不要弹「还没有完成过转写任务」，页面会给出可导出的空态说明。
    if (!opts.silent) toast((err as Error).message, 'warn');
  }
}


// ---------------------------------------------------------------------------
// 调参与预设
// ---------------------------------------------------------------------------

const TUNING_KEY = 'kikusub.tuning';

export async function loadTuning() {
  tuning.loading = true;
  try {
    const schema = await api.getParams();
    tuning.schema = schema.engines;

    let saved: Record<string, Record<string, number | boolean>> = {};
    try {
      saved = JSON.parse(localStorage.getItem(TUNING_KEY) || '{}');
    } catch {
      saved = {};
    }
    // 以默认值打底，再叠用户上次的调整；规格表里已删掉的键自然被丢掉
    const values: Record<string, Record<string, number | boolean>> = {};
    for (const engine of schema.engines) {
      values[engine.key] = { ...engine.defaults, ...(saved[engine.key] || {}) };
    }
    tuning.values = values;
    await refreshPresets();
  } catch (err) {
    toast(`加载参数失败：${(err as Error).message}`, 'error');
  } finally {
    tuning.loading = false;
  }
}

export function setParam(engine: string, key: string, value: number | boolean) {
  if (!tuning.values[engine]) tuning.values[engine] = {};
  tuning.values[engine][key] = value;
  tuning.activePreset = ''; // 手改之后就不再算「某个预设」了
  persistTuning();
}

export function resetParams(engine: string) {
  const entry = tuning.schema?.find((e) => e.key === engine);
  if (!entry) return;
  tuning.values[engine] = { ...entry.defaults };
  tuning.activePreset = '';
  persistTuning();
}

function persistTuning() {
  try {
    localStorage.setItem(TUNING_KEY, JSON.stringify(tuning.values));
  } catch {
    /* 隐私模式下写不了，忽略 */
  }
}

export async function refreshPresets() {
  try {
    const data = await api.listPresets();
    tuning.presets = data.items;
    if (data.load_error) toast(`预设文件读取异常：${data.load_error}`, 'warn');
  } catch {
    tuning.presets = [];
  }
}

export async function applyPreset(name: string) {
  if (!name) return;
  try {
    const preset = await api.getPreset(name);
    const engine = preset.engine || 'whisper';
    tuning.values[engine] = {
      ...(tuning.values[engine] || {}),
      ...preset.values,
    };
    tuning.activePreset = name;
    persistTuning();
    toast(`已载入预设「${name}」`);
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

export async function savePresetAs(name: string, engine: string) {
  const trimmed = name.trim();
  if (!trimmed) {
    toast('请先填写预设名称', 'warn');
    return;
  }
  try {
    const values = tuning.values[engine] || {};
    await api.savePreset(trimmed, engine, values);
    tuning.activePreset = trimmed;
    await refreshPresets();
    toast(`已保存预设「${trimmed}」`);
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

export async function deletePreset(name: string) {
  if (!name) return;
  try {
    await api.deletePreset(name);
    if (tuning.activePreset === name) tuning.activePreset = '';
    await refreshPresets();
    toast(`已删除预设「${name}」`);
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

// ---------------------------------------------------------------------------
// 质检队列
// ---------------------------------------------------------------------------

export async function refreshQa() {
  qa.loading = true;
  try {
    qa.payload = await api.getQa();
  } catch {
    qa.payload = null;
  } finally {
    qa.loading = false;
  }
}

export async function toggleQaPanel(open?: boolean) {
  qa.open = open ?? !qa.open;
  if (qa.open) await refreshQa();
}

export async function qaAction(cmd: {
  id: string;
  action: string;
  status?: string;
  resolution?: string;
}) {
  try {
    logEvent('info', 'qa-action', `${cmd.action} | ${cmd.status ?? ''} | ${cmd.resolution ?? ''}`, { id: cmd.id });
    const res = await api.qaAction(cmd);
    if (res.warning) toast(res.warning, 'warn');
    else if (res.message) toast(res.message);
    if (res.cues_changed) {
      app.cues = res.cues;
      app.canUndo = res.can_undo;
      app.canRedo = res.can_redo;
      scheduleDraftSave();
    }
    if (res.focus) {
      play.selected = Math.max(0, res.focus.index - 1);
      setView('review');
      toast(`已定位到第 ${res.focus.index} 条`);
    }
    await refreshQa();
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}


// ---------------------------------------------------------------------------
// 译文平行轨
// ---------------------------------------------------------------------------

export async function loadTranslations() {
  try {
    const data = await api.getTranslations();
    const map: Record<string, TranslationTrack> = {};
    for (const item of data.items) map[item.lang] = item;
    app.translations = map;
    // 当前语种没有轨时退回原文，避免界面停在"译文"却没有内容
    if (app.track !== 'source' && !map[app.trackLang]) app.track = 'source';
    return data;
  } catch {
    app.translations = {};
    return null;
  }
}

export function setTrackMode(mode: TrackMode) {
  app.track = mode;
  try {
    localStorage.setItem('kikusub.track', mode);
  } catch {
    /* 隐私模式下写不进去，忽略 */
  }
}

export function setTrackLang(lang: string) {
  app.trackLang = lang;
  try {
    localStorage.setItem('kikusub.trackLang', lang);
  } catch {
    /* 同上 */
  }
  if (!app.translations[lang]) setTrackMode('source');
}

/** 当前显示语种下、第 i 条的译文（原文模式下返回空串）。 */
export function translationAt(index: number): string {
  if (app.track === 'source') return '';
  return app.translations[app.trackLang]?.texts[index] ?? '';
}

/**
 * 这一条的译文是否已经过期。
 *
 * 本地按 `base`（生成译文时的原文快照）实时比较，而不是读服务端返回的 `stale`：
 * 用户改一句原文后界面要立刻变黄，不该等下一次请求。服务端那份仍保留给 API 消费者。
 */
export function isTranslationStale(index: number): boolean {
  const track = app.translations[app.trackLang];
  if (!track) return false;
  const base = track.base ?? [];
  if (index >= base.length) return true;
  return base[index] !== (app.cues[index]?.text ?? '');
}

export function staleTranslationCount(): number {
  if (app.track === 'source' || !app.translations[app.trackLang]) return 0;
  let count = 0;
  for (let i = 0; i < app.cues.length; i += 1) if (isTranslationStale(i)) count += 1;
  return count;
}

export async function undoTranslation(lang = app.trackLang) {
  try {
    const res = await api.undoTranslation(lang);
    await loadTranslations();
    toast(res.undone ? '已退回上一版译文' : '这个语种没有更早的译文了', res.undone ? 'info' : 'warn');
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

export async function deleteTranslation(lang = app.trackLang) {
  try {
    await api.deleteTranslation(lang);
    await loadTranslations();
    toast(`已删除 ${lang} 译文`);
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

// ---------------------------------------------------------------------------
// AI 提案（M1：读取 / 另存 / 应用，不调模型）
// ---------------------------------------------------------------------------

/**
 * 当前这轮提案的上下文。
 *
 * `accept` / `edits` 用普通对象而不是 Set/Map：Svelte 5 的 runes 只追踪对象属性
 * 读写，`Set.add()` 不会触发重渲染，界面会出现"勾了没反应"。
 */
export const ai = $state({
  kind: 'polish' as 'polish' | 'translate',
  lang: 'zh-Hans',
  path: '',
  proposal: null as AiProposal | null,
  warnings: [] as string[],
  errors: [] as string[],
  digestMatch: true,
  /** i -> 是否采纳；默认全采纳 */
  accept: {} as Record<number, boolean>,
  /** i -> 人手工改过的文本（优先于提案原文） */
  edits: {} as Record<number, string>,
  changedOnly: true,
  loading: false,
  applying: false,
  saving: false,
  /** 手动粘贴通道：把网页版模型的回复解析成提案 */
  pasteOpen: false,
  pasteText: '',
  parsing: false,
  /** 正在生成提案（后台任务） */
  generating: false,
  progress: 0,
  stage: '',
  jobId: '',
  /** 已经为哪一份上下文拉过提案，避免 $effect 反复请求 */
  loadedFor: '',
});

function aiContextKey(): string {
  return `${app.media?.id ?? ''}:${ai.kind}:${ai.lang}`;
}

export function resetAi() {
  ai.proposal = null;
  ai.path = '';
  ai.warnings = [];
  ai.errors = [];
  ai.accept = {};
  ai.edits = {};
  ai.digestMatch = true;
  ai.loadedFor = '';
}

export async function loadAiProposal(force = false) {
  if (!app.connected || ai.loading) return;
  const key = aiContextKey();
  if (!force && ai.loadedFor === key) return;
  ai.loading = true;
  try {
    const res = await api.getAiProposal(ai.kind, ai.kind === 'translate' ? ai.lang : '');
    ai.proposal = res.proposal;
    ai.path = res.path;
    ai.warnings = res.warnings ?? [];
    ai.errors = res.errors ?? [];
    ai.digestMatch = res.digest_match;
    ai.accept = {};
    ai.edits = {};
    for (const item of res.proposal.items) ai.accept[item.i] = true;
  } catch (err) {
    // "还没有提案"不是错误状态：界面给的是生成/导入的引导
    resetAi();
    ai.errors = [(err as Error).message];
  } finally {
    ai.loadedFor = key;
    ai.loading = false;
  }
}

export function setAiKind(kind: 'polish' | 'translate') {
  if (ai.kind === kind) return;
  ai.kind = kind;
  ai.loadedFor = '';
  void loadAiProposal();
}

export function toggleAiAccept(i: number) {
  ai.accept[i] = ai.accept[i] === false;
}

export function setAllAiAccept(value: boolean) {
  if (!ai.proposal) return;
  for (const item of ai.proposal.items) ai.accept[item.i] = value;
}

export function setAiEdit(i: number, text: string) {
  const item = ai.proposal?.items.find((it) => it.i === i);
  if (!item) return;
  if (text === item.after) delete ai.edits[i];
  else ai.edits[i] = text;
}

/** 某一行最终会写进字幕的文本（人工编辑优先于提案）。 */
export function aiFinalText(i: number, fallback: string): string {
  const edited = ai.edits[i];
  return edited !== undefined ? edited : (ai.proposal?.items.find((it) => it.i === i)?.after ?? fallback);
}

export async function applyAiProposal() {
  if (!ai.proposal || ai.applying) return;
  if (ai.proposal.kind === 'translate') return applyAiTranslation();
  ai.applying = true;
  try {
    const accept = ai.proposal.items.filter((it) => ai.accept[it.i] !== false).map((it) => it.i);
    const edits: Record<number, string> = {};
    for (const [k, v] of Object.entries(ai.edits)) edits[Number(k)] = v;

    const res = await api.applyAiProposal({ kind: ai.kind, lang: ai.lang, accept, edits });
    app.cues = res.cues;
    app.canUndo = res.can_undo;
    app.canRedo = res.can_redo;

    if (res.changed) {
      scheduleDraftSave();
      // 质检清单是按旧文本算的，这里不自动重算（开发文档 §9 R7）
      toast(`已应用 ${res.changed} 处修改（⌘Z 可整批撤回）；质检清单基于旧文本，如需复核请重新跑质检`);
    } else {
      toast('没有需要应用的修改', 'warn');
    }
    await refreshCues();
  } catch (err) {
    toast((err as Error).message, 'error');
  } finally {
    ai.applying = false;
  }
}

/**
 * 「一键复制提示词」：把当前字幕整成 SRT 塞进翻译模板，复制到剪贴板。
 *
 * 这条路是给没有 API Key、或想用网页版模型的用户：复制 → 粘到任意聊天窗 →
 * 把回复粘回来 → 解析成提案 → 同一套 diff。
 */
export async function copyAiPrompt() {
  if (!app.cues.length) {
    toast('当前没有可翻译的字幕', 'warn');
    return;
  }
  try {
    const res = await api.getAiPrompt('translate', ai.lang);
    if (window.kikusub?.writeClipboard) {
      await window.kikusub.writeClipboard(res.prompt);
    } else if (navigator.clipboard) {
      await navigator.clipboard.writeText(res.prompt);
    }
    toast(`提示词已复制：${res.count} 条字幕，${(res.chars / 1000).toFixed(1)}k 字符`);
    ai.pasteOpen = true;
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

/**
 * 解析粘贴回来的 SRT。
 *
 * 服务端只取**文本**（按顺序），序号与时间戳一律丢弃、改用我们自己的时间码；
 * 条数对不上会整批拒绝——这比生成半份错位译文安全得多。
 */
export async function parseAiPastedSrt() {
  const text = ai.pasteText.trim();
  if (!text) {
    toast('先把模型返回的 SRT 粘进来', 'warn');
    return;
  }
  ai.parsing = true;
  try {
    const res = await api.aiFromSrt({ kind: 'translate', lang: ai.lang, text });
    ai.proposal = res.proposal;
    ai.path = '';
    ai.errors = [];
    ai.warnings = res.warnings ?? [];
    ai.accept = {};
    ai.edits = {};
    for (const item of res.proposal.items) ai.accept[item.i] = true;
    ai.pasteOpen = false;
    ai.pasteText = '';
    // 标记成"已加载"，避免 $effect 又去拉磁盘上的旧提案把它顶掉
    ai.loadedFor = aiContextKey();
    toast(`已解析 ${res.count} 条译文，右侧就是待应用的建议`);
  } catch (err) {
    toast((err as Error).message, 'error');
  } finally {
    ai.parsing = false;
  }
}

/**
 * 应用译文：写进平行轨，**不动 review_cues**（D-3）。
 *
 * 应用后自动切到「双语」，让用户立刻看到原文 + 译文叠在一起。
 */
export async function applyAiTranslation() {
  if (!ai.proposal || ai.applying) return;
  const track = ai.proposal.kind === 'translate' ? ai.proposal : null;
  if (!track) {
    toast('这不是一份翻译提案', 'warn');
    return;
  }
  const lang = (track.dst_lang || ai.lang || '').trim();
  if (!lang) {
    toast('提案里没有目标语种', 'error');
    return;
  }
  ai.applying = true;
  try {
    const items = ai.proposal.items.map((it) => ({ ...it, after: ai.edits[it.i] ?? it.after }));
    const res = await api.applyTranslation({ lang, proposal: { ...ai.proposal, items } });
    await loadTranslations();
    setTrackLang(lang);
    setTrackMode('both');
    scheduleDraftSave();
    toast(`已应用 ${res.count} 条译文，核对台已切到双语`);
  } catch (err) {
    toast((err as Error).message, 'error');
  } finally {
    ai.applying = false;
  }
}

/** 另存当前（含人工编辑的）提案，供 agent 复用或留档。 */
export async function saveAiProposalAs() {
  if (!ai.proposal || ai.saving) return;
  ai.saving = true;
  try {
    const items = ai.proposal.items.map((it) => ({
      ...it,
      after: ai.edits[it.i] ?? it.after,
    }));
    const res = await api.saveAiProposal({ ...ai.proposal, items }, ai.kind, ai.lang);
    ai.path = res.path;
    toast(`已保存提案：${res.path.split('/').pop()}`);
  } catch (err) {
    toast((err as Error).message, 'error');
  } finally {
    ai.saving = false;
  }
}

/**
 * 「丢弃」= 真删文件 + 清界面。
 *
 * 注意末尾那行 `loadedFor`：`resetAi()` 会把它清空，而 AiView 的 `$effect` 依赖它，
 * 于是会立刻再去磁盘读一遍——刚删掉的提案就"复活"了。标记成本上下文已查过即可。
 */
export async function discardAiProposal() {
  try {
    await api.deleteAiProposal(ai.kind, ai.kind === 'translate' ? ai.lang : '');
  } catch {
    /* 文件删不掉也要让界面回到空态 */
  }
  resetAi();
  ai.loadedFor = aiContextKey();
  toast('已丢弃提案');
}

/** 改某一条译文（三种显示模式下右侧检查器都用它）。 */
export async function updateTranslation(index: number, text: string) {
  const lang = app.trackLang;
  if (!lang) return;
  try {
    await api.patchTranslation(lang, index, text);
    await loadTranslations();
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

let aiStream: (() => void) | null = null;

function onAiJobEvent(ev: any) {
  if (ev?.job) {
    ai.progress = Math.max(ai.progress, Number(ev.job.percent ?? 0));
    if (ev.job.stage) ai.stage = ev.job.stage;
  }
  if (ev?.type === 'done') {
    ai.generating = false;
    ai.jobId = '';
    ai.progress = 100;
    aiStream?.();
    aiStream = null;
    void loadAiProposal(true);
  } else if (ev?.type === 'error') {
    ai.generating = false;
    ai.jobId = '';
    aiStream?.();
    aiStream = null;
    toast(ev.message || '生成提案失败', 'error');
  } else if (ev?.type === 'cancelled') {
    ai.generating = false;
    ai.jobId = '';
    aiStream?.();
    aiStream = null;
    toast('已取消生成', 'warn');
  }
}

/**
 * 生成一份润色提案。
 *
 * 密钥在**发起这一刻**从主进程取，随请求头走一次；服务层不保存、日志也不会记。
 * 进度/取消复用转写那套 `/ws/jobs`，不另起一套轮询。
 */
export async function startAiPolish() {
  return startAiGeneration('polish');
}

export async function startAiTranslate() {
  return startAiGeneration('translate');
}

async function startAiGeneration(kind: 'polish' | 'translate') {
  if (!app.connected || ai.generating) return;
  if (!app.cues.length) {
    toast(kind === 'translate' ? '当前没有可翻译的字幕' : '当前没有可润色的字幕', 'warn');
    return;
  }
  if (kind === 'translate' && !ai.lang) {
    toast('先选目标语种', 'warn');
    return;
  }
  let cfg;
  try {
    cfg = await api.getAiConfig();
  } catch (err) {
    toast((err as Error).message, 'error');
    return;
  }
  if (!cfg.enabled) {
    toast('AI 优化未启用：设置 → AI 优化（实验功能）里打开', 'warn');
    return;
  }
  const key = await window.kikusub?.aiKey?.get?.();
  if (!key) {
    toast('还没有配置 API Key：设置 → AI 优化（实验功能）', 'warn');
    return;
  }

  ai.generating = true;
  ai.progress = 0;
  ai.stage = '正在提交…';
  try {
    const job = await api.createAiJob(
      {
        kind,
        base_url: cfg.base_url,
        model: cfg.model,
        chunk_cues: kind === 'translate' ? cfg.translate_chunk_cues : cfg.chunk_cues,
        context_cues: cfg.context_cues,
        lang: 'ja',
        dst_lang: kind === 'translate' ? ai.lang : '',
      },
      key,
    );
    ai.jobId = job.id;
    aiStream = api.streamJob(job.id, onAiJobEvent, () => {});
  } catch (err) {
    ai.generating = false;
    ai.jobId = '';
    toast((err as Error).message, 'error');
  }
}

export async function cancelAiPolish() {
  if (!ai.jobId) return;
  try {
    await api.cancelJob(ai.jobId);
    ai.stage = '正在取消…';
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

/** 用原生对话框导入一份外部提案（agent 写的、或别处存下来的）。 */
export async function importAiProposal() {
  const dir = app.config?.export_dir || app.config?.output_dir || '';
  const picked = await window.kikusub?.pickProposal?.(dir);
  if (!picked) return;
  try {
    await api.importAiProposal(picked, ai.kind, ai.lang);
    ai.loadedFor = '';
    await loadAiProposal(true);
    toast(`已导入提案：${picked.split('/').pop()}`);
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

// ---------------------------------------------------------------------------
// 设置 / 引擎配置
// ---------------------------------------------------------------------------

export async function loadSettings(force = false) {
  if (settings.data && !force) return settings.data;
  settings.loading = true;
  settings.error = '';
  try {
    settings.data = await api.getSettings();
    app.settings = settings.data.settings;
    return settings.data;
  } catch (err) {
    settings.error = (err as Error).message;
    logEvent('error', 'settings-load', settings.error);
    return null;
  } finally {
    settings.loading = false;
  }
}

export async function updateSettings(patch: {
  enabled_engines?: string[];
  auto_proxy?: boolean;
  export_dir?: string;
}) {
  try {
    const data = await api.patchSettings(patch);
    settings.data = data;
    app.settings = data.settings;
    await refreshConfig();
    logEvent('info', 'settings-update', JSON.stringify(patch));
    toast('设置已保存');
    return data;
  } catch (err) {
    toast((err as Error).message, 'error');
    logEvent('error', 'settings-update', String(err), patch);
    return null;
  }
}

export async function toggleEngine(key: string, enabled: boolean) {
  const current = settings.data?.engines.find((e) => e.key === key);
  const keys = new Set(settings.data?.settings.enabled_engines ?? []);
  if (enabled) keys.add(key);
  else keys.delete(key);
  // 保持注册表顺序
  const ordered = (settings.data?.engines ?? []).map((e) => e.key).filter((k) => keys.has(k));
  const data = await updateSettings({ enabled_engines: ordered });
  if (data && current) {
    toast(enabled ? `已启用 ${current.label}` : `已停用 ${current.label}`);
  }
}

export async function downloadEngine(key: string) {
  if (settings.download?.status === 'running') {
    toast('已有模型正在下载，请等它完成', 'warn');
    return;
  }
  const info = settings.data?.engines.find((e) => e.key === key);
  settings.download = {
    key,
    label: info?.label ?? key,
    percent: 0,
    stage: '准备下载…',
    status: 'running',
  };
  logEvent('info', 'engine-download-start', key);
  try {
    const job = await api.downloadEngine(key);
    api.streamJob(job.id, (ev) => {
      if (!settings.download || settings.download.key !== key) return;
      if (ev.job) {
        settings.download.percent = Math.max(settings.download.percent, ev.job.percent ?? 0);
        if (ev.job.stage) settings.download.stage = ev.job.stage;
      }
      if (ev.type === 'progress') {
        settings.download.percent = Math.max(
          settings.download.percent,
          ev.percent ?? ev.job_percent ?? 0,
        );
        if (ev.stage) settings.download.stage = ev.stage;
      }
      if (ev.type === 'done') {
        settings.download = { ...settings.download, percent: 100, stage: '下载完成', status: 'done' };
        toast(`${settings.download.label} 模型已就绪`);
        logEvent('info', 'engine-download-done', key);
        void loadSettings(true);
        void refreshConfig();
      }
      if (ev.type === 'error') {
        settings.download = {
          ...settings.download,
          stage: ev.message || '下载失败',
          status: 'error',
        };
        toast(`模型下载失败：${ev.message || ''}`, 'error');
        logEvent('error', 'engine-download-failed', key, ev.message);
      }
    });
  } catch (err) {
    settings.download = {
      key,
      label: info?.label ?? key,
      percent: 0,
      stage: (err as Error).message,
      status: 'error',
    };
    toast((err as Error).message, 'error');
    logEvent('error', 'engine-download-start', key, String(err));
  }
}

/** 设置页把启用的引擎数量同步给工具栏（工具栏只列 enabled 的）。 */
export const enabledEngines = (): EngineInfo[] =>
  (app.config?.engines ?? []).filter((e) => e.enabled);
