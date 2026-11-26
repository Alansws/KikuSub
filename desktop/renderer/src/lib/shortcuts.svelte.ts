/**
 * 可自定义键盘快捷键。
 *
 * 菜单里的固定 accelerator 不能跟着用户改，所以核对台的播放 / 上下句 / 删除、
 * 视图切换与「查找」都收在渲染层这一张表里。主进程菜单只保留点击动作，不再
 * 抢占这些按键（否则 ⌘1 在润色页里永远先切到「导入」）。
 *
 * 视图快捷键按工作流顺序固定为 ⌘1..⌘8：
 * 导入 / 转写 / 核对台 / 双引擎复核 / 润色 / 翻译 / 导出。
 * 提示词库不占键；设置页由 macOS 惯例的 ⌘, 进入（见下方 FIXED_SHORTCUTS）。
 */

import type { View } from './store.svelte';

export type ShortcutScope = 'global' | 'review' | 'view' | 'find';

export interface ShortcutDef {
  id: string;
  label: string;
  group: string;
  scope: ShortcutScope;
  /** 默认组合；格式见 `comboFromEvent`（mod / alt / shift + 键名）。 */
  def: string;
  /** 输入框聚焦时是否仍然生效（视图切换、打开面板等）。 */
  allowInTyping?: boolean;
  /**
   * 按钮 / 链接获得焦点时是否仍然生效。
   *
   * 只对非输入控件放行：`textarea` / `input`（含 range 滑杆）/ `select` /
   * `contenteditable` 永远让位。播放 / 步进这类传输键需要它——用户点过播放按钮后
   * 焦点留在按钮上，方向键不能失效。
   */
  allowOnControls?: boolean;
  /** 同一组合在某个上下文里优先于另一组（保留给将来的多上下文动作）。 */
  note?: string;
}

