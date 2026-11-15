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

/**
 * 设置页「外观与朗读」的三张缩略图。
 *
 * 为什么颜色放在注册表而不是 app.css：三张缩略图要**同时**显示三套主题，
 * 组件读当前主题的令牌只能拿到一套颜色。这里是“主题元信息”的唯一位置，
 * 组件只消费 `--shot-*` 变量，不写死色值。
 *
 * `desktop/test/theme-preview.test.mjs` 会把这些值与 app.css 对应主题块的
 * `--canvas / --paper / --raise / --ink / --accent / --line` 逐项对账，漂移就红。
 */
export interface ThemePreview {
  id: ThemeId;
  name: string;
  note: string;
  canvas: string;
  paper: string;
  /** 内容卡（= app.css 的 --raise）。 */
  card: string;
  ink: string;
  accent: string;
  line: string;
  /** 字幕字体角色：明朝墨用明朝，其余跟 UI 一致（缩略图里要看得出来）。 */
  cueFont: 'sans' | 'mincho';
}

export const THEME_PREVIEWS: ThemePreview[] = [
  {
    id: 'light',
    name: '青空浅',
    note: '浅天蓝 + 靛蓝，默认主题',
    canvas: '#edf3fb',
    paper: '#f9fbfe',
    card: '#ffffff',
    ink: '#1b2740',
    accent: '#4f6bff',
    line: 'rgba(27, 39, 64, 0.12)',
    cueFont: 'sans',
  },
  {
    id: 'dark',
    name: '青空深',
    note: '深空底 + 亮靛蓝，夜间校对',
    canvas: '#0a0c10',
    paper: '#111419',
    card: '#181c23',
    ink: '#ecf1fa',
    accent: '#7d93ff',
    line: 'rgba(236, 241, 250, 0.13)',
    cueFont: 'sans',
  },
  {
    id: 'mincho',
    name: '明朝墨',
    note: '纸白 + 墨黑 + 朱红，字幕用明朝',
    canvas: '#f1f3f0',
    paper: '#fafaf8',
    card: '#ffffff',
    ink: '#15181b',
    accent: '#c8412d',
    line: 'rgba(21, 24, 27, 0.12)',
    cueFont: 'mincho',
  },
];

/** 缩略图里那句日文字幕：三张卡用同一句，方便横向比较字体与色。 */
export const THEME_PREVIEW_CUE = 'ここで待っていたんだよ、ずっと。';
