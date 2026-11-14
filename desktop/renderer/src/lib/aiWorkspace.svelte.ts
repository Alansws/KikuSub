/**
 * AI 提案工作区（润色 / 翻译共用）。
 *
 * 从 `store.svelte.ts` 拆出来：那个文件有行数预算（只许变短），而提案状态与
 * 双源/分段逻辑只服务润色页、翻译页和提示词库。这里只依赖 store 暴露的
 * `app` / `toast` / 快照应用函数，不反向被 store 依赖。
 *
 * 三条不变量：
 * - 提案只认 `proposal.json` 契约（D-2），不关心是 in-app 还是外部 agent 生成；
 * - 应用 = 整批一次历史（D-5），走 `/api/ai/apply`，时间轴永远取自核对台（D-1）；
 * - 双源提案额外绑定第二版 digest（`digest_b`），B 变过就 409，字幕零改动。
 */

import { api, type AiProposal } from './api';
import { aiBridge } from './aiBridge';
import { needsSegments, planSegments, type AiSegment } from './aiSegments';
import { dual } from './dualReview.svelte';
import {
  applyCueSnapshot,
  applyHistoryMeta,
  app,
  currentExportUiState,
  loadCueHistory,
  loadTranslations,
  refreshCues,
  scheduleDraftSave,
  setTrackLang,
  setTrackMode,
  toast,
} from './store.svelte';
import {
  promptSelectedId,
  selectedPromptTemplate,
  type PromptCategory,
} from './promptStore.svelte';

export type AiMode = 'single' | 'dual';

/**
 * 当前这轮提案的上下文。
 *
 * `accept` / `edits` 用普通对象而不是 Set/Map：Svelte 5 的 runes 只追踪对象属性
 * 读写，`Set.add()` 不会触发重渲染，界面会出现"勾了没反应"。
 */
export const ai = $state({
  kind: 'polish' as 'polish' | 'translate',
  /** 润色页：single = 只吃 A；dual = 同时参考第二版 B。翻译恒为 single。 */
  mode: 'single' as AiMode,
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
  /** 长片双源：智能分段（A 的全局序号区间）。 */
  segments: [] as AiSegment[],
  segmentIndex: 0,
  /** 分段是否已回填：key = "from-to"。 */
  filled: {} as Record<string, boolean>,
  longMode: false,
});

function aiContextKey(): string {
  return `${app.media?.id ?? ''}:${ai.kind}:${ai.lang}:${ai.mode}`;
}

/**
 * 上下文切换（润色 ↔ 翻译、单源 ↔ 双源）时的本地编辑缓存。
 *
 * 切换上下文会重新从磁盘读提案；如果不缓存，用户刚勾掉的条目和双击改过的文本
 * 会在切到翻译页再回来时全部回到「全选 + 模型原文」。按上下文 key 记住即可，
 * 不参与磁盘提案（提案只存模型输出，人的编辑仍算 UI 草稿）。
 */
type AiDraftSnapshot = {
  accept: Record<number, boolean>;
  edits: Record<number, string>;
  changedOnly: boolean;
};

const aiDraftCache = new Map<string, AiDraftSnapshot>();

function takeDraftSnapshot(): AiDraftSnapshot {
  return {
    accept: { ...ai.accept },
    edits: { ...ai.edits },
    changedOnly: ai.changedOnly,
  };
}

function restoreDraftSnapshot(key: string) {
  if (!ai.proposal) return;
  const saved = aiDraftCache.get(key);
  if (!saved) return;
  ai.accept = { ...saved.accept };
  ai.edits = { ...saved.edits };
  ai.changedOnly = saved.changedOnly;
}

export function segmentKey(segment: AiSegment): string {
  return `${segment.from}-${segment.to}`;
}

/** 重算长片分段（进入双源模式 / 换片 / 第二版变化后调用）。 */
export function planAiSegments() {
  if (ai.kind !== 'polish' || ai.mode !== 'dual' || !dual.exists) {
    ai.segments = [];
    ai.longMode = false;
    ai.segmentIndex = 0;
    return;
  }
  ai.longMode = needsSegments(app.cues, dual.cues);
  ai.segments = ai.longMode ? planSegments(app.cues, dual.cues) : [];
  ai.segmentIndex = Math.min(ai.segmentIndex, Math.max(0, ai.segments.length - 1));
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
  ai.mode = 'single';
  ai.segments = [];
  ai.segmentIndex = 0;
  ai.filled = {};
  ai.longMode = false;
}

