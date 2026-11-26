/**
 * 外观注册表（Cue Script）。
 *
 * 两件事被拆开了（2026-11-25 用户拍板）：
 *
 * 1. **外观偏好** `auto | light | dark` —— `auto` 跟随系统，是默认。
 *    解析后的结果才是 `data-theme` 的取值，只有 `light` / `dark` 两个。
 * 2. **字幕字体** `sans | mincho` —— 与明暗正交的阅读偏好，只换 `--font-cue`。
 *
 * 「明朝墨」不再是第三套配色：它曾经是 `data-theme='mincho'`，既有自己的
 * 色板又有自己的字体，结果「想用明朝字幕」被迫连整套配色一起换。现在分开，
 * 一个偏好只回答一个问题。
 *
 * 组件一律不写主题分支：`data-theme` 由 store 解析后写到 `<html>`，
 * 色板在 app.css，这里只放「有哪些值、叫什么、缩略图长什么样」。
 */

/** 解析后的外观：只可能是这两个值，写进 `html[data-theme]`。 */
export type ThemeId = 'light' | 'dark';
/** 用户的偏好；`auto` 跟随系统。 */
export type AppearanceId = 'auto' | ThemeId;
/** 字幕字体偏好，写进 `html[data-cue-font]`。 */
export type CueFontId = 'sans' | 'mincho';

/**
 * 皮肤色板，写进 `html[data-palette]`。
 *
 * 与 `data-theme` 正交：色板只回答"用哪套基色"，明暗仍由 `data-theme` 回答。
 * 默认 `cobalt` 就是第一阶段封板的那套蓝/灰，不加任何覆写块。
 */
export type PaletteId =
  | 'cobalt'
  | 'nord'
  | 'rose-pine'
  | 'everforest'
  | 'catppuccin'
  | 'cinema-amber';

/** 系统外观（`prefers-color-scheme`）的取值。 */
export type SystemScheme = ThemeId;

export interface AppearanceOption {
  id: AppearanceId;
  name: string;
  note: string;
}

export const APPEARANCES: AppearanceOption[] = [
  {
    id: 'auto',
    name: '跟随系统',
    note: '白天日间校样，入夜自动切夜间配音间；一般不用动它',
  },
  { id: 'light', name: '日间校样', note: '纸白台面 · 墨 · 蓝铅笔，适合白天与交付前通读' },
  { id: 'dark', name: '夜间配音', note: '纯中性深炭黑 · 下沉暗槽 · 画面是唯一亮面' },
];

export interface CueFontOption {
  id: CueFontId;
  name: string;
  note: string;
}

export const CUE_FONTS: CueFontOption[] = [
  { id: 'sans', name: '黑体', note: '系统黑体（Hiragino Sans）；长时间扫读更稳，是默认' },
  { id: 'mincho', name: '明朝', note: 'Hiragino Mincho；字幕的「书」感更强，适合通读' },
];

export function isThemeId(value: unknown): value is ThemeId {
  return value === 'light' || value === 'dark';
}

export function isAppearanceId(value: unknown): value is AppearanceId {
  return value === 'auto' || isThemeId(value);
}

export function isCueFontId(value: unknown): value is CueFontId {
  return value === 'sans' || value === 'mincho';
}

export function isPaletteId(value: unknown): value is PaletteId {
  return PALETTES.some((palette) => palette.id === value);
}

export const DEFAULT_PALETTE: PaletteId = 'cobalt';

/** 偏好 × 系统外观 → `data-theme`。 */
export function resolveTheme(appearance: AppearanceId, system: SystemScheme): ThemeId {
  return appearance === 'auto' ? system : appearance;
}

export const appearanceName = (id: AppearanceId): string =>
  APPEARANCES.find((item) => item.id === id)?.name ?? id;

export const cueFontName = (id: CueFontId): string =>
  CUE_FONTS.find((item) => item.id === id)?.name ?? id;

export const paletteName = (id: PaletteId): string =>
  PALETTES.find((item) => item.id === id)?.name ?? id;


/* ============================================================
   色板注册表
   ============================================================ */

/**
 * 一张色板缩略图要用的最小基色集合。
 *
 * 这里只放**缩略图确实要画的颜色**，不是全量令牌；全量令牌在 app.css。
 * `desktop/test/theme-preview.test.mjs` 会把六个色板 × 两个明暗的这组值与
 * app.css 对应块逐项对账，任何一边漂移都会红。
 *
 * `card` 读 `--surface`（台本纸 / 卡片层），`rule` 读 `--rule`（1px 发丝线）。
 * 特意不读 `--line`：它是 color-mix 派生值，缩略图只需要一条能画出来的实色边。
 */
export interface PaletteShot {
  canvas: string;
  paper: string;
  card: string;
  ink: string;
  accent: string;
  rule: string;
}

export interface PaletteOption {
  id: PaletteId;
  name: string;
  note: string;
  light: PaletteShot;
  dark: PaletteShot;
}

/**
 * 六套双模色板。数值与 app.css 的基色块一一对应：
 * `cobalt` 对应 `:root` / `html[data-theme='dark']`，其余对应
 * `html[data-palette='…'][data-theme='…']`。
 *
 * 排序就是设置页卡片的顺序：默认钴蓝在最前，其余按冷暖/明暗气质排开。
 */
