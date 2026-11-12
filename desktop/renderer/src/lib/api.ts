/**
 * 服务层客户端。
 *
 * 端点由主进程通过握手注入（随机端口 + 一次性 token），所以这里不能有硬编码 URL。
 * 所有请求都带 `Authorization: Bearer`；`<video src>` 与 WebSocket 因为发不了自定义头，
 * 改走 `?token=`（与 `server/security.py` 的双通道一致）。
 */

export interface MediaInfo {
  id: string;
  name: string;
  path: string;
  size: number;
  duration: number;
  video_codec: string;
  audio_codec: string;
  video_width: number;
  video_height: number;
  video_bitrate: number;
  has_video: boolean;
  needs_proxy: boolean;
  proxy_reason: string;
  proxy_ready: boolean;
}

export interface EngineInfo {
  key: string;
  label: string;
  short_label: string;
  description: string;
  desc?: string;
  languages: string[];
  purpose: string;
  hf_repo: string;
  model_dir: string;
  approx_bytes: number;
  approx_label: string;
  min_ram_gb: number;
  notes: string;
  downloadable: boolean;
  installed: boolean;
  size_bytes: number;
  enabled: boolean;
}

export interface AppSettings {
  enabled_engines: string[];
  auto_proxy: boolean;
  /** 字幕默认导出目录；空字符串表示沿用应用输出目录。 */
  export_dir: string;
  /** 成片导出目录；空字符串表示跟随 export_dir。 */
  video_export_dir: string;
}

export interface SettingsPayload {
  settings: AppSettings;
  engines: EngineInfo[];
  paths: {
    output_dir: string;
    export_dir: string;
    video_export_dir: string;
    models_dir: string;
    presets_path: string;
    settings_path: string;
    proxy_dir: string;
    tts_cache_dir: string;
    voices_dir: string;
    tts_model_dir: string;
    log_path: string;
    log_dir: string;
  };
  runtime: {
    version: string;
    python: string;
    frozen: boolean;
    platform: string;
    machine: string;
    device: string;
  };
  ffmpeg: { path: string; version: string; ok: boolean };
}

export interface PromptTemplate {
  id: string;
  name: string;
  description: string;
  content: string;
  builtin: boolean;
  updated_at: number;
}

export interface PromptLibrary {
  version: number;
  selected: string;
  templates: PromptTemplate[];
  path: string;
}

export interface ExportSourceInfo {
  width: number;
  height: number;
  duration: number;
  video_bitrate: number;
  audio_bitrate: number;
  video_codec: string;
  audio_codec: string;
  has_video: boolean;
  has_audio: boolean;
  size: number;
  container: string;
}

export interface ExportPlan {
  mode: 'burn' | 'soft' | 'copy';
  track: 'source' | 'target' | 'both';
  lang: string;
  width: number;
  height: number;
  video_bitrate: number;
  audio_bitrate: number;
  duration: number;
  estimated_bytes: number;
  estimated_seconds: number;
  container: string;
  suffix: string;
  warnings: string[];
  source: ExportSourceInfo;
  style?: SubtitleStylePayload;
}

/** 烧录硬字幕的样式（只对 mode='burn' 生效）。 */
export interface SubtitleStylePayload {
  preset: string;
  font: string;
  weight: 'regular' | 'medium' | 'bold';
  size: number;
  outline: number;
  shadow: boolean;
  position: 'bottom' | 'top';
  margin: number;
  fill: string;
  outline_color: string;
}

export interface ExportStylePreset {
  key: string;
  label: string;
  hint: string;
  style: SubtitleStylePayload;
}

export interface ExportFontOption {
  key: string;
  label: string;
  hint: string;
  available: boolean;
  weights: { key: string; label: string }[];
}

export interface ExportStyleOptions {
  presets: ExportStylePreset[];
  fonts: ExportFontOption[];
  default: SubtitleStylePayload;
  weights: { key: string; label: string }[];
  ranges: {
    size: [number, number];
    outline: [number, number];
    margin: [number, number];
  };
  fonts_ok: boolean;
  font_error: string;
}

export interface ExportJobPayload {
  media_id: string;
  mode: 'burn' | 'soft' | 'copy';
  track: 'source' | 'target' | 'both';
  lang?: string;
  resolution: 'source' | '2160p' | '1440p' | '1080p' | '720p' | '480p';
  preset: 'small' | 'balanced' | 'high' | 'ultra';
  export_srt?: boolean;
  out_dir?: string;
  style?: SubtitleStylePayload;
}

export interface ExportResult {
  path: string;
  name: string;
  size: number;
  elapsed: number;
  width: number;
  height: number;
  video_bitrate: number;
  audio_bitrate: number;
  duration: number;
  mode: string;
  track: string;
  lang: string;
  resolution: string;
  actual_resolution: string;
  preset: string;
  container: string;
  subtitle_count: number;
  skipped: number;
  srt_path?: string;
}

