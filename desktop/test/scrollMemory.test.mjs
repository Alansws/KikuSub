import assert from 'node:assert/strict';
import test from 'node:test';

import { recallScroll, rememberScroll } from '../renderer/src/lib/scrollMemory.ts';

test('rememberScroll / recallScroll round-trips per key', () => {
  rememberScroll('dual:m1:100:diff', 1240);
  rememberScroll('dual:m1:100:all', 88);

  assert.equal(recallScroll('dual:m1:100:diff'), 1240);
  assert.equal(recallScroll('dual:m1:100:all'), 88);
  // 没记过的 key 从头开始，不能串到别的列表上
  assert.equal(recallScroll('dual:m2:100:diff'), 0);
});

test('negative or broken offsets clamp to zero', () => {
  rememberScroll('polish:m1:single:all', -40);
  assert.equal(recallScroll('polish:m1:single:all'), 0);

  rememberScroll('polish:m1:single:all', Number.NaN);
  assert.equal(recallScroll('polish:m1:single:all'), 0);

  rememberScroll('polish:m1:single:all', 12.6);
  assert.equal(recallScroll('polish:m1:single:all'), 13);
});