export const PALETTES: PaletteOption[] = [
  {
    id: 'cobalt',
    name: '皇家钴蓝',
    note: '净白纸台 · 纯中性炭黑；第一阶段封板的标准色板',
    light: {
      canvas: '#ffffff',
      paper: '#f5f5f7',
      card: '#ffffff',
      ink: '#15191c',
      accent: '#295ce6',
      rule: '#e2e2e7',
    },
    dark: {
      canvas: '#161618',
      paper: '#1d1d1f',
      card: '#242427',
      ink: '#ededef',
      accent: '#3467eb',
      rule: '#303034',
    },
  },
  {
    id: 'nord',
    name: '北欧极夜',
    note: 'Snow Storm 冷调纸面 / Polar Night 极夜蓝灰',
    light: {
      canvas: '#f7f9fc',
      paper: '#eceff4',
      card: '#ffffff',
      ink: '#2e3440',
      accent: '#456e9e',
      rule: '#d8dee9',
    },
    dark: {
      canvas: '#242933',
      paper: '#2e3440',
      card: '#353c4a',
      ink: '#eceff4',
      accent: '#4772a6',
      rule: '#3b4252',
    },
  },
  {
    id: 'rose-pine',
    name: '玫瑰松木',
    note: 'Dawn 暖手稿纸 / Main 黑胶紫墨',
    light: {
      canvas: '#fffaf3',
      paper: '#faf4ed',
      card: '#fffcf8',
      ink: '#575279',
      accent: '#286983',
      rule: '#e4d8ce',
    },
    dark: {
      canvas: '#191724',
      paper: '#1f1d2e',
      card: '#26233a',
      ink: '#e0def4',
      accent: '#31748f',
      rule: '#2e2a44',
    },
  },
  {
    id: 'everforest',
    name: '暮森护眼',
    note: '暖纸米色 / 深林绿灰；长时间阅读更松弛',
    light: {
      canvas: '#fcf8ec',
      paper: '#f3ead3',
      card: '#fffdf5',
      ink: '#424e54',
      accent: '#277355',
      rule: '#dfd5b7',
    },
    dark: {
      canvas: '#1e2428',
      paper: '#272e33',
      card: '#2e373c',
      ink: '#d3c6aa',
      accent: '#2b7e5e',
      rule: '#374248',
    },
  },
  {
    id: 'catppuccin',
    name: '拿铁与摩卡',
    note: 'Latte 清凉拿铁 / Mocha 紫调摩卡',
    light: {
      canvas: '#f7f8fc',
      paper: '#eff1f5',
      card: '#ffffff',
      ink: '#4c4f69',
      accent: '#1e66f5',
      rule: '#dce0e8',
    },
    dark: {
      canvas: '#181825',
      paper: '#1e1e2e',
      card: '#26273a',
      ink: '#cdd6f4',
      accent: '#3b6ce2',
      rule: '#313244',
    },
  },
  {
    id: 'cinema-amber',
    name: '暗房琥珀',
    note: '暖白暗房纸 / 放映间琥珀；强调色偏胶片',
    light: {
      canvas: '#fcfbf7',
      paper: '#f4f1ea',
      card: '#ffffff',
      ink: '#1f1d1a',
      accent: '#b45309',
      rule: '#e0dbd0',
    },
    dark: {
      canvas: '#141413',
      paper: '#1b1b19',
      card: '#232320',
      ink: '#ecebe6',
      accent: '#b8590c',
      rule: '#2e2e2a',
    },
  },
];

export const paletteShot = (id: PaletteId, theme: ThemeId): PaletteShot => {
  const palette = PALETTES.find((item) => item.id === id) ?? PALETTES[0];
  return theme === 'dark' ? palette.dark : palette.light;
};

/**
 * 标题栏按钮 / ⇧⌘A：**直接两态翻转**。
 *
 * 2026-11-26 用户反馈：之前这里在 `auto → light → dark → auto` 之间循环，
 * 于是「跟随系统且系统是浅色」时，想切到夜间要先点一下（先变成显式 light，
 * 视觉上没变化）再点第二下。工具栏按钮不该考这个脑筋。
 *
 * 现在只回答一个问题：**从眼前的画面翻到另一面**。所以取的是解析后的
 * `current`（`auto` 已经解析成光/暗），返回它的反面并写成显式偏好。
 * 「跟随系统」只留在设置 → 外观里，不再进这条循环。
 */
export function flipAppearance(current: ThemeId): ThemeId {
  return current === 'dark' ? 'light' : 'dark';
}

/**
 * 设置页外观缩略图的配色（日间 / 夜间两张，`auto` 卡用左右拼合）。
 *
 * 颜色从 `PALETTES` 的 cobalt 取，避免同一组色值维护两份；缩略图组件只消费
 * `--shot-*` 变量。`theme-preview.test.mjs` 会把这三处（注册表 / app.css /
 * 组件）钉在一起。`rule` 读 `--rule`：缩略图只需要一条画得出来的实色边，
 * `--line` 是 color-mix 派生值，不参与缩略图。
 */
export interface AppearanceShot {
  id: ThemeId;
  name: string;
  note: string;
  canvas: string;
  paper: string;
  /** 台本纸 / 内容卡（= app.css 的 --surface）。 */
  card: string;
  ink: string;
  accent: string;
  rule: string;
}

const cobalt = PALETTES[0];

export const APPEARANCE_SHOTS: AppearanceShot[] = [
  {
    id: 'light',
    name: '日间校样',
    note: '明亮纸台面 · 墨 · 强调色；白天与交付前通读',
    ...cobalt.light,
  },
  {
    id: 'dark',
    name: '夜间配音',
    note: '深色台面 · 下沉暗槽 · 画面是唯一亮面',
    ...cobalt.dark,
  },
];

/** 缩略图里那句日文字幕：三张卡用同一句，方便横向比较字体与色。 */
export const THEME_PREVIEW_CUE = 'ここで待っていたんだよ、ずっと。';
