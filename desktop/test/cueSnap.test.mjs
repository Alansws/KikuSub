import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MAX_SNAP_SECONDS,
  MIN_SNAP_SECONDS,
  collectSnapTargets,
  snapCueTimes,
  snapThreshold,
} from '../renderer/src/lib/cueSnap.ts';

const cue = (start, end) => ({ start, end, text: '' });

test('吸附阈值按像素换算，并有 20ms / 120ms 上下限', () => {
  assert.ok(Math.abs(snapThreshold(1000, 10) - 0.07) < 1e-9);
  assert.equal(snapThreshold(1000, 1000), MAX_SNAP_SECONDS);
  assert.equal(snapThreshold(1000, 0.001), MIN_SNAP_SECONDS);
  assert.equal(snapThreshold(0, 10), 0.05);
});

test('候选包含播放头、片头片尾与未拖动字幕边缘，并去重', () => {
  const cues = [cue(0.5, 1.5), cue(2, 3), cue(4, 5)];
  assert.deepEqual(collectSnapTargets(cues, [0], 2.5, 8), [0, 2, 2.5, 3, 4, 5, 8]);
  // 拖动第 3 条时，自己的边缘不能作为候选
  assert.deepEqual(collectSnapTargets(cues, [2], 6, 8), [0, 0.5, 1.5, 2, 3, 6, 8]);
});

test('拖左端吸附到播放头 / 邻句边缘', () => {
  const snapped = snapCueTimes({ start: 1.98, end: 2.48 }, 'start', [2], 0.05, 8);
  assert.equal(snapped.start, 2);
  assert.equal(snapped.end, 2.48);
  assert.equal(snapped.guide, 2);
});

test('拖右端吸附到邻句起点', () => {
  const snapped = snapCueTimes({ start: 2, end: 2.48 }, 'end', [2.5], 0.05, 8);
  assert.equal(snapped.end, 2.5);
  assert.equal(snapped.guide, 2.5);
});

test('整体移动时在起点 / 终点里选更近的一侧，时长保持不变', () => {
  const byStart = snapCueTimes({ start: 1.98, end: 2.48 }, 'move', [2], 0.05, 8);
  assert.equal(byStart.start, 2);
  assert.equal(byStart.end, 2.5);
  assert.equal(byStart.guide, 2);

  const byEnd = snapCueTimes({ start: 1.98, end: 2.48 }, 'move', [2.5], 0.05, 8);
  assert.equal(byEnd.start, 2);
  assert.equal(byEnd.end, 2.5);
  assert.equal(byEnd.guide, 2.5);
});

test('超出阈值 / 关闭吸附时原样返回', () => {
  const base = { start: 1, end: 2 };
  assert.deepEqual(snapCueTimes(base, 'start', [2.5], 0.05, 8), {
    start: 1,
    end: 2,
    guide: null,
  });
  assert.deepEqual(snapCueTimes(base, 'start', [1], 0.05, 8, null, false), {
    start: 1,
    end: 2,
    guide: null,
  });
});

test('clamp 后边缘不再等于候选时丢弃参考线', () => {
  const snapped = snapCueTimes({ start: 1, end: 1.2 }, 'start', [1.2], 0.5, 8);
  assert.equal(snapped.start, 1.15);
  assert.equal(snapped.guide, null);
});
