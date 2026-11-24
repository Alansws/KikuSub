/**
 * 服务层客户端。
 *
 * 端点由主进程通过握手注入（随机端口 + 一次性 token），所以这里不能有硬编码 URL。
 * 所有请求都带 `Authorization: Bearer`；`<video src>` 与 WebSocket 因为发不了自定义头，
 * 改走 `?token=`（与 `server/security.py` 的双通道一致）。
 */

import { vocalSeparation } from './vocalSeparation.svelte';

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
  /** 源视频平均帧率；纯音频 / 未知时缺省或 0（前端按 30fps 兜底）。 */
  video_fps?: number;
  has_video: boolean;
  needs_proxy: boolean;
  proxy_reason: string;
  proxy_ready: boolean;
  /** 代理文件版本（大小 + mtime）；重新导入代理后 URL 会带上它来避开缓存。 */
  proxy_version?: string;
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
  /** 推理运行时族：whisper / qwen / sherpa（服务端注册表给出）。 */
  family?: string;
  /** 能否做「另一引擎复核」（窗口直送模型，只回文本）。 */
  reviewable?: boolean;
  installed: boolean;
  size_bytes: number;
  enabled: boolean;
}

export interface AppSettings {
  enabled_engines: string[];
  /** 字幕默认导出目录；空字符串表示沿用应用输出目录。 */
  export_dir: string;
  /** 成片导出目录；空字符串表示跟随 export_dir。 */
  video_export_dir: string;
  /** 章节自动命名模板：`{num}` 中文数字 / `{n}` 阿拉伯数字，默认 `章节{num}`。 */
  chapter_name_template?: string;
}

export interface VadAsset {
  key: string;
  label: string;
  description: string;
  installed: boolean;
  model_dir: string;
  required_files: string[];
  approx_bytes: number;
  size_bytes: number;
}

export interface SettingsPayload {
  settings: AppSettings;
  engines: EngineInfo[];
  vad_assets: VadAsset[];
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
  /** polish_single / polish_dual / reshape_single / reshape_dual / translate；旧模板缺省按 translate。 */
  category?: 'polish_single' | 'polish_dual' | 'reshape_single' | 'reshape_dual' | 'translate';
  name: string;
  description: string;
  content: string;
  builtin: boolean;
  updated_at: number;
}

