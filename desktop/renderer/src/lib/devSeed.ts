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

import { api, type ChapterMark, type Cue, type ReportData, type ReviewSource } from './api';
import { loadChapters } from './chapters.svelte';
import {
  app,
  loadTranslations,
  openMedia,
  openSubtitle,
  qa,
  refreshCues,
  setView,
  toast,
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
    setView('review');
  } catch (err) {
    toast(`种子注入失败：${(err as Error).message}`, 'error');
  }
}
