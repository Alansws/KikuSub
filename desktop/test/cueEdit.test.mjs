import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MIN_CUE_LENGTH,
  alignCueEnd,
  alignCueStart,
  canSplitAt,
} from '../renderer/src/lib/cueEdit.ts';

const cue = (start, end) => ({ start, end, text: 'あ' });

test('入点可以对齐到播放头，但必须留出最短时长', () => {
  assert.deepEqual(alignCueStart(cue(1, 3), 2, 10), { ok: true, time: 2 });
  assert.equal(alignCueStart(cue(1, 3), 2.98, 10).ok, false);
  assert.deepEqual(alignCueStart(cue(1, 3), -5, 10), { ok: true, time: 0 });
  // 播放头在片尾时不能拿来当入点（会越过出点）。
  assert.equal(alignCueStart(cue(1, 3), 99, 10).ok, false);
});

test('出点可以对齐到播放头，但必须留出最短时长', () => {
  assert.deepEqual(alignCueEnd(cue(1, 3), 2, 10), { ok: true, time: 2 });
  assert.equal(alignCueEnd(cue(1, 3), 1.02, 10).ok, false);
  assert.deepEqual(alignCueEnd(cue(1, 3), 99, 10), { ok: true, time: 10 });
});

test('切割点必须在两端各留 0.05 秒', () => {
  assert.equal(canSplitAt(cue(1, 3), 2), true);
  assert.equal(canSplitAt(cue(1, 3), 1 + MIN_CUE_LENGTH), false);
  assert.equal(canSplitAt(cue(1, 3), 3 - MIN_CUE_LENGTH), false);
  assert.equal(canSplitAt(cue(1, 3), 0.5), false);
  assert.equal(canSplitAt(cue(1, 3), 4), false);
});