export const SHORTCUT_DEFS: ShortcutDef[] = [
  {
    id: 'shortcuts.open',
    label: '打开键盘快捷键面板',
    group: '全局',
    scope: 'global',
    def: 'mod+k',
    allowInTyping: true,
  },
  {
    id: 'review.togglePlay',
    label: '播放 / 暂停',
    group: '核对台',
    scope: 'review',
    def: 'space',
  },
  {
    id: 'review.prevCue',
    label: '上一句',
    group: '核对台',
    scope: 'review',
    def: 'arrowup',
    allowOnControls: true,
  },
  {
    id: 'review.nextCue',
    label: '下一句',
    group: '核对台',
    scope: 'review',
    def: 'arrowdown',
    allowOnControls: true,
  },
  {
    id: 'review.stepBack',
    label: '后退 1 帧',
    group: '核对台',
    scope: 'review',
    def: 'arrowleft',
    // 方向键不能落到 WebView 的 history 上；App.onKey 还会兜一层 preventDefault。
    allowOnControls: true,
    note: '自动暂停；纯音频 / 未知帧率按 30fps 步进',
  },
  {
    id: 'review.stepForward',
    label: '前进 1 帧',
    group: '核对台',
    scope: 'review',
    def: 'arrowright',
    allowOnControls: true,
    note: '自动暂停；纯音频 / 未知帧率按 30fps 步进',
  },
  {
    id: 'review.stepBackSecond',
    label: '后退 1 秒',
    group: '核对台',
    scope: 'review',
    def: 'mod+arrowleft',
    allowOnControls: true,
  },
  {
    id: 'review.stepForwardSecond',
    label: '前进 1 秒',
    group: '核对台',
    scope: 'review',
    def: 'mod+arrowright',
    allowOnControls: true,
  },
  {
    id: 'review.inPoint',
    label: '入点对齐播放头',
    group: '核对台',
    scope: 'review',
    def: 'q',
    note: '当前字幕；服务端一步历史，⌘Z 可撤回',
  },
  {
    id: 'review.outPoint',
    label: '出点对齐播放头',
    group: '核对台',
    scope: 'review',
    def: 'e',
    note: '当前字幕；服务端一步历史，⌘Z 可撤回',
  },
  {
    id: 'review.chapterStart',
    label: '章节：把播放头设为起点',
    group: '核对台',
    scope: 'review',
    def: 'i',
    note: '先把时刻点设为章末（章节面板「补起点」），再缩放到起点位置',
  },
  {
    id: 'review.chapterEnd',
    label: '章节：把播放头设为终点',
    group: '核对台',
    scope: 'review',
    def: 'o',
    note: '先把时刻点设为章首（章节面板「补终点」），再缩放到终点位置',
  },
  {
    id: 'review.splitAtPlayhead',
    label: '在播放头切割当前字幕',
    group: '核对台',
    scope: 'review',
    def: 'w',
    note: '复用右键切割；⌘Z 可撤回',
  },
  {
    id: 'review.auditionCue',
    label: '试听选中的字幕',
    group: '核对台',
    scope: 'review',
    def: 'shift+space',
    allowOnControls: true,
    note: '播到该句终点自动停住',
  },
  {
    id: 'review.toggleSnap',
    label: '磁吸吸附开关',
    group: '核对台',
    scope: 'review',
    def: 'n',
    note: '拖字幕块时吸附播放头与邻句边缘；偏好持久化',
  },
  {
    id: 'review.toggleFit',
    label: '全片适应 / 回到上次缩放',
    group: '核对台',
    scope: 'review',
    def: 'shift+z',
  },
  {
    id: 'review.speedDown',
    label: '降一档倍速并播放',
    group: '核对台',
    scope: 'review',
    def: '1',
    note: '0.5× / 1× / 1.5× / 2×，到头停住',
  },
  {
    id: 'review.speedPause',
    label: '暂停（保留倍速）',
    group: '核对台',
    scope: 'review',
    def: '2',
    note: '⇧2 归 1×',
  },
  {
    id: 'review.speedUp',
    label: '升一档倍速并播放',
    group: '核对台',
    scope: 'review',
    def: '3',
    note: '0.5× / 1× / 1.5× / 2×，到头停住',
  },
  {
    id: 'review.speedReset',
    label: '倍速归 1×',
    group: '核对台',
    scope: 'review',
    def: 'shift+2',
  },
  {
    id: 'review.deleteCue',
    label: '删除选中的字幕（多选时一起删）',
    group: '核对台',
    scope: 'review',
    def: 'enter',
    note: 'Delete / Backspace 也可删除',
  },
  {
    id: 'review.addCue',
    label: '在播放头添加空字幕',
    group: '核对台',
    scope: 'review',
    def: 'mod+enter',
  },
  {
    id: 'review.copyCue',
    label: '复制选中的字幕',
    group: '核对台',
    scope: 'review',
    // 不用 ⌘C：主进程编辑菜单的 role:'copy' 会先接走这个键；⌘⇧C 不与任何菜单
    // / 固定快捷键冲突，文本框内仍由原生 ⌘C 处理。
    def: 'mod+shift+c',
    note: '文本 + 时长 + 译文；文本框内仍是系统复制',
  },
  {
    id: 'review.pasteCue',
    label: '粘贴字幕到播放头',
    group: '核对台',
    scope: 'review',
    def: 'mod+shift+v',
    note: '新建一条；起点=播放头，不改邻句时间轴',
  },
  {
    id: 'review.find',
    label: '查找与替换',
    group: '核对台',
    // 从任意页面按 ⌘F 都应切到核对台并打开查找栏
    scope: 'global',
    def: 'mod+f',
    allowInTyping: true,
  },
  {
    id: 'review.cleanPunct',
    label: '清理标点',
    group: '核对台',
    // 从任意页面按 ⌘⇧L 都应切到核对台并展开清理浮层（⌘K 是快捷键面板，不能占）
    scope: 'global',
    def: 'mod+shift+l',
    allowInTyping: true,
  },
  {
    id: 'review.findPrev',
    label: '查找：上一处',
    group: '查找',
    scope: 'find',
    def: 'mod+shift+g',
    note: '查找栏打开时生效',
  },
  {
    id: 'review.findNext',
    label: '查找：下一处',
    group: '查找',
    scope: 'find',
    def: 'mod+g',
    note: '查找栏打开时生效',
  },
  {
    id: 'review.toggleQa',
    label: '打开 / 收起质检面板',
    group: '核对台',
    scope: 'review',
    def: 'mod+shift+k',
  },
  {
    id: 'view.import',
    label: '导入',
    group: '视图',
    scope: 'view',
    def: 'mod+1',
    allowInTyping: true,
  },
  {
    id: 'view.transcribe',
    label: '转写',
    group: '视图',
    scope: 'view',
    def: 'mod+2',
    allowInTyping: true,
  },
  {
    id: 'view.review',
    label: '核对台',
    group: '视图',
    scope: 'view',
    def: 'mod+3',
    allowInTyping: true,
  },
  {
    id: 'view.dual',
    label: '双引擎复核',
    group: '视图',
    scope: 'view',
    def: 'mod+4',
    allowInTyping: true,
  },
  {
    id: 'view.polish',
    label: '润色',
    group: '视图',
    scope: 'view',
    def: 'mod+5',
    allowInTyping: true,
  },
  {
    id: 'view.reshape',
    label: '断句重排',
    group: '视图',
    scope: 'view',
    def: 'mod+6',
    allowInTyping: true,
  },
  {
    id: 'view.translate',
    label: '翻译',
    group: '视图',
    scope: 'view',
    def: 'mod+7',
    allowInTyping: true,
  },
  {
    id: 'view.export',
    label: '导出',
    group: '视图',
    scope: 'view',
    def: 'mod+8',
    allowInTyping: true,
  },
];

