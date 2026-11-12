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
  type CueHistoryItem,
  type CueSnapshot,
  type EngineInfo,
  type ExportJobPayload,
  type ExportPlan,
  type ExportResult,
  type ExportStyleOptions,
  type JobSnapshot,
  type MediaInfo,
  type ParamSpec,
  type PromptLibrary,
  type PromptTemplate,
  type ReportData,
  type ReviewSource,
  type SettingsPayload,
  type SubtitleStylePayload,
  type TrackMode,
  type TranslationTrack,
  type TtsDownloadStatus,
  type TtsEngineInfo,
  type TtsVoiceInfo,
  ttsAudioUrl,
} from './api';
import { isThemeId, schemeOf, skinOf, type Scheme, type SkinId, type ThemeId } from './themes';

export type View = 'import' | 'transcribe' | 'review' | 'ai' | 'prompts' | 'export' | 'report' | 'settings';

export interface AppConfig {
  version: string;
  device: string;
  models_dir: string;
  output_dir: string;
  export_dir: string;
  video_export_dir?: string;
  settings_path?: string;
  formats: string[];
  engines: EngineInfo[];
  settings?: AppSettings;
}

export const app = $state({
  // 连接
  connected: false,
  connecting: true,
  sidecarPid: 0,
  /** 主进程已开始退出：此后的内核断开是收尾，不是崩溃重启。 */
  quitting: false,

  // 界面
  view: 'import' as View,
  /** 外观 id（不是 scss 类名）：'light' / 'dark' 属于青空，'mincho' 是明朝墨。 */
  theme: 'light' as ThemeId,
  inspectorOpen: true,
  /** 右侧检查器当前页签：当前条目 / 质检待核。 */
  inspectorTab: 'cue' as 'cue' | 'qa',
  /** 紧凑模式（≤900px CSS 视口）：检查器是抽屉，切页/换片时默认收起。 */
  compact: false,
  /** 当前识别引擎；工具栏切换时同步，核对台局部重转与质检补录都读它。 */
  engine: 'whisper',
  /** 质检「补录」正在等哪一条：局部转写完成后自动把它标为 filled。 */
  qaFillId: '' as string,

  // 数据
  config: null as AppConfig | null,
  settings: null as AppSettings | null,
  media: null as MediaInfo | null,
  cues: [] as Cue[],
  /** 每次服务端字幕快照落地都自增：检查器据此刷新编辑框（撤销后不会停在旧文本）。 */
  cuesRevision: 0,
  /** 译文轨每次重新加载都自增：检查器据此刷新译文编辑框。 */
  translationsRevision: 0,
  /**
   * 当前核对表的来源。`import` / `draft` 时右侧检查器不能再用最近一次转写的
   * 质检与参数——那份报告对应的是另一版字幕。
   */
  reviewSource: null as ReviewSource | null,
  canUndo: false,
  canRedo: false,
  /** 下一步 ⌘Z / ⇧⌘Z 会做什么（服务端历史标签，用于按钮提示）。 */
  undoLabel: '',
  redoLabel: '',
  /** 服务端「下一步撤销/重做」那一步的记录时间（显示用）。 */
  undoAt: 0,
  redoAt: 0,
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
  jobKind: '' as '' | 'transcribe' | 'proxy' | 'export',
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
  /**
   * 「强制把某条字幕滚进视窗」的序号。转写选区完成后新句可能就在原下标上，
   * 只改 selected 会被 lastRevealed 的去重挡掉，必须靠这个非零变化强制同步。
   */
  selectNonce: 0,
  /** 请求右侧检查器把光标放进「当前条目」文本框（右键新建空字幕用）。 */
  editNonce: 0,
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

function applyHistoryMeta(data: CueSnapshot) {
  app.canUndo = data.can_undo;
  app.canRedo = data.can_redo;
  if (data.undo_label !== undefined) app.undoLabel = data.undo_label;
  if (data.redo_label !== undefined) app.redoLabel = data.redo_label;
  if (data.undo_at !== undefined) app.undoAt = data.undo_at;
  if (data.redo_at !== undefined) app.redoAt = data.redo_at;
  if (cueHistory.open) void loadCueHistory();
}

/** 把服务端返回的字幕快照统一写回状态（含撤销/重做按钮的说明）。 */
function applyCueSnapshot(data: CueSnapshot, opts: { applyClientState?: boolean } = {}) {
  app.cues = data.cues;
  app.cuesRevision += 1;
  app.canUndo = data.can_undo;
  app.canRedo = data.can_redo;
  // 来源与字幕一起回滚：导入字幕 / 撤销 / 历史跳转都会带新的来源。
  if (data.review_source !== undefined) app.reviewSource = data.review_source;
  // 不是每个接口都返回标签（例如旧版 QA 响应）：缺省时保留上一次的值，
  // 不要用空串把工具栏提示抹掉。
  if (data.undo_label !== undefined) app.undoLabel = data.undo_label;
  if (data.redo_label !== undefined) app.redoLabel = data.redo_label;
  if (data.undo_at !== undefined) app.undoAt = data.undo_at;
  if (data.redo_at !== undefined) app.redoAt = data.redo_at;
  // 只有撤销 / 重做 / 历史跳转的回包带本地状态；普通编辑不能用稍旧的快照
  // 覆盖用户刚在导出面板 / AI 优化台改好的值。
  if (opts.applyClientState) {
    if (data.export_ui) applyServerExportUi(data.export_ui);
    if (data.ai_draft) applyAiDraft(data.ai_draft);
  }
  if (cueHistory.open) void loadCueHistory();
}

/**
 * 定位到某一条字幕，并强制表格滚过去。
 *
 * 只设 `play.selected` 不够：`lastRevealed` 会认为「还是这一句」而跳过滚动，
 * 局部转写完成后正是这种情况（新句落在同一个下标上）。
 */
export function jumpToCue(index: number, opts: { seek?: boolean } = {}) {
  const cue = app.cues[index];
  if (!cue) return;
  play.selected = index;
  if (opts.seek !== false) seekTo(cue.start + 0.02);
  play.selectNonce += 1;
}

/** 20 步可回溯历史列表（工具栏下拉用）。 */
export const cueHistory = $state({
  open: false,
  items: [] as CueHistoryItem[],
  cursor: -1,
  loading: false,
  error: '',
});

export async function loadCueHistory() {
  if (!app.connected) return;
  cueHistory.loading = true;
  cueHistory.error = '';
  try {
    const data = await api.getCueHistory();
    cueHistory.items = data.items;
    cueHistory.cursor = data.cursor;
    app.canUndo = data.can_undo;
    app.canRedo = data.can_redo;
    app.undoLabel = data.undo_label;
    app.redoLabel = data.redo_label;
    app.undoAt = data.undo_at;
    app.redoAt = data.redo_at;
  } catch (err) {
    cueHistory.error = (err as Error).message;
  } finally {
    cueHistory.loading = false;
  }
}

export async function toggleCueHistory(open?: boolean) {
  const next = open ?? !cueHistory.open;
  cueHistory.open = next;
  if (next) await loadCueHistory();
}

/** 点历史里的任意一步，直接回到那个状态。 */
export async function jumpCueHistory(index: number) {
  exportCoalesce = null;
  try {
    const data = await api.jumpCueHistory(index);
    applyCueSnapshot(data, { applyClientState: true });
    await loadTranslations();
    // 历史里可能从「导入字幕」跳回「转写结果」：质检队列的可用性跟着来源变。
    await refreshQa();
    scheduleDraftSave();
    if (play.selected >= app.cues.length) {
      play.selected = Math.max(0, app.cues.length - 1);
    }
    // 时间线里条数可能变了：强制表格滚到当前选中行，别让它停在旧位置
    play.selectNonce += 1;
    toast(`已回到：${data.label}`);
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

/**
 * 查找与替换的界面状态。匹配计算放在 ReviewView（它要按原文渲染高亮），
 * 批量替换放这里（一次整表提交，只压一步历史）。
 */
export const findState = $state({
  open: false,
  query: '',
  replacement: '',
  caseSensitive: false,
  /** 当前匹配在 matches 数组里的位置 */
  pos: 0,
  /** 每按一次 ⌘F 自增：已经打开时也能把焦点拉回查找框 */
  focusNonce: 0,
});

export function openFind() {
  if (app.view !== 'review') setView('review');
  findState.open = true;
  findState.focusNonce += 1;
}

export function closeFind() {
  findState.open = false;
  findState.pos = 0;
}

function escapeRegExp(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * 只替换某一条里的**当前**匹配。
 *
 * `at` 是 ReviewView 算出来的匹配起点；没有它时退回替换该条的第一处。
 * 一条字幕里出现两次同样的词时，按位置替换才不会总是改第一处。
 */
export async function replaceInCue(
  index: number,
  query: string,
  replacement: string,
  caseSensitive: boolean,
  at = -1,
): Promise<boolean> {
  const cue = app.cues[index];
  if (!cue || !query) return false;
  let text: string;
  if (at >= 0 && at + query.length <= cue.text.length) {
    const hitText = cue.text.slice(at, at + query.length);
    if (caseSensitive ? hitText !== query : hitText.toLowerCase() !== query.toLowerCase()) {
      return false;
    }
    text = cue.text.slice(0, at) + replacement + cue.text.slice(at + query.length);
  } else {
    const pattern = new RegExp(escapeRegExp(query), caseSensitive ? '' : 'i');
    if (!pattern.test(cue.text)) return false;
    // 用函数替换：替换文本里的 $& / $1 不能被当成正则替换模式
    text = cue.text.replace(pattern, () => replacement);
  }
  try {
    const data = await api.patchCue(index, { text });
    applyCueSnapshot(data);
    scheduleDraftSave();
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  }
}

/** 把服务端返回的单条 / 整轨译文写回当前语种。 */
function applyTranslationTrack(track: TranslationTrack) {
  app.translations = { ...app.translations, [track.lang]: track };
  app.translationsRevision += 1;
  // 每次写译文都会在服务端压一步统一历史；刷新撤销按钮的标签。
  void loadCueHistory();
}

/** 当前语种下第 i 条译文（不受「原文 / 译文 / 双语」显示模式影响，查找用）。 */
export function translationTextAt(index: number): string {
  return app.translations[app.trackLang]?.texts[index] ?? '';
}

/**
 * 替换某一条译文里的**当前**匹配（核对台「译文 / 双语」下的查找替换）。
 *
 * 与原文替换分开：译文不写进 review_cues，改的是 `translations[lang].texts`；
 * `at` 用于一条译文里出现多次同一词时只替换当前那一处。
 */
export async function replaceInTranslation(
  index: number,
  query: string,
  replacement: string,
  caseSensitive: boolean,
  at = -1,
): Promise<boolean> {
  const lang = app.trackLang;
  const track = app.translations[lang];
  const text = track?.texts[index] ?? '';
  if (!track || !query) return false;
  let nextText: string;
  if (at >= 0 && at + query.length <= text.length) {
    const hitText = text.slice(at, at + query.length);
    if (caseSensitive ? hitText !== query : hitText.toLowerCase() !== query.toLowerCase()) {
      return false;
    }
    nextText = text.slice(0, at) + replacement + text.slice(at + query.length);
  } else {
    const pattern = new RegExp(escapeRegExp(query), caseSensitive ? '' : 'i');
    if (!pattern.test(text)) return false;
    nextText = text.replace(pattern, () => replacement);
  }
  try {
    applyTranslationTrack(await api.patchTranslation(lang, index, nextText));
    scheduleDraftSave();
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  }
}

/**
 * 双语「全部批量替换」：原文与译文一次提交。
 *
 * 拆成两次请求时，双语模式下一次「全部替换」会压两步历史，用户要按两次 ⌘Z
 * 才退干净；这里把两份完整数组交给 `/api/cues/replace-all`，服务端只记一步。
 *
 * `skip` 是查找栏「本轮已跳过」的命中（键为 `cue:track:start`）。给了它以后
 * 只替换未跳过的命中——用户明确标了「这一轮不动它」的字符必须原样保留。
 */
export async function replaceAllInTracks(
  query: string,
  replacement: string,
  caseSensitive: boolean,
  tracks: ('source' | 'target')[],
  skip?: Set<string>,
): Promise<{ source: number; target: number }> {
  const empty = { source: 0, target: 0 };
  if (!query) return empty;
  const pattern = () => new RegExp(escapeRegExp(query), caseSensitive ? 'g' : 'gi');
  /** 正则 replacer 的倒数第二个参数是本次命中的起点（无捕获组时就是第 2 个）。 */
  const matchStart = (args: unknown[]) => Number(args[args.length - 2]);
  let sourceCount = 0;
  let nextCues: Cue[] | undefined;
  if (tracks.includes('source')) {
    nextCues = app.cues.map((cue, index) => {
      const text = cue.text.replace(pattern(), (match, ...args) => {
        if (skip?.has(`${index}:source:${matchStart(args)}`)) return match;
        sourceCount += 1;
        return replacement;
      });
      return { start: cue.start, end: cue.end, text };
    });
    if (!sourceCount) nextCues = undefined;
  }
  let targetCount = 0;
  let nextTexts: string[] | undefined;
  const lang = app.trackLang;
  const track = app.translations[lang];
  if (track && tracks.includes('target')) {
    nextTexts = track.texts.map((text, index) =>
      text.replace(pattern(), (match, ...args) => {
        if (skip?.has(`${index}:target:${matchStart(args)}`)) return match;
        targetCount += 1;
        return replacement;
      }),
    );
    if (!targetCount) nextTexts = undefined;
  }
  if (!sourceCount && !targetCount) return empty;
  const total = sourceCount + targetCount;
  try {
    const data = await api.replaceAll({
      label: `查找替换（${total} 处）`,
      cues: nextCues,
      lang: nextTexts ? lang : '',
      texts: nextTexts,
    });
    applyCueSnapshot(data);
    await loadTranslations();
    void loadCueHistory();
    scheduleDraftSave();
    return { source: sourceCount, target: targetCount };
  } catch (err) {
    toast((err as Error).message, 'error');
    return empty;
  }
}

/**
 * 在时间轴某处插入一条 0.8 秒空字幕，并直接把光标放进右侧文本框。
 * 用于气声 / 模型识别为空 / 只想手打一个「啊」的场景。
 */
export async function insertCueAt(center: number): Promise<number> {
  if (!app.media) {
    toast('请先导入媒体', 'warn');
    return -1;
  }
  const duration = app.media.duration || 0;
  const LENGTH = 0.8;
  let start = Math.max(0, center - LENGTH / 2);
  let end = start + LENGTH;
  if (duration > 0 && end > duration) {
    end = duration;
    start = Math.max(0, end - LENGTH);
  }
  start = Math.round(start * 1000) / 1000;
  end = Math.round(end * 1000) / 1000;
  if (end - start < 0.05) {
    toast('这里太靠近片尾，放不下 0.8 秒字幕', 'warn');
    return -1;
  }
  let index = app.cues.findIndex((cue) => cue.start > start);
  if (index < 0) index = app.cues.length;
  try {
    const data = await api.insertCue(index, { start, end, text: '' });
    applyCueSnapshot(data);
    await loadTranslations();
    scheduleDraftSave();
    // 空字幕一定是日文原文；切回原文模式，并确保右侧检查器可见，
    // 否则 editNonce 找不到 textarea，用户还得自己再点开一次。
    app.inspectorOpen = true;
    setTrackMode('source');
    play.selected = index;
    seekTo(start + 0.02);
    play.selectNonce += 1;
    play.editNonce += 1;
    toast('已插入 0.8 秒空字幕，直接输入文本即可');
    return index;
  } catch (err) {
    toast(`插入字幕失败：${(err as Error).message}`, 'error');
    return -1;
  }
}

// ---------------------------------------------------------------------------
// 本机 TTS：系统 say（零显存兜底）+ OmniVoice 零样本克隆
// ---------------------------------------------------------------------------

const clampSpeed = (value: number) =>
  Number.isFinite(value) ? Math.max(0.5, Math.min(2.0, Math.round(value * 10) / 10)) : 1.0;

/** 旧版本按 say 的 100–260 语速存 ttsRate，这里迁移成倍速。 */
function initialTtsSpeed(): number {
  const saved = Number(localStorage.getItem('kikusub.ttsSpeed') || 0);
  if (saved) return clampSpeed(saved);
  const legacyRate = Number(localStorage.getItem('kikusub.ttsRate') || 0);
  if (legacyRate) return clampSpeed(legacyRate / 175);
  return 1.0;
}

/** 旧版本存的是 say 音色名，迁移成 `system:<name>`。 */
function initialTtsVoiceId(): string {
  const saved = localStorage.getItem('kikusub.ttsVoiceId') || '';
  if (saved) return saved;
  const legacy = localStorage.getItem('kikusub.ttsVoice') || '';
  return legacy ? `system:${legacy}` : '';
}

/** 默认朗读偏好：系统语音（零显存）或克隆音色。 */
function initialTtsDefaultKind(): 'system' | 'clone' {
  return localStorage.getItem('kikusub.ttsDefaultKind') === 'clone' ? 'clone' : 'system';
}

function initialTtsDefaultVoiceId(): string {
  return localStorage.getItem('kikusub.ttsDefaultVoiceId') || '';
}

export const tts = $state({
  loaded: false,
  available: false,
  system: [] as TtsVoiceInfo[],
  custom: [] as TtsVoiceInfo[],
  voiceId: initialTtsVoiceId(),
  speed: initialTtsSpeed(),
  /** 设置页的默认朗读偏好；空字符串表示跟随当前选中的音色。 */
  defaultKind: initialTtsDefaultKind(),
  defaultVoiceId: initialTtsDefaultVoiceId(),
  /** 克隆音色资产目录（outputs/voices），音色库的「在访达中打开」。 */
  voicesDir: '',
  engine: null as TtsEngineInfo | null,
  download: null as TtsDownloadStatus | null,
  loading: false,
  playing: false,
  /** 正在朗读 / 生成的是哪一条字幕 */
  index: -1,
  filename: '',
  error: '',
});

let ttsAudio: HTMLAudioElement | null = null;
/** 防止「点了 A，又点 B」时 A 的慢请求回来把 B 的播放顶掉。 */
let ttsSeq = 0;
let ttsPollTimer: ReturnType<typeof setInterval> | null = null;

function ttsAudioEl(): HTMLAudioElement {
  if (!ttsAudio) {
    ttsAudio = new Audio();
    ttsAudio.preload = 'auto';
    ttsAudio.onended = () => {
      tts.playing = false;
    };
    ttsAudio.onerror = () => {
      tts.playing = false;
      tts.error = '音频播放失败';
    };
  }
  return ttsAudio;
}

export function stopTts() {
  ttsSeq += 1;
  if (ttsAudio) {
    ttsAudio.pause();
    try {
      ttsAudio.currentTime = 0;
    } catch {
      /* 还没 loadedmetadata 时忽略 */
    }
  }
  tts.playing = false;
  tts.loading = false;
}

/** 当前选中的音色（找不到时返回 null，界面据此提示「音色已失效」）。 */
export function ttsVoice(): TtsVoiceInfo | null {
  return (
    tts.custom.find((voice) => voice.id === tts.voiceId) ||
    tts.system.find((voice) => voice.id === tts.voiceId) ||
    null
  );
}

/** 克隆模型是否真的可用（依赖装了 + 权重下了）。 */
export function cloneEngineReady(): boolean {
  return Boolean(tts.engine?.installed && tts.engine?.package_installed);
}

export async function loadTtsVoices() {
  if (!app.connected) return;
  try {
    const data = await api.ttsVoices();
    tts.available = data.available;
    tts.system = data.system;
    tts.custom = data.custom;
    tts.engine = data.engine;
    tts.download = data.engine.download;
    tts.voicesDir = data.voices_dir || '';
    const known = [...data.system, ...data.custom].some((voice) => voice.id === tts.voiceId);
    if (!known) {
      // 默认偏好是克隆音色时，优先用用户保存的默认音色；没有就取最近一个。
      // 克隆音色还不存在就老实退回系统语音，不能让 TTS 变成“没有音色”。
      const preferred =
        tts.defaultKind === 'clone'
          ? data.custom.find((voice) => voice.id === tts.defaultVoiceId)?.id ||
            data.custom[0]?.id ||
            ''
          : '';
      tts.voiceId =
        preferred || data.default || data.system[0]?.id || data.custom[0]?.id || '';
    }
    localStorage.setItem('kikusub.ttsVoiceId', tts.voiceId);
    tts.loaded = true;
  } catch {
    tts.available = false;
    tts.loaded = true;
  }
}

export function setTtsVoiceId(voiceId: string) {
  tts.voiceId = voiceId;
  localStorage.setItem('kikusub.ttsVoiceId', voiceId);
  stopTts();
}

/**
 * 设置页切换默认朗读偏好。
 *
 * 切换后立刻把当前音色也换过去，否则用户会看到「默认设为克隆音色」但
 * TTS 面板仍选着 Kyoko，以为设置没生效。没有克隆音色时保留偏好，
 * 等用户建好音色后下次启动自动生效。
 */
export function setTtsDefaultKind(kind: 'system' | 'clone') {
  tts.defaultKind = kind === 'clone' ? 'clone' : 'system';
  localStorage.setItem('kikusub.ttsDefaultKind', tts.defaultKind);
  if (tts.defaultKind === 'clone') {
    const target =
      tts.custom.find((voice) => voice.id === tts.defaultVoiceId) || tts.custom[0];
    if (target) setTtsVoiceId(target.id);
    else stopTts();
  } else {
    const target = tts.system[0];
    if (target) setTtsVoiceId(target.id);
  }
}

/** 把某个克隆音色设为默认（音色库里的「设为默认」）。 */
export function setTtsDefaultVoiceId(voiceId: string) {
  if (!voiceId) {
    tts.defaultVoiceId = '';
    localStorage.removeItem('kikusub.ttsDefaultVoiceId');
    return;
  }
  const voice = tts.custom.find((item) => item.id === voiceId);
  if (!voice) return;
  tts.defaultKind = 'clone';
  tts.defaultVoiceId = voice.id;
  localStorage.setItem('kikusub.ttsDefaultKind', 'clone');
  localStorage.setItem('kikusub.ttsDefaultVoiceId', voice.id);
  setTtsVoiceId(voice.id);
}

export function setTtsSpeed(speed: number) {
  tts.speed = clampSpeed(speed);
  localStorage.setItem('kikusub.ttsSpeed', String(tts.speed));
  stopTts();
}

/** 朗读某一条字幕。再点一次同一条 = 停止。 */
export async function speakCue(index: number) {
  const cue = app.cues[index];
  if (!cue) return;
  if (tts.playing && tts.index === index) {
    stopTts();
    return;
  }
  await speakText(cue.text, index);
}

/** 音色管理里的「试听」：优先读当前句，没有字幕时用固定样例。 */
export async function previewTtsVoice() {
  if (tts.playing && tts.index === -1) {
    stopTts();
    return;
  }
  const selected = app.cues[play.selected];
  const sample = selected?.text?.trim() || 'こんにちは。これは音色のテストです。';
  await speakText(sample, -1);
}

async function speakText(rawText: string, index: number) {
  const text = (rawText || '').trim();
  if (!text) {
    toast('这句没有文本，先输入日文再朗读', 'warn');
    return;
  }
  const voice = ttsVoice();
  if (!voice) {
    toast('还没有可用音色，请先选择系统音色或新建克隆音色', 'warn');
    return;
  }
  if (voice.kind === 'clone' && !cloneEngineReady()) {
    toast('克隆模型还没就绪：先点「下载克隆模型」，或改用系统语音', 'warn');
    return;
  }
  const audio = ttsAudioEl();
  stopTts();
  const seq = ++ttsSeq;
  tts.loading = true;
  tts.index = index;
  tts.error = '';
  try {
    const result = await api.synthesizeTts({
      text,
      voice_id: voice.id,
      speed: tts.speed,
    });
    if (seq !== ttsSeq) return;
    tts.filename = result.filename;
    audio.src = ttsAudioUrl(result.filename);
    await audio.play();
    if (seq !== ttsSeq) {
      audio.pause();
      return;
    }
    tts.playing = true;
  } catch (err) {
    if (seq === ttsSeq) {
      tts.error = (err as Error).message;
      toast(`TTS 失败：${(err as Error).message}`, 'error');
    }
  } finally {
    if (seq === ttsSeq) tts.loading = false;
  }
}

/** 下载 OmniVoice 权重（约 3.3GB），期间轮询进度并刷新音色列表。 */
export async function downloadTtsModel() {
  try {
    tts.download = await api.downloadTtsModel();
  } catch (err) {
    toast(`启动下载失败：${(err as Error).message}`, 'error');
    return;
  }
  if (ttsPollTimer) clearInterval(ttsPollTimer);
  ttsPollTimer = setInterval(async () => {
    try {
      const status = await api.ttsModelStatus();
      tts.download = status;
      if (status.status === 'done' || status.status === 'error') {
        if (ttsPollTimer) clearInterval(ttsPollTimer);
        ttsPollTimer = null;
        if (status.status === 'done') {
          toast('克隆模型已就绪，可以试听日文效果了', 'info');
        } else {
          toast(`模型下载失败：${status.error || '未知错误'}`, 'error');
        }
        await loadTtsVoices();
      }
    } catch {
      /* 轮询失败下一轮再试 */
    }
  }, 1500);
}

export async function uploadTtsVoice(name: string, path: string, refText = '') {
  const voice = await api.uploadTtsVoice({ path, name, ref_text: refText });
  await loadTtsVoices();
  setTtsVoiceId(voice.id);
  toast(`已保存音色「${voice.name}」`, 'info');
  return voice;
}

/**
 * 一次上传多段参考音频：每段独立存成一个音色（OmniVoice 的克隆单位就是
 * 一段 3–10 秒的参考音频，不能把多段拼成同一个 embedding）。
 */
export async function uploadTtsVoices(
  paths: string[],
  onProgress?: (done: number, total: number, name: string) => void,
) {
  const created: TtsVoiceInfo[] = [];
  try {
    for (let i = 0; i < paths.length; i += 1) {
      const path = paths[i];
      const name = path.split('/').pop()?.replace(/\.[^.]+$/, '') || '新音色';
      onProgress?.(i, paths.length, name);
      created.push(await api.uploadTtsVoice({ path, name }));
      onProgress?.(i + 1, paths.length, name);
    }
  } finally {
    // 中途失败也要把已经建好的音色刷出来，不能让界面上看不到它们。
    await loadTtsVoices();
    if (created.length) setTtsVoiceId(created[created.length - 1].id);
  }
  return created;
}

/** 从某句字幕在视频里的区间切出声线，建立克隆音色。 */
export async function extractTtsVoiceFromCue(index: number, name: string, refText = '') {
  const cue = app.cues[index];
  if (!cue) throw new Error('这句字幕不存在');
  if (!app.media) throw new Error('还没有导入视频，无法切片');
  const voice = await api.extractTtsVoice({
    media_id: app.media.id,
    start: cue.start,
    end: cue.end,
    name,
    text: (refText || cue.text).trim(),
  });
  await loadTtsVoices();
  setTtsVoiceId(voice.id);
  toast(`已从这句提取音色「${voice.name}」`, 'info');
  return voice;
}

export async function renameTtsVoice(voiceId: string, name: string) {
  const voice = await api.renameTtsVoice(voiceId, name);
  await loadTtsVoices();
  setTtsVoiceId(voice.id);
  return voice;
}

export async function updateTtsRefText(voiceId: string, refText: string) {
  const voice = await api.updateTtsRefText(voiceId, refText);
  await loadTtsVoices();
  return voice;
}

export async function deleteTtsVoice(voiceId: string) {
  await api.deleteTtsVoice(voiceId);
  await loadTtsVoices();
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

/** 提示词模板库（AI 优化台与「提示词库」共用）。 */
export const prompts = $state({
  items: [] as PromptTemplate[],
  selected: '',
  path: '',
  loading: false,
  error: '',
});

/** 烧录样式：字段与 core/video_export.py 的 SubtitleStyle 一一对应。 */
const DEFAULT_EXPORT_STYLE: SubtitleStylePayload = {
  preset: 'fansub',
  font: 'pingfang',
  weight: 'bold',
  size: 1,
  outline: 1,
  shadow: true,
  position: 'bottom',
  margin: 4.5,
  fill: '#FFFFFF',
  outline_color: '#000000',
};

const EXPORT_STYLE_KEY = 'kikusub.exportStyle';
const EXPORT_PREVIEW_TEXT_KEY = 'kikusub.exportPreviewText';

function readSavedExportStyle(): { style: SubtitleStylePayload; saved: boolean } {
  if (typeof localStorage === 'undefined') {
    return { style: { ...DEFAULT_EXPORT_STYLE }, saved: false };
  }
  try {
    const raw = JSON.parse(localStorage.getItem(EXPORT_STYLE_KEY) || 'null');
    if (raw && typeof raw === 'object') {
      return { style: { ...DEFAULT_EXPORT_STYLE, ...raw }, saved: true };
    }
  } catch {
    /* 坏数据忽略，回默认 */
  }
  return { style: { ...DEFAULT_EXPORT_STYLE }, saved: false };
}

const initialExportStyle = readSavedExportStyle();
const initialPreviewText =
  (typeof localStorage !== 'undefined' && localStorage.getItem(EXPORT_PREVIEW_TEXT_KEY)) || '';

/** 成片导出面板状态。 */
export const exporter = $state({
  options: null as null | {
    modes: { key: string; label: string; hint: string }[];
    presets: { key: string; label: string; factor: number; crf: number; hint: string }[];
    resolutions: { key: string; label: string }[];
  },
  mode: 'burn' as 'burn' | 'soft' | 'copy',
  track: 'source' as 'source' | 'target' | 'both',
  lang: 'zh-Hans',
  resolution: '1080p' as 'source' | '2160p' | '1440p' | '1080p' | '720p' | '480p',
  preset: 'balanced' as 'small' | 'balanced' | 'high' | 'ultra',
  outDir: '',
  exportSrt: true,
  /** 烧录样式（仅 mode='burn' 生效）。 */
  style: initialExportStyle.style,
  styles: null as ExportStyleOptions | null,
  stylesLoaded: false,
  styleError: '',
  previewText: initialPreviewText,
  /** 预览模式：false=整帧，true=字幕区域特写（看得清字重/描边）。 */
  previewZoom: false,
  stylePreviewUrl: '',
  stylePreviewBusy: false,
  stylePreviewError: '',
  plan: null as ExportPlan | null,
  planLoading: false,
  planError: '',
  running: false,
  progress: 0,
  speed: '',
  stage: '',
  outS: 0,
  result: null as ExportResult | null,
  error: '',
  jobId: '',
  optionsLoaded: false,
});

/** 质检队列（浮标面板用）。 */
export const qa = $state({
  open: false,
  /** false = 停靠在右侧检查器「质检待核」页签；true = 独立浮窗。 */
  floating:
    typeof localStorage !== 'undefined' && localStorage.getItem('kikusub.qaFloating') === '1',
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
    void loadPrompts();
    void loadExportOptions();
    void loadExportStyles();
    // 设备探测在 sidecar 的后台预热线程里；先让界面出来，再补一次配置
    scheduleDeviceRefresh();
    // 恢复上次外观（main.ts 在挂载前已同步应用过一次，这里只补齐状态）
    const saved = localStorage.getItem('kikusub.theme');
    // 旧版本把「明朝墨」存成 'cool'，读到就迁移一次
    const restored = saved === 'cool' ? 'mincho' : saved;
    setTheme(isThemeId(restored) ? restored : app.theme);
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

/**
 * 主进程开始退出（⌘Q / 关窗）。
 *
 * 退出时必须杀掉 sidecar，随后到来的 `sidecar:down` 不是“内核崩溃”。没有这个标记，
 * 界面会弹「正在启动转写内核…」遮罩、清空会话并提示自动重启——退出反而像卡死了。
 */
export function markQuitting() {
  app.quitting = true;
}

export function markSidecarDown() {
  if (app.quitting) {
    // 用户已经要退出了：不显示重启遮罩，不清会话，也不弹“内核已断开”toast。
    app.connected = false;
    app.connecting = false;
    return;
  }
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
  app.reviewSource = null;
  app.canUndo = false;
  app.canRedo = false;
  app.undoLabel = '';
  app.redoLabel = '';
  cueHistory.items = [];
  cueHistory.cursor = -1;
  cueHistory.open = false;
  findState.open = false;
  findState.query = '';
  findState.replacement = '';
  stopTts();
  app.report = null;
  app.lastSavedPath = '';
  app.lastExportPath = '';
  app.job = null;
  app.jobMeta = null;
  app.jobKind = '';
  app.qaFillId = '';
  // 导出任务跟着 sidecar 一起没了：不能让进度条永远停在某个百分比。
  if (exporter.running) {
    exporter.error = '内核已重启，导出已中断';
    exporter.stage = '导出已中断';
  }
  exporter.running = false;
  exporter.jobId = '';
  exporter.progress = 0;
  exporter.outS = 0;
  exporter.speed = '';
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

export function setTheme(theme: ThemeId) {
  const next: ThemeId = isThemeId(theme) ? theme : 'light';
  app.theme = next;
  document.documentElement.dataset.theme = next;
  localStorage.setItem('kikusub.theme', next);
  // 青空的两档明暗记在单独一把 key 上：从明朝墨切回来时回到上次那一档
  if (skinOf(next) === 'clear') localStorage.setItem('kikusub.mode', schemeOf(next));
  // 原生 vibrancy / 红绿灯区域跟随应用主题，否则深色模式下侧栏会透成浅色。
  window.kikusub?.setTheme?.(next);
}

/** 切主题。单色主题直接落到它唯一的基调；青空回到上次用过的明暗。 */
export function setSkin(skin: SkinId) {
  if (skin === 'mincho') {
    setTheme('mincho');
    return;
  }
  setTheme(localStorage.getItem('kikusub.mode') === 'dark' ? 'dark' : 'light');
}

/** 只切明暗。单色主题没有第二档，直接忽略。 */
export function setMode(mode: Scheme) {
  if (skinOf(app.theme) !== 'clear') return;
  setTheme(mode);
}

export function toggleTheme() {
  // 月亮按钮永远翻到「另一种明暗」：青空里明暗互换；明朝墨没有自己的深色，按它就回深色那套。
  setTheme(app.theme === 'dark' ? 'light' : 'dark');
}

export function setView(view: View) {
  app.view = view;
  // 检查器只属于「核对」屏（已确认的设计决定）
  // 紧凑模式里检查器是抽屉：切到核对屏不主动盖住画面，由用户点开关打开
  app.inspectorOpen = view === 'review' && !app.compact;
  // 停靠的质检面板属于核对屏：离开时关掉，状态栏的开关与看不见的面板
  // 才不会互相矛盾；浮窗模式例外，切页后仍然保留。
  if (view !== 'review' && !qa.floating) {
    qa.open = false;
    app.inspectorTab = 'cue';
  }
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
export async function applyDevSeed(seed: {
  mediaPath: string;
  cues?: Cue[];
  /** 仅开发截图用：导入一版字幕，验证「换字幕后右侧信息跟着换」。 */
  subtitlePath?: string;
  /** 仅开发截图用：灌一份假报告，验证旧报告不会配到新字幕上。 */
  report?: ReportData | null;
  /** 仅开发截图用：直接灌一份质检 payload，避免为了看面板真跑一次转写。 */
  qa?: Record<string, any> | null;
  /** 仅开发截图用：灌了质检 payload 后是否自动打开面板（默认打开）。 */
  qaOpen?: boolean;
  reviewSource?: ReviewSource | null;
}) {
  if (!seed?.mediaPath) return;
  try {
    // 走真实的 openMedia 路径（含代理压制任务），这样截图/联调覆盖的是产品代码本身
    await openMedia(seed.mediaPath);
    if (seed.cues?.length) {
      await api.replaceCues(seed.cues);
      await refreshCues();
    }
    if (seed.report) app.report = seed.report;
    if (seed.subtitlePath) {
      // 走真实导入链路：服务端会把 review_source 改成 import，并暂停质检队列。
      await openSubtitle(seed.subtitlePath);
    } else if (seed.reviewSource) {
      app.reviewSource = seed.reviewSource;
    }
    if (seed.qa) {
      qa.payload = seed.qa;
      qa.open = seed.qaOpen !== false;
      if (qa.open) app.inspectorTab = 'qa';
    }
    setView('review');
  } catch (err) {
    toast(`种子注入失败：${(err as Error).message}`, 'error');
  }
}

const SUBTITLE_EXTS = ['.srt', '.vtt'];

// 上次会话：只存路径与小整数，不复制媒体/字幕；重启后按真实链路重新导入。
const LAST_MEDIA_KEY = 'kikusub.lastMedia';
const LAST_POSITION_KEY = 'kikusub.lastPosition';
const LAST_SUBTITLE_KEY = 'kikusub.lastSubtitle';

function rememberLastMedia(path: string) {
  try {
    localStorage.setItem(LAST_MEDIA_KEY, path);
  } catch {
    /* 隐私模式 / 存储满：不影响本次使用 */
  }
}

function rememberLastSubtitle(path: string, mediaPath: string) {
  try {
    localStorage.setItem(LAST_SUBTITLE_KEY, JSON.stringify({ path, mediaPath }));
  } catch {
    /* 同上 */
  }
}

function savedLastSubtitle(): { path: string; mediaPath: string } | null {
  try {
    const raw = JSON.parse(localStorage.getItem(LAST_SUBTITLE_KEY) || 'null');
    if (raw && typeof raw.path === 'string') {
      return { path: raw.path, mediaPath: String(raw.mediaPath || '') };
    }
  } catch {
    /* 旧格式 / 手改坏：忽略即可 */
  }
  return null;
}

/** 记住当前播放头（按媒体路径区分；换片后不会把上一部的时间带过来）。 */
export function rememberPlayhead(time: number) {
  const media = app.media;
  if (!media || !Number.isFinite(time)) return;
  try {
    localStorage.setItem(
      LAST_POSITION_KEY,
      JSON.stringify({ path: media.path, time: Math.max(0, time) }),
    );
  } catch {
    /* 同上 */
  }
}

function savedPlayhead(mediaPath: string): number {
  try {
    const raw = JSON.parse(localStorage.getItem(LAST_POSITION_KEY) || 'null');
    if (raw && raw.path === mediaPath && Number.isFinite(Number(raw.time))) {
      return Number(raw.time);
    }
  } catch {
    /* 忽略损坏的记录 */
  }
  return 0;
}

/** 内核未就绪时双击/拖入的媒体：握手完成后自动补导入，不丢用户的操作。 */
let pendingMediaPath = '';

/**
 * 启动时恢复上一次的视频 / 字幕 / 播放头。
 *
 * 不把字幕快照塞进 localStorage：重新走 `openMedia` → `restoreDraft` /
 * `openSubtitle` 的真实链路，服务端的来源、质检解耦与 ⌘Z 才能保持一致。
 */
export async function restoreLastSession() {
  if (!app.connected || app.media) return;
  let path = '';
  try {
    path = localStorage.getItem(LAST_MEDIA_KEY) || '';
  } catch {
    return;
  }
  if (!path) return;
  await openMedia(path, { restoreDraft: true });
  if (!app.media) {
    // 文件被移动/删除：清掉记录，避免每次启动都弹一次导入失败。
    try {
      localStorage.removeItem(LAST_MEDIA_KEY);
    } catch {
      /* 忽略 */
    }
  }
}

export async function openMedia(
  path: string,
  opts: { restoreDraft?: boolean } = {},
) {
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
    // 换片：不把「重置导出面板」记成一次编辑；新会话的起始状态由下面的
    // 静默同步建立。
    resetExportPanel({ record: false });
    exporter.outDir = defaultVideoExportDir();
    // 让服务端基线记住新片的默认导出设置，第一次调字号之前 ⌘Z 才有正确的起点。
    void syncClientState(false);
    app.view = 'review';
    app.inspectorOpen = !app.compact;
    app.inspectorTab = 'cue';
    app.report = null;
    app.lastSavedPath = '';
    app.lastExportPath = '';
    app.job = null;
    app.jobMeta = null;
    app.qaFillId = '';
    // 新片的新会话还没产生字幕来源；refreshCues 会用服务端快照覆盖。
    app.reviewSource = null;
    await refreshCues();
    await loadTranslations();
    await refreshQa();
    await refreshDraftInfo();
    // 换片后播放头必须归零，否则会带着上一部的进度落地
    play.time = 0;
    play.selected = 0;
    play.focus = null;
    rememberLastMedia(info.path);

    // 历史结果直接接上：有字幕就进核对，没有就停在转写
    if (!app.cues.length) {
      app.view = 'transcribe';
      app.inspectorOpen = false;
    }

    if (opts.restoreDraft) {
      // 草稿优先（它包含核对期的编辑）；草稿坏了/不存在再退回上次手动导入的字幕。
      if (reviewDraft.exists) await restoreDraft();
      if (!app.cues.length) {
        const saved = savedLastSubtitle();
        if (saved && saved.mediaPath === info.path) {
          await openSubtitle(saved.path, { remember: false, silent: true });
          if (!app.cues.length) {
            // 文件被移动/删除：清掉记录，别让每次启动都弹一次导入失败。
            try {
              localStorage.removeItem(LAST_SUBTITLE_KEY);
            } catch {
              /* 忽略 */
            }
          }
        }
      }
      const position = savedPlayhead(info.path);
      if (position > 0.2 && (!info.duration || position < info.duration - 0.2)) {
        seekTo(position);
      }
      if (app.cues.length) setView('review');
    }

    logEvent('info', 'media-import', `${info.name} | ${info.duration.toFixed(2)}s | ${info.video_codec}/${info.audio_codec}`, {
      path: info.path,
      id: info.id,
      needs_proxy: info.needs_proxy,
      proxy_ready: info.proxy_ready,
      size: info.size,
    });

    // MKV / HEVC 在 Chromium 里放不出来：后台压代理，不挡用户操作。
    // 已经有代理（包括刚挂载的）时不再重复压。
    if (info.needs_proxy && !info.proxy_ready && (app.settings?.auto_proxy ?? true)) {
      startProxyJob(info.id);
    }
  } catch (err) {
    toast(`导入失败：${(err as Error).message}`, 'error');
  } finally {
    app.busy = false;
  }
}

/** 导入字幕：只换核对基线，不动当前媒体与画面。 */
export async function openSubtitle(
  path: string,
  opts: { remember?: boolean; silent?: boolean } = {},
) {
  // 导入是“换基线”，不是一次编辑：取消还在排队的自动暂存，避免立刻覆盖旧草稿，
  // 让用户仍有机会从「恢复上次暂存」取回导入前的内容。
  clearTimeout(draftTimer);
  draftAgain = false;
  app.busy = true;
  try {
    logEvent('info', 'subtitle-import', path);
    const res = await api.importCues(path);
    applyCueSnapshot(res);
    await loadTranslations();
    setView('review');
    play.selected = 0;
    play.time = 0;
    play.focus = null;
    // 只读草稿状态，方便用户发现上一次的暂存；不要自动覆盖它。
    await refreshDraftInfo();
    // 导入会换掉整张表：媒体同名的质检队列已经对不上，刷新成「已暂停」空态，
    // 状态栏的待核数字也不能再显示上一版的条数。
    await refreshQa();
    if (opts.remember !== false) {
      rememberLastSubtitle(path, app.media?.path || '');
    }
    if (!opts.silent) toast(`已导入字幕 ${res.count} 条（可按 ⌘Z 撤回）`);
  } catch (err) {
    toast(`导入字幕失败：${(err as Error).message}`, 'error');
  } finally {
    app.busy = false;
  }
}

/** 从设置里的导出文件夹挑一个字幕导入核对台（换基线，不动当前媒体）。 */
export async function importSubtitleFromExport() {
  const dir = app.config?.export_dir || app.config?.output_dir || '';
  if (!dir) {
    toast('还没有可用的导出文件夹，请先到设置里选择', 'warn');
    return;
  }
  const file = await window.kikusub.pickSubtitle(dir);
  if (file) await openSubtitle(file);
}

/**
 * 从导出文件夹挑一份译文 SRT / VTT，挂到当前原文的平行轨上。
 *
 * 与原文导入不同：**不动时间轴与 review_cues**，只换 `translations[lang]`；
 * 条数对不上时服务端按时间重叠对齐，仍挂不上就整批拒绝。
 */
export async function importTranslationFromExport(lang = app.trackLang) {
  if (!app.cues.length) {
    toast('请先导入或转写原文字幕，再挂译文', 'warn');
    return;
  }
  const dir = app.config?.export_dir || app.config?.output_dir || '';
  const file = await window.kikusub.pickSubtitle(dir);
  if (!file) return;
  app.busy = true;
  try {
    logEvent('info', 'translation-import', `${lang} | ${file}`);
    const res = await api.importTranslation(file, lang);
    await loadTranslations();
    setTrackLang(res.lang || lang);
    setTrackMode('both');
    // 导入译文本身会压一步统一历史；刷新 can_undo / undo_label。
    await refreshCues();
    scheduleDraftSave();
    toast(`已导入 ${res.count} 条译文（${res.lang || lang}）`);
  } catch (err) {
    toast(`导入译文失败：${(err as Error).message}`, 'error');
  } finally {
    app.busy = false;
  }
}

/**
 * 压制 480p 监看代理。
 *
 * 除了导入时自动触发，核对台也提供手动入口：高码率 H.264 在原格式里能播，
 * 但拖动会卡，自动判定难免遗漏；用户应该能自己决定要不要压。
 */
export async function startProxyJob(mediaId?: string, notify = true) {
  const id = mediaId || app.media?.id || '';
  if (!id) {
    if (notify) toast('请先导入媒体', 'warn');
    return false;
  }
  if (!mediaId && app.media?.proxy_ready) {
    if (notify) toast('当前媒体已经有代理，无需再压', 'warn');
    return false;
  }
  if (app.job && (app.job.status === 'running' || app.job.status === 'queued')) {
    if (notify) toast('已有任务在运行，等它结束或先打断', 'warn');
    return false;
  }
  try {
    const job = await api.createProxyJob(id);
    if (notify) toast('正在后台压制 480p 监看代理…');
    watchJob(job, 'proxy');
    return true;
  } catch (err) {
    if (notify) toast(`压制代理失败：${(err as Error).message}`, 'error');
    return false;
  }
}

/**
 * 把用户已有的 480p 代理挂到当前媒体上，跳过重新压制。
 *
 * 写进标准代理路径后，`<video>` 会在 `refreshMedia()` 后自动切到代理流；
 * 重启应用再导入同一片源时也会被当作已就绪的代理。
 */
export async function importProxyFromFile() {
  if (!app.media) {
    toast('请先导入媒体', 'warn');
    return;
  }
  if (
    app.job &&
    (app.job.status === 'running' || app.job.status === 'queued') &&
    app.jobKind === 'proxy'
  ) {
    toast('已经有一个代理任务在跑，等它完成或先打断', 'warn');
    return;
  }
  if (app.media.proxy_ready) {
    toast('当前媒体已经有代理，无需重复导入', 'warn');
    return;
  }
  const mediaId = app.media.id;
  const file = await window.kikusub.pickMedia();
  if (!file) return;
  app.busy = true;
  try {
    logEvent('info', 'proxy-import', file);
    await api.attachProxy(mediaId, file);
    await refreshMedia();
    toast('代理已导入，监看画面会切换到该文件');
  } catch (err) {
    toast(`导入代理失败：${(err as Error).message}`, 'error');
  } finally {
    app.busy = false;
  }
}

// ---------------------------------------------------------------------------
// 成片导出
// ---------------------------------------------------------------------------

let exportPlanTimer: number | undefined;
let exportPlanSeq = 0;

export function defaultVideoExportDir(): string {
  return app.config?.video_export_dir || app.config?.export_dir || app.config?.output_dir || '';
}

export async function loadExportOptions(force = false) {
  if (!app.connected) return;
  if (exporter.optionsLoaded && !force) return;
  try {
    exporter.options = await api.exportOptions();
    exporter.optionsLoaded = true;
  } catch (err) {
    exporter.planError = (err as Error).message;
  }
}

/** 样式预设与可用字体（字体是否可用必须由后端探测）。 */
export async function loadExportStyles(force = false) {
  if (!app.connected) return;
  if (exporter.stylesLoaded && !force) return;
  try {
    const data = await api.exportStyles();
    exporter.styles = data;
    exporter.stylesLoaded = true;
    exporter.styleError = '';
    if (!initialExportStyle.saved && data.default) {
      exporter.style = { ...data.default };
    }
    const font = data.fonts.find((item) => item.key === exporter.style.font);
    if (!font?.available) {
      const fallback = data.fonts.find((item) => item.available);
      if (fallback) exporter.style.font = fallback.key;
    }
    // 样式默认值来自后端（字体可用性 / 预设），让服务端基线也知道当前值，
    // 第一次调字号时 ⌘Z 才能退回正确的起点。
    syncClientState(false);
  } catch (err) {
    exporter.styleError = (err as Error).message;
  }
}

export function saveExportStyle() {
  try {
    localStorage.setItem(EXPORT_STYLE_KEY, JSON.stringify(exporter.style));
    localStorage.setItem(EXPORT_PREVIEW_TEXT_KEY, exporter.previewText.slice(0, 120));
  } catch {
    /* 存储不可用时只影响记忆，不影响导出 */
  }
}

export function applyExportStylePreset(key: string) {
  const preset = exporter.styles?.presets.find((item) => item.key === key);
  if (!preset) return;
  editExportUi(
    'style.preset',
    (from, to) => `套用样式「${exportStylePresetLabel(to.style.preset)}」`,
    () => {
      exporter.style = { ...preset.style };
      saveExportStyle();
      scheduleStylePreview(0);
    },
  );
}

/** 手动微调任意样式字段；不再等同于任何预设。 */
export function updateExportStyle(patch: Partial<SubtitleStylePayload>) {
  const keys = Object.keys(patch) as (keyof SubtitleStylePayload)[];
  editExportUi(
    keys.length === 1 ? `style.${keys[0]}` : 'style.multi',
    (from, to) => describeStyleChange(from.style, to.style, keys),
    () => {
      exporter.style = { ...exporter.style, ...patch, preset: patch.preset ?? 'custom' };
      saveExportStyle();
      scheduleStylePreview();
    },
  );
}

/** 恢复出厂样式（预设优先，缺省回后端给的 default）。 */
export function resetExportStyle() {
  const fallback = exporter.styles?.default;
  const preset = exporter.styles?.presets?.find(
    (item) => item.key === (fallback?.preset ?? 'fansub'),
  );
  if (!preset && !fallback) return;
  editExportUi(
    'style.reset',
    () => '恢复默认样式',
    () => {
      exporter.style = { ...(preset ? preset.style : fallback!) };
      saveExportStyle();
      scheduleStylePreview(0);
    },
  );
}

/**
 * 导出面板的完整可编辑状态。
 *
 * 它不再单独维护撤销栈：每次改动通过 `/api/history/checkpoint` 记进服务端的
 * **统一工作区时间线**，与字幕 / 译文 / 质检 / AI 草稿共用一个 cursor。
 */
export type ExportUiState = {
  mode: 'burn' | 'soft' | 'copy';
  track: 'source' | 'target' | 'both';
  lang: string;
  resolution: 'source' | '2160p' | '1440p' | '1080p' | '720p' | '480p';
  preset: 'small' | 'balanced' | 'high' | 'ultra';
  exportSrt: boolean;
  outDir: string;
  style: SubtitleStylePayload;
};

/** 同一根滑杆 / 颜色盘连续输入多久算「一次调整」。 */
const UI_COALESCE_SECONDS = 1.2;

/**
 * 本地「拖动起点」快照：滑杆连续 input 时，历史说明要写成
 * 「字号 42 → 48」而不是「字号 47 → 48」。服务端按 coalesce 键合并步骤。
 */
let exportCoalesce: { kind: string; base: ExportUiState; at: number } | null = null;

function currentExportUiState(): ExportUiState {
  return {
    mode: exporter.mode,
    track: exporter.track,
    lang: exporter.lang,
    resolution: exporter.resolution,
    preset: exporter.preset,
    exportSrt: exporter.exportSrt,
    outDir: exporter.outDir,
    style: { ...exporter.style },
  };
}

function exportUiStatesEqual(a: ExportUiState, b: ExportUiState): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** 撤销 / 重做 / 历史跳转时恢复导出面板；只写状态，不再压历史。 */
function applyServerExportUi(raw: Record<string, any> | null | undefined) {
  if (!raw || typeof raw !== 'object') return;
  if (['burn', 'soft', 'copy'].includes(raw.mode)) exporter.mode = raw.mode;
  if (['source', 'target', 'both'].includes(raw.track)) exporter.track = raw.track;
  if (typeof raw.lang === 'string' && raw.lang) exporter.lang = raw.lang;
  if (['source', '2160p', '1440p', '1080p', '720p', '480p'].includes(raw.resolution)) {
    exporter.resolution = raw.resolution;
  }
  if (['small', 'balanced', 'high', 'ultra'].includes(raw.preset)) exporter.preset = raw.preset;
  if (typeof raw.exportSrt === 'boolean') exporter.exportSrt = raw.exportSrt;
  if (typeof raw.outDir === 'string') exporter.outDir = raw.outDir;
  if (raw.style && typeof raw.style === 'object') {
    exporter.style = { ...exporter.style, ...raw.style };
  }
  exportCoalesce = null;
  saveExportStyle();
  scheduleStylePreview(0);
}

/** 静默同步渲染层本地状态（导出设置 / AI 草稿）到服务端，不产生历史步骤。 */
export function syncClientState(record = false, label = "同步工作区状态") {
  if (!app.connected) return;
  void api
    .historyCheckpoint({
      label,
      export_ui: currentExportUiState(),
      ai_draft: currentAiDraft(),
      record,
    })
    .catch(() => {
      /* 同步失败不影响本地编辑；下一次动作会再带上完整状态 */
    });
}

/** 把一次导出设置改动记进统一历史。请求不阻塞界面；服务端负责合并连续滑动。 */
function checkpointExportUi(label: string, kind: string) {
  void api
    .historyCheckpoint({
      label,
      export_ui: currentExportUiState(),
      ai_draft: currentAiDraft(),
      coalesce: kind,
    })
    .then(applyHistoryMeta)
    .catch(() => {
      /* 历史提交失败不挡住导出设置本身；下一动会再提交一次完整状态 */
    });
}

/**
 * 执行一次导出设置改动并记入统一历史。
 *
 * `labeler(from, to)` 用改动前后的完整快照生成「这一步做了什么」。同一根滑杆的
 * 连续 `input` 事件会在 1.2 秒内合并成一步，否则拖一次字号会塞进二三十条历史。
 */
function editExportUi(
  kind: string,
  labeler: (from: ExportUiState, to: ExportUiState) => string,
  mutate: () => void,
) {
  const before = currentExportUiState();
  mutate();
  const after = currentExportUiState();
  // 没有实际变化（例如重复点同一个预设）不压历史
  if (exportUiStatesEqual(before, after)) return;

  const now = Date.now() / 1000;
  if (
    !exportCoalesce ||
    exportCoalesce.kind !== kind ||
    now - exportCoalesce.at > UI_COALESCE_SECONDS
  ) {
    exportCoalesce = { kind, base: before, at: now };
  } else {
    exportCoalesce.at = now;
  }
  checkpointExportUi(labeler(exportCoalesce.base, after), kind);
}

// ---- 导出交付参数（全部走历史，界面不得直接改 exporter.xxx） ----------------

export function setExportMode(mode: ExportUiState['mode']) {
  editExportUi(
    'mode',
    (from, to) => `导出形式 ${exportModeLabel(from.mode)} → ${exportModeLabel(to.mode)}`,
    () => {
      exporter.mode = mode;
    },
  );
}

export function setExportTrack(track: ExportUiState['track']) {
  editExportUi(
    'track',
    (from, to) => `字幕轨 ${exportTrackLabel(from.track)} → ${exportTrackLabel(to.track)}`,
    () => {
      exporter.track = track;
    },
  );
}

export function setExportLang(lang: string) {
  editExportUi(
    'lang',
    (from, to) => `译文语种 ${from.lang} → ${to.lang}`,
    () => {
      exporter.lang = lang;
    },
  );
}

export function setExportResolution(resolution: ExportUiState['resolution']) {
  editExportUi(
    'resolution',
    (from, to) => `分辨率 ${exportResolutionLabel(from.resolution)} → ${exportResolutionLabel(to.resolution)}`,
    () => {
      exporter.resolution = resolution;
    },
  );
}

export function setExportQuality(preset: ExportUiState['preset']) {
  editExportUi(
    'quality',
    (from, to) => `码率档位 ${exportQualityLabel(from.preset)} → ${exportQualityLabel(to.preset)}`,
    () => {
      exporter.preset = preset;
    },
  );
}

export function setExportSrt(enabled: boolean) {
  editExportUi(
    'exportSrt',
    (from, to) => `同时导出 SRT ${from.exportSrt ? '开' : '关'} → ${to.exportSrt ? '开' : '关'}`,
    () => {
      exporter.exportSrt = enabled;
    },
  );
}

export function setExportOutDir(path: string) {
  editExportUi(
    'outDir',
    (from, to) => `导出位置 ${shortPath(from.outDir)} → ${shortPath(to.outDir)}`,
    () => {
      exporter.outDir = path;
    },
  );
}

function shortPath(path: string): string {
  if (!path) return '—';
  const parts = path.split('/').filter(Boolean);
  return parts.length ? parts[parts.length - 1] : path;
}

function exportModeLabel(mode: string): string {
  return ({ burn: '烧录硬字幕', soft: '软字幕 MP4', copy: '仅封装' } as Record<string, string>)[mode] ?? mode;
}

function exportTrackLabel(track: string): string {
  return ({ source: '原文', target: '译文', both: '双语' } as Record<string, string>)[track] ?? track;
}

function exportResolutionLabel(resolution: string): string {
  return resolution === 'source' ? '原始' : resolution;
}

function exportQualityLabel(preset: string): string {
  return (
    exporter.options?.presets.find((item) => item.key === preset)?.label ??
    ({ small: '小', balanced: '甜点', high: '高', ultra: '极高' } as Record<string, string>)[preset] ??
    preset
  );
}

function exportStylePresetLabel(preset: string): string {
  return (
    exporter.styles?.presets.find((item) => item.key === preset)?.label ?? preset
  );
}

function styleFontLabel(font: string): string {
  return exporter.styles?.fonts.find((item) => item.key === font)?.label ?? font;
}

function styleWeightLabel(weight: string): string {
  return (
    exporter.styles?.weights.find((item) => item.key === weight)?.label ??
    ({ regular: '常规', medium: '中等', bold: '粗体' } as Record<string, string>)[weight] ??
    weight
  );
}

function stylePositionLabel(position: string): string {
  return position === 'top' ? '顶部' : '底部';
}

/** 一次改动可能同时动多个字段（恢复默认 / 套预设），逐个翻成可读文字。 */
function describeStyleChange(
  from: SubtitleStylePayload,
  to: SubtitleStylePayload,
  keys: (keyof SubtitleStylePayload)[],
): string {
  const parts: string[] = [];
  for (const key of keys) {
    if (sameStyleValue(from[key], to[key])) continue;
    switch (key) {
      case 'font':
        parts.push(`字体 ${styleFontLabel(from.font)} → ${styleFontLabel(to.font)}`);
        break;
      case 'weight':
        parts.push(`字重 ${styleWeightLabel(from.weight)} → ${styleWeightLabel(to.weight)}`);
        break;
      case 'size':
        parts.push(`字号 ${Math.round(from.size * 100)}% → ${Math.round(to.size * 100)}%`);
        break;
      case 'outline':
        parts.push(`描边 ${Math.round(from.outline * 100)}% → ${Math.round(to.outline * 100)}%`);
        break;
      case 'margin':
        parts.push(`边距 ${from.margin.toFixed(1)}% → ${to.margin.toFixed(1)}%`);
        break;
      case 'shadow':
        parts.push(`阴影 ${from.shadow ? '开' : '关'} → ${to.shadow ? '开' : '关'}`);
        break;
      case 'position':
        parts.push(`位置 ${stylePositionLabel(from.position)} → ${stylePositionLabel(to.position)}`);
        break;
      case 'fill':
        parts.push(`文字色 ${from.fill} → ${to.fill}`);
        break;
      case 'outline_color':
        parts.push(`描边色 ${from.outline_color} → ${to.outline_color}`);
        break;
      case 'preset':
        parts.push('自定义样式');
        break;
    }
  }
  return parts.length ? parts.join('、') : '调整字幕样式';
}

function sameStyleValue(a: unknown, b: unknown): boolean {
  if (typeof a === 'number' && typeof b === 'number') return Math.abs(a - b) < 0.0005;
  return a === b;
}

let stylePreviewTimer: number | undefined;
let stylePreviewSeq = 0;
let stylePreviewAbort: AbortController | null = null;

export function scheduleStylePreview(delay = 260) {
  clearTimeout(stylePreviewTimer);
  stylePreviewTimer = window.setTimeout(() => {
    void refreshStylePreview();
  }, delay);
}

export async function refreshStylePreview() {
  if (!app.connected || exporter.mode !== 'burn') return;
  const seq = ++stylePreviewSeq;
  stylePreviewAbort?.abort();
  const controller = new AbortController();
  stylePreviewAbort = controller;
  exporter.stylePreviewBusy = true;
  exporter.stylePreviewError = '';
  try {
    const blob = await api.exportStylePreview(
      {
        media_id: app.media?.id || '',
        text: exporter.previewText,
        width: 1280,
        height: 720,
        zoom: exporter.previewZoom,
        track: exporter.track,
        lang: exporter.track === 'source' ? '' : exporter.lang,
        style: exporter.style,
      },
      controller.signal,
    );
    if (seq !== stylePreviewSeq) return;
    const url = URL.createObjectURL(blob);
    if (exporter.stylePreviewUrl) URL.revokeObjectURL(exporter.stylePreviewUrl);
    exporter.stylePreviewUrl = url;
  } catch (err) {
    if (seq !== stylePreviewSeq) return;
    if ((err as Error).name === 'AbortError') return;
    exporter.stylePreviewError = (err as Error).message;
  } finally {
    if (seq === stylePreviewSeq) exporter.stylePreviewBusy = false;
  }
}

export function setPreviewText(text: string) {
  exporter.previewText = text.slice(0, 120);
  saveExportStyle();
  scheduleStylePreview(320);
}

export function setPreviewZoom(zoom: boolean) {
  if (exporter.previewZoom === zoom) return;
  exporter.previewZoom = zoom;
  scheduleStylePreview(0);
}

export function scheduleExportPlan(delay = 220) {
  clearTimeout(exportPlanTimer);
  exportPlanTimer = window.setTimeout(() => {
    void refreshExportPlan();
  }, delay);
}

export async function refreshExportPlan() {
  if (!app.connected || !app.media) return;
  const seq = ++exportPlanSeq;
  exporter.planLoading = true;
  exporter.planError = '';
  try {
    const res = await api.exportPlan({
      media_id: app.media.id,
      mode: exporter.mode,
      track: exporter.track,
      lang: exporter.track === 'source' ? '' : exporter.lang,
      resolution: exporter.resolution,
      preset: exporter.preset,
      export_srt: exporter.exportSrt,
      out_dir: exporter.outDir,
      style: exporter.style,
    });
    if (seq !== exportPlanSeq) return;
    exporter.plan = res.plan;
    if (!exporter.outDir) exporter.outDir = res.out_dir;
  } catch (err) {
    if (seq !== exportPlanSeq) return;
    exporter.plan = null;
    exporter.planError = (err as Error).message;
  } finally {
    if (seq === exportPlanSeq) exporter.planLoading = false;
  }
}

export function resetExportPanel(options: { record?: boolean; keepOutDir?: boolean } = {}) {
  const previousOutDir = exporter.outDir;
  const restore = () => {
    clearTimeout(exportPlanTimer);
    exporter.plan = null;
    exporter.result = null;
    exporter.error = '';
    exporter.progress = 0;
    exporter.stage = '';
    exporter.outS = 0;
    exporter.speed = '';
    exporter.running = false;
    exporter.jobId = '';
    exporter.outDir = options.keepOutDir ? previousOutDir : '';
    exporter.track = 'source';
    exporter.mode = 'burn';
    exporter.resolution = '1080p';
    exporter.preset = 'balanced';
    exporter.exportSrt = true;
    exporter.style = { ...DEFAULT_EXPORT_STYLE };
    exporter.previewText = '';
    exporter.previewZoom = false;
    exporter.stylePreviewError = '';
    if (exporter.stylePreviewUrl) URL.revokeObjectURL(exporter.stylePreviewUrl);
    exporter.stylePreviewUrl = '';
    scheduleStylePreview(0);
  };
  if (!options.record) {
    restore();
    return;
  }
  // 「再导一份」会清掉面板上的全部设置：这本身也该能撤回
  editExportUi('panel.reset', () => '重置导出设置', restore);
}

export async function startExport() {
  if (!app.media) {
    toast('请先导入媒体', 'warn');
    return;
  }
  if (exporter.running) return;
  if (!app.cues.length) {
    toast('当前没有字幕可导出', 'warn');
    return;
  }
  if (exporter.track !== 'source' && !app.translations[exporter.lang]?.texts.length) {
    toast(`还没有 ${exporter.lang} 译文；先在 AI 优化台生成并应用`, 'warn');
    return;
  }
  exporter.running = true;
  exporter.error = '';
  exporter.result = null;
  exporter.progress = 0;
  exporter.outS = 0;
  exporter.speed = '';
  exporter.stage = '正在创建导出任务…';
  try {
    const job = await api.createExport({
      media_id: app.media.id,
      mode: exporter.mode,
      track: exporter.track,
      lang: exporter.track === 'source' ? '' : exporter.lang,
      resolution: exporter.resolution,
      preset: exporter.preset,
      export_srt: exporter.exportSrt,
      out_dir: exporter.outDir,
      style: exporter.style,
    });
    exporter.jobId = job.id;
    watchJob(job, 'export');
  } catch (err) {
    exporter.running = false;
    exporter.error = (err as Error).message;
    toast(`导出失败：${(err as Error).message}`, 'error');
  }
}

export async function cancelExport() {
  if (!exporter.jobId) return;
  if (exporter.stage === '正在停止导出…') return;
  try {
    await api.cancelJob(exporter.jobId);
    exporter.stage = '正在停止导出…';
    toast('已发送取消指令，正在停止 ffmpeg', 'warn');
  } catch (err) {
    toast((err as Error).message, 'error');
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
    applyCueSnapshot(await api.getCues());
  } catch {
    /* 会话未绑定媒体时忽略 */
  }
}

/**
 * 菜单快捷键（main 进程的「编辑 → 撤回」）与渲染层 `App.svelte` 的 ⌘Z 兜底
 * 可能对同一次按键各触发一次。60ms 内只认第一次，避免一次 ⌘Z 退回两步；
 * macOS 的按键重复最快约 83ms，正常连按不会被吃掉。
 */
let lastUndoInvoke = 0;
let lastRedoInvoke = 0;
const UNDO_DEDUPE_SECONDS = 0.06;

/**
 * 全局撤销：**没有分域比较**。字幕、译文、质检、导出设置与 AI 草稿都在
 * 服务端同一条时间线上，⌘Z 永远退回最近一步。
 */
export async function undo() {
  const now = Date.now() / 1000;
  if (now - lastUndoInvoke < UNDO_DEDUPE_SECONDS) return;
  lastUndoInvoke = now;
  exportCoalesce = null;
  try {
    const data = await api.undo();
    applyCueSnapshot(data, { applyClientState: true });
    await loadTranslations();
    await refreshQa();
    if (play.selected >= app.cues.length) {
      play.selected = Math.max(0, app.cues.length - 1);
    }
    play.selectNonce += 1;
    scheduleDraftSave();
    toast(data.undone ? `已撤回：${data.undone}` : '已撤回');
  } catch (err) {
    toast((err as Error).message, 'warn');
  }
}

export async function redo() {
  const now = Date.now() / 1000;
  if (now - lastRedoInvoke < UNDO_DEDUPE_SECONDS) return;
  lastRedoInvoke = now;
  exportCoalesce = null;
  try {
    const data = await api.redo();
    applyCueSnapshot(data, { applyClientState: true });
    await loadTranslations();
    await refreshQa();
    if (play.selected >= app.cues.length) {
      play.selected = Math.max(0, app.cues.length - 1);
    }
    play.selectNonce += 1;
    scheduleDraftSave();
    toast(data.redone ? `已重做：${data.redone}` : '已重做');
  } catch (err) {
    toast((err as Error).message, 'warn');
  }
}

export async function updateCue(index: number, patch: Partial<Cue>) {
  try {
    applyCueSnapshot(await api.patchCue(index, patch));
    scheduleDraftSave();
  } catch (err) {
    toast((err as Error).message, 'error');
    await refreshCues();
  }
}

export async function deleteCue(index: number): Promise<boolean> {
  try {
    applyCueSnapshot(await api.deleteCue(index));
    // 服务端同时删掉了同位置的译文；不刷新的话双语行会整体错位。
    await loadTranslations();
    scheduleDraftSave();
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  }
}

/** 批量删除底部轨道上多选的字幕：一次历史、译文轨同步。 */
export async function deleteCues(indices: number[]) {
  const unique = [...new Set(indices)].filter((i) => i >= 0 && i < app.cues.length);
  if (!unique.length) return 0;
  try {
    const res = await api.deleteCues(unique);
    applyCueSnapshot(res);
    await loadTranslations();
    scheduleDraftSave();
    toast(`已删除 ${res.removed} 条字幕（⌘Z 可撤销）`);
    return res.removed;
  } catch (err) {
    toast((err as Error).message, 'error');
    return 0;
  }
}

/** 在音频时间轴当前位置把一条字幕切成两条；两段都先保留完整原文。 */
export async function splitCueAt(index: number, at: number) {
  try {
    const res = await api.splitCue(index, at);
    applyCueSnapshot(res);
    await loadTranslations();
    scheduleDraftSave();
    play.selected = res.index;
    play.selectNonce += 1;
    toast('已切成两句，两段都保留了原句；分别改掉多余部分即可（⌘Z 可撤销）');
    return res.index;
  } catch (err) {
    toast((err as Error).message, 'error');
    return -1;
  }
}

/** 合并连续多条字幕（双语时译文一起合并），一次历史。 */
export async function mergeCuesAt(indices: number[]) {
  try {
    const res = await api.mergeCues(indices);
    applyCueSnapshot(res);
    await loadTranslations();
    scheduleDraftSave();
    play.selected = res.index;
    play.selectNonce += 1;
    toast(`已合并 ${indices.length} 句字幕（⌘Z 可撤销）`);
    return res.index;
  } catch (err) {
    toast((err as Error).message, 'error');
    return -1;
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
    const data = await api.replaceCues(next, `调整 ${changes.length} 条字幕时间`);
    applyCueSnapshot(data);
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
    applyCueSnapshot(res);
    await loadTranslations();
    setView('review');
    if (play.selected >= app.cues.length) {
      play.selected = Math.max(0, app.cues.length - 1);
    }
    play.focus = null;
    await refreshDraftInfo();
    await refreshQa();
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

function watchJob(initial: JobSnapshot, kind: 'transcribe' | 'proxy' | 'export') {
  app.job = initial;
  app.jobKind = kind;

  api.streamJob(
    initial.id,
    async (ev) => {
      if (ev.job) app.job = ev.job;
      if (ev.type === 'progress' && (kind === 'transcribe' || kind === 'proxy') && app.job) {
        app.job = {
          ...app.job,
          percent: ev.job_percent ?? Math.round((ev.ratio ?? 0) * 100),
          stage: ev.stage || app.job.stage,
        };
      }
      if (kind === 'export') {
        const pct = ev.job_percent ?? ev.percent ?? Math.round((ev.ratio ?? 0) * 100);
        if (typeof pct === 'number') exporter.progress = Math.max(exporter.progress, pct);
        if (ev.stage) exporter.stage = ev.stage;
        if (typeof ev.out_s === 'number') exporter.outS = ev.out_s;
        if (ev.speed) exporter.speed = String(ev.speed);
        if (ev.type === 'done') {
          exporter.running = false;
          exporter.progress = 100;
          exporter.result = (ev.job?.result ?? null) as ExportResult | null;
          exporter.error = '';
          toast(
            `成片已导出：${exporter.result?.name ?? ''}${exporter.result?.srt_path ? '（含 SRT）' : ''}`,
          );
        }
        if (ev.type === 'error') {
          exporter.running = false;
          exporter.error = ev.message || '导出失败';
        }
        if (ev.type === 'cancelled') {
          exporter.running = false;
          exporter.error = '';
          exporter.stage = '已取消';
        }
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

async function onJobDone(job: JobSnapshot, kind: 'transcribe' | 'proxy' | 'export') {
  if (kind === 'export') {
    exporter.running = false;
    exporter.progress = 100;
    exporter.stage = '成片已导出';
    exporter.result = (job.result ?? null) as ExportResult | null;
    exporter.error = '';
    return;
  }
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
    // 局部转写：停在核对屏原处，把播放头放到**这次新转出的第一句**上。
    //
    // 以前这里调 focusRange(meta.start, meta.end)：一是会把波形猛地放大（用户
    // 明确不希望「转写选区」改变聚焦状态），二是 meta.start 带了 padding，
    // 播放头落在新句之前，cueIndex=-1，底部表格与右侧检查器都不会同步。
    // 现在服务端返回 target_index，直接选中并强制滚动。
    const added = Number(job.result?.added ?? 0);
    const removed = Number(job.result?.removed ?? 0);
    const total = app.cues.length;
    const target = Number(job.result?.target_index ?? -1);
    if (Number.isInteger(target) && target >= 0 && target < app.cues.length) {
      jumpToCue(target);
    } else {
      seekTo(Math.max(0, meta.start), { play: false });
    }
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

/** 切换右侧检查器的页签；切到「质检待核」会从浮窗模式收回。 */
export function setInspectorTab(tab: 'cue' | 'qa') {
  if (tab === 'qa' && qa.floating) {
    qa.floating = false;
    try {
      localStorage.setItem('kikusub.qaFloating', '0');
    } catch {
      /* 忽略 */
    }
  }
  app.inspectorTab = tab;
  if (tab === 'qa') {
    qa.open = true;
    app.inspectorOpen = true;
    if (app.view !== 'review') setView('review');
    void refreshQa();
  } else {
    qa.open = false;
  }
}

/** 质检面板：停靠到检查器页签 / 弹出为独立浮窗。 */
export function setQaFloating(floating: boolean) {
  qa.floating = floating;
  try {
    localStorage.setItem('kikusub.qaFloating', floating ? '1' : '0');
  } catch {
    /* 忽略 */
  }
  qa.open = true;
  if (app.view !== 'review') setView('review');
  if (floating) {
    if (app.inspectorTab === 'qa') app.inspectorTab = 'cue';
    app.inspectorOpen = true;
  } else {
    app.inspectorTab = 'qa';
    app.inspectorOpen = true;
  }
  void refreshQa();
}

export async function toggleQaPanel(open?: boolean) {
  // 浮窗模式：只开关浮窗，不改变当前页签。
  if (qa.floating) {
    qa.open = open ?? !qa.open;
    if (qa.open) await refreshQa();
    return;
  }
  const dockedOpen = qa.open && app.inspectorTab === 'qa' && app.inspectorOpen;
  const next = open ?? !dockedOpen;
  if (next) {
    app.inspectorTab = 'qa';
    qa.open = true;
    if (app.view !== 'review') setView('review');
    app.inspectorOpen = true;
    await refreshQa();
  } else {
    qa.open = false;
    if (app.inspectorTab === 'qa') app.inspectorTab = 'cue';
  }
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
    // 即使只改了待核状态（没有动字幕），也要更新 can_undo / undo_label；
    // QA 响应带 cues 但不带 count，补一个避免在两个快照形状之间做类型断言。
    applyCueSnapshot({ ...res, count: res.cues.length });
    if (res.cues_changed) scheduleDraftSave();
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
    app.translationsRevision += 1;
    // 当前语种没有轨时退回原文，避免界面停在"译文"却没有内容
    if (app.track !== 'source' && !map[app.trackLang]) app.track = 'source';
    return data;
  } catch {
    app.translations = {};
    app.translationsRevision += 1;
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
    // 「撤回上一版译文」本身也是统一历史的一步；刷新 can_undo / undo_label。
    if (res.undone) {
      await refreshCues();
      scheduleDraftSave();
    }
    toast(res.undone ? '已退回上一版译文' : '这个语种没有更早的译文了', res.undone ? 'info' : 'warn');
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

export async function deleteTranslation(lang = app.trackLang) {
  try {
    await api.deleteTranslation(lang);
    await loadTranslations();
    await refreshCues();
    scheduleDraftSave();
    toast(`已删除 ${lang} 译文`);
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

/** 删除全部原文字幕与时间轴（所有译文轨一起清空，一步历史）。 */
export async function clearOriginalTrack() {
  if (!app.cues.length) {
    toast('当前没有原文字幕', 'warn');
    return;
  }
  if (!window.confirm(`删除全部 ${app.cues.length} 条原文字幕？所有译文轨会一起清空，⌘Z 可撤回。`)) {
    return;
  }
  const count = app.cues.length;
  app.busy = true;
  try {
    logEvent('info', 'subtitle-clear', `cues=${count}`);
    applyCueSnapshot(await api.clearCues());
    await loadTranslations();
    setTrackMode('source');
    play.selected = 0;
    play.focus = null;
    seekTo(0);
    await refreshQa();
    scheduleDraftSave();
    toast(`已删除 ${count} 条原文字幕（可按 ⌘Z 撤回）`);
  } catch (err) {
    toast(`删除原文字幕失败：${(err as Error).message}`, 'error');
  } finally {
    app.busy = false;
  }
}

/** 删除当前语种的译文轨（原文与时间轴不动，一步历史）。 */
export async function removeTranslationTrack(lang = app.trackLang) {
  if (!app.translations[lang]) {
    toast('当前没有译文轨可删除', 'warn');
    return;
  }
  if (!window.confirm(`删除 ${lang} 译文字幕？原文与时间轴不受影响，⌘Z 可撤回。`)) {
    return;
  }
  await deleteTranslation(lang);
  if (app.track !== 'source' && !app.translations[lang]) setTrackMode('source');
}

// ---------------------------------------------------------------------------
// 提示词模板
// ---------------------------------------------------------------------------

let promptsLoaded = false;

function applyPromptLibrary(lib: PromptLibrary) {
  prompts.items = lib.templates ?? [];
  prompts.selected = lib.selected || prompts.items[0]?.id || '';
  prompts.path = lib.path || '';
  prompts.error = '';
}

export async function loadPrompts(force = false) {
  if (!app.connected) return;
  if (promptsLoaded && !force && prompts.items.length) return;
  prompts.loading = true;
  try {
    applyPromptLibrary(await api.getPrompts());
    promptsLoaded = true;
  } catch (err) {
    prompts.error = (err as Error).message;
  } finally {
    prompts.loading = false;
  }
}

export function selectedPromptTemplate(): PromptTemplate | null {
  return prompts.items.find((item) => item.id === prompts.selected) ?? prompts.items[0] ?? null;
}

export async function selectPromptTemplate(id: string) {
  if (!id || id === prompts.selected) return;
  try {
    applyPromptLibrary(await api.selectPrompt(id));
    toast(`已切换到「${selectedPromptTemplate()?.name ?? id}」`);
  } catch (err) {
    toast((err as Error).message, 'error');
  }
}

export async function savePromptTemplate(
  id: string,
  patch: { name?: string; description?: string; content?: string },
) {
  try {
    applyPromptLibrary(await api.updatePrompt(id, patch));
    promptsLoaded = true;
    toast('提示词模板已保存');
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  }
}

export async function createPromptTemplate(
  name: string,
  content: string,
  description = '',
) {
  try {
    const lib = await api.createPrompt({ name, content, description });
    applyPromptLibrary(lib);
    promptsLoaded = true;
    toast('已新建提示词模板');
    return lib.created;
  } catch (err) {
    toast((err as Error).message, 'error');
    return '';
  }
}

export async function resetPromptTemplate(id: string) {
  try {
    applyPromptLibrary(await api.resetPrompt(id));
    toast('已恢复内置模板');
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  }
}

export async function deletePromptTemplate(id: string) {
  try {
    applyPromptLibrary(await api.deletePrompt(id));
    toast('模板已删除');
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  }
}

/** 把某个模板 + 当前字幕渲染成完整提示词并复制。 */
export async function copyPromptTemplate(id?: string) {
  if (!app.cues.length) {
    toast('当前没有可翻译的字幕', 'warn');
    return false;
  }
  const templateId = id || prompts.selected;
  try {
    // 这是翻译提示词；复制后 AI 优化台应停在「翻译」，粘贴面板才会直接露出来。
    ai.kind = 'translate';
    const res = await api.getAiPrompt('translate', ai.lang, templateId);
    if (window.kikusub?.writeClipboard) {
      await window.kikusub.writeClipboard(res.prompt);
    } else if (navigator.clipboard) {
      await navigator.clipboard.writeText(res.prompt);
    }
    toast(
      `已复制「${res.template_name}」：${res.count} 条字幕，${(res.chars / 1000).toFixed(1)}k 字符`,
    );
    ai.pasteOpen = true;
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
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

let aiLoadPromise: Promise<void> | null = null;

/**
 * 拉取当前上下文的提案。
 *
 * 并发调用返回同一个 Promise：撤销 / 重做恢复 AI 草稿时，AiView 的 `$effect`
 * 可能同时触发一次加载，等待同一个任务才能保证 `.then` 写入的 edits 不被
 * 后完成的加载重置。
 */
export function loadAiProposal(force = false): Promise<void> {
  if (!app.connected) return Promise.resolve();
  if (aiLoadPromise) return aiLoadPromise;
  const key = aiContextKey();
  if (!force && ai.loadedFor === key) return Promise.resolve();
  ai.loading = true;
  const task = (async () => {
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
  })();
  aiLoadPromise = task;
  void task.finally(() => {
    if (aiLoadPromise === task) aiLoadPromise = null;
  });
  return task;
}

function switchAiContext(kind: 'polish' | 'translate', lang: string) {
  ai.kind = kind;
  ai.lang = lang;
  ai.loadedFor = '';
  ai.accept = {};
  ai.edits = {};
  void (async () => {
    if (aiLoadPromise) await aiLoadPromise;
    await loadAiProposal(true);
    syncClientState(false);
  })();
}

export function setAiKind(kind: 'polish' | 'translate') {
  if (ai.kind === kind) return;
  switchAiContext(kind, ai.lang);
}

export function setAiLang(lang: string) {
  if (ai.lang === lang) return;
  switchAiContext(ai.kind, lang);
}

/** 当前 AI diff 草稿（人工编辑 + 采纳/拒绝）；随统一历史快照回滚。 */
export function currentAiDraft(): Record<string, any> {
  return {
    key: aiContextKey(),
    kind: ai.kind,
    lang: ai.lang,
    edits: { ...ai.edits },
    accept: { ...ai.accept },
    changedOnly: ai.changedOnly,
  };
}

/** 撤销 / 重做 / 历史跳转时恢复 AI diff 草稿。 */
export function applyAiDraft(raw: Record<string, any> | null | undefined) {
  if (!raw || typeof raw !== 'object') return;
  const kind: 'polish' | 'translate' = raw.kind === 'translate' ? 'translate' : 'polish';
  const lang = typeof raw.lang === 'string' && raw.lang ? raw.lang : ai.lang;
  const contextChanged = kind !== ai.kind || lang !== ai.lang;
  const apply = () => {
    ai.edits = { ...(raw.edits ?? {}) };
    ai.accept = { ...(raw.accept ?? {}) };
    ai.changedOnly = raw.changedOnly ?? ai.changedOnly;
  };
  if (contextChanged) {
    void (async () => {
      // 先等掉可能还在飞的旧上下文请求，再切上下文强制重拉；否则旧请求的
      // finally 会用旧 key 覆盖 loadedFor，并把刚恢复的 edits 重置掉。
      if (aiLoadPromise) await aiLoadPromise;
      ai.kind = kind;
      ai.lang = lang;
      ai.loadedFor = '';
      await loadAiProposal(true);
      apply();
    })();
  } else {
    apply();
  }
}

function checkpointAiDraft(label: string, coalesce: string) {
  void api
    .historyCheckpoint({
      label,
      export_ui: currentExportUiState(),
      ai_draft: currentAiDraft(),
      coalesce,
    })
    .then(applyHistoryMeta)
    .catch(() => {
      /* 历史提交失败不挡住 diff 编辑本身；下一次操作会再提交完整状态 */
    });
}

export function toggleAiAccept(i: number) {
  ai.accept[i] = ai.accept[i] === false;
  checkpointAiDraft(
    ai.accept[i] === false ? `AI 建议：取消采纳第 ${i} 条` : `AI 建议：采纳第 ${i} 条`,
    `ai.accept.${i}`,
  );
}

export function setAllAiAccept(value: boolean) {
  if (!ai.proposal) return;
  for (const item of ai.proposal.items) ai.accept[item.i] = value;
  checkpointAiDraft(value ? 'AI 建议：全选' : 'AI 建议：全不选', 'ai.accept.all');
}

export function setAiEdit(i: number, text: string) {
  const item = ai.proposal?.items.find((it) => it.i === i);
  if (!item) return;
  const previous = ai.edits[i];
  if (text === item.after) {
    if (previous === undefined) return;
    delete ai.edits[i];
  } else {
    if (previous === text) return;
    ai.edits[i] = text;
  }
  checkpointAiDraft(`AI 建议：修改第 ${i} 条`, `ai.edit.${i}`);
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
    applyCueSnapshot(res);

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
    toast(ai.kind === 'translate' ? '当前没有可翻译的字幕' : '当前没有可润色的字幕', 'warn');
    return false;
  }
  try {
    const templateId = ai.kind === 'translate' ? prompts.selected : '';
    const res = await api.getAiPrompt(ai.kind, ai.kind === 'translate' ? ai.lang : '', templateId);
    if (window.kikusub?.writeClipboard) {
      await window.kikusub.writeClipboard(res.prompt);
    } else if (navigator.clipboard) {
      await navigator.clipboard.writeText(res.prompt);
    }
    toast(
      `已复制「${res.template_name}」：${res.count} 条字幕，${(res.chars / 1000).toFixed(1)}k 字符`,
    );
    ai.pasteOpen = true;
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
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
    const res = await api.aiFromSrt({
      kind: ai.kind,
      lang: ai.kind === 'translate' ? ai.lang : '',
      text,
    });
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
    toast(
      ai.kind === 'translate'
        ? `已解析 ${res.count} 条译文，右侧就是待应用的建议`
        : `已解析 ${res.count} 条修改，右侧就是待应用的建议`,
    );
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
    toast('这不是一份翻译建议', 'warn');
    return;
  }
  const lang = (track.dst_lang || ai.lang || '').trim();
  if (!lang) {
    toast('建议里没有目标语种', 'error');
    return;
  }
  ai.applying = true;
  try {
    const items = ai.proposal.items.map((it) => ({ ...it, after: ai.edits[it.i] ?? it.after }));
    const res = await api.applyTranslation({ lang, proposal: { ...ai.proposal, items } });
    await loadTranslations();
    await loadCueHistory();
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
    toast(`已保存建议：${res.path.split('/').pop()}`);
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
  toast('已丢弃建议');
}

/** 改某一条译文（三种显示模式下右侧检查器都用它）。 */
export async function updateTranslation(index: number, text: string) {
  const lang = app.trackLang;
  if (!lang) return;
  try {
    await api.patchTranslation(lang, index, text);
    await loadTranslations();
    void loadCueHistory();
    scheduleDraftSave();
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
    toast(ev.message || '生成建议失败', 'error');
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
    toast(`已导入建议：${picked.split('/').pop()}`);
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
  video_export_dir?: string;
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