let aiLoadPromise: Promise<void> | null = null;

/**
 * 拉取当前上下文的提案。
 *
 * 并发调用返回同一个 Promise：撤销 / 重做恢复 AI 草稿时，页面的 `$effect`
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
      resetAiContextOnly();
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

/** 只清提案内容，保留当前模式（切上下文失败时用，避免把 dual 打回 single）。 */
function resetAiContextOnly() {
  ai.proposal = null;
  ai.path = '';
  ai.warnings = [];
  ai.errors = [];
  ai.accept = {};
  ai.edits = {};
  ai.digestMatch = true;
}

function switchAiContext(kind: 'polish' | 'translate', lang: string, mode: AiMode) {
  const leavingKey = aiContextKey();
  if (ai.proposal) aiDraftCache.set(leavingKey, takeDraftSnapshot());
  ai.kind = kind;
  ai.lang = lang;
  ai.mode = mode;
  const nextKey = aiContextKey();
  ai.loadedFor = '';
  ai.accept = {};
  ai.edits = {};
  planAiSegments();
  void (async () => {
    if (aiLoadPromise) await aiLoadPromise;
    await loadAiProposal(true);
    // 同一个上下文的钩选/手改从缓存恢复；没有缓存时保持 loadAiProposal 的全选默认。
    restoreDraftSnapshot(nextKey);
  })();
}

export function setAiKind(kind: 'polish' | 'translate') {
  if (ai.kind === kind) return;
  switchAiContext(kind, ai.lang, kind === 'translate' ? 'single' : ai.mode);
}

export function setAiLang(lang: string) {
  if (ai.lang === lang) return;
  switchAiContext(ai.kind, lang, ai.mode);
}

/**
 * 润色页的「单源 / 双源」切换；没有第二版时不允许进入 dual。
 *
 * **B 的条数不要求等于 A**：两个引擎的断句本来就不同，双源只把 B 当参考，
 * 输出骨架永远取自 A。这里只检查第二版是否存在。
 */
export function setAiMode(mode: AiMode) {
  if (ai.mode === mode) return;
  if (mode === 'dual' && !dual.exists) {
    toast('还没有第二版字幕：先在转写页用另一个引擎转一次并放进双引擎复核', 'warn');
    return;
  }
  switchAiContext('polish', ai.lang, mode);
}

