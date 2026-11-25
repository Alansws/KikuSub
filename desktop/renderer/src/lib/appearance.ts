/**
 * 外观偏好的读取 / 迁移 / 落盘（纯函数，不 import store）。
 *
 * 为什么单独一层：`lib/store.svelte.ts` 有只许变短的行数预算，而外观这块
 * 「读 localStorage → 迁旧 key → 解析 → 写 DOM」是完全可以脱离 store 测的
 * 纯逻辑。抽出来之后 store 里只剩十几行接线，红线和可测性都受益。
 *
 * 存储约定（2026-11-25 起）：
 * - `kikusub.appearance`：'auto' | 'light' | 'dark'
 * - `kikusub.cueFont`：'sans' | 'mincho'
 * - 旧版的 `kikusub.theme`（'light' / 'dark' / 'mincho' / 'cool'）只读一次即迁，
 *   迁完删除；`kikusub.mode` 同样删除。
 *
 * 这些 key 都写在 `localStorage` 里，而每张截图 / 试用实例有独立的
 * `--user-data-dir`，所以新界面的偏好不会污染用户正在用的旧版（台账 §0.1）。
 */
/**
 * 注意这里是**显式 `.ts` 扩展名**：`desktop/test/appearance.test.mjs` 用
 * `node --test` 直接加载本文件，Node 的类型剥离不解析无扩展名的相对导入。
 * 项目里只有这一处这样写（tsconfig 开了 allowImportingTsExtensions）。
 */
import {
  isAppearanceId,
  isCueFontId,
  type AppearanceId,
  type CueFontId,
  type ThemeId,
} from './themes.ts';

export const APPEARANCE_KEY = 'kikusub.appearance';
export const CUE_FONT_KEY = 'kikusub.cueFont';
const LEGACY_THEME_KEY = 'kikusub.theme';
const LEGACY_MODE_KEY = 'kikusub.mode';

/** 只需要 getItem，方便单测传一个假 Storage。 */
type ReadableStorage = Pick<Storage, 'getItem'>;
/** 只需要 setItem / removeItem。 */
type WritableStorage = Pick<Storage, 'setItem' | 'removeItem'>;

export interface AppearancePrefs {
  appearance: AppearanceId;
  cueFont: CueFontId;
}

export function readAppearancePrefs(storage: ReadableStorage): AppearancePrefs {
  const legacy = storage.getItem(LEGACY_THEME_KEY);
  const savedAppearance = storage.getItem(APPEARANCE_KEY);
  const savedCue = storage.getItem(CUE_FONT_KEY);

  const appearance: AppearanceId = isAppearanceId(savedAppearance)
    ? savedAppearance
    : legacy === 'light' || legacy === 'dark'
      ? legacy
      : 'auto';

  const cueFont: CueFontId = isCueFontId(savedCue)
    ? savedCue
    : legacy === 'mincho' || legacy === 'cool'
      ? 'mincho'
      : 'sans';

  return { appearance, cueFont };
}

/** 旧 key 读一次就删：它们代表两套已经作废的模型（青空 / 明朝墨）。 */
export function clearLegacyKeys(storage: WritableStorage): void {
  storage.removeItem(LEGACY_THEME_KEY);
  storage.removeItem(LEGACY_MODE_KEY);
}

export function writeAppearance(storage: WritableStorage, appearance: AppearanceId): void {
  storage.setItem(APPEARANCE_KEY, appearance);
}

export function writeCueFont(storage: WritableStorage, cueFont: CueFontId): void {
  storage.setItem(CUE_FONT_KEY, cueFont);
}

/** 偏好 × 系统外观 → 写进 `<html>` 的两个 data 属性。 */
export function applyToDocument(
  theme: ThemeId,
  cueFont: CueFontId,
  root: HTMLElement = document.documentElement,
): void {
  root.dataset.theme = theme;
  root.dataset.cueFont = cueFont;
}
