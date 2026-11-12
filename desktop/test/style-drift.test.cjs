'use strict';

/**
 * 样式漂移守卫（2026-11-13 起）。
 *
 * 背景：颜色早就收敛到 app.css 的令牌了，但**布局节奏**没有——同一个语义块在不同页面
 * 各写一套，于是 `.sec-head` 在导出/设置里是 `align-items:flex-start`，在报告页变成
 * `baseline`；间距散着 7/9/11/13/14 这些一次性数值。这是「每个地方单独实现一套样式」
 * 的残留，靠人自觉守不住，所以在这里冻结基线、只许往下走。
 *
 * 三条规则：
 *   1. 共享块（.sec / .sec-head / .actions / .empty）不得在新文件里再定义一份；
 *   2. 间距属性不得再写与刻度等值的裸 px（出现就必须用 var(--sp-N)）；
 *   3. app.css 的 --sp-* 刻度不能被删减。
 *
 * 需要放宽时改 style-baseline.json，并在提交信息里写清理由。
 */

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const SRC = path.join(__dirname, '..', 'renderer', 'src');
const APP_CSS = path.join(SRC, 'app.css');
const BASELINE = JSON.parse(fs.readFileSync(path.join(__dirname, 'style-baseline.json'), 'utf8'));

const SPACING_PROPS =
  /(?:^|[;{\s])(gap|row-gap|column-gap|margin|margin-top|margin-right|margin-bottom|margin-left|padding|padding-top|padding-right|padding-bottom|padding-left)\s*:\s*([^;{}]+);/g;

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else if (entry.name.endsWith('.svelte')) out.push(full);
  }
  return out;
}

function styleBlocks() {
  return walk(SRC)
    .map((file) => {
      const text = fs.readFileSync(file, 'utf8');
      const m = text.match(/<style>([\s\S]*?)<\/style>/);
      return m ? { file: path.relative(SRC, file).replace(/\\/g, '/'), css: m[1] } : null;
    })
    .filter(Boolean);
}

test('共享块没有在新文件里各写一套', () => {
  const blocks = styleBlocks();
  const offenders = [];

  for (const [name, max] of Object.entries(BASELINE.sharedBlocks)) {
    const files = blocks
      .filter(({ css }) => new RegExp(`\\.${name}(?![\\w-])[^{]*\\{`).test(css))
      .map(({ file }) => file);
    if (files.length > max) {
      offenders.push(`.${name}: ${files.length} 个文件（基线 ${max}）→ ${files.join(', ')}`);
    }
  }

  assert.deepEqual(offenders, [], `共享块被重复实现：\n${offenders.join('\n')}`);
});

test('间距属性不再写与刻度等值的裸 px', () => {
  const scale = new Set(BASELINE.tokenScale);
  const offenders = [];

  for (const { file, css } of styleBlocks()) {
    for (const decl of css.matchAll(SPACING_PROPS)) {
      const value = decl[2];
      if (value.includes('var(') || value.includes('calc(')) continue;
      for (const px of value.matchAll(/(?<![\w.-])(\d+(?:\.\d+)?)px/g)) {
        const n = Number(px[1]);
        if (scale.has(n)) offenders.push(`${file}: ${decl[1]}: ${value.trim()}`);
      }
    }
  }

  assert.deepEqual(offenders, [], `这些间距该用 var(--sp-N)：\n${offenders.join('\n')}`);
});

test('app.css 保留完整间距刻度', () => {
  const css = fs.readFileSync(APP_CSS, 'utf8');
  const declared = new Set(
    [...css.matchAll(/--sp-\d+\s*:\s*(\d+)px/g)].map((m) => Number(m[1])),
  );
  const missing = BASELINE.tokenScale.filter((v) => !declared.has(v));
  assert.deepEqual(missing, [], `间距刻度缺失：${missing.join(', ')}`);
});