/** 当前 AI diff 草稿（人工编辑 + 采纳/拒绝）；随统一历史快照回滚。 */
export function currentAiDraft(): Record<string, any> {
  return {
    key: aiContextKey(),
    kind: ai.kind,
    mode: ai.mode,
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
  const mode: AiMode = raw.mode === 'dual' && dual.exists ? 'dual' : 'single';
  const contextChanged = kind !== ai.kind || lang !== ai.lang || mode !== ai.mode;
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
      ai.mode = mode;
      ai.loadedFor = '';
      planAiSegments();
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

/** 第 3 栏最终文本（人工编辑优先）。 */
export function aiAfter(i: number): string {
  if (ai.edits[i] !== undefined) return ai.edits[i];
  return ai.proposal?.items.find((it) => it.i === i)?.after ?? app.cues[i - 1]?.text ?? '';
}

function changedIndexes(): number[] {
  const out: number[] = [];
  for (const item of ai.proposal?.items ?? []) {
    if (aiAfter(item.i) !== (item.before ?? app.cues[item.i - 1]?.text ?? '')) out.push(item.i);
  }
  return out;
}

async function applyPolishWith(accept: number[] | null, label: string) {
  if (!ai.proposal || ai.applying) return;
  if (ai.proposal.kind === 'translate') return applyAiTranslation();
  const edits: Record<number, string> = {};
  for (const [k, v] of Object.entries(ai.edits)) edits[Number(k)] = v;
  ai.applying = true;
  try {
    // 必须把当前提案一起带上：手动粘贴 / 外部粘贴的提案在磁盘上可能还没有文件，
    // 只传 kind 会让服务端退回“从磁盘读”，直接 409「找不到提案文件」。
    const res = await api.applyAiProposal({
      kind: ai.kind,
      lang: ai.lang,
      accept,
      edits,
      proposal: ai.proposal,
    });
    applyCueSnapshot(res);
    if (res.changed) {
      scheduleDraftSave();
      toast(`${label}：${res.changed} 处修改（⌘Z 可整批撤回）`);
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

/** 默认：只应用「已采纳且确有差异」的条目。 */
export async function applyAiProposal() {
  const accepted = changedIndexes().filter((i) => ai.accept[i] !== false);
  return applyPolishWith(accepted, accepted.length ? '已应用采纳的修改' : '没有需要应用的修改');
}

/** 应用全部差异句（忽略逐条拒绝）。 */
export async function applyAiAllDiffs() {
  return applyPolishWith(changedIndexes(), '已应用全部差异句');
}

/** 仅应用已采纳的差异句（与默认一致，单独给按钮一个明确语义）。 */
export async function applyAiAcceptedDiffs() {
  return applyAiProposal();
}

/** 整列全部采纳并应用（第 3 栏全量写回核对台）。 */
export async function applyAiWholeColumn() {
  return applyPolishWith(null, '已整列应用 AI 终稿');
}

/**
 * 「一键复制提示词」。
 *
 * - 翻译：当前 `translate` 分类模板整片；
 * - 润色单源：`polish_single` 分类模板整片；
 * - 润色双源：短片整片；长片自动进入分段模式，只复制当前段。
 */
export async function copyAiPrompt() {
  if (!app.cues.length) {
    toast(ai.kind === 'translate' ? '当前没有可翻译的字幕' : '当前没有可润色的字幕', 'warn');
    return false;
  }
  if (ai.kind === 'polish' && ai.mode === 'dual' && !dual.exists) {
    toast('还没有第二版字幕：先在转写页用另一个引擎转一次', 'warn');
    return false;
  }
  planAiSegments();
  const templateId = ai.kind === 'translate' ? promptSelectedId('translate') : '';
  let from: number | undefined;
  let to: number | undefined;
  let segmentLabel = '';
  if (ai.kind === 'polish' && ai.mode === 'dual' && ai.longMode && ai.segments.length) {
    const segment = ai.segments[Math.min(ai.segmentIndex, ai.segments.length - 1)];
    from = segment.from;
    to = segment.to;
    segmentLabel = ` · 第 ${segment.from}–${segment.to} 段`;
  }
  try {
    const res = await api.getAiPrompt(ai.kind, ai.lang, templateId, {
      mode: ai.kind === 'polish' ? ai.mode : 'single',
      from,
      to,
    });
    if (window.kikusub?.writeClipboard) {
      await window.kikusub.writeClipboard(res.prompt);
    } else if (navigator.clipboard) {
      await navigator.clipboard.writeText(res.prompt);
    }
    toast(
      `已复制「${res.template_name}」${segmentLabel}：${res.count} 条字幕，${(res.chars / 1000).toFixed(1)}k 字符`,
    );
    ai.pasteOpen = true;
    ai.pasteText = '';
    return true;
  } catch (err) {
    toast((err as Error).message, 'error');
    return false;
  }
}

/** 提示词库卡片上的「复制提示词」：按分类选择单源/双源/翻译。 */
export async function copyPromptTemplateForCategory(id: string, category: PromptCategory) {
  if (!app.cues.length) {
    toast('当前还没有字幕；导入并转写后再复制', 'warn');
    return false;
  }
  const kind = category === 'translate' ? 'translate' : 'polish';
  const mode: AiMode = category === 'polish_dual' ? 'dual' : 'single';
  if (mode === 'dual' && !dual.exists) {
    toast('双源模板需要第二版字幕：先把另一引擎的稿放进双引擎复核', 'warn');
    return false;
  }
  try {
    const res = await api.getAiPrompt(kind, ai.lang, id, { mode });
    if (window.kikusub?.writeClipboard) {
      await window.kikusub.writeClipboard(res.prompt);
    } else if (navigator.clipboard) {
      await navigator.clipboard.writeText(res.prompt);
    }
    toast(`已复制「${res.template_name}」：${res.count} 条字幕`);
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
 * 条数对不上会整批拒绝，错误里带「本段期望第 k~m 条（共 X 条），实际解析到 Y 条」。
 * 长片分段时，新结果只覆盖当前段的序号区间，之前已回填的段保留。
 */
export async function parseAiPastedSrt() {
  const text = ai.pasteText.trim();
  if (!text) {
    toast('先把模型返回的 SRT 粘进来', 'warn');
    return;
  }
  ai.parsing = true;
  try {
    const segmented =
      ai.kind === 'polish' && ai.mode === 'dual' && ai.longMode && ai.segments.length > 0;
    const segment = segmented
      ? ai.segments[Math.min(ai.segmentIndex, ai.segments.length - 1)]
      : null;
    const res = await api.aiFromSrt({
      kind: ai.kind,
      lang: ai.kind === 'translate' ? ai.lang : '',
      text,
      from_index: segment?.from,
      to_index: segment?.to,
      mode: ai.kind === 'polish' ? ai.mode : 'single',
    });
    let proposal = res.proposal;
    if (segment && ai.proposal && ai.proposal.items.length === proposal.items.length) {
      // 合并：段外的条目保留上一次回填的结果
      const previous = new Map(ai.proposal.items.map((it) => [it.i, it]));
      proposal = {
        ...proposal,
        items: proposal.items.map((it) => {
          if (it.i >= segment.from && it.i <= segment.to) return it;
          const old = previous.get(it.i);
          return old ? { ...it, after: old.after, note: old.note } : it;
        }),
      };
    }
    const previousAccept = segment ? { ...ai.accept } : {};
    const previousEdits = segment ? { ...ai.edits } : {};
    ai.proposal = proposal;
    ai.path = '';
    ai.errors = [];
    ai.warnings = res.warnings ?? [];
    ai.accept = {};
    ai.edits = {};
    for (const item of res.proposal.items) {
      if (segment) {
        if (item.i >= segment.from && item.i <= segment.to) {
          ai.accept[item.i] = true;
        } else {
          // 段外的采纳/手改属于之前已回填的段，必须原样保留
          ai.accept[item.i] = previousAccept[item.i] !== false;
          if (previousEdits[item.i] !== undefined) ai.edits[item.i] = previousEdits[item.i];
        }
      } else {
        ai.accept[item.i] = true;
      }
    }
    // 解析结果立刻落盘：这份提案可能是「复制提示词 → 外部模型 → 粘回来」来的，
    // 磁盘上原本没有对应文件。不落盘的话，切到翻译页再回来（或重开页面）时
    // `loadAiProposal` 会读到 409，把刚解析好的整页内容清空。
    try {
      const saved = await api.saveAiProposal(proposal, ai.kind, ai.lang);
      ai.path = saved.path;
    } catch (err) {
      ai.path = '';
      ai.warnings = [
        ...ai.warnings,
        `解析成功，但没能写入提案文件：${(err as Error).message}（切页前请先点「另存」）`,
      ];
    }
    if (segment) {
      ai.filled[segmentKey(segment)] = true;
      const next = ai.segments.findIndex((item, index) => index > ai.segmentIndex && !ai.filled[segmentKey(item)]);
      ai.segmentIndex = next >= 0 ? next : ai.segmentIndex;
      ai.pasteText = '';
      toast(`第 ${segment.from}–${segment.to} 段已回填（${segment.count} 条）`);
    } else {
      ai.pasteOpen = false;
      ai.pasteText = '';
      toast(
        ai.kind === 'translate'
          ? `已解析 ${res.count} 条译文，右侧就是待应用的建议`
          : `已解析 ${res.count} 条修改，右侧就是待应用的建议`,
      );
    }
    // 标记成"已加载"，避免 $effect 又去拉磁盘上的旧提案把它顶掉
    ai.loadedFor = aiContextKey();
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
 * 注意末尾那行 `loadedFor`：`resetAi()` 会把它清空，页面的 `$effect` 依赖它，
 * 于是会立刻再去磁盘读一遍——刚删掉的提案就"复活"了。标记成本上下文已查过即可。
 */
export async function discardAiProposal() {
  try {
    await api.deleteAiProposal(ai.kind, ai.kind === 'translate' ? ai.lang : '');
  } catch {
    /* 文件删不掉也要让界面回到空态 */
  }
  resetAiContextOnly();
  ai.loadedFor = aiContextKey();
  toast('已丢弃建议');
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
  if (kind === 'polish' && ai.mode === 'dual' && !dual.exists) {
    toast('还没有第二版字幕：先在转写页用另一个引擎转一次', 'warn');
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
        mode: kind === 'polish' ? ai.mode : 'single',
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

// 把 AI 草稿的读写挂到零依赖桥上，供 store 的快照/历史路径复用。
aiBridge.applyDraft = applyAiDraft;
aiBridge.currentDraft = currentAiDraft;

/** 当前模式绑定的模板名（页头显示用）。 */
export function currentPolishTemplateName(): string {
  const category: PromptCategory = ai.mode === 'dual' ? 'polish_dual' : 'polish_single';
  return selectedPromptTemplate(category)?.name ?? '—';
}