/**
 * 由 macOS 菜单 / 系统占用的固定组合，不允许在快捷键面板里改成它们。
 *
 * 之前这些组合不在检查范围内：用户把「播放」改成 ⌘Q 也能保存，按下去却
 * 直接退出应用。现在录制时就会提示「与『退出 KikuSub』快捷键重复」。
 */
export interface FixedShortcut {
  id: string;
  label: string;
  combo: string;
  /** 为什么不能改（菜单 / 系统 / 文本编辑）。 */
  reason: string;
}

export const FIXED_SHORTCUTS: FixedShortcut[] = [
  { id: 'system.settings', label: '设置', combo: 'mod+,', reason: 'macOS 菜单' },
  { id: 'system.open', label: '打开…', combo: 'mod+o', reason: '文件菜单' },
  { id: 'system.export', label: '导出…', combo: 'mod+e', reason: '文件菜单' },
  { id: 'system.undo', label: '撤回', combo: 'mod+z', reason: '编辑菜单' },
  { id: 'system.redo', label: '重做', combo: 'mod+shift+z', reason: '编辑菜单' },
  { id: 'system.inspector', label: '切换检查器', combo: 'mod+alt+i', reason: '显示菜单' },
  { id: 'system.theme', label: '切换外观', combo: 'mod+shift+a', reason: '显示菜单' },
  { id: 'system.quit', label: '退出 KikuSub', combo: 'mod+q', reason: '系统' },
  { id: 'system.close', label: '关闭窗口', combo: 'mod+w', reason: '系统' },
  { id: 'system.minimize', label: '最小化', combo: 'mod+m', reason: '系统' },
  { id: 'system.hide', label: '隐藏 KikuSub', combo: 'mod+h', reason: '系统' },
  { id: 'system.cut', label: '剪切', combo: 'mod+x', reason: '文本编辑' },
  { id: 'system.copy', label: '拷贝', combo: 'mod+c', reason: '文本编辑' },
  { id: 'system.paste', label: '粘贴', combo: 'mod+v', reason: '文本编辑' },
  { id: 'system.selectAll', label: '全选', combo: 'mod+a', reason: '文本编辑' },
];

const STORAGE_KEY = 'kikusub.shortcuts.v1';

const DEFAULTS: Record<string, string> = Object.fromEntries(
  SHORTCUT_DEFS.map((def) => [def.id, def.def]),
);

function loadMap(): Record<string, string> {
  const map = { ...DEFAULTS };
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    if (!raw || typeof raw !== 'object') return map;
    for (const def of SHORTCUT_DEFS) {
      const value = raw[def.id];
      if (typeof value === 'string' && value.trim()) map[def.id] = value;
    }
    // 旧默认值迁移（一）：上一版 ⌘4 是 AI 优化、⌘5 是导出。只有这两个值仍等于
    // 旧默认时才重排到 ⌘4..⌘7，避免覆盖用户自己改过的键。
    if (raw['view.ai'] === 'mod+4' && raw['view.export'] === 'mod+5') {
      map['view.dual'] = 'mod+4';
      map['view.polish'] = 'mod+5';
      map['view.translate'] = 'mod+6';
      map['view.export'] = 'mod+7';
    }
    // 旧默认值迁移（二）：⌘6 曾是翻译、⌘7 是导出。加了「断句重排」后顺延到
    // ⌘6..⌘8；同样只在仍是旧默认时迁移（第二段判断读 map，因为 (一) 可能刚改过它）。
    if (map['view.translate'] === 'mod+6' && map['view.export'] === 'mod+7') {
      map['view.reshape'] = 'mod+6';
      map['view.translate'] = 'mod+7';
      map['view.export'] = 'mod+8';
    }
  } catch {
    /* 手改坏 / 隐私模式：回到默认，不影响使用 */
  }
  return map;
}

