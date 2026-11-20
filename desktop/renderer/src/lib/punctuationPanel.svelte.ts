/**
 * 「清理标点」面板的状态与提交。
 *
 * 为什么单独一个文件：`lib/store.svelte.ts` 有行数预算（只许变短），而这块状态
 * 只服务一个功能，放进 store 等于给所有人加阅读成本。这里只做三件事——
 * 面板开关、偏好持久化、把「一次性整轨替换」交给现成的 replace-all 接口
 * （服务端整批只压一步历史，⌘Z 能一次退干净）。
 *
 * 规则本身在 `lib/punctuation.ts`（纯函数、有单测），这里不写任何字符串处理。
 */

import { planClean, type CleanPlan, type EllipsisMode, type MidStyle } from './punctuation';
import { api } from './api';
import {
  app,
  applyCueSnapshot,
  loadCueHistory,
  scheduleDraftSave,
  setView,
  toast,
} from './store.svelte';

/**
 * v2：口径变了（句中默认**删掉**、行尾省略号默认清），所以换一个键。
 * 读旧键会让老用户的 `space: 'half'` 把这次修复整个抵消掉——他们点完会发现
 * 「顿号还是变成空格」，以为没修。旧键就留在 localStorage 里不读也不删。
 */
const STORAGE_KEY = 'kikusub.punctClean.v2';

interface PunctPrefs {
  mid?: MidStyle;
  ellipsis?: EllipsisMode;
}

function readPrefs(): PunctPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const p = JSON.parse(raw) as PunctPrefs;
    const mid: MidStyle =
      p.mid === 'half' || p.mid === 'full' || p.mid === 'delete' ? p.mid : 'delete';
    const ellipsis: EllipsisMode =
      p.ellipsis === 'all' || p.ellipsis === 'keep' || p.ellipsis === 'trailing'
        ? p.ellipsis
        : 'trailing';
    return { mid, ellipsis };
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
  mid: (prefs.mid ?? 'delete') as MidStyle,
  ellipsis: (prefs.ellipsis ?? 'trailing') as EllipsisMode,
  busy: false,
});

function persist() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ mid: punctPanel.mid, ellipsis: punctPanel.ellipsis }),
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

/** 面板当前选项。组件与预演读同一份，避免出现「面板说 A、结果按 B 算」。 */
export function punctOptions() {
  return { mid: punctPanel.mid, ellipsis: punctPanel.ellipsis };
}

/** 打开面板：不在核对台就先切过去（与 ⌘F 的行为一致）。 */
export function openPunctPanel() {
  if (app.view !== 'review') setView('review');
  punctPanel.open = true;
}

export function closePunctPanel() {
  punctPanel.open = false;
}

/** 当前选项下的预演结果。组件用 `$derived` 调它，选项一变数字就跟着变。 */
export function currentPunctPlan(): CleanPlan {
  return planClean(
    app.cues.map((cue) => cue.text),
    punctOptions(),
  );
}

/**
 * 应用清理。
 *
 * 走 `/api/cues/replace-all`（与「全部替换」同一条路）：客户端算好完整数组，
 * 服务端只压**一步**历史。回包交给 `applyCueSnapshot` —— 字幕表、底部字幕块、
 * 撤销按钮文案、历史面板都吃同一份状态，`cuesRevision` 自增会让波形与画布重绘。
 * 再补一次草稿暂存，避免「清完就崩」丢掉这一批改动。
 *
 * 只替换 `text`，条数与时间轴原样送回：条数没变，已有译文轨不会被丢弃。
 */
export async function applyPunctClean(): Promise<number> {
  if (punctPanel.busy) return 0;
  const plan = currentPunctPlan();
  const total = plan.changed.length;
  if (!total) {
    toast('没有需要清理的标点');
    return 0;
  }

  punctPanel.busy = true;
  try {
    const cues = app.cues.map((cue, index) => ({
      start: cue.start,
      end: cue.end,
      text: plan.texts[index],
    }));
    const data = await api.replaceAll({
      label: `清理标点（${total} 条）`,
      cues,
    });
    applyCueSnapshot(data);
    scheduleDraftSave();
    void loadCueHistory();
    punctPanel.open = false;
    toast(`已清理 ${total} 条（⌘Z 可撤回）`);
    return total;
  } catch (err) {
    toast((err as Error).message, 'error');
    return 0;
  } finally {
    punctPanel.busy = false;
  }
}
