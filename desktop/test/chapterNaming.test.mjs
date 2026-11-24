import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_CHAPTER_TEMPLATE,
  MAX_TEMPLATE_LENGTH,
  autoChapterName,
  chapterOrdinal,
  chineseNumber,
  formatChapterName,
  isAutoTitle,
  normalizeTemplate,
} from '../renderer/src/lib/chapterNaming.ts';

test('中文序号：个位 / 十几 / 几十 / 百位', () => {
  assert.equal(chineseNumber(1), '一');
  assert.equal(chineseNumber(9), '九');
  assert.equal(chineseNumber(10), '十');
  assert.equal(chineseNumber(11), '十一');
  assert.equal(chineseNumber(20), '二十');
  assert.equal(chineseNumber(28), '二十八');
  assert.equal(chineseNumber(100), '一百');
  assert.equal(chineseNumber(105), '一百零五');
  assert.equal(chineseNumber(110), '一百一十');
  assert.equal(chineseNumber(115), '一百一十五');
  assert.equal(chineseNumber(1000), '1000');
});

test('模板收敛：空 / 无占位符 / 超长', () => {
  assert.equal(normalizeTemplate(''), DEFAULT_CHAPTER_TEMPLATE);
  assert.equal(normalizeTemplate(null), DEFAULT_CHAPTER_TEMPLATE);
  assert.equal(normalizeTemplate('  '), DEFAULT_CHAPTER_TEMPLATE);
  assert.equal(normalizeTemplate('章节'), '章节 {num}');
  assert.equal(normalizeTemplate('场景{num}'), '场景{num}');
  assert.equal(normalizeTemplate('第{n}章'), '第{n}章');

  const long = '很长的章节前缀'.repeat(20);
  const capped = normalizeTemplate(long);
  assert.ok(capped.length <= MAX_TEMPLATE_LENGTH, `${capped.length} <= ${MAX_TEMPLATE_LENGTH}`);
  assert.ok(capped.endsWith('{num}'), capped);
});

test('替换占位符', () => {
  assert.equal(formatChapterName('章节{num}', 1), '章节一');
  assert.equal(formatChapterName('章节{num}', 12), '章节十二');
  assert.equal(formatChapterName('场景 {n}', 3), '场景 3');
  assert.equal(formatChapterName('{num}·{n}', 2), '二·2');
  assert.equal(formatChapterName('章节', 2), '章节 二');
});

test('只认系统自动标题', () => {
  assert.equal(isAutoTitle(''), true);
  assert.equal(isAutoTitle('时刻点 14:06'), true);
  assert.equal(isAutoTitle('时刻点 0:14:06'), true);
  assert.equal(isAutoTitle('场景 00:10–14:06'), true);
  assert.equal(isAutoTitle('章节一'), false, '用户可能自己起了这个名字，不要动');
  assert.equal(isAutoTitle('场景 3'), false);
  assert.equal(isAutoTitle('开场'), false);
});

test('序号只数区间章节，按起点排序', () => {
  const marks = [
    { id: 'a', start: 10, end: 20 },
    { id: 'p', start: 15, end: null }, // 时刻点不算章节
    { id: 'b', start: 40, end: 50 },
  ];
  assert.equal(chapterOrdinal(marks, { start: 5, end: 8 }), 1);
  assert.equal(chapterOrdinal(marks, { start: 25, end: 30 }), 2);
  assert.equal(chapterOrdinal(marks, { start: 60, end: 70 }), 3);
  // 自己不算自己
  assert.equal(chapterOrdinal(marks, { id: 'b', start: 40, end: 50 }), 2);
});

test('中间插一章时不与已有标题重名', () => {
  const marks = [
    { id: 'a', start: 10, end: 20, title: '开场' },
    { id: 'b', start: 30, end: 40, title: '章节二' },
  ];
  // 位置算出来是第 2 个（10–20 在它前面），但「章节二」已被占用 → 顺延到三
  assert.equal(autoChapterName('章节{num}', marks, { id: 'c', start: 22, end: 28 }), '章节三');
});

test('自动命名：补完起点后按位置取名', () => {
  const marks = [{ id: 'a', start: 10, end: 20 }];
  const candidate = { id: 'b', start: 30, end: 40 };
  assert.equal(autoChapterName('章节{num}', marks, candidate), '章节二');
  assert.equal(autoChapterName('场景{num}', marks, candidate), '场景二');
  assert.equal(autoChapterName(undefined, marks, candidate), '章节二');
});
