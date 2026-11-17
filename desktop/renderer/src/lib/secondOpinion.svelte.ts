/**
 * 第二引擎复核的状态机（P1-1 段二）。
 *
 * 为什么单开一个模块而不是塞进 `store.svelte.ts`：那个文件有行数预算（只许变短），
 * 而复核状态只属于「当前条目 / 质检条目」这一小块界面，不值得让全应用共享。
 * 这里只依赖 store 暴露的 `app` / `updateCue` / `toast`，不反向被 store 依赖
 * （开发种子注入在 `lib/devSeed.ts`，同样只单向依赖）。
 *
 * 关键约定：
 * - **不自动采用**：结果只放在 `records` 里，采用要用户点；
 * - **采用走现有历史**：`updateCue()` → 服务端压一步统一历史，可撤销；
 * - **收起不改质检状态**：dismiss 只清本地卡片，质检条目要处理仍走它自己的按钮。
 */

import { api, type JobEvent } from './api';
import { app, toast, updateCue } from './store.svelte';
import {
  MAX_BATCH,
  buildRanges,
  cueIndexForRange,
  pickReviewEngine,
  sharesLanguage,
  type ReviewEngineChoice,
} from './secondOpinion';

export type SecondOpinionStatus = 'idle' | 'running' | 'done' | 'error';

export const secondOpinion = $state({
  status: 'idle' as SecondOpinionStatus,
  /** 本次复核用的引擎 key（另一个引擎）。 */
  engine: '',
  jobId: '',
  ratio: 0,
  stage: '',
  /**
   * 字幕下标 → { 这条字幕当时的起止时间, 另一引擎的文本 }。
   * 记时间是为了防止「删掉一条之后下标整体前移」时把备选安到错句上：
   * 采用前会核对当前这条的起止时间，对不上就当没有。
   */
  records: {} as Record<number, { start: number; end: number; text: string }>,
  /** 发起时的下标（「再听一次」用它）。 */
  requested: [] as number[],
  error: '',
  /** 本次复核属于哪一条字幕（卡片跟着它显示；切换选中时不清空）。 */
  index: -1,
});

/** 复核引擎的持久化偏好（纯界面状态，跟 TTS 音色一样留在渲染层）。 */
const REVIEW_ENGINE_KEY = 'kikusub.secondOpinionEngine';

function initialReviewEngine(): string {
  try {
    return localStorage.getItem(REVIEW_ENGINE_KEY) || '';
  } catch {
    /* 隐私模式 / 存储不可用时按未选择处理 */
  }
  return '';
}

const reviewEngine = $state({ preferred: initialReviewEngine() });

export interface ReviewEngineCandidate extends ReviewEngineChoice {
  /** 工具栏 / 下拉里用的短名（与引擎卡的显示口径一致）。 */
  shortLabel: string;
  /** 与当前稿共享的语种（仅用于界面上解释为什么它出现在这里）。 */
  languages: string[];
}

function engineLabel(key: string): string {
  const fromConfig = app.config?.engines?.find((engine) => engine.key === key);
  if (fromConfig) return fromConfig.label;
  if (key === 'qwen') return 'Qwen3-ASR';
  if (key === 'whisper') return 'Anime Whisper';
  return key || '';
}

function engineShortLabel(key: string): string {
  const fromConfig = app.config?.engines?.find((engine) => engine.key === key);
  if (fromConfig?.short_label) return fromConfig.short_label;
  if (key === 'qwen') return 'Qwen3';
  if (key === 'whisper') return 'Whisper';
  return engineLabel(key);
}

function engineEnabled(key: string): boolean {
  const fromSettings = app.settings?.enabled_engines;
  if (Array.isArray(fromSettings)) return fromSettings.includes(key);
  return app.config?.engines.some((engine) => engine.key === key && engine.enabled) ?? true;
}

/**
 * 当前稿是哪个引擎转的。
 *
 * 优先 `review_source.engine`：用户可能在转写页把引擎切成了别的，但核对台这张
 * 稿还是上一个引擎的——「另一引擎」要相对**这张稿**，不是相对下拉框。
 * 导入稿识别不出引擎时退回转写页当前选择，与旧行为一致。
 */
export function currentEngineKey(): string {
  return String(app.reviewSource?.engine || '') || app.engine;
}

export function currentEngineLabel(): string {
  const fromSource = String(app.reviewSource?.engine || '');
  if (
    !fromSource &&
    (app.reviewSource?.kind === 'import' || app.reviewSource?.kind === 'draft')
  ) {
    // 导入 / 草稿识别不出引擎时不要假冒转写页当前选择。
    return '当前稿';
  }
  return engineLabel(fromSource || app.engine);
}

export function currentEngineShortLabel(): string {
  const fromSource = String(app.reviewSource?.engine || '');
  if (
    !fromSource &&
    (app.reviewSource?.kind === 'import' || app.reviewSource?.kind === 'draft')
  ) {
    return '当前稿';
  }
  return engineShortLabel(fromSource || app.engine);
}

