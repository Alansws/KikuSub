/**
 * 待译补译批次：复制 → 粘回 → **只回填这几条**。
 *
 * 为什么单独一个模块：这块状态只服务「补译」这一个流程，放进 `store.svelte.ts`
 * 会占它的行数预算；而且它同时被两个入口调用（检查器的「补译 N 条」、翻译页的
 * 卡片），逻辑必须只有一份。
 *
 * 三道锁都在服务端（见 `server/routes_translations.py` 的 `/api/translations/gap`）：
 * 只接受显式下标、`before` 必须是当前原文、空文本不覆盖。这里只负责把「哪几条」
 * 算对、把请求发对，绝不能在前端自己拼一份整轨去提交。
 *
 * 复制出去的提示词也**不是整段**：服务端 `?indices=` 只把这些条目拼成 SRT，
 * 序号用全片条号；回填解析按序号落位（`/api/ai/gap-from-srt`）。
 */
import { api } from './api';
import { clipCaption, clipSpan } from './clipRange';
import { gapCounts, gapIndices, type GapCounts } from './gapBatch';
import { promptSelectedId } from './promptStore.svelte';
import {
  app,
  exporter,
  jumpToCue,
  loadCueHistory,
  loadTranslations,
  scheduleDraftSave,
  setTrackLang,
  setTrackMode,
  setView,
  toast,
} from './store.svelte';

export interface GapRow {
  /** 全片 1 基条号。 */
  i: number;
  /** 复制时的原文：回填时服务端用它确认「这一条没有被改过」。 */
  before: string;
  after: string;
  accepted: boolean;
}

export const gapFill = $state({
  open: false,
  lang: '',
  /** 本次复制出去的条目（也是回填允许写入的唯一集合）。 */
  indices: [] as number[],
  /** 复制时的源指纹；回填时带回，原文改过就 409。 */
  digest: '',
  items: [] as GapRow[],
  warnings: [] as string[],
  error: '',
  stage: '' as '' | 'copying' | 'parsing' | 'applying',
  pasteOpen: false,
  pasteText: '',
  scopeLabel: '',
  /** 是否把「原文已改」也纳入本批（默认不，重翻会覆盖现有译文）。 */
  includeStale: false,
});

/** 当前处理范围（章节 / 区间 / 全片），与翻译页下拉同一个 `exporter.clip`。 */
export function gapScope() {
  return clipSpan(app.cues, exporter.clip);
}

export function gapScopeLabel(): string {
  return clipCaption(exporter.clip);
}

function trackOf(lang: string) {
  return app.translations[lang];
}

/** 当前语种、当前处理范围里的待译 / 原文已改计数。 */
export function gapCountsNow(): GapCounts {
  return gapCounts(app.cues, trackOf(app.trackLang), gapScope());
}

/** 按当前勾选重算这次要复制的条号（升序）。 */
export function gapListNow(): number[] {
  return gapIndices(app.cues, trackOf(app.trackLang), gapScope(), gapFill.includeStale);
}

export function setGapIncludeStale(value: boolean) {
  gapFill.includeStale = value;
}

export function closeGapFill() {
  gapFill.open = false;
  gapFill.stage = '';
  gapFill.pasteOpen = false;
  gapFill.pasteText = '';
  gapFill.items = [];
  gapFill.error = '';
  gapFill.warnings = [];
}