export const shortcuts = $state({
  map: loadMap(),
  open: false,
  /** 正在录制新组合的动作 id；空串表示没在录制。 */
  capturing: '',
  /** 录制时的重复提示（会显示在正在录制的那一行下面）。 */
  conflict: '',
});

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(shortcuts.map));
  } catch {
    /* 忽略 */
  }
}

export function shortcutDef(id: string): ShortcutDef | undefined {
  return SHORTCUT_DEFS.find((def) => def.id === id);
}

export function comboOf(id: string): string {
  return shortcuts.map[id] ?? DEFAULTS[id] ?? '';
}

export function setShortcut(id: string, combo: string) {
  if (!shortcutDef(id) || !combo) return;
  shortcuts.map = { ...shortcuts.map, [id]: combo };
  shortcuts.conflict = '';
  persist();
}

export function resetShortcuts() {
  shortcuts.map = { ...DEFAULTS };
  shortcuts.conflict = '';
  persist();
}

function normalizeKey(key: string): string {
  if (key === ' ' || key === 'Spacebar') return 'space';
  if (key === 'Esc') return 'escape';
  if (key === 'Up') return 'arrowup';
  if (key === 'Down') return 'arrowdown';
  if (key === 'Left') return 'arrowleft';
  if (key === 'Right') return 'arrowright';
  if (key === 'Del') return 'delete';
  if (key.length === 1) return key.toLowerCase();
  return key.toLowerCase();
}

/**
 * 物理键 → 组合里的键名。
 *
 * 为什么不能只用 `e.key`：macOS 的 `⌥[` 会变成 `“`，JIS / AZERTY 布局下 Q/E/W 与
 * 括号也不是 US 键位上的字符。这里按 `e.code` 兜底，保证「同一个物理键」在录制与
 * 匹配时一致。文本框内仍然让位，所以不会影响正常输入。
 */
const CODE_KEYS: Record<string, string> = {
  BracketLeft: '[',
  BracketRight: ']',
  Backslash: '\\',
  KeyQ: 'q',
  KeyE: 'e',
  KeyW: 'w',
  Digit1: '1',
  Digit2: '2',
  Digit3: '3',
};

function eventKey(e: KeyboardEvent): string {
  return CODE_KEYS[e.code] ?? normalizeKey(e.key);
}

interface ParsedCombo {
  mod: boolean;
  alt: boolean;
  shift: boolean;
  key: string;
}

function parseCombo(combo: string): ParsedCombo {
  const parts = String(combo || '').toLowerCase().split('+');
  const key = parts.pop() || '';
  return {
    mod: parts.includes('mod'),
    alt: parts.includes('alt'),
    shift: parts.includes('shift'),
    key: normalizeKey(key),
  };
}

/** 把组合写成固定顺序（mod → alt → shift → key），用于比较是否重复。 */
function canonicalCombo(combo: string): string {
  const parsed = parseCombo(combo);
  if (!parsed.key) return '';
  const parts: string[] = [];
  if (parsed.mod) parts.push('mod');
  if (parsed.alt) parts.push('alt');
  if (parsed.shift) parts.push('shift');
  parts.push(parsed.key);
  return parts.join('+');
}

export interface ShortcutConflict {
  id: string;
  label: string;
  /** true = 由菜单 / 系统固定占用，不能改。 */
  fixed?: boolean;
  reason?: string;
}

/** 同一个组合被别的动作占用时返回那个动作；固定组合也会返回（fixed=true）。 */
export function conflictingShortcut(id: string, combo: string): ShortcutConflict | null {
  const target = canonicalCombo(combo);
  if (!target) return null;
  for (const other of SHORTCUT_DEFS) {
    if (other.id === id) continue;
    if (canonicalCombo(comboOf(other.id)) === target) {
      return { id: other.id, label: other.label };
    }
  }
  for (const fixed of FIXED_SHORTCUTS) {
    if (canonicalCombo(fixed.combo) === target) {
      return { id: fixed.id, label: fixed.label, fixed: true, reason: fixed.reason };
    }
  }
  return null;
}

/** 已经保存过的组合是否与另一项重复（用于在面板里标红，而不是等到按下才发现）。 */
export function savedConflict(id: string): ShortcutConflict | null {
  const combo = comboOf(id);
  if (!combo) return null;
  return conflictingShortcut(id, combo);
}

