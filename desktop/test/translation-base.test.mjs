import assert from 'node:assert/strict';
import test from 'node:test';

const { applyRebasedBases } = await import('../renderer/src/lib/translationBase.ts');

function track(texts, base) {
  return { lang: 'zh-Hans', exists: true, count: texts.length, texts, base, stale: [], created_at: 0, entry: 'test' };
}

test('把服务端对齐后的 base 就地写回，不动译文与条数', () => {
  const tracks = { 'zh-Hans': track(['早上好', '再见'], ['…おはよう', 'またね']) };
  const cues = [{ text: 'おはよう' }, { text: 'またね' }];
  const n = applyRebasedBases(tracks, cues, { 'zh-Hans': [0] });
  assert.equal(n, 1);
  assert.deepEqual(tracks['zh-Hans'].base, ['おはよう', 'またね']);
  assert.deepEqual(tracks['zh-Hans'].texts, ['早上好', '再见']);
});

test('越界 / 不存在的语种 / 空 rebased 都不炸', () => {
  const tracks = { 'zh-Hans': track(['a'], ['x']) };
  const cues = [{ text: 'x' }];
  assert.equal(applyRebasedBases(tracks, cues, undefined), 0);
  assert.equal(applyRebasedBases(tracks, cues, {}), 0);
  assert.equal(applyRebasedBases(tracks, cues, { 'zh-Hans': [3, -1] }), 0);
  assert.equal(applyRebasedBases(tracks, cues, { 'en': [0] }), 0);
  assert.equal(applyRebasedBases(tracks, [], { 'zh-Hans': [0] }), 0);
});

test('多语种各自按自己的下标对齐', () => {
  const tracks = {
    'zh-Hans': track(['甲', '乙'], ['A…', 'B…']),
    en: track(['a', 'b'], ['A…', 'B…']),
  };
  const cues = [{ text: 'A' }, { text: 'B' }];
  const n = applyRebasedBases(tracks, cues, { 'zh-Hans': [0, 1], en: [1] });
  assert.equal(n, 3);
  assert.deepEqual(tracks['zh-Hans'].base, ['A', 'B']);
  assert.deepEqual(tracks.en.base, ['A…', 'B']);
});
