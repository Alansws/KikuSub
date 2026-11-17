import assert from 'node:assert/strict';
import test from 'node:test';

import { SPEEDS, nextSpeed, speedLabel } from '../renderer/src/lib/playbackRate.ts';

test('档位固定为 0.5 / 1 / 1.5 / 2', () => {
  assert.deepEqual([...SPEEDS], [0.5, 1, 1.5, 2]);
});

test('升 / 降一档，到端点停住', () => {
  assert.equal(nextSpeed(0.5, 1), 1);
  assert.equal(nextSpeed(1, 1), 1.5);
  assert.equal(nextSpeed(1.5, 1), 2);
  assert.equal(nextSpeed(2, 1), 2);
  assert.equal(nextSpeed(2, -1), 1.5);
  assert.equal(nextSpeed(1.5, -1), 1);
  assert.equal(nextSpeed(1, -1), 0.5);
  assert.equal(nextSpeed(0.5, -1), 0.5);
});

test('未知倍速按最近档位参与升降', () => {
  assert.equal(nextSpeed(1.25, 1), 1.5);
  // 1.25 与 1 / 1.5 等距，取较低档位再降一档 → 0.5
  assert.equal(nextSpeed(1.25, -1), 0.5);
  assert.equal(nextSpeed(1.9, 1), 2);
});

test('标签保留一位小数以内的写法', () => {
  assert.equal(speedLabel(1), '1×');
  assert.equal(speedLabel(1.5), '1.5×');
  assert.equal(speedLabel(0.5), '0.5×');
});
