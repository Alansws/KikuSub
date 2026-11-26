import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { APPEARANCE_SHOTS, PALETTES } from '../renderer/src/lib/themes.ts';

/**
 * 守卫 1：六套色板 × 两个明暗的缩略图配色必须与 `app.css` 的基色块逐项一致。
 * 守卫 2：派生令牌（铬件 / 发丝线 / 强调洗色）必须从当前基色算，而不是写死第二份蓝灰。
 * 守卫 3：外观仍然只有 light / dark 两个解析值，明朝只改字体。
 *
 * 为什么需要：色板缩略图的颜色只能放注册表（六张卡要同时显示六套色，组件读当前
 * 令牌只能拿到一套），于是同一组颜色有了两个来源。色板越多，靠人记越会漂——
 * 改 CSS 忘了改注册表，卡片就会“看起来像旧版”。这里把两边冻在一起。
 *
 * `cobalt` 是默认色板，对应 `:root`（浅色）与 `html[data-theme='dark']`（深色），
 * 不另设 `[data-palette='cobalt']` 块——默认零成本。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP_CSS = path.join(HERE, '..', 'renderer', 'src', 'app.css');
const CSS = fs.readFileSync(APP_CSS, 'utf8');

const SELECTORS = {
  cobalt: {
    light: ':root',
    dark: "html[data-theme='dark']",
  },
  nord: {
    light: "html[data-palette='nord'][data-theme='light']",
    dark: "html[data-palette='nord'][data-theme='dark']",
  },
  'rose-pine': {
    light: "html[data-palette='rose-pine'][data-theme='light']",
    dark: "html[data-palette='rose-pine'][data-theme='dark']",
  },
  everforest: {
    light: "html[data-palette='everforest'][data-theme='light']",
    dark: "html[data-palette='everforest'][data-theme='dark']",
  },
  catppuccin: {
    light: "html[data-palette='catppuccin'][data-theme='light']",
    dark: "html[data-palette='catppuccin'][data-theme='dark']",
  },
  'cinema-amber': {
    light: "html[data-palette='cinema-amber'][data-theme='light']",
    dark: "html[data-palette='cinema-amber'][data-theme='dark']",
  },
};

/** 取出一个选择器的声明块（令牌里没有嵌套枝，第一个换行+右括号即块尾）。 */
function blockOf(selector) {
  const at = CSS.indexOf(`${selector} {`);
  assert.notEqual(at, -1, `app.css 里找不到 ${selector} 块`);
  const open = CSS.indexOf('{', at);
  const close = CSS.indexOf('\n}', open);
  assert.notEqual(close, -1, `${selector} 块没有闭合`);
  return CSS.slice(open + 1, close);
}

function tokensOf(block) {
  const out = new Map();
  for (const match of block.matchAll(/--([a-z0-9-]+)\s*:\s*([^;]+);/gi)) {
    out.set(`--${match[1].toLowerCase()}`, match[2].trim().replace(/\s+/g, ' '));
  }
  return out;
}

/** 缩略图要对账的令牌：card 读 --surface（台本纸），rule 读 --rule（实色发丝线）。 */
const KEYS = [
  ['canvas', '--canvas'],
  ['paper', '--paper'],
  ['card', '--surface'],
  ['ink', '--ink'],
  ['accent', '--accent'],
  ['rule', '--rule'],
];

test('六套色板 × 两个明暗的缩略图配色与 app.css 基色块一致', () => {
  assert.equal(PALETTES.length, 6, '色板注册表必须是 6 套');
  assert.equal(PALETTES[0].id, 'cobalt', '默认色板必须是 cobalt');

  const mismatches = [];
  for (const palette of PALETTES) {
    for (const theme of ['light', 'dark']) {
      const tokens = tokensOf(blockOf(SELECTORS[palette.id][theme]));
      const shot = theme === 'dark' ? palette.dark : palette.light;
      for (const [field, token] of KEYS) {
        const actual = tokens.get(token);
        if (!actual) {
          mismatches.push(`${palette.id}.${theme} 块缺少 ${token}`);
          continue;
        }
        const expected = String(shot[field]).replace(/\s+/g, ' ');
        if (actual.toLowerCase() !== expected.toLowerCase()) {
          mismatches.push(
            `${palette.id}.${theme}.${field}: themes.ts=${expected} / app.css ${token}=${actual}`,
          );
        }
      }
    }
  }

  assert.deepEqual(
    mismatches,
    [],
    '缩略图配色和 app.css 漂移了（改色板时两边要一起改）：\n' + mismatches.join('\n'),
  );
});

