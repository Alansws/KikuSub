import assert from 'node:assert/strict';
import test from 'node:test';

const { cueIsStale, countPending } = await import('../renderer/src/lib/translationStatus.ts');

function track(texts, base) {
  return { lang: 'zh-Hans', exists: true, count: texts.length, texts, base, stale: [], created_at: 0, entry: 'test' };
}

const CUES = [{ text: 'おはよう' }, { text: '今日は雨だ' }, { text: 'またね' }];

test('空译文算待译，不算过期', () => {
  const t = track(['早上好', '', '再见'], ['おはよう', '今日は雨だ', 'またね']);
  assert.equal(cueIsStale(t, 1, CUES), false);
  assert.deepEqual(countPending(t, CUES), { gap: 1, stale: 0 });
});

test('原文改过才算过期', () => {
  const t = track(['早上好', '今天下雨', '再见'], ['おはよう', '今日は雪だ', 'またね']);
  assert.equal(cueIsStale(t, 1, CUES), true);
  assert.deepEqual(countPending(t, CUES), { gap: 0, stale: 1 });
});

test('base 短于字幕时，有译文的越界条目算过期', () => {
  const t = track(['早上好', '今天下雨'], ['おはよう']);
  assert.equal(cueIsStale(t, 1, CUES), true);
  assert.deepEqual(countPending(t, CUES), { gap: 1, stale: 1 });
});

test('没有轨时全部为 0，不炸', () => {
  assert.deepEqual(countPending(undefined, CUES), { gap: 0, stale: 0 });
  assert.equal(cueIsStale(undefined, 0, CUES), false);
});
