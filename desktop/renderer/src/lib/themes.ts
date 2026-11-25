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
  { id: 'dark', name: '夜间配音', note: '碳黑剪辑台 · 暖纸白字，画面是唯一亮面' },
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

/** 偏好 × 系统外观 → `data-theme`。 */
export function resolveTheme(appearance: AppearanceId, system: SystemScheme): ThemeId {
  return appearance === 'auto' ? system : appearance;
}

export const appearanceName = (id: AppearanceId): string =>
  APPEARANCES.find((item) => item.id === id)?.name ?? id;

export const cueFontName = (id: CueFontId): string =>
  CUE_FONTS.find((item) => item.id === id)?.name ?? id;

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
 * 设置页三张外观缩略图的配色。
 *
 * 为什么颜色放在注册表而不是 app.css：三张缩略图要**同时**显示三套配色，
 * 组件读当前主题的令牌只能拿到一套。这里是「外观元信息」的唯一位置，
 * 组件只消费 `--shot-*` 变量，不写死色值。
 *
 * `desktop/test/theme-preview.test.mjs` 会把这些值与 app.css 对应块的
 * `--canvas / --paper / --raise / --ink / --accent / --line` 逐项对账，漂移就红。
 * `line` 与 app.css 一样保留 rgba：测试按字符串对账，换成等效实色会两边都读不出同一个值。
 */
export interface AppearanceShot {
  id: ThemeId;
  name: string;
  note: string;
  canvas: string;
  paper: string;
  /** 台本纸 / 内容卡（= app.css 的 --raise）。 */
  card: string;
  ink: string;
  accent: string;
  line: string;
}

export const APPEARANCE_SHOTS: AppearanceShot[] = [
  {
    id: 'light',
    name: '日间校样',
    note: '纸白台面 · 铬件浅灰 · 蓝铅笔',
    canvas: '#ffffff',
    paper: '#f0f2f4',
    card: '#ffffff',
    ink: '#15191c',
    accent: '#0b63e5',
    line: 'rgba(21, 25, 28, 0.14)',
  },
  {
    id: 'dark',
    name: '夜间配音',
    note: '碳灰四阶 · 暖纸白字',
    canvas: '#1a1c1f',
    paper: '#24272b',
    card: '#2c3136',
    ink: '#e9e6df',
    accent: '#84a9e6',
    line: 'rgba(236, 232, 223, 0.15)',
  },
];

/** 缩略图里那句日文字幕：三张卡用同一句，方便横向比较字体与色。 */
export const THEME_PREVIEW_CUE = 'ここで待っていたんだよ、ずっと。';
