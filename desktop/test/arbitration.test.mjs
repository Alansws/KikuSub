import assert from 'node:assert/strict';
import test from 'node:test';

import {
  adoptLabel,
  canAdopt,
  classifyText,
  contextFor,
  isFreshRecord,
} from '../renderer/src/lib/arbitration.ts';

function cue(start, end, text = '') {
  return { start, end, text };
}

test('contextFor takes three nearest by time, excluding the current index', () => {
  const cues = [
    cue(8, 9, '后2'),
    cue(0, 1, '前1'),
    cue(4, 5, '当前'),
    cue(2, 3, '前2'),
    cue(6, 7, '后1'),
    cue(10, 11, '后3'),
    cue(1.2, 2.4, '前3'),
  ];
  const ctx = contextFor(cues, 2);
  assert.deepEqual(ctx.before, ['前1', '前3', '前2']);
  assert.deepEqual(ctx.after, ['后1', '后2', '后3']);
});

test('contextFor keeps neighbours that overlap due to selection padding', () => {
  // 当前句 5.0-7.0，邻句被 pad 到 4.7-5.1 / 6.9-7.3：不能按 end <= start 过滤。
  const cues = [cue(4.7, 5.1, '重叠前'), cue(5.0, 7.0, '当前'), cue(6.9, 7.3, '重叠后')];
  const ctx = contextFor(cues, 1);
  assert.deepEqual(ctx.before, ['重叠前']);
  assert.deepEqual(ctx.after, ['重叠后']);
});

test('contextFor skips empty text and caps at radius', () => {
  const cues = [
    cue(0, 1, ''),
    cue(1, 2, 'a'),
    cue(2, 3, 'b'),
    cue(3, 4, 'c'),
    cue(4, 5, 'd'),
    cue(5, 6, '当前'),
  ];
  const ctx = contextFor(cues, 5);
  assert.deepEqual(ctx.before, ['b', 'c', 'd']);
  assert.deepEqual(ctx.after, []);
});

test('classifyText distinguishes same-as-A, same-as-B and third', () => {
  assert.equal(classifyText('A', 'B', 'A'), 'a');
  assert.equal(classifyText('A', 'B', 'B'), 'b');
  assert.equal(classifyText('A', 'B', 'C'), 'third');
  assert.equal(classifyText('A', 'B', ' A '), 'a');
});

test('isFreshRecord guards media, time, A and B snapshots', () => {
  const record = {
    start: 1,
    end: 2,
    textA: 'A',
    textB: 'B',
    text: 'C',
    note: '',
    model: 'm',
    mediaId: 'm1',
  };
  assert.equal(isFreshRecord(record, cue(1, 2, 'A'), 'B', 'm1'), true);
  assert.equal(isFreshRecord(record, cue(1.1, 2, 'A'), 'B', 'm1'), false);
  assert.equal(isFreshRecord(record, cue(1, 2, 'A2'), 'B', 'm1'), false);
  assert.equal(isFreshRecord(record, cue(1, 2, 'A'), 'B2', 'm1'), false);
  assert.equal(isFreshRecord(record, cue(1, 2, 'A'), 'B', 'm2'), false);
  assert.equal(isFreshRecord(null, cue(1, 2, 'A'), 'B', 'm1'), false);
});


test('same-as-B keeps an adopt button labelled 同 B 版', () => {
  assert.equal(canAdopt('b'), true);
  assert.equal(adoptLabel('b'), '采用（同 B 版）');
  assert.equal(canAdopt('a'), false);
  assert.equal(adoptLabel('third'), '采用 AI 版');
});