test('派生令牌从当前基色算，不再写死第二份蓝灰', () => {
  const root = tokensOf(blockOf(':root'));

  // 铬件：三块半透明面必须由 --paper 混合，而不是 rgba(245,245,247,…)
  for (const token of ['--bg-toolbar', '--bg-status', '--bg-sidebar']) {
    const value = root.get(token) ?? '';
    assert.match(value, /color-mix\(in srgb, var\(--paper\)/, `${token} 必须从 --paper 派生`);
    assert.match(value, /transparent/, `${token} 必须保留"叠在 vibrancy 上"的半透明语义`);
  }
  assert.equal(CSS.includes('245, 245, 247'), false, 'app.css 里仍有写死的旧铬件 rgba');
  assert.equal(CSS.includes('29, 29, 31'), false, 'app.css 里仍有写死的旧暗色铬件 rgba');

  // 强调色派生：选中洗色 / 焦点环 / 描边 / cue 记号都从 --accent / --accent-text 来
  assert.match(root.get('--accent-soft') ?? '', /var\(--accent-soft-color\)/);
  assert.match(root.get('--accent-ring') ?? '', /var\(--accent-ring-color\)/);
  assert.match(root.get('--accent-line') ?? '', /var\(--accent-line-color\)/);
  assert.match(root.get('--cue-block-active') ?? '', /var\(--accent\)/);
  assert.match(root.get('--cue-edge') ?? '', /var\(--cue-edge-color\)/);
  assert.match(root.get('--meter-a') ?? '', /var\(--accent\)/);

  // 凹陷边线 / 发丝线从明暗方向参数派生，色板与明暗都能接管
  for (const token of ['--line', '--rule', '--well-line', '--well-hover', '--well-focus']) {
    assert.ok(root.get(token), `--root 缺少 ${token}`);
  }
  assert.match(root.get('--well-line') ?? '', /var\(--neutral-wash\)/);

  // 每套色板都必须覆写“方向性”基色：rule / well / accent / stage-bg
  for (const palette of PALETTES.slice(1)) {
    for (const theme of ['light', 'dark']) {
      const tokens = tokensOf(blockOf(SELECTORS[palette.id][theme]));
      for (const token of ['--rule', '--well', '--accent', '--accent-text']) {
        assert.ok(tokens.get(token), `${palette.id}.${theme} 缺少 ${token}`);
      }
      if (theme === 'light') {
        assert.match(
          tokens.get('--stage-bg') ?? '',
          /color-mix/,
          `${palette.id} 浅色舞台必须从基色派生`,
        );
        assert.ok(tokens.get('--bg-inspector'), `${palette.id} 浅色缺少 --bg-inspector`);
      }
    }
  }
});

test('外观只有 light / dark 两个解析值，明朝只改字体', () => {
  assert.deepEqual(
    APPEARANCE_SHOTS.map((item) => item.id),
    ['light', 'dark'],
    '解析后的外观只允许 light / dark；明朝（mincho）不能再作为 data-theme 的取值',
  );

  // 旧的三主题块不允许复活：那会让「想用明朝字幕」被迫连整套配色一起换。
  assert.equal(
    CSS.includes("html[data-theme='mincho']"),
    false,
    "app.css 里仍有 html[data-theme='mincho']：明朝应当只走 data-cue-font",
  );

  const cueBlock = tokensOf(blockOf("html[data-cue-font='mincho']"));
  assert.deepEqual(
    [...cueBlock.keys()],
    ['--font-cue'],
    '明朝字体块只允许声明 --font-cue：字号 / 行高 / 颜色都不该在这里改',
  );
  assert.match(cueBlock.get('--font-cue') ?? '', /font-cue-mincho/);
});

test('外观与色板正交：主题块只管明暗，色板块只管基色', () => {
  const dark = tokensOf(blockOf("html[data-theme='dark']"));
  // 深色块继续负责"这一面是暗的"：下沉暗槽、抬升层、深色舞台
  for (const token of ['--stage', '--canvas', '--paper', '--surface', '--raise', '--well']) {
    assert.ok(dark.get(token), `深色块缺少 ${token}`);
  }
  // 色板块不声明 data-theme，声明的是 data-palette + data-theme 两个条件
  const paletteBlocks = [...CSS.matchAll(/html\[data-palette='([a-z-]+)'\]\[data-theme='(light|dark)'\]/g)];
  assert.equal(paletteBlocks.length, 10, '应恰好有 5 套非默认色板 × 2 个明暗块');
  assert.equal(
    paletteBlocks.some(([, id]) => id === 'cobalt'),
    false,
    'cobalt 是默认值，不应再有覆写块（否则默认色板会有两份来源）',
  );
});