/** 面板 / 检查器上的「N 条待译」文案（由组件调用，跟着 state 重算）。 */
export function gapPendingLabel(): string {
  const counts = gapCountsNow();
  if (!counts.pending && !counts.stale) return '全部同步';
  return [
    counts.pending ? `${counts.pending} 条待译` : '',
    counts.stale ? `${counts.stale} 条原文已改` : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

async function writeClipboard(text: string): Promise<void> {
  if (window.kikusub?.writeClipboard) {
    await window.kikusub.writeClipboard(text);
  } else if (navigator.clipboard) {
    await navigator.clipboard.writeText(text);
  }
}

/**
 * 打开补译：切到翻译页、展开卡片，默认顺手复制。
 *
 * 复制是「一键」的那一下——用户正在核对台逐句听，点完就能直接去外部模型。
 */
export async function openGapFill(copy = true): Promise<boolean> {
  const track = trackOf(app.trackLang);
  if (!track) {
    toast('还没有译文轨：先在检查器里「导入译文」或应用一版译文', 'warn');
    return false;
  }
  const indices = gapListNow();
  if (!indices.length && copy) {
    toast(
      gapFill.includeStale
        ? '当前处理范围里没有待译或原文已改的条目'
        : '当前处理范围里没有待译条目（「原文已改」要勾选后才补）',
      'warn',
    );
    return false;
  }
  gapFill.open = true;
  gapFill.lang = app.trackLang;
  gapFill.scopeLabel = gapScopeLabel();
  gapFill.items = [];
  gapFill.warnings = [];
  gapFill.error = '';
  gapFill.pasteOpen = false;
  gapFill.pasteText = '';
  setView('translate');
  return copy ? copyGapPrompt() : true;
}

/**
 * 复制补译提示词：**只含这些条目**。序号是全片条号，服务端回填按它落位。
 * 模板用翻译页当前选中的那一个（提示词里的批次说明由服务端注入，不改模板）。
 */
export async function copyGapPrompt(): Promise<boolean> {
  if (gapFill.stage) return false;
  const lang = app.trackLang;
  if (!trackOf(lang)) {
    toast('还没有译文轨：先应用或导入一版译文', 'warn');
    return false;
  }
  const span = gapScope();
  const indices = gapListNow();
  if (!indices.length) {
    toast('当前处理范围里没有可补译的条目', 'warn');
    return false;
  }
  gapFill.stage = 'copying';
  gapFill.error = '';
  try {
    const res = await api.getAiPrompt('translate', lang, promptSelectedId('translate'), {
      indices,
      rangeFrom: span.from,
      rangeTo: span.to,
    });
    await writeClipboard(res.prompt);
    gapFill.lang = lang;
    gapFill.scopeLabel = gapScopeLabel();
    gapFill.indices = res.indices ?? indices;
    gapFill.digest = res.digest ?? '';
    gapFill.items = [];
    gapFill.warnings = [];
    // 复制成功后自动展开：用户下一步就是粘贴回复，不该再点一次「展开」。
    gapFill.open = true;
    gapFill.pasteOpen = true;
    gapFill.pasteText = '';
    toast(
      `已复制 ${res.count} 条待译（${gapFill.scopeLabel || '全片'}）：粘到外部模型后，把回复贴回来`,
    );
    return true;
  } catch (err) {
    gapFill.error = (err as Error).message;
    toast(gapFill.error, 'error');
    return false;
  } finally {
    gapFill.stage = '';
  }
}

/** 解析粘贴回来的 SRT：条数必须与复制出去的一致，按序号落位。 */
export async function parseGapReply(): Promise<boolean> {
  const text = gapFill.pasteText.trim();
  if (!text) {
    toast('先把外部模型返回的 SRT 粘进来', 'warn');
    return false;
  }
  if (!gapFill.indices.length) {
    toast('这批还没有复制过：先点「复制待译」', 'warn');
    return false;
  }
  if (gapFill.stage) return false;
  gapFill.stage = 'parsing';
  gapFill.error = '';
  try {
    const res = await api.gapFromSrt({
      indices: gapFill.indices,
      text,
      digest: gapFill.digest || undefined,
    });
    gapFill.items = res.items.map((item) => ({ ...item, accepted: true }));
    gapFill.warnings = res.warnings ?? [];
    gapFill.pasteOpen = false;
    gapFill.pasteText = '';
    toast(`已解析 ${res.count} 条补译：确认后点「应用补译」`);
    return true;
  } catch (err) {
    gapFill.error = (err as Error).message;
    toast(gapFill.error, 'error');
    return false;
  } finally {
    gapFill.stage = '';
  }
}

export function toggleGapAccepted(index: number) {
  const row = gapFill.items.find((item) => item.i === index);
  if (row) row.accepted = !row.accepted;
}

export function updateGapItem(index: number, text: string) {
  const row = gapFill.items.find((item) => item.i === index);
  if (row) row.after = text;
}

/**
 * 应用补译：只提交**勾选且非空**的条目；其余条目服务端不写。
 *
 * 成功后回到核对台、切双语、定位到第一条补译——用户接下来的动作就是听一遍。
 */
export async function applyGapFill(): Promise<number> {
  if (gapFill.stage) return 0;
  const accepted = gapFill.items.filter((item) => item.accepted && item.after.trim());
  if (!accepted.length) {
    toast('没有勾选要写入的条目', 'warn');
    return 0;
  }
  const lang = gapFill.lang || app.trackLang;
  gapFill.stage = 'applying';
  gapFill.error = '';
  try {
    const res = await api.applyGap({
      lang,
      items: accepted.map((item) => ({ i: item.i, before: item.before, after: item.after })),
    });
    await loadTranslations();
    await loadCueHistory();
    scheduleDraftSave();
    setTrackLang(lang);
    setTrackMode('both');
    const first = accepted[0].i;
    closeGapFill();
    setView('review');
    jumpToCue(first - 1);
    const written = res.applied ?? accepted.length;
    const kept = res.kept ?? Math.max(0, app.cues.length - written);
    toast(`已补译 ${written} 条 · 保留 ${kept} 条（⌘Z 一步撤回）`);
    return written;
  } catch (err) {
    gapFill.error = (err as Error).message;
    toast(gapFill.error, 'error');
    return 0;
  } finally {
    gapFill.stage = '';
  }
}
