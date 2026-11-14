import assert from 'node:assert/strict';
import test from 'node:test';

import {
  cueBlockAtX,
  cueDragTimes,
  keysInRange,
  rangeSelection,
} from '../renderer/src/lib/selection.ts';

function cue(start, end, text = '') {
  return { start, end, text };
}

test('rangeSelection includes both ends and spans full blocks', () => {
  const cues = [cue(10, 12), cue(13, 15), cue(16, 18), cue(19, 21)];
  const range = rangeSelection(cues, 1, 2);
  assert.deepEqual(range.indices, [1, 2]);
  assert.deepEqual(range.keys, ['13:15', '16:18']);
  assert.equal(range.start, 13);
  assert.equal(range.end, 18);
});

test('rangeSelection works backwards and dedupes bilingual rows', () => {
  // 双语：同一区间的两行算一块；从第 3 行往回选到第 1 行。
  const cues = [cue(1, 2), cue(1, 2), cue(3, 4), cue(3, 4), cue(5, 6)];
  const range = rangeSelection(cues, 3, 0);
  assert.deepEqual(range.indices, [0, 1, 2, 3]);
  assert.deepEqual(range.keys, ['1:2', '3:4']);
  assert.equal(range.start, 1);
  assert.equal(range.end, 4);
});

test('rangeSelection clamps to the cue table', () => {
  const cues = [cue(0, 1), cue(2, 3)];
  assert.deepEqual(rangeSelection(cues, 0, 99).indices, [0, 1]);
  assert.equal(rangeSelection([], 0, 1), null);
});

test('keysInRange reports blocks overlapping the time window', () => {
  const cues = [cue(0, 1), cue(2, 3), cue(4, 5)];
  assert.deepEqual(keysInRange(cues, 0.5, 4.5), ['0:1', '2:3', '4:5']);
  assert.deepEqual(keysInRange(cues, 1.0, 2.0), []);
});

test('cueDragTimes keeps duration when moving a block', () => {
  const drag = { start: 10, end: 12, edge: 'move', anchorT: 11 };
  const moved = cueDragTimes(drag, 14, 100);
  assert.equal(moved.start, 13);
  assert.equal(moved.end, 15);
  // 拖出片头/片尾时整块被夹住，时长不变
  assert.deepEqual(cueDragTimes(drag, -50, 100), { start: 0, end: 2 });
  assert.deepEqual(cueDragTimes(drag, 500, 100), { start: 98, end: 100 });
});

test('cueDragTimes clamps both edges and rounds to milliseconds', () => {
  const base = { start: 10, end: 12, anchorT: 0 };
  const left = cueDragTimes({ ...base, edge: 'start' }, 12.0004, 100);
  assert.equal(left.end, 12);
  assert.ok(left.start <= 12 - 0.05);
  const right = cueDragTimes({ ...base, edge: 'end' }, 10.0001, 100);
  assert.ok(right.end >= 10 + 0.05);
  assert.equal(right.start, 10);
});

test('cueBlockAtX picks the narrowest block under the cursor', () => {
  const cues = [cue(0, 10), cue(2, 3), cue(2, 3)];
  const xOf = (time) => time * 10;
  const block = cueBlockAtX(cues, 25, xOf);
  assert.equal(block.key, '2:3');
  assert.deepEqual(block.indices, [1, 2]);
  assert.equal(cueBlockAtX(cues, 500, xOf), null);
});
