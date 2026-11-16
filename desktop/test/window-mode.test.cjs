'use strict';

/**
 * 无窗口铁律的单元测试（AGENTS.md §0.5）。
 *
 * 这组用例守的是「默认行为」而不是某次截图的结果：判定一旦退回「开发模式直接 show」，
 * 智能体改功能的每一条命令都会在用户桌面上弹窗，而单看某次改动是察觉不到的。
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  REASON,
  NO_WINDOW_REFUSAL,
  resolveWindowMode,
} = require('../main/windowmode.cjs');

test('截图取证永远不显示窗口（打包版也一样）', () => {
  for (const isPackaged of [false, true]) {
    const mode = resolveWindowMode({ isPackaged, shotPath: '/tmp/kikusub.png', env: {} });
    assert.deepEqual(mode, { visible: false, reason: REASON.SCREENSHOT });
  }
});

test('KIKUSUB_NO_WINDOW=1 是压过一切的总开关', () => {
  for (const isPackaged of [false, true]) {
    const mode = resolveWindowMode({
      isPackaged,
      env: { KIKUSUB_NO_WINDOW: '1', KIKUSUB_ALLOW_WINDOW: '1' },
    });
    assert.deepEqual(mode, { visible: false, reason: REASON.NO_WINDOW_ENV });
  }
});

test('开发模式默认拒绝：智能体的 `npx electron .` 走这条', () => {
  assert.deepEqual(resolveWindowMode({ isPackaged: false, env: {} }), {
    visible: false,
    reason: REASON.DEV_GUARD,
  });
  // 只认显式的 1：环境里随手一个 true 不该把窗口放出来
  for (const value of ['true', 'yes', '0', '']) {
    const mode = resolveWindowMode({ isPackaged: false, env: { KIKUSUB_ALLOW_WINDOW: value } });
    assert.equal(mode.reason, REASON.DEV_GUARD);
  }
});

test('显式许可 / 打包版才显示', () => {
  assert.deepEqual(
    resolveWindowMode({ isPackaged: false, env: { KIKUSUB_ALLOW_WINDOW: '1' } }),
    { visible: true, reason: REASON.ALLOWED },
  );
  assert.deepEqual(resolveWindowMode({ isPackaged: true, env: {} }), {
    visible: true,
    reason: REASON.PACKAGED,
  });
});

test('拒绝信息必须指路（截图怎么做、人类入口是什么）', () => {
  assert.match(NO_WINDOW_REFUSAL, /--screenshot/);
  assert.match(NO_WINDOW_REFUSAL, /KIKUSUB_ALLOW_WINDOW=1/);
  assert.match(NO_WINDOW_REFUSAL, /npm start/);
  assert.match(NO_WINDOW_REFUSAL, /AGENTS\.md/);
});