export interface ParamSpec {
  key: string;
  label: string;
  engine: string;
  kind: 'bool' | 'float' | 'int';
  default: number | boolean;
  group: string;
  min: number | null;
  max: number | null;
  step: number | null;
  help: string;
  is_config: boolean;
}

export interface Cue {
  start: number;
  end: number;
  text: string;
}

/** 当前核对表的来源。kind=transcription 才能引用该次转写的报告与质检。 */
export interface ReviewSource {
  kind: 'transcription' | 'import' | 'draft' | string;
  name?: string;
  path?: string;
  job_id?: string;
  at?: number;
  apply?: string;
}

/** 服务端返回的字幕快照。`undo_label` / `redo_label` 用于按钮提示与历史列表。 */
export interface CueSnapshot {
  cues: Cue[];
  count: number;
  can_undo: boolean;
  can_redo: boolean;
  undo_label?: string;
  redo_label?: string;
  /** 下一步撤回/重做那一步的服务端记录时间（显示用）。 */
  undo_at?: number;
  redo_at?: number;
  /** 当前字幕来自本次转写、导入文件还是恢复的草稿。 */
  review_source?: ReviewSource | null;
  /** 只有撤销 / 重做 / 历史跳转才带：把导出设置与 AI 草稿一起回滚。 */
  export_ui?: Record<string, any>;
  ai_draft?: Record<string, any>;
}

/** 历史时间线上的一步。past=可点回去；current=当前状态；undone=可重做。 */
export interface CueHistoryItem {
  id: number;
  label: string;
  at: number;
  state: 'past' | 'current' | 'undone';
  cue_count: number;
}

export interface CueHistory {
  items: CueHistoryItem[];
  cursor: number;
  can_undo: boolean;
  can_redo: boolean;
  undo_label: string;
  redo_label: string;
  undo_at: number;
  redo_at: number;
}

/** 一个可用音色：系统 say 音色或克隆音色（kind 区分）。 */
export interface TtsVoiceInfo {
  id: string;
  name: string;
  engine: 'mac_say' | 'omnivoice' | string;
  kind: 'system' | 'clone' | string;
  locale: string;
  sample: string;
  duration: number;
  ref_text: string;
  created_at: number;
  source: Record<string, unknown>;
}

/** 兼容旧命名（Inspector/store 都从 TtsVoiceInfo 走）。 */
export type TtsVoice = TtsVoiceInfo;

export interface TtsDownloadStatus {
  status: 'idle' | 'running' | 'done' | 'error' | string;
  percent: number;
  stage: string;
  error: string;
  bytes: number;
  total: number;
  installed: boolean;
  missing?: string[];
  model_dir: string;
  repo: string;
}

export interface TtsModelVerify {
  installed: boolean;
  missing: string[];
  model_dir: string;
  repo: string;
  bytes: number;
  package_installed?: boolean;
}

export interface TtsEngineInfo {
  key: string;
  label: string;
  repo: string;
  model_dir: string;
  approx_label: string;
  min_ram_gb: number;
  downloadable: boolean;
  package_installed: boolean;
  installed: boolean;
  loaded: boolean;
  device: string;
  steps: number;
  error: string;
  max_chars: number;
  download: TtsDownloadStatus;
}

export interface TtsVoicesPayload {
  available: boolean;
  platform: string;
  max_chars: number;
  say_max_chars: number;
  default: string;
  default_name: string;
  /** 克隆音色资产目录（outputs/voices）。 */
  voices_dir: string;
  system: TtsVoiceInfo[];
  custom: TtsVoiceInfo[];
  voices: TtsVoiceInfo[];
  speeds: number[];
  engine: TtsEngineInfo;
  say: { available: boolean; default: string; platform: string };
}

export interface TtsResult {
  filename: string;
  voice_id: string;
  voice_name: string;
  engine: string;
  cached: boolean;
  duration: number;
  elapsed: number;
}

/** 核对工作草稿（临时全量保存）的落盘状态。 */
export interface DraftInfo {
  exists: boolean;
  path: string;
  count: number;
  saved_at: number;
}

/** AI 提案里的一条：只有序号与文本，**没有时间码**（见开发文档 D-1）。 */
export interface AiProposalItem {
  i: number;
  before?: string;
  after: string;
  note?: string;
}

/** AI 提案（`proposal.json`）。in-app 与外部 skill 产出的是同一份结构。 */
export interface AiProposal {
  version: number;
  kind: 'polish' | 'translate';
  src_lang: string;
  dst_lang?: string;
  source: { path: string; count: number; digest: string };
  model?: string;
  entry?: string;
  created_at?: number;
  chunks?: number;
  glossary?: { src: string; dst: string }[];
  items: AiProposalItem[];
}

export type TrackMode = 'source' | 'target' | 'both';

export interface TranslationTrack {
  lang: string;
  exists: boolean;
  count: number;
  texts: string[];
  base: string[];
  stale: number[];
  created_at: number;
  entry: string;
}

