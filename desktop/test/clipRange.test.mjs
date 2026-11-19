import assert from 'node:assert/strict';
import test from 'node:test';

import {
  FULL_CLIP,
  chapterScopeOptions,
  clipCaption,
  clipFileTag,
  clipSpan,
  clockLabel,
  formatRange,
  hasCuesInScope,
  isFullClip,
  matchedChapterId,
  normalizeClip,
  safeClipLabel,
  scopeForChapter,
  scopeSelectValue,
} from '../renderer/src/lib/clipRange.ts';

const cue = (start, end, text = '') => ({ start, end, text });

// 与 core/clip_range.py 的用例一一对应：两个实现必须同一套边界规则。
test('全片：end<=0 视为未选片段', () => {
  assert.equal(isFullClip(FULL_CLIP), true);
  assert.equal(isFullClip({ start: 10, end: 0, label: '' }), true);
  assert.equal(isFullClip({ start: 10, end: 20, label: '' }), false);
  assert.deepEqual(normalizeClip({ start: 10, end: 20, label: 'x' }, 14), {
    start: 10,
    end: 14,
    label: 'x',
  });
});

test('命中规则：首尾蹭边 <0.1s 不算，整条在区间内的短句要保留', () => {
  const cues = [
    cue(8.0, 10.05, '上一个场景的尾巴'),
    cue(9.0, 12.0, '跨过片头但真的在说话'),
    cue(12.5, 12.56, 'はい'),
    cue(19.9, 20.02, '片尾蹦字'),
    cue(20.5, 22.0, '片段之后'),
  ];
  const span = clipSpan(cues, { start: 10, end: 20, label: '' });
  assert.deepEqual(span, { from: 2, to: 4, count: 3 });
  assert.equal(hasCuesInScope(cues, { start: 10, end: 20, label: '' }), true);
  assert.equal(hasCuesInScope(cues, { start: 30, end: 40, label: '' }), false);
});

test('命中区间：1 基、含两端，全片时就是 1..n', () => {
  const cues = [cue(0, 1), cue(1, 2), cue(2, 3), cue(30, 31)];
  assert.deepEqual(clipSpan(cues, { start: 0.5, end: 2.5, label: '' }), {
    from: 1,
    to: 3,
    count: 3,
  });
  assert.deepEqual(clipSpan(cues, FULL_CLIP), { from: 1, to: 4, count: 4 });
  assert.deepEqual(clipSpan([], { start: 0, end: 10, label: '' }), { from: 0, to: 0, count: 0 });
});

test('章节选项：只取带 end 的区间，时刻点不单独成项', () => {
  const marks = [
    { id: 'point', start: 9.5, end: null, title: '发射点' },
    { id: 'scene', start: 1.0, end: 13.0, title: '章节1' },
    { id: 'short', start: 20.0, end: 20.05, title: '太短' },
    { id: 'open', start: 21.0, end: 30.0, title: '越界' },
  ];
  const options = chapterScopeOptions(marks, 24);
  assert.deepEqual(
    options.map((option) => [option.id, option.start, option.end]),
    [
      ['scene', 1, 13],
      ['open', 21, 24],
    ],
  );
  assert.equal(options.some((option) => option.id === 'point'), false);
  assert.equal(options.some((option) => option.id === 'short'), false);
});

test('章节 ↔ 范围：回显与下拉取值', () => {
  const marks = [
    { id: 'scene', start: 1.0, end: 13.0, title: '章节1' },
    { id: 'other', start: 20.0, end: 22.0, title: '章节2' },
  ];
  const options = chapterScopeOptions(marks, 24);
  const scope = scopeForChapter(options[0]);
  assert.equal(matchedChapterId(scope, options), 'scene');
  assert.equal(scopeSelectValue(scope, options), 'chapter:scene');
  assert.equal(scopeSelectValue({ start: 3, end: 5, label: '' }, options), 'custom');
  assert.equal(scopeSelectValue(FULL_CLIP, options), 'full');
});

test('时间与范围文案', () => {
  assert.equal(clockLabel(10), '00m10s');
  assert.equal(clockLabel(1462), '24m22s');
  assert.equal(clockLabel(3723), '1h02m03s');
  assert.equal(formatRange({ start: 10, end: 1462, label: '' }), '0:10 → 24:22');
  assert.equal(
    clipCaption({ start: 10, end: 1462, label: '章节1' }),
    '章节1 · 0:10 → 24:22',
  );
  assert.equal(clipCaption(FULL_CLIP), '全片');
});

test('文件名标签与 core.clip_range.clip_tag 同一结果', () => {
  // Python: safe_label("场景 1/发射; #点") == "场景-1-发射-点"
  assert.equal(safeClipLabel('场景 1/发射; #点'), '场景-1-发射-点');
  // Python: clip_tag(10, 1462, "章节1") == "章节1-00m10s-24m22s"
  assert.equal(clipFileTag({ start: 10, end: 1462, label: '章节1' }), '章节1-00m10s-24m22s');
  assert.equal(clipFileTag({ start: 10, end: 1462, label: '' }), '00m10s-24m22s');
  assert.equal(clipFileTag(FULL_CLIP), '');
  assert.equal(safeClipLabel('   '), '');
});
