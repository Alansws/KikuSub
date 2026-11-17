import assert from 'node:assert/strict';
import test from 'node:test';

import {
  FALLBACK_FPS,
  frameStepSeconds,
  normalizeFps,
  stepFrameTime,
  stepSecondTime,
} from '../renderer/src/lib/frameStep.ts';

const near = (actual, expected, eps = 1e-9) => {
  assert.ok(Math.abs(actual - expected) <= eps, `${actual} != ${expected}`);
};

test('normalizeFps 只接受 1–240 的有限值', () => {
  assert.equal(normalizeFps(23.976), 23.976);
  assert.equal(normalizeFps(30), 30);
  assert.equal(normalizeFps(240), 240);
  for (const bad of [0, -1, 0.5, 241, NaN, Infinity, null, undefined]) {
    assert.equal(normalizeFps(bad), 0, String(bad));
  }
});

test('未知 / 纯音频帧率回落到 30fps', () => {
  assert.equal(FALLBACK_FPS, 30);
  near(frameStepSeconds(0), 1 / 30);
  near(frameStepSeconds(undefined), 1 / 30);
  near(frameStepSeconds(24), 1 / 24);
});

test('逐帧前进 / 后退落在帧网格上，并在片头片尾 clamp', () => {
  near(stepFrameTime(0, 1, 24, 8), 1 / 24);
  near(stepFrameTime(0, -1, 24, 8), 0);
  near(stepFrameTime(1 / 24, -1, 24, 8), 0);
  near(stepFrameTime(8, 1, 24, 8), 8);
  near(stepFrameTime(7.99, 1, 24, 8), 8);
});

test('连续步进不累计浮点漂移：100 次前进 = 100 帧', () => {
  let time = 0;
  for (let i = 0; i < 100; i += 1) time = stepFrameTime(time, 1, 23.976, 100);
  const expected = 100 / 23.976;
  near(time, expected, 1e-6);
});

test('未知时长时只保证非负，不强行夹上界', () => {
  near(stepFrameTime(10, 1, 25, 0), 10 + 1 / 25);
  near(stepSecondTime(10, 1, 0), 11);
});

test('逐秒步进按 1 秒推进并在片尾 clamp', () => {
  near(stepSecondTime(3.25, 1, 100), 4.25);
  near(stepSecondTime(3.25, -1, 100), 2.25);
  near(stepSecondTime(0.2, -1, 100), 0);
  near(stepSecondTime(99.5, 1, 100), 100);
});
