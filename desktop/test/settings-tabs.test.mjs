import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_SETTINGS_TAB,
  SETTINGS_TABS,
  SETTINGS_TAB_STORAGE_KEY,
  isSettingsTabId,
  readSettingsTab,
  saveSettingsTab,
  stepSettingsTab,
} from '../renderer/src/lib/settings/tabs.ts';

function fakeStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {
    map,
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
  };
}

test('页签顺序固定：引擎 → 外观 → AI → 环境', () => {
  assert.deepEqual(
    SETTINGS_TABS.map((tab) => tab.id),
    ['engines', 'appearance', 'ai', 'env'],
  );
  assert.equal(DEFAULT_SETTINGS_TAB, 'engines');
  // 每个页签都要有图标与提示语，否则 UI 会退化成纯文字
  for (const tab of SETTINGS_TABS) {
    assert.ok(tab.icon && tab.label && tab.hint, `${tab.id} 缺少 icon/label/hint`);
  }
});

test('读页签：没有记录 / 坏值 / 没有 storage 都退回第一页', () => {
  assert.equal(readSettingsTab(fakeStorage()), 'engines');
  assert.equal(readSettingsTab(fakeStorage({ [SETTINGS_TAB_STORAGE_KEY]: 'ai' })), 'ai');
  assert.equal(readSettingsTab(fakeStorage({ [SETTINGS_TAB_STORAGE_KEY]: 'diagnostics' })), 'engines');
  assert.equal(readSettingsTab(fakeStorage({ [SETTINGS_TAB_STORAGE_KEY]: '' })), 'engines');
  assert.equal(readSettingsTab(null), 'engines');
  assert.equal(readSettingsTab(undefined), 'engines');
});

test('写页签：只接受合法 id，写失败不影响流程', () => {
  const storage = fakeStorage();
  saveSettingsTab('env', storage);
  assert.equal(storage.map.get(SETTINGS_TAB_STORAGE_KEY), 'env');

  saveSettingsTab('nope', storage);
  assert.equal(storage.map.get(SETTINGS_TAB_STORAGE_KEY), 'env', '非法 id 不能覆盖已有值');

  const throwing = {
    getItem: () => {
      throw new Error('denied');
    },
    setItem: () => {
      throw new Error('denied');
    },
  };
  assert.equal(readSettingsTab(throwing), 'engines');
  assert.doesNotThrow(() => saveSettingsTab('ai', throwing));
});

test('←/→ 到头绕回另一端', () => {
  assert.equal(stepSettingsTab('engines', 1), 'appearance');
  assert.equal(stepSettingsTab('appearance', 1), 'ai');
  assert.equal(stepSettingsTab('env', 1), 'engines');
  assert.equal(stepSettingsTab('engines', -1), 'env');
  assert.equal(stepSettingsTab('ai', -2), 'engines');
  assert.equal(stepSettingsTab('engines', 4), 'engines', '整圈应回到原位');
});

test('isSettingsTabId 只认这四个 id', () => {
  assert.equal(isSettingsTabId('engines'), true);
  assert.equal(isSettingsTabId('settings'), false);
  assert.equal(isSettingsTabId(null), false);
});
