'use strict';

/**
 * 安全模式判定（纯函数）。真实崩溃不好复现，但这几条边界必须钉住：
 * 空/脏数据不能把用户直接送进安全模式，正常关闭必须能清零。
 */

const assert = require('node:assert/strict');
const test = require('node:test');

const guard = require('../main/launchguard.cjs');

test('readFailureCount 对脏数据一律当 0', () => {
  for (const prefs of [undefined, null, {}, { launchFailures: 'abc' }, { launchFailures: -3 }, { launchFailures: Infinity }]) {
    assert.equal(guard.readFailureCount(prefs), 0);
  }
  assert.equal(guard.readFailureCount({ launchFailures: '3' }), 3);
  assert.equal(guard.readFailureCount({ launchFailures: 2.9 }), 2);
});

test('连续两次才算打不开', () => {
  assert.equal(guard.shouldEnterSafeMode({}), false);
  assert.equal(guard.shouldEnterSafeMode({ launchFailures: 1 }), false);
  assert.equal(guard.shouldEnterSafeMode({ launchFailures: 2 }), true);
  assert.equal(guard.shouldEnterSafeMode({ launchFailures: 4 }), true);
  assert.equal(guard.shouldEnterSafeMode({ launchFailures: 1 }, 1), true);
});

test('attemptPatch 只加一，并保留其他偏好', () => {
  const before = { theme: 'dark', modelsDir: '/tmp/models' };
  const patch = guard.attemptPatch(before, new Date('2026-11-13T00:00:00Z'));
  assert.deepEqual(patch.launchFailures, 1);
  assert.equal(patch.lastLaunchAt, '2026-11-13T00:00:00.000Z');
  assert.deepEqual(Object.keys(patch).sort(), ['lastLaunchAt', 'launchFailures']);
  assert.equal(guard.attemptPatch({ launchFailures: 1 }).launchFailures, 2);
});

test('stablePatch 清零，且 STABLE_AFTER_MS 足够盖住首帧', () => {
  assert.deepEqual(guard.stablePatch(), { launchFailures: 0 });
  assert.ok(guard.STABLE_AFTER_MS >= 5000, '8 秒级才盖得住模型加载');
  assert.equal(guard.CRASH_LIMIT, 2);
});