export interface TranslationsPayload {
  items: TranslationTrack[];
  count: number;
  cue_count: number;
}

export interface AiConfig {
  enabled: boolean;
  base_url: string;
  model: string;
  chunk_cues: number;
  translate_chunk_cues: number;
  context_cues: number;
  /** 密钥不归服务层管；服务端只声明"由渲染进程持有" */
  key_held_by: string;
}

export interface AiProposalPayload {
  path: string;
  proposal: AiProposal;
  ok: boolean;
  errors: string[];
  warnings: string[];
  digest_match: boolean;
  source_count: number;
  current_count: number;
}

export interface JobSnapshot {
  id: string;
  kind: string;
  status: 'queued' | 'running' | 'cancelling' | 'done' | 'error' | 'cancelled';
  ratio: number;
  percent: number;
  stage: string;
  error: string;
  created_at: number;
  started_at: number;
  finished_at: number;
  elapsed: number;
  result: Record<string, any> | null;
}

export interface JobEvent {
  type: 'snapshot' | 'start' | 'progress' | 'done' | 'error' | 'cancelled' | 'cancelling';
  job?: JobSnapshot;
  ratio?: number;
  percent?: number;
  stage?: string;
  message?: string;
  out_s?: number;
  duration?: number;
  speed?: string;
  note?: string;
  job_percent?: number;
}

export interface ReportSection {
  id: string;
  title: string;
  headline: string;
  note?: string;
  empty_text?: string;
  hidden?: number;
  hidden_text?: string;
  count?: number;
  truncated?: number;
  total_degraded?: number;
  disabled?: boolean;
  items: any[];
}

export interface ReportData {
  /** 报告对应的转写任务；与 review_source.job_id 比对，避免拿旧报告配新字幕。 */
  job_id?: string;
  media_id?: string;
  out_filename?: string;
  out_path?: string;
  overview: { label: string; value: string }[];
  params: { label: string; value: string }[];
  quality: {
    headline: string;
    coverage?: number;
    low_confidence?: number;
    missed: number;
    hidden_missed: number;
    dropped: number;
    suspect: number;
    degraded: number;
    has_findings: boolean;
    qwen_limited: boolean;
  };
  sections: ReportSection[];
  raw_text: string;
}

let BASE = '';
let TOKEN = '';

/**
 * 会话 id：由客户端生成并持久化。
 *
 * 不能用 cookie —— 渲染进程是 file:// 源，对 127.0.0.1 的请求是跨源，
 * 浏览器默认不带 cookie，会话会每次新建（写入的字幕下次就读不到）。
 */
const SID = (() => {
  const key = 'kikusub.sid';
  let value = localStorage.getItem(key);
  if (!value) {
    value = crypto.randomUUID().replace(/-/g, '');
    localStorage.setItem(key, value);
  }
  return value;
})();

export function setEndpoint(port: number, token: string) {
  BASE = `http://127.0.0.1:${port}`;
  TOKEN = token;
  // 启动早期（BASE 还没注入）的客户端事件先排队，握手后一次补发
  const queued = pendingLogs.splice(0, pendingLogs.length);
  for (const entry of queued) void sendClientLog(entry);
}

let pendingLogs: ClientLogEntry[] = [];
let logBudget = 30;
let logBudgetReset = Date.now() + 60_000;

interface ClientLogEntry {
  level: 'debug' | 'info' | 'warn' | 'error';
  event: string;
  message: string;
  detail?: unknown;
}

