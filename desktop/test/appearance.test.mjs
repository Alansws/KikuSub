import assert from 'node:assert/strict';
import test from 'node:test';

import { flipAppearance } from '../renderer/src/lib/themes.ts';
import {
  APPEARANCE_KEY,
  CUE_FONT_KEY,
  applyToDocument,
  clearLegacyKeys,
  readAppearancePrefs,
  writeAppearance,
  writeCueFont,
} from '../renderer/src/lib/appearance.ts';

/**
 * 外观偏好的纯逻辑守卫（2026-11-25）。
 *
 * 这几条规则一旦错，用户升级后会「莫名其妙变成另一个外观」：
 * 深色用户被带回浅色、想用明朝的用户被改成黑体、或者旧 key 留在盘上反复迁移。
 * 它们不需要 DOM，也不需要 store，所以直接测函数。
 */

function fakeStorage(entries) {
  const map = new Map(Object.entries(entries));
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: (key) => map.delete(key),
    /** 只给断言用 */
    dump: () => Object.fromEntries(map),
  };
}

test('没有存过任何偏好时默认跟随系统 + 黑体', () => {
  const prefs = readAppearancePrefs(fakeStorage({}));
  assert.equal(prefs.appearance, 'auto');
  assert.equal(prefs.cueFont, 'sans');
});

test('旧版的 light / dark 直接继承为显式覆盖', () => {
  assert.equal(readAppearancePrefs(fakeStorage({ 'kikusub.theme': 'light' })).appearance, 'light');
  assert.equal(readAppearancePrefs(fakeStorage({ 'kikusub.theme': 'dark' })).appearance, 'dark');
});

test('旧版「明朝墨」拆成「跟随系统 + 明朝」：深色用户不该被锁回浅色', () => {
  for (const legacy of ['mincho', 'cool']) {
    const prefs = readAppearancePrefs(fakeStorage({ 'kikusub.theme': legacy }));
    assert.equal(prefs.appearance, 'auto', `${legacy} 的外观应为 auto`);
    assert.equal(prefs.cueFont, 'mincho', `${legacy} 的字幕字体应保留明朝`);
  }
});

test('新 key 优先于旧 key（迁移完成后旧 key 不再生效）', () => {
  const prefs = readAppearancePrefs(
    fakeStorage({
      'kikusub.theme': 'dark',
      'kikusub.appearance': 'light',
      'kikusub.cueFont': 'sans',
    }),
  );
  assert.equal(prefs.appearance, 'light');
  assert.equal(prefs.cueFont, 'sans');
});

test('存进去的非法值一律回落到默认，不把垃圾值写进 data-theme', () => {
  const prefs = readAppearancePrefs(
    fakeStorage({ 'kikusub.appearance': 'midnight', 'kikusub.cueFont': 'gothic' }),
  );
  assert.equal(prefs.appearance, 'auto');
  assert.equal(prefs.cueFont, 'sans');
});

test('旧 key 读完即删（两套作废模型不留在盘上）', () => {
  const storage = fakeStorage({ 'kikusub.theme': 'mincho', 'kikusub.mode': 'dark' });
  clearLegacyKeys(storage);
  assert.deepEqual(storage.dump(), {});
});

test('写偏好只写新 key，不动别的 key', () => {
  const storage = fakeStorage({ 'kikusub.something': 'keep' });
  writeAppearance(storage, 'dark');
  writeCueFont(storage, 'mincho');
  assert.equal(storage.getItem(APPEARANCE_KEY), 'dark');
  assert.equal(storage.getItem(CUE_FONT_KEY), 'mincho');
  assert.equal(storage.getItem('kikusub.something'), 'keep');
});

test('applyToDocument 只写两个 data 属性（主题走 data-theme，字体走 data-cue-font）', () => {
  const root = { dataset: {} };
  applyToDocument('dark', 'mincho', root);
  assert.deepEqual(root.dataset, { theme: 'dark', cueFont: 'mincho' });
});

test('标题栏外观按钮是两态直切：日间 ⇄ 夜间（不再经过 auto）', () => {
  // 2026-11-26 用户反馈：旧的三态循环让「跟随系统 + 系统浅色」的用户
  // 要点两下才变暗。工具栏只回答「翻到另一面」，「跟随系统」留在设置页。
  assert.equal(flipAppearance('light'), 'dark');
  assert.equal(flipAppearance('dark'), 'light');
});
