/**
 * 双引擎复核「对照范围」的展示逻辑（2026-11-26）。
 *
 * 服务端算真正的切片（`core/dual_scope.py` + `tests/test_dual_scope.py`），
 * 这里守的是**用户看到的那几句话**：范围横幅必须同时说清「在看哪一段」
 * 与「外面藏了多少条」；写回按钮的文案必须让「替换当前范围」与「整列覆盖」
 * 一眼分得开——用户报障里最危险的一步就是这两件事长得一样。
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  clockOf,
  replaceConfirmText,
  replaceIsDestructive,
  replaceLabel,
  scopeBanner,
  scopeEmptyHint,
  scopeName,
  scopeRangeLabel,
  scopeStatSuffix,
  scopeTabLabel,
} from '../renderer/src/lib/dualScope.ts';

/** 真机现场：章节三、35:53–55:41，范围外还有 416 条 A。 */
function chapterScope(patch = {}) {
  return {
    kind: 'chapter',
    key: 'ch:ch-3',
    start: 2153.364,
    end: 3341.072,
    label: '章节三',
    range_label: '35:53–55:41',
    auto: true,
    partial_b: true,
    hidden_a: 416,
    hidden_b: 0,
    would_trim: 418,
    replace_mode: 'range',
    replace_count: 220,
    ...patch,
  };
}

function fullScope(patch = {}) {
  return chapterScope({
    kind: 'all',
    key: 'all',
    label: '全片',
    range_label: '00:13–55:41',
    auto: false,
    hidden_a: 0,
    hidden_b: 0,
    would_trim: 0,
    replace_mode: 'all',
    replace_count: 220,
    ...patch,
  });
}

test('时钟：分秒补零，超过一小时带小时位', () => {
  assert.equal(clockOf(0), '00:00');
  assert.equal(clockOf(2153.364), '35:53');
  assert.equal(clockOf(3341.072), '55:41');
  assert.equal(clockOf(3723), '1:02:03');
  assert.equal(clockOf(Number.NaN), '00:00');
});

test('范围名与区间标签：章节三 · 35:53–55:41', () => {
  const scope = chapterScope();
  assert.equal(scopeName(scope), '章节三');
  assert.equal(scopeRangeLabel(scope), '章节三 · 35:53–55:41');
  assert.equal(scopeRangeLabel(fullScope()), '全片');
});

test('横幅：同时说出聚焦对象与隐去条数', () => {
  const text = scopeBanner(chapterScope());
  assert.match(text, /当前聚焦/);
  assert.match(text, /章节三/);
  assert.match(text, /35:53–55:41/);
  assert.match(text, /已隐去范围外 A 416 条/);
  assert.match(text, /可切换到全片/);
});

test('横幅：B 也有一部分在范围外时两边都报', () => {
  const text = scopeBanner(chapterScope({ hidden_b: 12 }));
  assert.match(text, /A 416 条 \/ B 12 条/);
});

test('横幅：全片且 B 只覆盖局部时明确警告', () => {
  const text = scopeBanner(fullScope({ partial_b: true }));
  assert.match(text, /全片/);
  assert.match(text, /只覆盖了一部分/);
  assert.match(scopeBanner(fullScope({ partial_b: false })), /^当前聚焦：全片$/);
});

test('范围切换器标签带条数', () => {
  assert.equal(
    scopeTabLabel({ key: 'ch:ch-3', label: '章节三', a_count: 220, b_count: 220, kind: 'chapter' }),
    '章节三（220）',
  );
  assert.equal(scopeTabLabel({ key: 'all', label: '全片', a_count: 636, b_count: 220, kind: 'all' }), '全片');
  // B 只覆盖一段时按 A/B 里较大的那个报，避免「章节三（0）」
  assert.equal(
    scopeTabLabel({ key: 'ch:ch-2', label: '章节二', a_count: 216, b_count: 0, kind: 'chapter' }),
    '章节二（216）',
  );
});

test('写回按钮：范围对照叫「替换当前范围」，整片才叫「覆盖核对台」', () => {
  assert.equal(replaceLabel(chapterScope()), '用 B 替换当前范围');
  assert.equal(replaceLabel(fullScope()), '用 B 覆盖核对台');
  assert.equal(replaceLabel(chapterScope(), true), '写入中…');
  // 全片但 B 是局部稿：也不给整列按钮（那会清空别的章节）
  assert.equal(replaceLabel(fullScope({ partial_b: true, replace_mode: 'range' })), '用 B 替换当前范围');
});

test('危险度：范围替换永不判危险，整列覆盖丢字才判', () => {
  assert.equal(replaceIsDestructive(chapterScope()), false);
  assert.equal(replaceIsDestructive(fullScope()), false);
  assert.equal(replaceIsDestructive(fullScope({ replace_mode: 'all', would_trim: 418 })), true);
});

test('二次确认：范围替换写明「窗口外一条不动」', () => {
  const text = replaceConfirmText(chapterScope(), 636, 220);
  assert.match(text, /替换「章节三 · 35:53–55:41」这一段的字幕/);
  assert.match(text, /只换窗口内的 220 条/);
  // 窗口外 = hidden_a（被范围隐去的 416 条），不是「总数 − 隐去数」
  assert.match(text, /窗口外的 416 条（其它章节）一条不动/);
  assert.match(text, /⌘Z/);
});

test('二次确认：整列覆盖必须写出会丢多少条', () => {
  const text = replaceConfirmText(fullScope({ would_trim: 418 }), 636, 220);
  assert.match(text, /整列覆盖/);
  assert.match(text, /636 条会被 220 条替换/);
  assert.match(text, /范围外还有 418 条会被丢掉/);
});

test('空范围文案：章节里没有可对照的句子', () => {
  assert.match(scopeEmptyHint(chapterScope()), /「章节三」里没有可对照的句子/);
  assert.match(scopeEmptyHint(fullScope()), /整片范围内都没有可对照的行/);
});

test('统计口径后缀：范围对照补「仅本段」', () => {
  assert.equal(scopeStatSuffix(chapterScope()), '仅本段');
  assert.equal(scopeStatSuffix(fullScope()), '');
});
