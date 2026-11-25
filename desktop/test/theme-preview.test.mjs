import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { APPEARANCE_SHOTS } from '../renderer/src/lib/themes.ts';

/**
 * 守卫：设置页的外观缩略图必须与 `app.css` 的外观块逐项一致。
 *
 * 为什么需要：缩略图的颜色只能放注册表（三张卡要同时显示两套配色，组件读当前
 * 主题令牌只能拿到一套），于是同一组颜色有了两个来源。这种“两处写同一个值”
 * 的地方靠人记一定会漂——改外观时只改一边，缩略图就会「看起来像旧版」。
 * 这里把两边冻在一起：改任何一边，另一边没跟上就红。
 *
 * 2026-11-25：外观从三套（light/dark/mincho）收敛成两套，明朝降为
 * `html[data-cue-font='mincho']` 的字体偏好，不再是第三块色板。所以这里只对账
 * light / dark 两块，并额外断言字体块存在且只改 `--font-cue`。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP_CSS = path.join(HERE, '..', 'renderer', 'src', 'app.css');
const CSS = fs.readFileSync(APP_CSS, 'utf8');

const SELECTOR = {
  light: ':root',
  dark: "html[data-theme='dark']",
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

/**
 * 缩略图要对账的令牌。
 *
 * `card` 读 **`--surface`**（面板 / 台本层）而不是 `--raise`：2026-11-26 第三次
 * 修正把暗色的「台本纸」与「按钮/浮层」拆成了两档（#242427 / #313135），
 * 缩略图里那张小卡片是台本纸，不是浮层按钮。
 */
const KEYS = [
  ['canvas', '--canvas'],
  ['paper', '--paper'],
  ['card', '--surface'],
  ['ink', '--ink'],
  ['accent', '--accent'],
  ['line', '--line'],
];

test('两张外观缩略图的配色与 app.css 外观块一致', () => {
  const mismatches = [];

  for (const shot of APPEARANCE_SHOTS) {
    const tokens = tokensOf(blockOf(SELECTOR[shot.id]));
    for (const [field, token] of KEYS) {
      const actual = tokens.get(token);
      assert.ok(actual, `${shot.id} 块缺少 ${token}`);
      const expected = String(shot[field]).replace(/\s+/g, ' ');
      if (actual.toLowerCase() !== expected.toLowerCase()) {
        mismatches.push(`${shot.id}.${field}: themes.ts=${expected} / app.css ${token}=${actual}`);
      }
    }
  }

  assert.deepEqual(
    mismatches,
    [],
    '缩略图配色和 app.css 漂移了（改外观时两边要一起改）：\n' + mismatches.join('\n'),
  );
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
    'app.css 里仍有 html[data-theme=\'mincho\']：明朝应当只走 data-cue-font',
  );

  const cueBlock = tokensOf(blockOf("html[data-cue-font='mincho']"));
  assert.deepEqual(
    [...cueBlock.keys()],
    ['--font-cue'],
    '明朝字体块只允许声明 --font-cue：字号 / 行高 / 颜色都不该在这里改',
  );
  assert.match(cueBlock.get('--font-cue'), /font-cue-mincho/);
});
