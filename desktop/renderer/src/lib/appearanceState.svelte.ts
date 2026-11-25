/**
 * 外观偏好的**响应式状态 + 落地**（偏好 / 字幕字体 / 系统外观）。
 *
 * 为什么单独一个模块：
 * 1. `lib/store.svelte.ts` 有只许变短的行数预算，而外观这块与工作区数据无关；
 * 2. 解析后的 `app.theme` 仍留在 store 里——核对台只认它来重绘波形，
 *    所以这里把解析结果写回 `app.theme`，同时写 `<html data-theme>`。
 *
 * 依赖方向是单向的：本模块 → store；store 不 import 本模块（否则成环）。
 * 纯读写 / 迁移逻辑在 `lib/appearance.ts`（可被 node --test 直接加载）。
 */
import { app } from './store.svelte';
import {
  applyToDocument,
  clearLegacyKeys,
  readAppearancePrefs,
  writeAppearance,
  writeCueFont,
} from './appearance';
import {
  isAppearanceId,
  isCueFontId,
  nextAppearance,
  resolveTheme,
  type AppearanceId,
  type CueFontId,
  type ThemeId,
} from './themes';

export const appearance = $state({
  /** 用户偏好：'auto' 跟随系统。 */
  preference: 'auto' as AppearanceId,
  /** 字幕字体：与明暗正交。 */
  cueFont: 'sans' as CueFontId,
  /** 系统当前是否深色（`prefers-color-scheme`）。 */
  systemDark: false,
});

/**
 * 解析 → 写 DOM → 通知主进程。
 * `next` 为空表示「不改偏好，按当前状态重算」（系统外观变化 / 冷启动）。
 */
function apply(next?: AppearanceId) {
  if (next && isAppearanceId(next)) appearance.preference = next;
  const theme: ThemeId = resolveTheme(
    appearance.preference,
    appearance.systemDark ? 'dark' : 'light',
  );
  // 核对台的波形按主题重绘，只读 app.theme；保持这一条镜像关系。
  app.theme = theme;
  writeAppearance(localStorage, appearance.preference);
  applyToDocument(theme, appearance.cueFont);
  // 传**偏好**而不是解析值：主进程在 auto 时要设 nativeTheme.themeSource='system'
  window.kikusub?.setAppearance?.(appearance.preference);
}

/** 设置页三选一。 */
export function setAppearance(id: AppearanceId) {
  apply(id);
}

/** ⇧⌘A / 标题栏外观按钮：跟随系统 → 日间校样 → 夜间配音 → 跟随系统。 */
export function toggleAppearance() {
  apply(nextAppearance(appearance.preference));
}

/** 字幕字体：黑体 / 明朝。只换 --font-cue，不动任何颜色。 */
export function setCueFont(id: CueFontId) {
  appearance.cueFont = isCueFontId(id) ? id : 'sans';
  writeCueFont(localStorage, appearance.cueFont);
  applyToDocument(app.theme, appearance.cueFont);
}

/** 冷启动补齐状态 + 订阅系统外观；返回解绑函数。 */
export function initAppearance(): () => void {
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  appearance.systemDark = mq.matches;
  const prefs = readAppearancePrefs(localStorage);
  appearance.preference = prefs.appearance;
  appearance.cueFont = prefs.cueFont;
  clearLegacyKeys(localStorage);
  apply();
  const onChange = () => {
    appearance.systemDark = mq.matches;
    if (appearance.preference === 'auto') apply();
  };
  mq.addEventListener('change', onChange);
  return () => mq.removeEventListener('change', onChange);
}
