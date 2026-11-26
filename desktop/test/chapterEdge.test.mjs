import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MIN_MARK_SPAN,
  clampEdgeTime,
  edgeBounds,
  roundMs,
} from '../renderer/src/lib/chapterEdge.ts';

const base = { start: 20, end: 40, nextStart: 90, duration: 100 };

test('起点：夹进 [0, 终点 - 0.2]', () => {
  const bounds = edgeBounds({ ...base, edge: 'start' });
  assert.equal(bounds.lo, 0);
  assert.equal(bounds.hi, 40 - MIN_MARK_SPAN);
  assert.equal(clampEdgeTime(-5, bounds), 0);
  assert.equal(clampEdgeTime(10, bounds), 10);
  assert.equal(clampEdgeTime(39.9, bounds), 40 - MIN_MARK_SPAN);
});

test('终点：夹进 [起点 + 0.2, 下一条标记起点]', () => {
  const bounds = edgeBounds({ ...base, edge: 'end' });
  assert.equal(bounds.lo, 20 + MIN_MARK_SPAN);
  assert.equal(bounds.hi, 90);
  assert.equal(clampEdgeTime(0, bounds), 20 + MIN_MARK_SPAN);
  assert.equal(clampEdgeTime(60, bounds), 60);
  assert.equal(clampEdgeTime(1000, bounds), 90, '不许越过后一条标记');
});

test('没有下一条标记时终点可以拖到片尾', () => {
  const bounds = edgeBounds({ ...base, edge: 'end', nextStart: 0 });
  assert.equal(bounds.hi, base.duration);
});

test('下一条标记比片尾还远时按片尾收', () => {
  const bounds = edgeBounds({ ...base, edge: 'end', nextStart: 500, duration: 100 });
  assert.equal(bounds.hi, 100);
});

test('时长未知（0）时终点不设上限，但仍然不能早于起点', () => {
  const bounds = edgeBounds({ ...base, edge: 'end', duration: 0, nextStart: 0 });
  assert.equal(bounds.hi, Number.POSITIVE_INFINITY);
  assert.equal(clampEdgeTime(9999, bounds), 9999);
  assert.equal(clampEdgeTime(1, bounds), 20 + MIN_MARK_SPAN);
});

test('下一个标记紧贴起点时 hi 不会低于 lo', () => {
  const bounds = edgeBounds({ start: 20, end: 20.2, nextStart: 20.1, duration: 100, edge: 'end' });
  assert.ok(bounds.hi >= bounds.lo, `${bounds.lo} <= ${bounds.hi}`);
  assert.equal(clampEdgeTime(20.1, bounds), bounds.lo);
});

test('非法时间退回下界，毫秒取整', () => {
  const bounds = edgeBounds({ ...base, edge: 'end' });
  assert.equal(clampEdgeTime(Number.NaN, bounds), bounds.lo);
  assert.equal(roundMs(50.00049), 50);
  assert.equal(roundMs(50.0005), 50.001);
});