export interface PromptLibrary {
  version: number;
  /** 翻译分类的选中项（旧字段名保留）。 */
  selected: string;
  selected_polish_single: string;
  selected_polish_dual: string;
  selected_reshape_single?: string;
  selected_reshape_dual?: string;
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

/** 章节 / 时刻点标记：`end === null` 表示时刻点（结束于下一个标记或片尾）。 */
export interface ChapterMark {
  id: string;
  start: number;
  end: number | null;
  title: string;
}

export interface ChaptersPayload {
  marks: ChapterMark[];
  /** 实际写进容器的区间（已排序、已衔接 / 防重叠）。 */
  chapters: { start: number; end: number; start_ms: number; end_ms: number; title: string }[];
  count: number;
  duration: number;
  media_path: string;
  can_undo?: boolean;
  can_redo?: boolean;
  undo_label?: string;
  redo_label?: string;
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
  /** 本次导出会写入容器的章节（`write_chapters` 关闭时为空）。 */
  chapters?: { start: number; end: number; start_ms: number; end_ms: number; title: string }[];
  /** 片段导出信息；全片时为空对象。 */
  clip?: ClipInfo;
}

/** 片段范围（秒，原片时间）。`end <= 0` = 全片。 */
export interface ClipInfo {
  start: number;
  end: number;
  duration: number;
  label: string;
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
  /** 把章节 / 时刻点标记写进容器（默认开启）。 */
  write_chapters?: boolean;
  /** 片段导出（0 / 0 = 全片）：只导出这一段，字幕与章节平移到 0 起。 */
  clip_start?: number;
  clip_end?: number;
  /** 片段标签（章节标题）；空值由服务端按时间范围生成。 */
  clip_label?: string;
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
  /** 片段导出信息；全片时为空对象。 */
  clip?: ClipInfo;
}

export interface ParamSpec {
  key: string;
  label: string;
  engine: string;
  kind: 'bool' | 'float' | 'int' | 'enum';
  default: number | boolean | string;
  choices?: string[] | null;
  /** 枚举值的友好文案（值 → 展示）；缺省时直接用值。 */
  choice_labels?: Record<string, string> | null;
  group: string;
  min: number | null;
  max: number | null;
  step: number | null;
  help: string;
  is_config: boolean;
  /** 只对某个兄弟枚举值生效（如句首提前仅 Silero）；空/缺省 = 都生效。 */
  backend_only?: string | null;
  /** 按兄弟枚举值给出的校准提示（如 WhisperSeg 推荐阈值 0.35）。 */
  backend_notes?: Record<string, string> | null;
  /** 按兄弟枚举值给出的推荐数值；用于一键「采用推荐值」。 */
  backend_recommended?: Record<string, number> | null;
}

export interface Cue {
  start: number;
  end: number;
  text: string;
}

/** 当前核对表的来源。kind=transcription 才能引用该次转写的报告与质检。 */
export interface ReviewSource {
  kind: 'transcription' | 'import' | 'draft' | string;
  /** 产生这一版稿的引擎 key（whisper / qwen / sensevoice / firered）。 */
  engine?: string;
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
  /**
   * 「只动了句读」的原文改动被服务端静默对齐的译文下标：`{语种: [i…]}`。
   * 前端只就地改本地 base，不重拉译文轨（避免回灌正在编辑的输入框）。
   */
  rebased?: Record<string, number[]>;
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

/** 翻译时间轴对齐的一行状态（`i` 是全片 1 基序号）。 */
export interface AiAlignmentRow {
  i: number;
  /** ok = 正常对齐；merged = 合并覆盖；missing = 没匹配到译文。 */
  state: 'ok' | 'merged' | 'missing';
  text?: string;
  /** 起止任一端与原文的最大偏差（秒）；> 0.5 高亮。 */
  drift?: number;
  label?: string;
  /** 被并入哪一条（全片序号）；只有「被合并覆盖」的槽位有值。 */
  merged_into?: number | null;
  /** 这一条译文覆盖到哪一条（全片序号）；只有合并的主条目有值。 */
  merged_to?: number | null;
}

/** 翻译提案的时间轴对齐摘要：界面高亮与计数都用它。 */
export interface AiAlignment {
  from: number;
  to: number;
  /** 粘贴内容实际解析到的条数（可与原批不同）。 */
  pasted?: number;
  rows: AiAlignmentRow[];
  counts: {
    ok: number;
    merged: number;
    missing: number;
    drift: number;
    out_of_range: number;
  };
  warnings: string[];
}

/** AI 提案（`proposal.json`）。in-app 与外部 skill 产出的是同一份结构。 */
export interface AiProposal {
  version: number;
  kind: 'polish' | 'translate';
  src_lang: string;
  dst_lang?: string;
  source: {
    path: string;
    count: number;
    digest: string;
    /** 双源润色额外绑定第二版；单源提案没有这两个字段（向后兼容）。 */
    count_b?: number;
    digest_b?: string;
    /** 片段提案：作用范围（全片 1 基、含两端），i 仍是全片序号。 */
    range?: { from: number; to: number; count: number };
  };
  model?: string;
  entry?: string;
  created_at?: number;
  chunks?: number;
  glossary?: { src: string; dst: string }[];
  /** 翻译手动通道的时间轴对齐结果（严格模式关闭且条数不同时才有）。 */
  alignment?: AiAlignment;
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
  /** 单句判定模型覆盖；空串 = 该字段跟随全局。 */
  arbitrate_base_url: string;
  arbitrate_model: string;
  /** 本地 LM Studio 的上下文档位；只有点「加载 / 重载」时生效。 */
  local_context: number;
  /** 两版不一致时自动触发一次单句判定。 */
  auto_arbitrate: boolean;
  /** 当前地址是否本机/局域网：本地模型可以不带 Key。 */
  key_optional: boolean;
  arbitrate_key_optional: boolean;
  /** 判定目标是否本机 loopback（设置页据此探测 LM Studio）。 */
  arbitrate_loopback: boolean;
  /** 密钥不归服务层管；服务端只声明"由渲染进程持有" */
  key_held_by: string;
}

export interface LocalModelStatus {
  available: boolean;
  reason?: string;
  error?: string;
  loopback?: boolean;
  model?: string;
  loaded?: boolean;
  context_length?: number | null;
  max_context_length?: number | null;
}

export interface LocalModelLoadResult {
  ok: boolean;
  reloaded: boolean;
  model: string;
  context_length: number;
  load_time_seconds?: number | null;
}

export interface AiArbitrationHistoryItem {
  role: 'user' | 'assistant';
  text: string;
}

export interface AiArbitrationRequest {
  text_a: string;
  text_b: string;
  before: string[];
  after: string[];
  lang: string;
  /** 听音线索（空耳 / 罗马音 / 描述）；不是时间轴，也不是音频。 */
  hint?: string;
  /** 最近几轮追问；core 会再按轮数与字符预算裁剪。 */
  history?: AiArbitrationHistoryItem[];
}

export interface AiArbitrationResult {
  text: string;
  note: string;
  model: string;
  elapsed_ms: number;
}

/** 双引擎复核对齐后的一行。`kind` 对应 = / ~ / + / −。 */
export interface DualRow {
  kind: 'same' | 'diff' | 'only_a' | 'only_b';
  a_indices: number[];
  b_indices: number[];
  a_text: string;
  b_text: string;
  start: number;
  end: number;
  a_start: number | null;
  a_end: number | null;
  b_start: number | null;
  b_end: number | null;
  ratio: number;
  char_ops?: { op: 'eq' | 'del' | 'ins'; text: string }[];
  /** 两边只有标点 / 空白不同（服务端 ``ignore_punct`` 判为一致时的标记）。 */
  punct_only?: boolean;
}

export interface DualStats {
  total: number;
  same: number;
  diff: number;
  only_a: number;
  only_b: number;
  a_count: number;
  b_count: number;
  /** 被 ``ignore_punct`` 忽略的「仅标点 / 空白不同」行数（解释性统计）。 */
  punct_only: number;
  /** 侧栏徽标只统计 ~（文本不同）条数；`ignore_punct` 下已排除仅标点差异。 */
  badge: number;
}

export interface AltReviewPayload {
  exists: boolean;
  engine: string;
  count: number;
  source: Record<string, any>;
  created_at: number;
  cues: Cue[];
  media_path?: string;
  params?: Record<string, unknown>;
  rows: DualRow[];
  stats: DualStats | null;
  /** 服务端这次实际用的口径（``false`` = 标点也算差异）。 */
  ignore_punct?: boolean;
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
  total_count?: number;
  range?: { from: number; to: number } | null;
}

/** 结构建议（Phase 1）：外部模型只给 ops，本地绑定 digest/revision。 */
export interface StructureOpView {
  id: number;
  op: 'merge' | 'retime' | 'replace_text' | 'insert' | 'delete';
  reason: string;
  conflict: string[];
  before: string;
  after: string;
  text: string;
  old_start: number | null;
  old_end: number | null;
  new_start: number | null;
  new_end: number | null;
  index_label: string;
  from_index: number | null;
  to_index: number | null;
  after_index: number | null;
}

export interface StructureSummary {
  input_count: number;
  output_count: number;
  total_ops: number;
  conflicts: number;
  counts: Record<string, number>;
}

export interface StructurePayload {
  exists: boolean;
  path: string;
  revision: string;
  source: { path?: string; count: number; digest: string };
  current_count: number;
  digest_match: boolean;
  ops: StructureOpView[];
  warnings: string[];
  summary: StructureSummary;
}

export interface StructureApplyPayload extends CueSnapshot {
  changed: number;
  applied: number;
  output_count: number;
}

/** 断句重排（整份换稿）：一条行内提示，`index` 是新稿里的 1-based 行号。 */
export interface ReshapeIssue {
  index: number;
  kind: 'overlap' | 'out_of_order' | 'too_long' | 'too_short' | 'out_of_range' | 'empty_text';
  label: string;
}

export interface ReshapeNote {
  text: string;
  level: 'plain' | 'warn';
}

export interface ReshapeDiagnostics {
  count: number;
  count_before: number;
  chars: number;
  span: { start: number; end: number };
  issues: ReshapeIssue[];
  totals: Record<string, number>;
  identical: boolean;
}

/** 解析粘贴 SRT 的结果：整份新稿 + 体检 + 覆盖区间 + 源指纹。 */
export interface ReshapeDraft {
  format: 'srt';
  cues: Cue[];
  diagnostics: ReshapeDiagnostics;
  notes: ReshapeNote[];
  digest: string;
  range: { from: number; to: number; start: number; end: number; full: boolean };
}

export interface ReshapeReplaceInfo {
  from: number;
  to: number;
  replaced: number;
  inserted: number;
  count: number;
  count_before: number;
  changed: boolean;
  dropped_translations: string[];
  /** 局部重排后跟着平移的译文轨（范围外头部 / 尾部保持对齐）。 */
  shifted_translations?: string[];
}

export interface ReshapeApplyPayload extends CueSnapshot {
  replace: ReshapeReplaceInfo;
}

export interface ReshapePromptPayload {
  prompt: string;
  count: number;
  total: number;
  chars: number;
  mode: 'single' | 'dual';
  from: number;
  to: number;
  alt_count: number;
  template_id: string;
  template_name: string;
  category: string;
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
    /** 纯喘息/笑声/拟声：已从字幕移除，但进了质检队列（P0）。 */
    nonverbal?: number;
    degraded: number;
    has_findings: boolean;
    qwen_limited: boolean;
    /** whisper / qwen / sherpa：决定对齐文案用「逐字对齐」还是「token 时间戳」。 */
    engine_family?: string;
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

/**
 * 媒体流地址。
 *
 * `proxy=true` 时走 480p 监看代理——Chromium 解不开 MKV / HEVC，
 * 原片直接喂给 `<video>` 只会黑屏。
 */
export function mediaUrl(mediaId: string, proxy = false, version = '') {
  const q = new URLSearchParams({ token: TOKEN });
  if (proxy) {
    q.set('proxy', '1');
    // 重新导入代理后文件内容变了但路径没变；带上版本号让 <video> 真正换源。
    if (version) q.set('v', version);
  }
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
        defaults: Record<string, number | boolean | string>;
      }[];
    }>('/api/params'),