/**
 * 可选的复核引擎：注册表标了 `reviewable`、不是当前稿的引擎、且与当前稿共享语种。
 *
 * 未下载 / 已停用的也会返回（界面置灰并说明），否则用户只看到「没有引擎」却
 * 不知道差的是什么。
 */
export function reviewEngineCandidates(): ReviewEngineCandidate[] {
  const current = currentEngineKey();
  const engines = app.config?.engines ?? [];
  // 只看当前稿的**主语种**（注册表 languages[0]）：SenseVoice 同时会日语，但它是
  // 中文稿时不该把日语引擎当成「同语种」推荐——两边都听不清对方在说什么。
  const primary = engines.find((engine) => engine.key === current)?.languages?.[0] ?? '';
  return engines
    .filter(
      (engine) =>
        Boolean(engine.reviewable) &&
        engine.key !== current &&
        sharesLanguage(primary ? [primary] : undefined, engine.languages),
    )
    .map((engine) => ({
      key: engine.key,
      label: engine.label,
      shortLabel: engineShortLabel(engine.key),
      enabled: engineEnabled(engine.key),
      installed: Boolean(engine.installed),
      languages: engine.languages ?? [],
    }));
}

/** 真正可用的复核引擎；空串表示没有（按钮禁用）。 */
export function selectedReviewEngine(): string {
  return pickReviewEngine(reviewEngineCandidates(), currentEngineKey(), reviewEngine.preferred);
}

export function selectedReviewEngineLabel(): string {
  const key = selectedReviewEngine();
  return key ? engineLabel(key) : '';
}

export function selectedReviewEngineShortLabel(): string {
  const key = selectedReviewEngine();
  return key ? engineShortLabel(key) : '';
}

/** 用户在下拉里改「另一引擎」。只接受候选里的引擎，避免落进一个不可用的 key。 */
export function setReviewEngine(key: string): void {
  if (!reviewEngineCandidates().some((engine) => engine.key === key)) return;
  reviewEngine.preferred = key;
  try {
    localStorage.setItem(REVIEW_ENGINE_KEY, key);
  } catch {
    /* 存不下不影响本次使用 */
  }
}

/** 本次结果由哪个引擎给出（切换下拉后，已出的结果仍然属于旧引擎）。 */
export function resultEngineLabel(): string {
  return secondOpinion.engine ? engineLabel(secondOpinion.engine) : '';
}

function reset(): void {
  secondOpinion.status = 'idle';
  secondOpinion.engine = '';
  secondOpinion.jobId = '';
  secondOpinion.ratio = 0;
  secondOpinion.stage = '';
  secondOpinion.records = {};
  secondOpinion.requested = [];
  secondOpinion.error = '';
  secondOpinion.index = -1;
  // 注意：不重置 reviewEngine.preferred——那是用户跨这次复核记住的选择。
}

function matchingRecord(index: number): { start: number; end: number; text: string } | null {
  const record = secondOpinion.records[index];
  const cue = app.cues[index];
  if (!record || !cue) return null;
  if (Math.abs(cue.start - record.start) > 1e-6 || Math.abs(cue.end - record.end) > 1e-6) {
    return null;  // 下标对应的已经不是同一条字幕（删除 / 重排 / 改时间）
  }
  return record;
}

/** 某条是否已有备选文本（用于决定卡片是否展开）。 */
export function hasAlternative(index: number): boolean {
  return matchingRecord(index) !== null;
}

export function alternativeText(index: number): string {
  return matchingRecord(index)?.text ?? '';
}

function onEvent(event: JobEvent): void {
  if (event.type === 'progress') {
    secondOpinion.ratio = Math.max(secondOpinion.ratio, event.ratio ?? 0);
    if (event.stage) secondOpinion.stage = event.stage;
    return;
  }
  if (event.type === 'start' && event.job?.stage) {
    secondOpinion.stage = event.job.stage;
    return;
  }
  if (event.type === 'done') {
    const texts = (event.job?.result?.texts ?? []) as Array<{ index: number; text: string }>;
    const next: Record<number, { start: number; end: number; text: string }> = {};
    for (const item of texts) {
      const cue = app.cues[item?.index ?? -1];
      if (typeof item?.index === 'number' && cue) {
        next[item.index] = { start: cue.start, end: cue.end, text: item.text ?? '' };
      }
    }
    secondOpinion.records = next;
    secondOpinion.status = 'done';
    secondOpinion.ratio = 1;
    secondOpinion.stage = '';
    return;
  }
  if (event.type === 'error') {
    secondOpinion.status = 'error';
    secondOpinion.error = event.message || '复核失败';
    return;
  }
  if (event.type === 'cancelled') {
    reset();
  }
}

