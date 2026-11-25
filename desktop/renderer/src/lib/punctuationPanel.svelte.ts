/**
 * 「清理标点」面板的状态与提交。
 *
 * 为什么单独一个文件：`lib/store.svelte.ts` 有行数预算（只许变短），而这块状态
 * 只服务一个功能，放进 store 等于给所有人加阅读成本。这里只做四件事——
 * 面板开关、偏好持久化、按「原文 / 译文 / 两轨」分别预演、把结果一次性交给
 * 现成的 replace-all 接口（服务端整批只压一步历史，⌘Z 能一次退干净）。
 *
 * 规则本身在 `lib/punctuation.ts`（纯函数、有单测），这里不写任何字符串处理。
 * 2026-11-25：译文轨接入。中文 / 英文必须用另一套规则（`flavor: 'target'`），
 * 把日语档套上去会把「今天，下雨了」变成「今天下雨了」——那是破坏不是整理。
 */

import {
  planClean,
  type CleanOptions,
  type CleanPlan,
  type EllipsisMode,
  type MidStyle,
} from './punctuation';
import { api } from './api';
import {
  app,
  applyCueSnapshot,
  loadCueHistory,
  loadTranslations,
  scheduleDraftSave,
  setView,
  toast,
} from './store.svelte';

/**
 * v3：新增「清理哪一轨」与译文轨口径（2026-11-25）。
 * 读一次 v2 迁移 `mid` / `ellipsis`：那两个键的口径没变，直接沿用不算「读旧键」。
 * 更早的 v1 仍然不读也不删（口径变了，读它会抵消历史修复）。
 */
const STORAGE_KEY = 'kikusub.punctClean.v3';
const LEGACY_V2_KEY = 'kikusub.punctClean.v2';

export type CleanTracks = 'source' | 'target' | 'both';

interface PunctPrefs {
  mid?: MidStyle;
  ellipsis?: EllipsisMode;
  tracks?: CleanTracks;
  targetEllipsis?: boolean;
  targetCollapse?: boolean;
}

function normalizeTracks(value: unknown): CleanTracks | undefined {
  return value === 'source' || value === 'target' || value === 'both' ? value : undefined;
}

function readPrefs(): PunctPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const p = JSON.parse(raw) as PunctPrefs;
      return {
        mid: p.mid === 'half' || p.mid === 'full' || p.mid === 'delete' ? p.mid : undefined,
        ellipsis:
          p.ellipsis === 'all' || p.ellipsis === 'keep' || p.ellipsis === 'trailing'
            ? p.ellipsis
            : undefined,
        tracks: normalizeTracks(p.tracks),
        targetEllipsis: typeof p.targetEllipsis === 'boolean' ? p.targetEllipsis : undefined,
        targetCollapse: typeof p.targetCollapse === 'boolean' ? p.targetCollapse : undefined,
      };
    }
    // 迁移 v2：只有原文口径，且它的含义与现在一致。
    const legacy = localStorage.getItem(LEGACY_V2_KEY);
    if (!legacy) return {};
    const old = JSON.parse(legacy) as PunctPrefs;
    return {
      mid: old.mid === 'half' || old.mid === 'full' || old.mid === 'delete' ? old.mid : undefined,
      ellipsis:
        old.ellipsis === 'all' || old.ellipsis === 'keep' || old.ellipsis === 'trailing'
          ? old.ellipsis
          : undefined,
    };
  } catch {
    // 读坏了就当没存过：偏好不是关键数据，不能因为它把界面弄挂
    return {};
  }
}

const prefs = readPrefs();

/**
 * 面板状态。`open` 只表示浮层展开；选项是**记住**的，下次打开还是上次那套。
 * 默认「句中直接删掉 + 只清行尾省略号」：日语字幕不靠空格断句，删掉才真干净；
 * 句中省略号是语气，不该被顺手抹掉。
 */
export const punctPanel = $state({
  open: false,
  /** 清理哪一轨。没有译文轨时会被 `effectiveTracks()` 夹回 `source`。 */
  tracks: (prefs.tracks ?? 'source') as CleanTracks,
  /** 用户是否自己选过「哪一轨」——没选过时按当前显示模式给默认值。 */
  tracksTouched: prefs.tracks !== undefined,
  mid: (prefs.mid ?? 'delete') as MidStyle,
  ellipsis: (prefs.ellipsis ?? 'trailing') as EllipsisMode,
  /** 译文轨：行尾省略号默认也清（与原文一致），可在面板里保留。 */
  targetEllipsis: prefs.targetEllipsis ?? true,
  /** 译文轨：折叠连续重复标点，默认开。 */
  targetCollapse: prefs.targetCollapse ?? true,
  busy: false,
});

function persist() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        mid: punctPanel.mid,
        ellipsis: punctPanel.ellipsis,
        tracks: punctPanel.tracks,
        targetEllipsis: punctPanel.targetEllipsis,
        targetCollapse: punctPanel.targetCollapse,
      }),
    );
  } catch {
    // 隐私模式 / 配额满了：记住偏好是锦上添花，失败就失败
  }
}

export function setPunctMid(mid: MidStyle) {
  punctPanel.mid = mid;
  persist();
}

export function setPunctEllipsis(mode: EllipsisMode) {
  punctPanel.ellipsis = mode;
  persist();
}

export function setPunctTargetEllipsis(value: boolean) {
  punctPanel.targetEllipsis = value;
  persist();
}

export function setPunctTargetCollapse(value: boolean) {
  punctPanel.targetCollapse = value;
  persist();
}