  // ---- 预设 ----
  listPresets: (engine?: string) => {
    const q = engine ? `?engine=${encodeURIComponent(engine)}` : '';
    return req<{ items: { name: string; engine: string | null }[]; load_error: string }>(
      `/api/presets${q}`,
    );
  },

  getPreset: (name: string, engine: string) =>
    req<{ name: string; engine: string | null; values: Record<string, number | boolean | string> }>(
      `/api/presets/${encodeURIComponent(name)}?engine=${encodeURIComponent(engine)}`,
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
    kind?: 'transcribe' | 'dual';
    engine: string;
    secondary_engine?: string;
    secondary_params?: Record<string, unknown>;
    output_format?: string;
    save_beside?: boolean;
    start?: number | null;
    end?: number | null;
    keep_absolute_timeline?: boolean;
    apply?: 'replace' | 'append' | 'replace_range';
    alt_review?: boolean;
    separate_vocals?: boolean;
    separate_mode?: 'vad_only' | 'to_asr';
    params?: Record<string, unknown>;
  }) =>
    req<JobSnapshot>('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({
        ...payload,
        // 全局勾选对整片与区间都生效：整片由服务端按 0..总时长分离。
        separate_vocals: payload.separate_vocals ?? (vocalSeparation.enabled || undefined),
        // 默认只给 VAD 用分离人声；高级档才把分离人声送去识别。
        separate_mode: payload.separate_mode ?? vocalSeparation.mode,
      }),
    }),

  /** 用另一个引擎把若干字幕窗口各听一遍；服务端只回文本、不落盘。 */
  createCompareJob: (payload: {
    media_id: string;
    engine: string;
    ranges: Array<{
      index: number;
      start: number;
      end: number;
      prev_end?: number;
      next_start?: number;
    }>;
    params?: Record<string, unknown>;
  }) => req<JobSnapshot>('/api/jobs', { method: 'POST', body: JSON.stringify({ ...payload, kind: 'compare' }) }),

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

  getChapters: () => req<ChaptersPayload>('/api/chapters'),

  /** 整表保存章节（一步历史）。label 决定历史面板里显示「做了什么」。 */
  saveChapters: (body: { marks: ChapterMark[]; label: string }) =>
    req<ChaptersPayload>('/api/chapters', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

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

  /** `label` 写进统一历史（复核页「采用 B 句」用它，⌘Z 提示才说得清）。 */
  patchCue: (index: number, patch: Partial<Cue>, label = '') =>
    req<CueSnapshot>(`/api/cues/${index}`, {
      method: 'PATCH',
      body: JSON.stringify({ ...patch, label }),
    }),

  deleteCue: (index: number) =>
    req<CueSnapshot & { removed: number }>(`/api/cues/${index}`, { method: 'DELETE' }),

  /** 批量删除（底部轨道 ⌘ 多选）：一次历史，译文轨同步。 */
  deleteCues: (indices: number[]) =>
    req<CueSnapshot & { removed: number }>('/api/cues/delete', {
      method: 'POST',
      body: JSON.stringify({ indices }),
    }),

  /** 在指定下标插入一条（右键「添加字幕」/空字幕补录 / 粘贴字幕）。 */
  insertCue: (
    index: number,
    cue: Cue & {
      label?: string;
      /** lang -> 该语种译文与生成时的原文快照；只写当前会话已有的轨。 */
      translations?: Record<string, { text: string; base: string }>;
    },
  ) =>
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
    opts: {
      track?: TrackMode;
      lang?: string;
      clipStart?: number;
      clipEnd?: number;
      clipLabel?: string;
    } = {},
  ) =>
    req<{
      path: string;
      name: string;
      requested_name: string;
      /** 同名文件已有不同内容时，服务端自动改名为 `… (2).srt`。 */
      renamed: boolean;
      text: string;
      format: string;
      count: number;
      track: string;
      lang: string;
      clip: string | null;
      skipped: number;
    }>('/api/cues/export', {
      method: 'POST',
      body: JSON.stringify({
        format,
        track: opts.track ?? 'source',
        lang: opts.lang ?? '',
        clip_start: opts.clipStart ?? 0,
        clip_end: opts.clipEnd ?? 0,
        clip_label: opts.clipLabel ?? '',
      }),
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
    export_dir?: string;
    video_export_dir?: string;
    chapter_name_template?: string;
  }) =>
    req<SettingsPayload>('/api/settings', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  downloadEngine: (key: string) =>
    req<JobSnapshot>(`/api/engines/${encodeURIComponent(key)}/download`, { method: 'POST' }),

  downloadVadAsset: (key: string) =>
    req<JobSnapshot>(`/api/vad/assets/${encodeURIComponent(key)}/download`, {
      method: 'POST',
    }),

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

  createPrompt: (body: {
    name: string;
    description?: string;
    content: string;
    category?:
      | 'polish_single'
      | 'polish_dual'
      | 'reshape_single'
      | 'reshape_dual'
      | 'translate';
  }) =>
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

  selectPrompt: (id: string, category = '') =>
    req<PromptLibrary>(
      `/api/prompts/${encodeURIComponent(id)}/select${category ? `?category=${encodeURIComponent(category)}` : ''}`,
      { method: 'POST' },
    ),

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
    opts: {
      mode?: 'single' | 'dual';
      from?: number;
      to?: number;
      rangeFrom?: number;
      rangeTo?: number;
    } = {},
  ) => {
    const q = new URLSearchParams({ kind, lang });
    if (templateId) q.set('template_id', templateId);
    if (opts.mode) q.set('mode', opts.mode);
    if (opts.from !== undefined) q.set('from_index', String(opts.from));
    if (opts.to !== undefined) q.set('to_index', String(opts.to));
    if (opts.rangeFrom !== undefined) q.set('range_from', String(opts.rangeFrom));
    if (opts.rangeTo !== undefined) q.set('range_to', String(opts.rangeTo));
    return req<{
      prompt: string;
      count: number;
      total?: number;
      lang: string;
      chars: number;
      mode?: 'single' | 'dual';
      from?: number;
      to?: number;
      range_from?: number;
      range_to?: number;
      category?: string;
      template_id: string;
      template_name: string;
    }>(`/api/ai/prompt?${q}`);
  },

  // ---- 双引擎复核（第二版）-----------------------------------------------
  /**
   * 第二版摘要 / 差异行。
   *
   * `ignorePunct` 默认开：只有标点 / 空白不同的行由服务端判为一致，
   * 不计入 `~ 文本不同` 与侧栏徽标（`core.dual_review.build_review`）。
   */
  getAltReview: (diff = false, ignorePunct = true) => {
    const q = new URLSearchParams();
    if (diff) q.set('diff', '1');
    q.set('ignore_punct', ignorePunct ? '1' : '0');
    return req<AltReviewPayload>(`/api/alt-review?${q}`);
  },

  deleteAltReview: () => req<{ removed: boolean; exists: boolean }>('/api/alt-review', { method: 'DELETE' }),

  /** 把工作流里已经做好的另一版字幕直接导入第二列（与转写产出的 B 版同构）。 */
  importAltReview: (path: string) =>
    req<{
      exists: boolean;
      engine: string;
      count: number;
      source: Record<string, any>;
      created_at: number;
      warning: string;
    }>('/api/alt-review/import', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),

  replacePrimaryWithAlt: (clearAlt = true) =>
    req<CueSnapshot & { replaced: number; alt_cleared: boolean }>(
      '/api/alt-review/replace-primary',
      { method: 'POST', body: JSON.stringify({ clear_alt: clearAlt }) },
    ),

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
  aiFromSrt: (body: {
    kind: 'translate' | 'polish';
    lang: string;
    text: string;
    from_index?: number;
    to_index?: number;
    range_from?: number;
    range_to?: number;
    mode?: 'single' | 'dual';
    /** 翻译：false = 允许条数不同，按时间轴区间交集对齐（默认页面行为）。 */
    strict_count?: boolean;
  }) =>
    req<{
      proposal: AiProposal;
      warnings: string[];
      count: number;
      mode?: 'single' | 'dual';
      from?: number;
      to?: number;
      range_from?: number;
      range_to?: number;
      expected?: number;
      alignment?: AiAlignment | null;
    }>('/api/ai/from-srt', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // ---- 译文平行轨 -----------------------------------------------------------
  getTranslations: () => req<TranslationsPayload>('/api/translations'),

  applyTranslation: (body: { lang: string; texts?: string[]; proposal?: AiProposal }) =>
    req<TranslationTrack & { partial?: boolean; applied?: number; range?: { from: number; to: number } }>(
      '/api/translations',
      { method: 'POST', body: JSON.stringify(body) },
    ),

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
    arbitrate_base_url: string;
    arbitrate_model: string;
    local_context: number;
    auto_arbitrate: boolean;
  }>) => req<AiConfig>('/api/ai/config', { method: 'PATCH', body: JSON.stringify(patch) }),

  localModelStatus: () => req<LocalModelStatus>('/api/ai/local-model/status'),

  loadLocalModel: (context: number) =>
    req<LocalModelLoadResult>('/api/ai/local-model/load', {
      method: 'POST',
      body: JSON.stringify({ context }),
    }),

  arbitrateAi: (
    payload: AiArbitrationRequest,
    opts: {
      globalKey: string;
      arbitrateKey?: string;
      useArbitrate: boolean;
      signal?: AbortSignal;
    },
  ) =>
    req<AiArbitrationResult>('/api/ai/arbitrate', {
      method: 'POST',
      body: JSON.stringify(payload),
      headers: {
        'X-AI-Key': opts.globalKey,
        ...(opts.useArbitrate ? { 'X-AI-Arbitrate-Key': opts.arbitrateKey || '' } : {}),
      },
      signal: opts.signal,
    }),

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
      mode?: 'single' | 'dual';
      /** 处理范围（1 基、含两端）：只生成这一段的提案。 */
      from_index?: number;
      to_index?: number;
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


  // ---- 结构建议（Phase 1：合并 / 改时间 / 改文字 / 新增 / 删除）------------
  getStructure: () => req<StructurePayload>('/api/ai/structure'),

  parseStructure: (text: string) =>
    req<StructurePayload>('/api/ai/structure/from-json', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),

  applyStructure: (payload: { accept: number[]; revision: string }) =>
    req<StructureApplyPayload>('/api/ai/structure/apply', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  deleteStructure: () =>
    req<{ removed: boolean; path: string }>('/api/ai/structure', { method: 'DELETE' }),

  getStructurePrompt: (mode: 'single' | 'dual' = 'single') =>
    req<{ prompt: string; count: number; chars: number; mode: string; alt_count: number }>(
      `/api/ai/structure/prompt?mode=${mode}`,
    ),

  // ---- 断句重排（整份换稿：条数与时间码都可变）----------------------------
  getReshapePrompt: (
    mode: 'single' | 'dual',
    from = 1,
    to: number | null = null,
    templateId = '',
  ) => {
    const query = new URLSearchParams({
      mode,
      from_index: String(from),
    });
    if (to !== null) query.set('to_index', String(to));
    if (templateId) query.set('template_id', templateId);
    return req<ReshapePromptPayload>(`/api/ai/reshape/prompt?${query.toString()}`);
  },

  parseReshape: (text: string, from: number, to: number | null) =>
    req<ReshapeDraft>('/api/ai/reshape/from-text', {
      method: 'POST',
      body: JSON.stringify({ text, from_index: from, to_index: to }),
    }),

  applyReshape: (payload: {
    cues: Cue[];
    from_index: number;
    to_index: number | null;
    digest: string;
    label?: string;
  }) =>
    req<ReshapeApplyPayload>('/api/ai/reshape/apply', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** 四类提案文件的存在性/版本（2 秒轮询用；只 stat，不拉正文）。 */
  proposalStatus: () =>
    req<{
      media_stem: string;
      revision: string;
      items: {
        kind: 'polish' | 'translate' | 'structure' | 'reshape';
        lang: string;
        path: string;
        name: string;
        mtime: number;
        mtime_ns: number;
        size: number;
      }[];
    }>('/api/proposals/status'),

  /** 外部 agent 落盘的断句重排提案（只读预览；应用仍走 /apply）。 */
  getReshapeProposal: () =>
    req<{
      path: string;
      stale: boolean;
      source: Record<string, any>;
      cues: Cue[];
      text: string;
      diagnostics: Record<string, any>;
      notes: string[];
      range: { from: number; to: number; total: number };
    }>('/api/ai/reshape/proposal'),

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
