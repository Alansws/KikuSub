import assert from 'node:assert/strict';
import test from 'node:test';

import { takeSlice } from '../renderer/src/lib/transcribeSlice.ts';

test('同步过来的区间只生效一次，读走就置空', () => {
  const holder = { slice: { start: '40:20', end: '44:25', nonce: 1 } };
  assert.deepEqual(takeSlice(holder), { start: '40:20', end: '44:25', nonce: 1 });
  assert.equal(holder.slice, null);
  // 视图重建（例如 #key app.view）后再次挂载：不能再把旧区间填回来
  assert.equal(takeSlice(holder), null);
});

test('新的一次同步仍然会生效', () => {
  const holder = { slice: null };
  assert.equal(takeSlice(holder), null);
  holder.slice = { start: '10:00', end: '11:00', nonce: 2 };
  assert.deepEqual(takeSlice(holder), { start: '10:00', end: '11:00', nonce: 2 });
  assert.equal(holder.slice, null);
});
