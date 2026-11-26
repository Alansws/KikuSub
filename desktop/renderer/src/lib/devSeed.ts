/**
 * 开发用种子注入（`KIKUSUB_DEV_SEED`）：把主进程注入的媒体 + 字幕灌进当前会话。
 *
 * 为什么从 `store.svelte.ts` 抽出来：store 有 3315 行的体积预算（只许变短，见
 * `tests/test_big_file_budget.py`），而这段只在开发截图里执行、产品路径永远走不到。
 * 抽出来之后 store 不再塞着一条 dev-only 分支，新功能也还有空间。
 *
 * 必须在渲染进程里做——会话由 cookie 认，主进程发的请求是另一个会话。
 * 打包后 `getDevSeed()` 恒为 null，不会调用这里。
 */

import { api, type ChapterMark, type Cue, type JobSnapshot, type ReportData, type ReviewSource, type TtsVoiceInfo } from './api';
import { loadChapters } from './chapters.svelte';
import { transcribeTask } from './transcribeTask.svelte';
import {
  app,
  loadTranslations,
  openMedia,
  openSubtitle,
  qa,
  refreshCues,
  setView,
  toast,
  tts,
} from './store.svelte';

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
  /** 仅开发截图用：灌一份假的「另一引擎复核」结果，避免为看卡片真跑模型。 */
  secondOpinion?: { engine?: string; index?: number; text?: string };
  /** 仅开发截图用：灌一份假的「单句 AI 判定」结果，避免为看卡片真加载本地模型。 */
  arbitration?: {
    index?: number;
    text?: string;
    note?: string;
    model?: string;
    hint?: string;
    history?: Array<{
      role: 'user' | 'assistant';
      text: string;
      note?: string;
      model?: string;
    }>;
    dialogOpen?: boolean;
  };
  /** 仅开发截图用：灌一版译文平行轨（验证「有译文轨时默认双语」与双语排版）。 */
  translations?: { lang: string; texts: string[] };
  reviewSource?: ReviewSource | null;
  /** 仅开发截图 / 无窗口回归用：灌一份章节 / 时刻点标记（走真实保存链路）。 */
  chapters?: ChapterMark[];
  /**
   * 仅开发截图 / 无窗口回归用：灌一份任务快照，验证转写页底部执行栏的
   * 「进行中 / 失败」两态，而不必真跑一遍模型。
   *
   * `target` / `engine` 必须与页面当前设置一致，底栏才会认这份快照
   * （`TranscribeView` 用 `submittedSig === dockSig` 分辨「旧结果冒充新配置」）。
   */
  job?: {
    status?: 'queued' | 'running' | 'cancelling' | 'done' | 'error';
    percent?: number;
    stage?: string;
    error?: string;
    target?: 'primary' | 'alt' | 'both';
    engine?: string;
  } | null;
  /**
   * 仅开发截图 / 无窗口回归用：灌一版朗读音色（含克隆音色），验证检查器里
   * 「朗读 ⚙」展开面板在 348px 窄栏内不溢出——真建一个 OmniVoice 音色要先装
   * 3.3GB 权重，截图不该付这个代价。
   */
  tts?: {
    voiceId?: string;
    system?: string[];
    custom?: { name: string; duration?: number }[];
  } | null;
}) {
  if (!seed?.mediaPath) return;
  try {
    // 走真实的 openMedia 路径（含代理提示，但不再自动开压制任务），这样截图/联调覆盖的是产品代码本身
    await openMedia(seed.mediaPath);
    if (seed.cues?.length) {
      await api.replaceCues(seed.cues);
      await refreshCues();
    }
    if (seed.chapters?.length) {
      await api.saveChapters({ marks: seed.chapters, label: '开发种子：章节标记' });
      await loadChapters(true);
    }
    if (seed.translations?.texts?.length) {
      // 走真实接口：`loadTranslations()` 之后 app.track 的默认双语逻辑才会命中
      await api.applyTranslation({
        lang: seed.translations.lang || 'zh-Hans',
        texts: seed.translations.texts,
      });
      await loadTranslations();
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
    if (seed.secondOpinion) {
      // 动态 import：store 不能静态依赖 secondOpinion（后者反过来依赖 store）。
      // 这条路径只在 KIKUSUB_DEV_SEED 存在时执行。
      const { applyDevSecondOpinion } = await import('./secondOpinion.svelte');
      applyDevSecondOpinion(seed.secondOpinion);
    }
    if (seed.arbitration) {
      const { applyDevArbitration } = await import('./arbitration.svelte');
      applyDevArbitration(seed.arbitration);
    }
    if (seed.tts) {
      const spec = seed.tts;
      const now = Date.now();
      const voice = (
        id: string,
        name: string,
        kind: 'system' | 'clone',
        extra: Partial<TtsVoiceInfo> = {},
      ): TtsVoiceInfo => ({
        id,
        name,
        engine: kind === 'clone' ? 'omnivoice' : 'mac_say',
        kind,
        locale: 'ja-JP',
        sample: '',
        duration: kind === 'clone' ? 4.7 : 0,
        ref_text: '',
        created_at: now,
        source: {},
        ...extra,
      });
      const applyVoices = () => {
        tts.loaded = true;
        tts.available = true;
        tts.system = (spec.system ?? ['系统语音']).map((name, i) =>
          voice(`sys-${i}`, name, 'system'),
        );
        tts.custom = (spec.custom ?? []).map((item, i) =>
          voice(`clone-${i}`, item.name, 'clone', { duration: item.duration ?? 4.7 }),
        );
        tts.voiceId = spec.voiceId ?? tts.custom[0]?.id ?? tts.system[0]?.id ?? '';
      };
      applyVoices();
      // 检查器挂载后会 `loadTtsVoices()` 用服务端**真实的**（这台机器上通常是空的）
      // 音色覆盖一次。截图 / 回归场景没有真音色，等它落地后再灌一次。
      window.setTimeout(applyVoices, 2000);
    }
    if (seed.job) {
      // 底栏只认「本页提交的这次任务」：`jobKind` + `jobMeta.origin` 决定归属，
      // `submittedSig === dockSig` 决定它还算不算当前设置的结果。两者都摆对，
      // 截出来的才是用户真会看到的进行中 / 失败态。
      const target = seed.job.target ?? 'alt';
      const engineKey = seed.job.engine ?? 'whisper';
      // 转写页挂载时会 `resetForMedia(app.media.id)`：mediaId 不一致就把范围 /
      // 上次提交清空。种子必须先把 mediaId 摆成当前这部片，快照才认得出「本页提交」。
      transcribeTask.mediaId = app.media?.id ?? transcribeTask.mediaId;
      // `targetTouched = true`：页面挂载时会按「已有一稿 → 默认写第二版」重算一次默认产出，
      // 不锁住就盖掉种子里指定的产出，底栏会退回到待命态。
      transcribeTask.target = target;
      transcribeTask.targetTouched = true;
      transcribeTask.scope = { startText: '', endText: '', from: 'full', label: '' };
      transcribeTask.lastSubmit = {
        engine: engineKey,
        target,
        startText: '',
        endText: '',
        label: '',
        apply: 'replace',
        at: Date.now(),
      };
      app.jobKind = 'transcribe';
      app.jobMeta = { scope: 'full', apply: 'replace', origin: 'transcribe', start: 0, end: 0, label: '' };
      app.job = {
        id: 'dev-preview',
        kind: 'transcribe',
        status: seed.job.status ?? 'running',
        ratio: (seed.job.percent ?? 0) / 100,
        percent: seed.job.percent ?? 0,
        stage: seed.job.stage ?? '',
        error: seed.job.error ?? '',
        created_at: Date.now() / 1000,
        started_at: Date.now() / 1000,
        finished_at: 0,
        elapsed: 0,
        result: null,
      } as JobSnapshot;
    }
    setView('review');
  } catch (err) {
    toast(`种子注入失败：${(err as Error).message}`, 'error');
  }
}