export function setPunctTracks(tracks: CleanTracks) {
  punctPanel.tracks = tracks;
  punctPanel.tracksTouched = true;
  persist();
}

/** 当前语种下有没有译文轨（模板 / 历史 / 检查器都按同一条轨判断）。 */
export function hasTranslationTrack(): boolean {
  const track = app.translations[app.trackLang];
  return Boolean(track && track.texts.length);
}

/**
 * 实际生效的清理范围：没有译文轨时「译文 / 两轨」都夹回原文。
 * 界面上的禁用态与请求口径都读这个函数，避免「面板选了译文、提交却清原文」。
 */
export function effectiveTracks(): CleanTracks {
  return hasTranslationTrack() ? punctPanel.tracks : 'source';
}

/** 原文轨口径（`ja`）。组件与预演读同一份，避免「面板说 A、结果按 B 算」。 */
export function punctOptions(): CleanOptions {
  return { mid: punctPanel.mid, ellipsis: punctPanel.ellipsis };
}

/** 译文轨口径（`target`）：语种决定英文缩写 / 空格怎么处理。 */
export function targetOptions(): CleanOptions {
  return {
    flavor: 'target',
    lang: app.trackLang,
    target: { ellipsis: punctPanel.targetEllipsis, collapse: punctPanel.targetCollapse },
  };
}

export interface PunctPlans {
  tracks: CleanTracks;
  source: CleanPlan | null;
  target: CleanPlan | null;
  sourceTexts: string[];
  targetTexts: string[];
}

/**
 * 当前选项下的双轨预演。`source` / `target` 为 null 表示这一轨本次不参与。
 * 组件用 `$derived` 调它，选项一变数字就跟着变；只做纯计算，不碰网络。
 */
export function punctPlans(): PunctPlans {
  const tracks = effectiveTracks();
  const sourceTexts = app.cues.map((cue) => cue.text);
  const targetTexts = hasTranslationTrack()
    ? [...(app.translations[app.trackLang]?.texts ?? [])]
    : [];
  // 防御：译文轨理论上与原文条数一致；万一不一致，补空位后仍按同一套下标预演，
  // 提交时服务端会按条数校验拒绝（绝不落一份错位的轨）。
  while (targetTexts.length < sourceTexts.length) targetTexts.push('');
  const wantSource = tracks !== 'target';
  const wantTarget = tracks !== 'source' && hasTranslationTrack();
  return {
    tracks,
    source: wantSource ? planClean(sourceTexts, punctOptions()) : null,
    target: wantTarget ? planClean(targetTexts, targetOptions()) : null,
    sourceTexts,
    targetTexts,
  };
}

/** 打开面板：不在核对台就先切过去（与 ⌘F 的行为一致）。 */
export function openPunctPanel() {
  if (app.view !== 'review') setView('review');
  // 用户没自己选过「哪一轨」时按当前显示模式给默认：正在看双语 / 译文，就默认两轨；
  // 只看原文时维持历史行为（只清原文），避免顺手改掉已核对的译文。
  if (!punctPanel.tracksTouched) {
    punctPanel.tracks =
      hasTranslationTrack() && app.track !== 'source' ? 'both' : 'source';
  }
  punctPanel.open = true;
}

export function closePunctPanel() {
  punctPanel.open = false;
}

/**
 * 应用清理。
 *
 * 走 `/api/cues/replace-all`（与“全部替换”同一条路）：客户端算好完整数组，
 * 服务端只压**一步**历史。两轨一起清时也只发一个请求——拆两次会让用户按两次
 * ⌘Z 才退干净。
 *
 * 回包交给 `applyCueSnapshot` —— 字幕表、底部字幕块、撤销按钮文案、历史面板
 * 都吃同一份状态，`cuesRevision` 自增会让波形与画布重绘。译文轨改过时再拉一次
 * `/api/translations`，否则双语行还显示旧文本。
 */
export async function applyPunctClean(): Promise<number> {
  if (punctPanel.busy) return 0;
  const plans = punctPlans();
  const sourceTotal = plans.source?.changed.length ?? 0;
  const targetTotal = plans.target?.changed.length ?? 0;
  const total = sourceTotal + targetTotal;
  if (!total) {
    toast('没有需要清理的标点');
    return 0;
  }

  punctPanel.busy = true;
  try {
    const label = [
      sourceTotal ? `原文 ${sourceTotal} 条` : '',
      targetTotal ? `译文 ${targetTotal} 条` : '',
    ]
      .filter(Boolean)
      .join(' / ');
    const body: {
      label: string;
      cues?: { start: number; end: number; text: string }[];
      lang?: string;
      texts?: string[];
    } = { label: `清理标点（${label}）` };

    if (plans.source && sourceTotal) {
      body.cues = app.cues.map((cue, index) => ({
        start: cue.start,
        end: cue.end,
        text: plans.source!.texts[index],
      }));
    }
    if (plans.target && targetTotal) {
      body.lang = app.trackLang;
      body.texts = plans.target.texts;
    }

    const data = await api.replaceAll(body);
    applyCueSnapshot(data);
    if (plans.target && targetTotal) await loadTranslations();
    scheduleDraftSave();
    void loadCueHistory();
    punctPanel.open = false;
    toast(
      sourceTotal && targetTotal
        ? `已清理原文 ${sourceTotal} 条、译文 ${targetTotal} 条（⌘Z 可一步撤回）`
        : `已清理 ${total} 条（⌘Z 可撤回）`,
    );
    return total;
  } catch (err) {
    toast((err as Error).message, 'error');
    return 0;
  } finally {
    punctPanel.busy = false;
  }
}
