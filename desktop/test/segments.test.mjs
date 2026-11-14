import assert from 'node:assert/strict';
import test from 'node:test';

import { needsSegments, planSegments } from '../renderer/src/lib/aiSegments.ts';

function cues(count, gapAt = -1, gapSeconds = 0) {
  const out = [];
  let t = 0;
  for (let i = 0; i < count; i += 1) {
    if (i === gapAt) t += gapSeconds;
    out.push({ start: t, end: t + 1, text: `句${i}` });
    t += 1.1;
  }
  return out;
}

test('needsSegments switches on cue count or total characters', () => {
  assert.equal(needsSegments(cues(100), cues(100)), false);
  assert.equal(needsSegments(cues(200), cues(200)), true);
  const long = cues(10).map((cue) => ({ ...cue, text: '长'.repeat(10000) }));
  assert.equal(needsSegments(long, [], { maxChars: 50_000 }), true);
});

test('planSegments covers every cue exactly once', () => {
  const a = cues(420);
  const b = cues(430);
  const segments = planSegments(a, b, { targetCues: 150, toleranceCues: 20 });
  assert.ok(segments.length >= 3);
  assert.equal(segments[0].from, 1);
  assert.equal(segments.at(-1).to, a.length);
  for (let i = 0; i < segments.length; i += 1) {
    const seg = segments[i];
    assert.equal(seg.count, seg.to - seg.from + 1);
    assert.ok(seg.count <= 170, `段落过长：${seg.count}`);
    if (i > 0) assert.equal(seg.from, segments[i - 1].to + 1, '段与段之间不能重叠或漏条');
  }
});

test('planSegments prefers the largest silence gap near the target', () => {
  // 在第 160 条后放 8 秒静音：分段应该落在这里，而不是硬切在第 151 条。
  const a = cues(420, 160, 8);
  const b = cues(430, 162, 8);
  const segments = planSegments(a, b, { targetCues: 150, toleranceCues: 20 });
  assert.equal(segments[0].to, 160);
});

test('short input stays one segment', () => {
  const a = cues(80);
  const segments = planSegments(a, [], { targetCues: 150 });
  assert.equal(segments.length, 1);
  assert.deepEqual(
    { from: segments[0].from, to: segments[0].to },
    { from: 1, to: 80 },
  );
});