async function sendClientLog(entry: ClientLogEntry): Promise<void> {
  if (!BASE || !TOKEN) return;
  try {
    await fetch(`${BASE}/api/log`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${TOKEN}`,
        'X-Kikusub-Session': SID,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        level: entry.level,
        event: entry.event,
        message: entry.message.slice(0, 3800),
        detail:
          entry.detail === undefined
            ? null
            : typeof entry.detail === 'string'
              ? entry.detail.slice(0, 7000)
              : JSON.stringify(entry.detail).slice(0, 7000),
      }),
    });
  } catch {
    /* 日志失败绝不能反过来影响主流程 */
  }
}

/**
 * 把渲染进程的事件写进 sidecar 的 kikusub.log。
 *
 * 这是「用户报问题 → 日志能定位」的核心：以前渲染层的异常只存在于 DevTools，
 * 关掉窗口就没了。现在 API 失败、未捕获异常、关键操作都会落盘。
 */
export function logEvent(
  level: ClientLogEntry['level'],
  event: string,
  message: string,
  detail?: unknown,
): void {
  if (Date.now() > logBudgetReset) {
    logBudget = 30;
    logBudgetReset = Date.now() + 60_000;
  }
  if (logBudget <= 0) return;
  logBudget -= 1;
  const entry = { level, event, message, detail };
  if (!BASE) {
    if (pendingLogs.length < 30) pendingLogs.push(entry);
    return;
  }
  void sendClientLog(entry);
}

if (typeof window !== 'undefined') {
  window.addEventListener('error', (e) => {
    logEvent('error', 'uncaught', e.message || 'unknown error', e.error?.stack);
  });
  window.addEventListener('unhandledrejection', (e) => {
    const reason = e.reason as { message?: string; stack?: string } | undefined;
    logEvent('error', 'unhandled-rejection', String(reason?.message ?? reason), reason?.stack);
  });
}

export function endpoint() {
  return { base: BASE, token: TOKEN };
}

/**
 * 媒体流地址。
 *
 * `proxy=true` 时走 480p 监看代理——Chromium 解不开 MKV / HEVC，
 * 原片直接喂给 `<video>` 只会黑屏。
 */
export function mediaUrl(mediaId: string, proxy = false) {
  const q = new URLSearchParams({ token: TOKEN });
  if (proxy) q.set('proxy', '1');
  return `${BASE}/media/${mediaId}?${q}`;
}

/** 最近打开列表的封面：后端按需生成、按路径+mtime 缓存。 */
export function mediaThumbUrl(path: string, version = '') {
  const q = new URLSearchParams({ token: TOKEN, path });
  if (version) q.set('v', version);
  return `${BASE}/api/media/thumb?${q}`;
}

/** TTS 音频地址：`<audio>` 同样发不了 Authorization 头，走 `?token=`。 */
export function ttsAudioUrl(filename: string) {
  const q = new URLSearchParams({ token: TOKEN });
  return `${BASE}/media/tts/${encodeURIComponent(filename)}?${q}`;
}

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${TOKEN}`,
    'X-Kikusub-Session': SID,
    ...((init.headers as Record<string, string>) || {}),
  };
  if (init.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';

  let resp: Response;
  try {
    resp = await fetch(BASE + path, { ...init, headers });
  } catch (err) {
    logEvent('error', 'api-network', `${init.method || 'GET'} ${path}`, String(err));
    throw new ApiError(`无法连接本地服务：${(err as Error).message}`, 0);
  }
  const reqId = resp.headers.get('X-Request-Id') || '';
  const text = await resp.text();

  // 服务端理论上只回 JSON，但代理/框架层的错误可能是纯文本
  // （比如 `Internal Server Error`）。直接 JSON.parse 会炸成
  // 「Unexpected token 'I'」，对用户毫无信息量。
  let data: any = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!resp.ok) {
    const detail =
      (data && typeof data.detail === 'string' && data.detail) ||
      text.trim().slice(0, 300) ||
      `${resp.status} ${resp.statusText}`;
    // 4xx 里 401/404 可能是正常探测，仍然记 info；5xx 记 error
    logEvent(
      resp.status >= 500 ? 'error' : 'warn',
      'api-failed',
      `${init.method || 'GET'} ${path} -> ${resp.status}`,
      reqId ? `req=${reqId} detail=${detail}` : detail,
    );
    // 5xx 把请求 id 带进给用户看的错误里，报障时可以拿它精确定位日志
    const shown = resp.status >= 500 && reqId ? `${detail}（请求 ${reqId}）` : detail;
    throw new ApiError(shown, resp.status);
  }
  if (data === null) {
    throw new ApiError(`服务返回了非 JSON 内容：${text.slice(0, 200)}`, resp.status);
  }
  return data as T;
}

export const api = {
  health: () => req<{ ok: boolean; version: string }>('/api/health'),

  config: () =>
    req<{
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
    }>('/api/config'),

  // ---- 媒体 ----
  importMedia: (path: string) =>
    req<MediaInfo>('/api/media', { method: 'POST', body: JSON.stringify({ path }) }),

  getMedia: (id: string) => req<MediaInfo>(`/api/media/${id}`),

  /** 挂载用户已有的代理文件，跳过重复压制。 */
  attachProxy: (mediaId: string, path: string) =>
    req<MediaInfo>(`/api/media/${mediaId}/proxy`, {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),

  listMedia: () => req<{ items: MediaInfo[] }>('/api/media'),

  peaks: (
    id: string,
    opts: {
      bins?: number;
      lod?: 'overview' | 'mid' | 'fine' | 'ultra';
      from?: number;
      to?: number;
    },
  ) => {
    const q = new URLSearchParams();
    if (opts.lod) q.set('lod', opts.lod);
    if (opts.bins) q.set('bins', String(opts.bins));
    if (opts.from !== undefined) q.set('from', String(opts.from));
    if (opts.to !== undefined) q.set('to', String(opts.to));
    return req<{ id: string; bins: number; duration: number; peaks: number[] }>(
      `/api/media/${id}/peaks?${q}`,
    );
  },

  // ---- 参数 ----
  getParams: () =>
    req<{
      engines: {
        key: string;
        groups: { group: string; params: ParamSpec[] }[];
        defaults: Record<string, number | boolean>;
      }[];
    }>('/api/params'),

  // ---- 预设 ----
  listPresets: () =>
    req<{ items: { name: string; engine: string | null }[]; load_error: string }>('/api/presets'),

  getPreset: (name: string) =>
    req<{ name: string; engine: string | null; values: Record<string, number | boolean> }>(
      `/api/presets/${encodeURIComponent(name)}`,
    ),

  savePreset: (name: string, engine: string, values: Record<string, unknown>) =>
    req<{ name: string; created: boolean }>('/api/presets', {
      method: 'POST',
      body: JSON.stringify({ name, engine, values }),
    }),

  deletePreset: (name: string) =>
    req<{ deleted: string }>(`/api/presets/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  // ---- 会话 ----
  bindSession: (mediaId: string) =>
    req<{ id: string; media: MediaInfo }>('/api/session/bind', {
      method: 'POST',
      body: JSON.stringify({ media_id: mediaId }),
    }),

  session: () =>
    req<{
      id: string;
      media: MediaInfo | null;
      cue_count: number;
      latest_cue_count: number;
      can_undo: boolean;
      can_redo: boolean;
    }>('/api/session'),

  // ---- 任务 ----
  createTranscribeJob: (payload: {
    media_id: string;
    engine: string;
    output_format?: string;
    save_beside?: boolean;
    start?: number | null;
    end?: number | null;
    keep_absolute_timeline?: boolean;
    apply?: 'replace' | 'append' | 'replace_range';
    params?: Record<string, unknown>;
  }) => req<JobSnapshot>('/api/jobs', { method: 'POST', body: JSON.stringify(payload) }),

  createProxyJob: (mediaId: string) =>
    req<JobSnapshot>('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({ media_id: mediaId, kind: 'proxy' }),
    }),

  getJob: (id: string) => req<JobSnapshot>(`/api/jobs/${id}`),

  cancelJob: (id: string) => req<{ cancelled: boolean }>(`/api/jobs/${id}`, { method: 'DELETE' }),

  /** 订阅任务进度。返回一个解绑函数。 */
  streamJob(id: string, onEvent: (ev: JobEvent) => void, onClose?: () => void) {
    const ws = new WebSocket(`${BASE.replace('http', 'ws')}/ws/jobs/${id}?token=${encodeURIComponent(TOKEN)}`);
    ws.onmessage = (msg) => {
      try {
        onEvent(JSON.parse(msg.data));
      } catch {
        /* 忽略坏帧 */
      }
    };
    ws.onclose = () => onClose?.();
    return () => {
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    };
  },

  // ---- 字幕 ----
  getCues: () => req<CueSnapshot>('/api/cues'),

  /** 按路径导入 SRT / VTT，整表替换核对基线。 */
  importCues: (path: string) =>
    req<CueSnapshot & { source: string }>('/api/cues/import', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),

  /** 整表替换；`label` 会作为这一步历史在撤销列表里显示。 */
  replaceCues: (cues: Cue[], label?: string) =>
    req<CueSnapshot>('/api/cues', {
      method: 'POST',
      body: JSON.stringify({ cues, label: label ?? '' }),
    }),

  /** 清空原文字幕（连同无法再对齐的译文轨，一次历史）。 */
  clearCues: () => req<CueSnapshot>('/api/cues/clear', { method: 'POST' }),

  patchCue: (index: number, patch: Partial<Cue>) =>
    req<CueSnapshot>(`/api/cues/${index}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  deleteCue: (index: number) =>
    req<CueSnapshot & { removed: number }>(`/api/cues/${index}`, { method: 'DELETE' }),

  /** 批量删除（底部轨道 ⌘ 多选）：一次历史，译文轨同步。 */
  deleteCues: (indices: number[]) =>
    req<CueSnapshot & { removed: number }>('/api/cues/delete', {
      method: 'POST',
      body: JSON.stringify({ indices }),
    }),

  /** 在指定下标插入一条（右键「添加字幕」/空字幕补录）。 */
  insertCue: (index: number, cue: Cue) =>
    req<CueSnapshot & { index: number }>(`/api/cues/${index}/insert`, {
      method: 'POST',
      body: JSON.stringify({ index, ...cue }),
    }),

  /** 在音频时间轴上切割一条字幕；两段都保留完整原文。 */
  splitCue: (index: number, at: number) =>
    req<CueSnapshot & { index: number; new_index: number }>(`/api/cues/${index}/split`, {
      method: 'POST',
      body: JSON.stringify({ at }),
    }),

  /** 合并连续多条字幕（双语时译文一起拼），一次历史。 */
  mergeCues: (indices: number[]) =>
    req<CueSnapshot & { index: number }>('/api/cues/merge', {
      method: 'POST',
      body: JSON.stringify({ indices }),
    }),

  undo: () => req<CueSnapshot & { undone?: string }>('/api/cues/undo', { method: 'POST' }),

  redo: () => req<CueSnapshot & { redone?: string }>('/api/cues/redo', { method: 'POST' }),

  /** 50 步可回溯历史（字幕 / 译文 / 质检 / 导出设置 / AI 草稿共用）。 */
  getCueHistory: () => req<CueHistory>('/api/cues/history'),

  /** 双语「全部替换」：原文 + 译文一次提交，只压一步历史。 */
  replaceAll: (body: {
    label?: string;
    cues?: Cue[];
    lang?: string;
    texts?: string[];
  }) =>
    req<CueSnapshot>('/api/cues/replace-all', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** 渲染层本地状态的一次历史提交（导出设置 / AI diff 草稿）。 */
  historyCheckpoint: (body: {
    label: string;
    export_ui?: Record<string, any>;
    ai_draft?: Record<string, any>;
    coalesce?: string;
    record?: boolean;
  }) =>
    req<CueSnapshot>('/api/history/checkpoint', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  jumpCueHistory: (index: number) =>
    req<CueSnapshot & { label: string; index: number }>('/api/cues/history/jump', {
      method: 'POST',
      body: JSON.stringify({ index }),
    }),

  exportCues: (
    format: 'SRT' | 'VTT' | 'TXT',
    opts: { track?: TrackMode; lang?: string } = {},
  ) =>
    req<{
      path: string;
      text: string;
      format: string;
      count: number;
      track: string;
      lang: string;
      skipped: number;
    }>('/api/cues/export', {
      method: 'POST',
      body: JSON.stringify({ format, track: opts.track ?? 'source', lang: opts.lang ?? '' }),
    }),

  /** 工作草稿：核对精修期间的全量暂存，不碰导出文件夹里的交付文件。 */
  getDraft: () => req<DraftInfo>('/api/cues/draft'),

  saveDraft: () => req<DraftInfo>('/api/cues/draft', { method: 'POST' }),

  restoreDraft: () =>
    req<CueSnapshot & { source: string }>('/api/cues/draft/restore', { method: 'POST' }),

  // ---- 报告 / 质检 ----
  // ---- 设置 / 引擎 / 诊断 ----
  getSettings: () => req<SettingsPayload>('/api/settings'),

  patchSettings: (patch: {
    enabled_engines?: string[];
    auto_proxy?: boolean;
    export_dir?: string;
    video_export_dir?: string;
  }) =>
    req<SettingsPayload>('/api/settings', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  downloadEngine: (key: string) =>
    req<JobSnapshot>(`/api/engines/${encodeURIComponent(key)}/download`, { method: 'POST' }),

  diagnostics: (lines = 200) =>
    req<{
      generated_at: number;
      runtime: SettingsPayload['runtime'];
      paths: SettingsPayload['paths'];
      ffmpeg: SettingsPayload['ffmpeg'];
      settings: AppSettings;
      engines: EngineInfo[];
      log_path: string;
      log_exists: boolean;
      log_bytes: number;
      log_tail: string;
      recent_problems: string[];
    }>(`/api/diagnostics?lines=${lines}`),

  diagnosticsLog: (lines = 300) =>
    req<{ path: string; exists: boolean; lines: number; text: string }>(
      `/api/diagnostics/log?lines=${lines}`,
    ),

  cleanLogs: () =>
    req<{ removed: number; freed: number; total_bytes: number; kept: number; log_dir: string }>(
      '/api/diagnostics/log/clean',
      { method: 'POST' },
    ),

  /** 清空全部日志（轮转活动日志 + 删除所有备份），设置页用。 */
  clearAllLogs: () =>
    req<{
      removed: number;
      freed: number;
      total_bytes: number;
      kept: number;
      log_dir: string;
      rotated: number;
    }>('/api/diagnostics/log/clear', { method: 'POST' }),

  // ---- 提示词模板 ----
  getPrompts: () => req<PromptLibrary>('/api/prompts'),

  createPrompt: (body: { name: string; description?: string; content: string }) =>
    req<PromptLibrary & { created: string }>('/api/prompts', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  updatePrompt: (
    id: string,
    body: { name?: string; description?: string; content?: string },
  ) =>
    req<PromptLibrary>(`/api/prompts/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  selectPrompt: (id: string) =>
    req<PromptLibrary>(`/api/prompts/${encodeURIComponent(id)}/select`, { method: 'POST' }),

  deletePrompt: (id: string) =>
    req<PromptLibrary>(`/api/prompts/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  resetPrompt: (id: string) =>
    req<PromptLibrary>(`/api/prompts/${encodeURIComponent(id)}/reset`, { method: 'POST' }),

  // ---- 成片导出 ----
  exportOptions: () =>
    req<{
      modes: { key: string; label: string; hint: string }[];
      presets: { key: string; label: string; factor: number; crf: number; hint: string }[];
      resolutions: { key: string; label: string }[];
    }>('/api/export/options'),

  exportStyles: () => req<ExportStyleOptions>('/api/export/styles'),

  /** 样式预览是 PNG，不能走 req()（它按 JSON 解析）。 */
  exportStylePreview: async (
    body: {
      media_id?: string;
      at?: number;
      text?: string;
      width?: number;
      height?: number;
      zoom?: boolean;
      track?: 'source' | 'target' | 'both';
      lang?: string;
      style: SubtitleStylePayload;
    },
    signal?: AbortSignal,
  ): Promise<Blob> => {
    const resp = await fetch(`${BASE}/api/export/style-preview`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${TOKEN}`,
        'X-Kikusub-Session': SID,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal,
    });
    if (!resp.ok) {
      let detail = `${resp.status} ${resp.statusText}`;
      try {
        const data = await resp.json();
        if (data && typeof data.detail === 'string') detail = data.detail;
      } catch {
        /* 非 JSON 错误体 */
      }
      logEvent(
        resp.status >= 500 ? 'error' : 'warn',
        'api-failed',
        `POST /api/export/style-preview -> ${resp.status}`,
        detail,
      );
      throw new ApiError(detail, resp.status);
    }
    return resp.blob();
  },

  exportPlan: (body: ExportJobPayload) =>
    req<{ plan: ExportPlan; out_dir: string; fonts_ok: boolean }>('/api/export/plan', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  createExport: (body: ExportJobPayload) =>
    req<JobSnapshot>('/api/export', { method: 'POST', body: JSON.stringify(body) }),

  getReport: (jobId?: string) =>
    req<ReportData & { job_id: string; media_id: string; out_filename: string; out_path: string }>(
      `/api/report${jobId ? `?job_id=${jobId}` : ''}`,
    ),

  getQa: () => req<Record<string, any>>('/api/qa'),

  /** 「一键复制提示词」：服务端用同一份 cues_to_srt 组好整段提示词 */
  getAiPrompt: (
    kind: 'translate' | 'polish' = 'translate',
    lang = 'zh-Hans',
    templateId = '',
  ) => {
    const q = new URLSearchParams({ kind, lang });
    if (templateId) q.set('template_id', templateId);
    return req<{
      prompt: string;
      count: number;
      lang: string;
      chars: number;
      template_id: string;
      template_name: string;
    }>(`/api/ai/prompt?${q}`);
  },

  /** 删除磁盘上的提案文件（「丢弃」用；只清界面不算丢弃） */
  deleteAiProposal: (kind: 'polish' | 'translate' = 'polish', lang = '') => {
    const q = new URLSearchParams({ kind });
    if (lang) q.set('lang', lang);
    return req<{ removed: boolean; path: string }>(`/api/ai/proposal?${q}`, { method: 'DELETE' });
  },

  /** 整轨替换译文文本（查找替换 - 全部替换）：条数必须与当前轨道一致。 */
  replaceTranslationTexts: (lang: string, texts: string[]) =>
    req<TranslationTrack>(`/api/translations/${encodeURIComponent(lang)}/replace`, {
      method: 'POST',
      body: JSON.stringify({ texts }),
    }),

  /** 改某一条译文（核对台「译文 / 双语」模式下直接编辑） */
  patchTranslation: (lang: string, index: number, text: string) =>
    req<TranslationTrack>(`/api/translations/${encodeURIComponent(lang)}/${index}`, {
      method: 'PATCH',
      body: JSON.stringify({ text }),
    }),

  /** 把粘贴回来的 SRT 解析成提案（只解析，不落盘、不改字幕） */
  aiFromSrt: (body: { kind: 'translate' | 'polish'; lang: string; text: string }) =>
    req<{ proposal: AiProposal; warnings: string[]; count: number }>('/api/ai/from-srt', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // ---- 译文平行轨 -----------------------------------------------------------
  getTranslations: () => req<TranslationsPayload>('/api/translations'),

  applyTranslation: (body: { lang: string; texts?: string[]; proposal?: AiProposal }) =>
    req<TranslationTrack>('/api/translations', { method: 'POST', body: JSON.stringify(body) }),

  /** 按路径导入译文 SRT / VTT；按时间对齐到当前原文时间轴。 */
  importTranslation: (path: string, lang: string) =>
    req<TranslationTrack & { path: string }>('/api/translations/import', {
      method: 'POST',
      body: JSON.stringify({ path, lang }),
    }),

  undoTranslation: (lang: string) =>
    req<TranslationTrack & { undone: boolean }>('/api/translations/undo', {
      method: 'POST',
      body: JSON.stringify({ lang }),
    }),

  deleteTranslation: (lang: string) =>
    req<{ lang: string; removed: boolean; count: number }>(
      `/api/translations/${encodeURIComponent(lang)}`,
      { method: 'DELETE' },
    ),

  // ---- 本机 TTS（系统 say / OmniVoice 克隆）--------------------------------
  ttsVoices: () => req<TtsVoicesPayload>('/api/tts/voices'),

  ttsStatus: () => req<TtsEngineInfo>('/api/tts/status'),

  synthesizeTts: (body: { text: string; voice_id?: string; speed?: number }) =>
    req<TtsResult>('/api/tts/synthesize', { method: 'POST', body: JSON.stringify(body) }),

  /** 从视频指定区间切一句参考音频，建立克隆音色。 */
  extractTtsVoice: (body: {
    media_id?: string;
    path?: string;
    start: number;
    end: number;
    name: string;
    text?: string;
    pad?: number;
  }) =>
    req<TtsVoiceInfo>('/api/tts/voices/extract-from-media', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  uploadTtsVoice: (body: { path: string; name: string; ref_text?: string }) =>
    req<TtsVoiceInfo>('/api/tts/voices/upload', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  renameTtsVoice: (voiceId: string, name: string) =>
    req<TtsVoiceInfo>(`/api/tts/voices/${encodeURIComponent(voiceId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    }),

  updateTtsRefText: (voiceId: string, refText: string) =>
    req<TtsVoiceInfo>(`/api/tts/voices/${encodeURIComponent(voiceId)}/ref-text`, {
      method: 'PUT',
      body: JSON.stringify({ ref_text: refText }),
    }),

  deleteTtsVoice: (voiceId: string) =>
    req<{ ok: boolean }>(`/api/tts/voices/${encodeURIComponent(voiceId)}`, {
      method: 'DELETE',
    }),

  downloadTtsModel: () =>
    req<TtsDownloadStatus>('/api/tts/model/download', { method: 'POST' }),

  ttsModelStatus: () => req<TtsDownloadStatus>('/api/tts/model/status'),

  /** 只读校验 OmniVoice 权重，不弹下载、不占任务槽。 */
  verifyTtsModel: () => req<TtsModelVerify>('/api/tts/model/verify'),

  // ---- AI 配置与生成 -------------------------------------------------------
  getAiConfig: () => req<AiConfig>('/api/ai/config'),

  patchAiConfig: (patch: Partial<{
    enabled: boolean;
    base_url: string;
    model: string;
    chunk_cues: number;
    translate_chunk_cues: number;
    context_cues: number;
  }>) => req<AiConfig>('/api/ai/config', { method: 'PATCH', body: JSON.stringify(patch) }),

  testAi: (payload: { base_url: string; model: string }, key: string) =>
    req<{ ok: boolean; latency_ms: number; model: string; host: string }>('/api/ai/test', {
      method: 'POST',
      body: JSON.stringify(payload),
      // 只在这一跳带上 key；它不落盘、不进日志
      headers: { 'X-AI-Key': key },
    }),

  createAiJob: (
    payload: {
      kind?: 'polish' | 'translate';
      base_url: string;
      model: string;
      chunk_cues: number;
      context_cues: number;
      lang: string;
      dst_lang?: string;
    },
    key: string,
  ) =>
    req<JobSnapshot>('/api/ai/jobs', {
      method: 'POST',
      body: JSON.stringify(payload),
      headers: { 'X-AI-Key': key },
    }),

  // ---- AI 提案（M1：读取 / 另存 / 应用）------------------------------------
  getAiProposal: (kind: 'polish' | 'translate' = 'polish', lang = '') => {
    const q = new URLSearchParams({ kind });
    if (lang) q.set('lang', lang);
    return req<AiProposalPayload>(`/api/ai/proposal?${q}`);
  },

  saveAiProposal: (proposal: AiProposal, kind: 'polish' | 'translate' = 'polish', lang = '') =>
    req<{ path: string; count: number; warnings: string[] }>('/api/ai/proposal', {
      method: 'POST',
      body: JSON.stringify({ kind, lang, proposal }),
    }),

  importAiProposal: (path: string, kind: 'polish' | 'translate' = 'polish', lang = '') =>
    req<{ path: string; from: string; count: number; warnings: string[] }>('/api/ai/proposal/import', {
      method: 'POST',
      body: JSON.stringify({ path, kind, lang }),
    }),

  applyAiProposal: (payload: {
    kind?: 'polish' | 'translate';
    lang?: string;
    accept?: number[] | null;
    edits?: Record<number, string>;
    proposal?: AiProposal;
  }) =>
    req<{
      cues: Cue[];
      count: number;
      can_undo: boolean;
      can_redo: boolean;
      changed: number;
      warnings: string[];
    }>('/api/ai/apply', { method: 'POST', body: JSON.stringify(payload) }),

  qaAction: (cmd: { id: string; action: string; status?: string; resolution?: string }) =>
    req<{
      ok: boolean;
      message: string;
      warning: string;
      cues_changed: boolean;
      focus: { index: number; start: string; end: string; text: string } | null;
      cues: Cue[];
      can_undo: boolean;
      can_redo: boolean;
      review_source?: ReviewSource | null;
      qa: Record<string, any>;
    }>('/api/qa/action', { method: 'POST', body: JSON.stringify(cmd) }),
};

export { ApiError };
