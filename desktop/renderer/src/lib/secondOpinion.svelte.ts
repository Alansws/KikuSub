/**
 * 第二引擎复核的状态机（P1-1 段二）。
 *
 * 为什么单开一个模块而不是塞进 `store.svelte.ts`：那个文件有行数预算（只许变短），
 * 而复核状态只属于「当前条目 / 质检条目」这一小块界面，不值得让全应用共享。
 * 这里只依赖 store 暴露的 `app` / `play` / `updateCue` / `toast`，不反向被 store 依赖。
 *
 * 关键约定：
 * - **不自动采用**：结果只放在 `texts` 里，采用要用户点；
 * - **采用走现有历史**：`updateCue()` → 服务端压一步统一历史，可撤销；
 * - **收起不改质检状态**：dismiss 只清本地卡片，质检条目要处理仍走它自己的按钮。
 */

import { api, type JobEvent } from './api';
import { app, toast, updateCue } from './store.svelte';
import { buildRanges, cueIndexForRange, otherEngineKey } from './secondOpinion';

export type SecondOpinionStatus = 'idle' | 'running' | 'done' | 'error';

export const secondOpinion = $state({
  status: 'idle' as SecondOpinionStatus,
  /** 本次复核用的引擎 key（另一个引擎）。 */
  engine: '',
  jobId: '',
  ratio: 0,
  stage: '',
  /** 字幕下标 → 另一引擎给出的文本。 */
  texts: {} as Record<number, string>,
  /** 发起时的下标（「再听一次」用它）。 */
  requested: [] as number[],
  error: '',
  /** 本次复核属于哪一条字幕（卡片跟着它显示；切换选中时不清空）。 */
  index: -1,
});

function engineLabel(key: string): string {
  const fromConfig = app.config?.engines?.find((engine) => engine.key === key);
  return fromConfig?.label || (key === 'qwen' ? 'Qwen3-ASR' : 'Anime Whisper');
}

function engineEnabled(key: string): boolean {
  const fromSettings = app.settings?.enabled_engines;
  if (Array.isArray(fromSettings)) return fromSettings.includes(key);
  return app.config?.engines.some((engine) => engine.key === key && engine.enabled) ?? true;
}

/** 当前可用的「另一引擎」；不可用时返回空串，UI 据此禁用按钮。 */
export function availableEngine(): string {
  const key = otherEngineKey(app.engine);
  return engineEnabled(key) ? key : '';
}

export function availableEngineLabel(): string {
  const key = availableEngine();
  return key ? engineLabel(key) : '';
}

export function currentEngineLabel(): string {
  return engineLabel(app.engine);
}

/** 某条是否已有备选文本（用于决定卡片是否展开）。 */
export function hasAlternative(index: number): boolean {
  return typeof secondOpinion.texts[index] === 'string';
}

export function alternativeText(index: number): string {
  return secondOpinion.texts[index] ?? '';
}

function reset(): void {
  secondOpinion.status = 'idle';
  secondOpinion.engine = '';
  secondOpinion.jobId = '';
  secondOpinion.ratio = 0;
  secondOpinion.stage = '';
  secondOpinion.texts = {};
  secondOpinion.requested = [];
  secondOpinion.error = '';
  secondOpinion.index = -1;
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
    const next: Record<number, string> = {};
    for (const item of texts) {
      if (typeof item?.index === 'number') next[item.index] = item.text ?? '';
    }
    secondOpinion.texts = next;
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
  const engine = availableEngine();
  if (!engine) {
    toast(`另一个引擎（${engineLabel(otherEngineKey(app.engine))}）已停用：到「设置 → 引擎与模型」里启用`, 'warn');
    return;
  }
  const ranges = buildRanges(app.cues, indices);
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
  const text = secondOpinion.texts[index];
  if (text === undefined) return;
  await updateCue(index, { text });
  const rest: Record<number, string> = { ...secondOpinion.texts };
  delete rest[index];
  secondOpinion.texts = rest;
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
