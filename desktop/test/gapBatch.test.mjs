import assert from 'node:assert/strict';
import test from 'node:test';

const { gapCounts, gapIndices, gapSummary } = await import('../renderer/src/lib/gapBatch.ts');
const { cueIsStale } = await import('../renderer/src/lib/translationStatus.ts');

function track(texts, base) {
  return {
    lang: 'zh-Hans',
    exists: true,
    count: texts.length,
    texts,
    base: base ?? texts.map(() => ''),
    stale: [],
    created_at: 0,
    entry: 'test',
  };
}

const CUES = [
  { start: 0, end: 1, text: 'おはよう' },
  { start: 1, end: 2, text: '今日は雨だ' },
  { start: 2, end: 3, text: 'またね' },
  { start: 3, end: 4, text: '気をつけて' },
];

const FULL = { from: 1, to: 4, count: 4 };

test('空译文算待译，有译文算已同步', () => {
  const t = track(['早上好', '', '再见', ''], ['おはよう', '今日は雨だ', 'またね', '気をつけて']);
  assert.deepEqual(gapCounts(CUES, t, FULL), { total: 4, pending: 2, stale: 0, translated: 2 });
  assert.deepEqual(gapIndices(CUES, t, FULL), [2, 4]);
  assert.equal(gapSummary(gapCounts(CUES, t, FULL)), '2 条待译');
});

test('只算处理范围里的条目（章节）', () => {
  const t = track(['早上好', '', '再见', ''], ['おはよう', '今日は雨だ', 'またね', '気をつけて']);
  const chapter = { from: 3, to: 4, count: 2 };
  assert.deepEqual(gapCounts(CUES, t, chapter), { total: 2, pending: 1, stale: 0, translated: 1 });
  assert.deepEqual(gapIndices(CUES, t, chapter), [4]);
});

test('原文已改默认不纳入补译，勾选才纳入', () => {
  const t = track(['早上好', '今天下雨', '再见', ''], ['おはよう', '今日は雪だ', 'またね', '気をつけて']);
  const counts = gapCounts(CUES, t, FULL);
  assert.deepEqual(counts, { total: 4, pending: 1, stale: 1, translated: 3 });
  assert.equal(gapSummary(counts), '1 条待译 · 1 条原文已改');
  assert.deepEqual(gapIndices(CUES, t, FULL), [4]);
  assert.deepEqual(gapIndices(CUES, t, FULL, true), [2, 4]);
});

test('没有译文轨时整段都算待译', () => {
  assert.deepEqual(gapCounts(CUES, undefined, FULL), {
    total: 4,
    pending: 4,
    stale: 0,
    translated: 0,
  });
  assert.deepEqual(gapIndices(CUES, undefined, FULL), [1, 2, 3, 4]);
});

test('空范围不炸，返回空集合', () => {
  assert.deepEqual(gapIndices(CUES, undefined, { from: 0, to: 0, count: 0 }), []);
  assert.deepEqual(gapCounts(CUES, undefined, { from: 0, to: 0, count: 0 }), {
    total: 0,
    pending: 0,
    stale: 0,
    translated: 0,
  });
});

test('stale 判定与 translationStatus 同口径（parity，防两份实现分叉）', () => {
  const t = track(
    ['早上好', '今天下雨', '', '小心'],
    ['おはよう', '今日は雪だ', 'またね', '気をつけて'],
  );
  for (let index = 0; index < CUES.length; index += 1) {
    const mine = gapCounts(
      CUES,
      t,
      { from: index + 1, to: index + 1, count: 1 },
    ).stale;
    const theirs = cueIsStale(t, index, CUES) ? 1 : 0;
    assert.equal(mine, theirs, `index ${index}`);
  }
});