/** 对若干字幕发起复核（单条时 `indices` 只有一个元素）。 */
export async function runSecondOpinion(indices: number[]): Promise<void> {
  if (!app.media) {
    toast('请先导入媒体', 'warn');
    return;
  }
  if (!app.cues.length) {
    toast('当前没有字幕可复核', 'warn');
    return;
  }
  const engine = selectedReviewEngine();
  if (!engine) {
    const candidates = reviewEngineCandidates();
    if (!candidates.length) {
      toast(
        `「${currentEngineKey()}」没有可复核的同语种引擎：到「设置 → 引擎与模型」启用另一个引擎`,
        'warn',
      );
    } else {
      const names = candidates.map((item) => item.label).join(' / ');
      toast(`复核引擎还没就绪（${names}）：到「设置 → 引擎与模型」启用并下载模型`, 'warn');
    }
    return;
  }
  if (indices.length > MAX_BATCH) {
    toast(`一次最多复核 ${MAX_BATCH} 条，已取前 ${MAX_BATCH} 条`, 'warn');
  }
  const ranges = buildRanges(app.cues, indices.slice(0, MAX_BATCH));
  if (!ranges.length) {
    toast('没有可复核的字幕', 'warn');
    return;
  }
  // 先清上一次的结果，避免「点了新的，卡片还显示旧的」。
  const first = ranges[0].index;
  reset();
  secondOpinion.engine = engine;
  secondOpinion.requested = ranges.map((range) => range.index);
  secondOpinion.index = first;
  secondOpinion.status = 'running';
  secondOpinion.stage = `正在准备 ${engineLabel(engine)}…`;
  try {
    const job = await api.createCompareJob({
      media_id: app.media.id,
      engine,
      ranges,
    });
    secondOpinion.jobId = job.id;
    api.streamJob(
      job.id,
      onEvent,
      () => {
        // WS 关了但没收到终态事件：拉一次快照兜底，避免卡片永远停在「正在复核」。
        if (secondOpinion.status === 'running' && secondOpinion.jobId) {
          void api
            .getJob(secondOpinion.jobId)
            .then((snapshot) => {
              if (snapshot.result) {
                onEvent({ type: 'done', job: snapshot });
              } else if (snapshot.error) {
                onEvent({ type: 'error', message: snapshot.error });
              }
            })
            .catch(() => {
              secondOpinion.status = 'error';
              secondOpinion.error = '复核任务中断（连接已断开）';
            });
        }
      },
    );
  } catch (err) {
    secondOpinion.status = 'error';
    const message = (err as Error).message || '复核失败';
    secondOpinion.error =
      message.includes('409') || message.includes('任务') ? `${message}（等当前任务结束再复核）` : message;
  }
}

/** 再听一遍：用上次的下标重跑。 */
export function retrySecondOpinion(): void {
  const indices = secondOpinion.requested;
  if (!indices.length) return;
  void runSecondOpinion(indices);
}

export async function cancelSecondOpinion(): Promise<void> {
  if (!secondOpinion.jobId) {
    reset();
    return;
  }
  try {
    await api.cancelJob(secondOpinion.jobId);
  } catch (err) {
    toast((err as Error).message, 'warn');
  }
}

/** 采用备选文本：走既有的 updateCue（服务端记一步历史，可撤销）。 */
export async function adoptAlternative(index = secondOpinion.index): Promise<void> {
  const record = matchingRecord(index);
  if (!record) return;
  await updateCue(index, { text: record.text });
  const rest = { ...secondOpinion.records };
  delete rest[index];
  secondOpinion.records = rest;
  toast('已采用另一引擎的文本（可撤销）');
  if (secondOpinion.index === index || !Object.keys(rest).length) {
    secondOpinion.status = 'idle';
    secondOpinion.index = -1;
  }
}

/** 收起卡片：只清本地状态，不改任何字幕与质检状态。 */
export function dismissAlternative(): void {
  reset();
}

/** 质检条目 → 字幕下标（没有对应字幕时返回 -1）。 */
export function cueIndexForItem(start: number, end: number): number {
  return cueIndexForRange(app.cues, start, end);
}

export function itemAlternativeText(start: number, end: number): string {
  const index = cueIndexForItem(start, end);
  return index >= 0 ? alternativeText(index) : '';
}

/**
 * 仅开发截图用：灌一份假的复核结果。
 *
 * 复核要加载另一个引擎（冷启动 20–40 秒），为了看卡片动效/对齐不值得真跑模型；
 * `applyDevSeed()` 只在 `KIKUSUB_DEV_SEED` 存在时调用它，打包后永远走不到。
 */
export function applyDevSecondOpinion(seed: {
  engine?: string;
  index?: number;
  text?: string;
}): void {
  const index = Number(seed?.index ?? 0);
  const cue = app.cues[index];
  if (!cue) return;
  reset();
  secondOpinion.engine = seed?.engine || selectedReviewEngine() || 'qwen';
  secondOpinion.records = {
    [index]: { start: cue.start, end: cue.end, text: String(seed?.text ?? '') },
  };
  secondOpinion.requested = [index];
  secondOpinion.index = index;
  secondOpinion.status = 'done';
  secondOpinion.ratio = 1;
  secondOpinion.stage = '';
}
