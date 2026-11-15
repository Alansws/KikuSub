import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { THEME_PREVIEWS } from '../renderer/src/lib/themes.ts';

/**
 * 守卫：设置页的三张主题缩略图必须与 `app.css` 的主题块逐项一致。
 *
 * 为什么需要：缩略图的颜色只能放注册表（三套要同时显示，组件读当前主题令牌
 * 只能拿到一套），于是同一组颜色有了两个来源。这种“两处写同一个值”的地方
 * 靠人记一定会漂——改主题时只改一边，缩略图就会「看起来像旧版」。
 * 这里把两边冻在一起：改任何一边，另一边没跟上就红。
 *
 * 只对账 6 个可判定的值（canvas / paper / raise / ink / accent / line）。
 * 渐变、阴影等派生令牌不在这里比——它们没有“唯一正确值”。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP_CSS = path.join(HERE, '..', 'renderer', 'src', 'app.css');
const CSS = fs.readFileSync(APP_CSS, 'utf8');

const SELECTOR = {
  light: ':root',
  dark: "html[data-theme='dark']",
  mincho: "html[data-theme='mincho']",
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

const KEYS = [
  ['canvas', '--canvas'],
  ['paper', '--paper'],
  ['card', '--raise'],
  ['ink', '--ink'],
  ['accent', '--accent'],
  ['line', '--line'],
];

test('三张缩略图的配色与 app.css 主题块一致', () => {
  const mismatches = [];

  for (const preview of THEME_PREVIEWS) {
    const tokens = tokensOf(blockOf(SELECTOR[preview.id]));
    for (const [field, token] of KEYS) {
      const actual = tokens.get(token);
      assert.ok(actual, `${preview.id} 块缺少 ${token}`);
      const expected = String(preview[field]).replace(/\s+/g, ' ');
      if (actual.toLowerCase() !== expected.toLowerCase()) {
        mismatches.push(
          `${preview.id}.${field}: themes.ts=${expected} / app.css ${token}=${actual}`,
        );
      }
    }
  }

  assert.deepEqual(
    mismatches,
    [],
    '缩略图配色和 app.css 漂移了（改主题时两边要一起改）：\n' + mismatches.join('\n'),
  );
});

test('三张缩略图覆盖三套主题，且只有明朝墨换字幕字体', () => {
  assert.deepEqual(
    THEME_PREVIEWS.map((item) => item.id),
    ['light', 'dark', 'mincho'],
    '缩略图顺序应与设置页展示顺序一致（青空浅 / 青空深 / 明朝墨）',
  );
  assert.equal(
    THEME_PREVIEWS.find((item) => item.id === 'mincho')?.cueFont,
    'mincho',
    '明朝墨的缩略图必须用明朝字幕，否则用户看不出这套主题的区别',
  );
  assert.deepEqual(
    THEME_PREVIEWS.filter((item) => item.id !== 'mincho').map((item) => item.cueFont),
    ['sans', 'sans'],
  );
});
