/**
 * 主题注册表。
 *
 * 一个外观 id 对应 `app.css` 里的一块 `html[data-theme='<id>']` 令牌覆盖。
 * 组件不再写主题分支：新主题 = 这里加一条 + app.css 写一块覆盖，其他地方不动。
 *
 * `scheme` 只影响两件事：主进程的 `nativeTheme`（侧栏毛玻璃 / 红绿灯）
 * 和 `color-scheme`（原生滚动条、表单控件）。它跟外观 id 不是一回事——
 * 「明朝墨」是浅色 scheme 的一次性主题，没有深色变体。
 */

export type ThemeId = 'light' | 'dark' | 'mincho';
export type SkinId = 'clear' | 'mincho';
export type Scheme = 'light' | 'dark';

export interface Skin {
  id: SkinId;
  /** 设置页里的名字。 */
  name: string;
  /** 一句话调性；鼠标悬停和读屏都能看到。 */
  note: string;
  /** 预览色块：底 / 强调 / 墨。 */
  swatch: [string, string, string];
  /** 这套主题自带的明暗基调。单元素就是「固定浅色」。 */
  schemes: Scheme[];
}

export const SKINS: Skin[] = [
  {
    id: 'clear',
    name: '青空',
    note: '浅天蓝 + 靛蓝，默认主题，浅色与深色两套',
    swatch: ['#edf3fb', '#4f6bff', '#1b2740'],
    schemes: ['light', 'dark'],
  },
  {
    id: 'mincho',
    name: '明朝墨',
    note: '纸白 + 墨黑 + 一点朱红；只有字幕用明朝，固定浅色',
    swatch: ['#f1f3f0', '#c8412d', '#15181b'],
    schemes: ['light'],
  },
];

interface ThemeMeta {
  skin: SkinId;
  scheme: Scheme;
  name: string;
}

const META: Record<ThemeId, ThemeMeta> = {
  light: { skin: 'clear', scheme: 'light', name: '浅色' },
  dark: { skin: 'clear', scheme: 'dark', name: '深色' },
  mincho: { skin: 'mincho', scheme: 'light', name: '明朝墨' },
};

export function isThemeId(value: unknown): value is ThemeId {
  return value === 'light' || value === 'dark' || value === 'mincho';
}

export const schemeOf = (theme: ThemeId): Scheme => META[theme].scheme;
export const skinOf = (theme: ThemeId): SkinId => META[theme].skin;
export const themeName = (theme: ThemeId): string => META[theme].name;

/** 青空的两档明暗；单色主题在设置页里禁用这一行。 */
export const SCHEMES: { id: Scheme; name: string }[] = [
  { id: 'light', name: '浅色' },
  { id: 'dark', name: '深色' },
];
