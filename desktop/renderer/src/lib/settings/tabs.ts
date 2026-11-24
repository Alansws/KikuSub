/**
 * 设置页的四个子页签（2026-11 重构）。
 *
 * 为什么要独立成文件：页签 id 要同时被三处使用——侧栏 ⌘, 之后的落点（记忆）、
 * 截图脚本的 `?tab=`、以及测试。散在组件里就会出现「页面里叫 env、脚本里叫
 * diagnostics」这种对不上的情况。
 *
 * 侧栏的 ⌘1–⌘8 主导航与这里无关：页签只在设置页内部生效（设置是独立一页，
 * 见 docs/contracts/review-console.md §3.4.18）。
 */

export type SettingsTabId = 'engines' | 'appearance' | 'ai' | 'env';

export interface SettingsTabSpec {
  id: SettingsTabId;
  label: string;
  /** Icon.svelte 的图标名（不要用 emoji）。 */
  icon: string;
  /** 读屏与首次进入时的一句话。 */
  hint: string;
}

export const SETTINGS_TABS: SettingsTabSpec[] = [
  {
    id: 'engines',
    label: '引擎与模型',
    icon: 'chip',
    hint: '本机模型总览与四个转写引擎',
  },
  {
    id: 'appearance',
    label: '外观与朗读',
    icon: 'swatch',
    hint: '主题与 TTS 默认偏好',
  },
  {
    id: 'ai',
    label: 'AI 与技能',
    icon: 'sparkle',
    hint: 'AI 接口、密钥与 Agent 技能',
  },
  {
    id: 'env',
    label: '环境与诊断',
    icon: 'gauge',
    hint: '硬件、路径与日志',
  },
];

/** 记忆用：上次停在哪一页。 */
export const SETTINGS_TAB_STORAGE_KEY = 'kikusub.settingsTab';

interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const DEFAULT_TAB: SettingsTabId = 'engines';

export function isSettingsTabId(value: unknown): value is SettingsTabId {
  return SETTINGS_TABS.some((tab) => tab.id === value);
}

/** 读上次的页签；旧值/坏值/无 localStorage 都退回第一页。 */
export function readSettingsTab(storage?: StorageLike | null): SettingsTabId {
  const store = storage ?? (typeof localStorage === 'undefined' ? null : localStorage);
  if (!store) return DEFAULT_TAB;
  try {
    const raw = store.getItem(SETTINGS_TAB_STORAGE_KEY);
    return isSettingsTabId(raw) ? raw : DEFAULT_TAB;
  } catch {
    return DEFAULT_TAB;
  }
}

export function saveSettingsTab(id: SettingsTabId, storage?: StorageLike | null) {
  const store = storage ?? (typeof localStorage === 'undefined' ? null : localStorage);
  if (!store || !isSettingsTabId(id)) return;
  try {
    store.setItem(SETTINGS_TAB_STORAGE_KEY, id);
  } catch {
    /* 隐私模式写不进去时忽略：页签记忆不是关键数据 */
  }
}

/** ↑/↓ 切换：到头绕回另一端（macOS 侧栏列表的习惯；分段控件时代是 ←/→）。 */
export function stepSettingsTab(current: SettingsTabId, delta: number): SettingsTabId {
  const index = SETTINGS_TABS.findIndex((tab) => tab.id === current);
  if (index < 0) return DEFAULT_TAB;
  const count = SETTINGS_TABS.length;
  const next = (((index + delta) % count) + count) % count;
  return SETTINGS_TABS[next].id;
}

export { DEFAULT_TAB as DEFAULT_SETTINGS_TAB };
