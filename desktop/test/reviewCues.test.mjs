import assert from 'node:assert/strict';
import test from 'node:test';

const {
  captionLinesAt,
  captionTextLines,
  cueDisplayText,
  cueIndexAtTimeExclusive,
} = await import('../renderer/src/lib/reviewCues.ts');

const cue = (start, end, text) => ({ start, end, text });
const noTranslation = () => '';

test('cueIndexAtTimeExclusive：命中区间内，句尾不算命中（与核对台二分口径一致）', () => {
  const cues = [cue(0, 1.4, 'a'), cue(1.5, 2.9, 'b')];
  assert.equal(cueIndexAtTimeExclusive(cues, 0), 0);
  assert.equal(cueIndexAtTimeExclusive(cues, 1.39), 0);
  // 旧二分在 time === end 时右移；改为 <= 会让播放头在句尾多留一帧
  assert.equal(cueIndexAtTimeExclusive(cues, 1.4), -1);
  assert.equal(cueIndexAtTimeExclusive(cues, 1.45), -1);
  assert.equal(cueIndexAtTimeExclusive(cues, 1.5), 1);
  assert.equal(cueIndexAtTimeExclusive(cues, 2.9), -1);
  assert.equal(cueIndexAtTimeExclusive([], 1), -1);
});

test('captionTextLines / cueDisplayText：拆硬换行、去空行，表格用「 / 」', () => {
  assert.deepEqual(captionTextLines('よう、久しぶり。\n\n 元気だった？ '), [
    'よう、久しぶり。',
    '元気だった？',
  ]);
  assert.deepEqual(captionTextLines(''), []);
  assert.deepEqual(captionTextLines(null), []);
  assert.equal(cueDisplayText('日文\n中文'), '日文 / 中文');
  assert.equal(cueDisplayText('单行'), '单行');
});

test('captionLinesAt：原文 / 译文 / 双语三态，双语是原文在上、译文在下', () => {
  const cues = [cue(0, 1.4, 'よう、久しぶり。'), cue(1.5, 2.9, '元気？')];
  const translation = (i) => (i === 0 ? '好久不见。' : '还好吗？');

  assert.deepEqual(captionLinesAt(cues, 0.2, 'source', translation), ['よう、久しぶり。']);
  assert.deepEqual(captionLinesAt(cues, 0.2, 'target', translation), ['好久不见。']);
  assert.deepEqual(captionLinesAt(cues, 0.2, 'both', translation), ['よう、久しぶり。', '好久不见。']);
  assert.deepEqual(captionLinesAt(cues, 1.6, 'both', translation), ['元気？', '还好吗？']);
});

test('captionLinesAt：同区间的多条 cue 作为一块一起显示（双语 SRT 的日 / 中两行）', () => {
  const cues = [cue(0, 1.4, '日文一'), cue(0, 1.4, '日文二'), cue(1.5, 2.9, '下一句')];
  assert.deepEqual(captionLinesAt(cues, 0.2, 'source', noTranslation), ['日文一', '日文二']);
  assert.deepEqual(captionLinesAt(cues, 1.6, 'source', noTranslation), ['下一句']);
});

test('captionLinesAt：译文缺失时退回原文，决不在画面上留空行', () => {
  const cues = [cue(0, 1.4, 'よう、久しぶり。')];
  assert.deepEqual(captionLinesAt(cues, 0.2, 'target', noTranslation), ['よう、久しぶり。']);
  assert.deepEqual(captionLinesAt(cues, 0.2, 'both', noTranslation), ['よう、久しぶり。']);
});

test('captionLinesAt：整块源文本为空时不显示任何行；时间在块外返回空', () => {
  const cues = [cue(0, 1.4, '   '), cue(1.5, 2.9, '元気？')];
  assert.deepEqual(captionLinesAt(cues, 0.2, 'source', noTranslation), []);
  assert.deepEqual(captionLinesAt(cues, 1.45, 'source', noTranslation), []);
  assert.deepEqual(captionLinesAt([], 0.2, 'source', noTranslation), []);
});
