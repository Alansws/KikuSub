/**
 * 可自定义键盘快捷键。
 *
 * 菜单里的固定 accelerator 不能跟着用户改，所以核对台的播放 / 上下句 / 删除、
 * 视图切换与 AI 优化台的润色 / 翻译都收在渲染层这一张表里。主进程菜单只保留
 * 点击动作，不再抢占这些按键（否则 ⌘1 在 AI 优化台里永远先切到「导入」）。
 */

import type { View } from './store.svelte';

export type ShortcutScope = 'global' | 'review' | 'ai' | 'view';

export interface ShortcutDef {
  id: string;
  label: string;
  group: string;
  scope: ShortcutScope;
  /** 默认组合；格式见 `comboFromEvent`（mod / alt / shift + 键名）。 */
  def: string;
  /** 输入框聚焦时是否仍然生效（视图切换、打开面板等）。 */
  allowInTyping?: boolean;
  /** 同一组合在某个上下文里优先于另一组（AI 优化台的 ⌘1/⌘2 优先于视图切换）。 */
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
  },
  {
    id: 'review.nextCue',
    label: '下一句',
    group: '核对台',
    scope: 'review',
    def: 'arrowdown',
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
    id: 'review.find',
    label: '查找与替换',
    group: '核对台',
    // 从任意页面按 ⌘F 都应切到核对台并打开查找栏
    scope: 'global',
    def: 'mod+f',
    allowInTyping: true,
  },
  {
    id: 'review.toggleQa',
    label: '打开 / 收起质检面板',
    group: '核对台',
    scope: 'review',
    def: 'mod+shift+k',
  },
  {
    id: 'ai.polish',
    label: '润色',
    group: 'AI 优化台',
    scope: 'ai',
    def: 'mod+1',
    allowInTyping: true,
    note: '在 AI 优化台内优先于视图切换',
  },
  {
    id: 'ai.translate',
    label: '翻译',
    group: 'AI 优化台',
    scope: 'ai',
    def: 'mod+2',
    allowInTyping: true,
    note: '在 AI 优化台内优先于视图切换',
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
    label: '核对',
    group: '视图',
    scope: 'view',
    def: 'mod+3',
    allowInTyping: true,
  },
  {
    id: 'view.export',
    label: '导出',
    group: '视图',
    scope: 'view',
    def: 'mod+4',
    allowInTyping: true,
  },
  {
    id: 'view.report',
    label: '任务详报',
    group: '视图',
    scope: 'view',
    def: 'mod+5',
    allowInTyping: true,
  },
];

const STORAGE_KEY = 'kikusub.shortcuts.v1';

const DEFAULTS: Record<string, string> = Object.fromEntries(
  SHORTCUT_DEFS.map((def) => [def.id, def.def]),
);

function loadMap(): Record<string, string> {
  const map = { ...DEFAULTS };
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    if (raw && typeof raw === 'object') {
      for (const def of SHORTCUT_DEFS) {
        const value = raw[def.id];
        if (typeof value === 'string' && value.trim()) map[def.id] = value;
      }
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
  /** 录制时的重复提示。 */
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

/** 同一个组合被别的动作占用时返回那个动作；AI / 视图两组允许同键（上下文优先）。 */
export function conflictingShortcut(id: string, combo: string): ShortcutDef | null {
  const current = shortcutDef(id);
  if (!current) return null;
  for (const other of SHORTCUT_DEFS) {
    if (other.id === id || comboOf(other.id) !== combo) continue;
    const ctxPair =
      (current.scope === 'ai' && other.scope === 'view') ||
      (current.scope === 'view' && other.scope === 'ai');
    if (ctxPair) continue;
    return other;
  }
  return null;
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

/** 把一次 keydown 变成可持久化的组合；纯修饰键返回 null。 */
export function comboFromEvent(e: KeyboardEvent): string | null {
  const key = normalizeKey(e.key);
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
    key,
  };
}

export function comboMatches(e: KeyboardEvent, combo: string): boolean {
  const parsed = parseCombo(combo);
  if (!parsed.key) return false;
  if (parsed.mod !== Boolean(e.metaKey || e.ctrlKey)) return false;
  if (parsed.alt !== Boolean(e.altKey)) return false;
  if (parsed.shift !== Boolean(e.shiftKey)) return false;
  return normalizeKey(e.key) === parsed.key;
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
function blocksShortcut(e: KeyboardEvent, target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  if (isTextEntry(el)) return true;
  const tag = el.tagName;
  const key = normalizeKey(e.key);
  if (tag === 'SELECT') return true;
  if (tag === 'BUTTON' || tag === 'A') {
    return [' ', 'enter', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'tab'].includes(key);
  }
  if (tag === 'INPUT') {
    return [' ', 'enter', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'tab'].includes(key);
  }
  return false;
}

const SCOPE_ORDER: Record<ShortcutScope, number> = {
  ai: 0,
  review: 0,
  view: 1,
  global: 2,
};

/**
 * 找出这次按键对应的动作。上下文优先：AI 优化台里 ⌘1/⌘2 切润色 / 翻译，
 * 在其他页面才按视图快捷键理解。
 */
export function resolveShortcut(e: KeyboardEvent, view: View): ShortcutDef | null {
  const available = SHORTCUT_DEFS.filter((def) => {
    if (def.scope === 'global') return true;
    if (def.scope === 'view') return true;
    if (def.scope === 'review') return view === 'review';
    return view === 'ai';
  }).sort((a, b) => SCOPE_ORDER[a.scope] - SCOPE_ORDER[b.scope]);

  for (const def of available) {
    if (!comboMatches(e, comboOf(def.id))) continue;
    if (!def.allowInTyping && blocksShortcut(e, e.target)) continue;
    return def;
  }
  return null;
}