/** 把一次 keydown 变成可持久化的组合；纯修饰键返回 null。 */
export function comboFromEvent(e: KeyboardEvent): string | null {
  const key = eventKey(e);
  if (['meta', 'control', 'alt', 'shift'].includes(key)) return null;
  // Escape 保留给「取消 / 关闭」，不作为可绑定键
  if (key === 'escape') return null;
  const parts: string[] = [];
  if (e.metaKey || e.ctrlKey) parts.push('mod');
  if (e.altKey) parts.push('alt');
  if (e.shiftKey) parts.push('shift');
  parts.push(key);
  return parts.join('+');
}

export function comboMatches(e: KeyboardEvent, combo: string): boolean {
  const parsed = parseCombo(combo);
  if (!parsed.key) return false;
  if (parsed.mod !== Boolean(e.metaKey || e.ctrlKey)) return false;
  if (parsed.alt !== Boolean(e.altKey)) return false;
  if (parsed.shift !== Boolean(e.shiftKey)) return false;
  return eventKey(e) === parsed.key;
}

const KEY_LABEL: Record<string, string> = {
  space: 'Space',
  enter: '↩',
  escape: 'Esc',
  arrowup: '↑',
  arrowdown: '↓',
  arrowleft: '←',
  arrowright: '→',
  backspace: '⌫',
  delete: '⌦',
  tab: 'Tab',
};

export function formatCombo(combo: string): string {
  const parsed = parseCombo(combo);
  if (!parsed.key) return '—';
  let out = '';
  if (parsed.mod) out += '⌘';
  if (parsed.alt) out += '⌥';
  if (parsed.shift) out += '⇧';
  const label = KEY_LABEL[parsed.key] ?? parsed.key.toUpperCase();
  return out + label;
}

function isTextEntry(el: HTMLElement): boolean {
  if (el.isContentEditable) return true;
  if (el.tagName === 'TEXTAREA') return true;
  if (el.tagName !== 'INPUT') return false;
  const type = (el as HTMLInputElement).type;
  return !['range', 'checkbox', 'radio', 'button', 'submit', 'file'].includes(type);
}

/**
 * 焦点在控件上时是否要让位给原生行为。
 *
 * 文本框里当然不能触发核对台快捷键；按钮 / 链接只在 Space / Enter / 方向键
 * 时让位（那是激活与导航），字母键仍然可以触发用户自定义的动作——否则
 * 点过一次工具栏按钮后，用户把「删除」改成 s 就再也按不出来了。
 */
function blocksShortcut(
  e: KeyboardEvent,
  target: EventTarget | null,
  allowOnControls = false,
): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  // 文本输入永远让位；range 滑杆 / 复选框 / 下拉也保留原生键盘行为。
  if (isTextEntry(el)) return true;
  const tag = el.tagName;
  const key = normalizeKey(e.key);
  if (tag === 'SELECT' || tag === 'INPUT') return true;
  if (allowOnControls) return false;
  if (tag === 'BUTTON' || tag === 'A') {
    return [' ', 'enter', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'tab'].includes(key);
  }
  return false;
}

/**
 * 找出这次按键对应的动作。
 *
 * 视图动作只有一个上下文：⌘1–⌘8 在任何页面都切页。
 *
 * `findOpen` 给「查找：上一处 / 下一处」用：这两个动作只在查找栏打开时存在，
 * 避免用户把键设成方向键后，平时在表格/正文里按方向键也被劫走。
 */
export interface ShortcutContext {
  findOpen?: boolean;
}

/** 事件焦点是否在查找栏内（查找框、替换框、上一处/下一处按钮）。 */
function insideFindBar(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest('.find-bar'));
}

export function resolveShortcut(
  e: KeyboardEvent,
  view: View,
  context: ShortcutContext = {},
): ShortcutDef | null {
  const available = SHORTCUT_DEFS.filter((def) => {
    if (def.scope === 'find') return Boolean(context.findOpen) && view === 'review';
    if (def.scope === 'global' || def.scope === 'view') return true;
    if (def.scope === 'review') return view === 'review';
    return false;
  });

  const inFindBar = insideFindBar(e.target);
  for (const def of available) {
    if (!comboMatches(e, comboOf(def.id))) continue;
    // 查找动作在查找栏里要能压过「输入框让位」规则：用户正在查找框/替换框里
    // 按快捷键是主要用法。焦点在正文编辑框里时仍然让位，不抢文字输入。
    if (def.scope === 'find') {
      if (!inFindBar && blocksShortcut(e, e.target)) continue;
    } else if (!def.allowInTyping && blocksShortcut(e, e.target, def.allowOnControls)) {
      continue;
    }
    return def;
  }
  return null;
}
