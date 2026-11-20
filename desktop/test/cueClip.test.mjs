import assert from 'node:assert/strict';
import test from 'node:test';

import { clipSummary, planCuePaste } from '../renderer/src/lib/cueClip.ts';

const cue = (start, end) => ({ start, end });

test('正常粘贴：起点=播放头，长度=复制句，插到下一句之前', () => {
  const result = planCuePaste({
    at: 5,
    length: 0.67,
    cues: [cue(0, 1), cue(6, 7)],
    mediaDuration: 8,
  });
  assert.equal(result.ok, true);
  assert.deepEqual(result.plan, {
    start: 5,
    end: 5.67,
    index: 1,
    overlapSeconds: 0,
    overlapCount: 0,
    clamped: false,
  });
});

test('不居中对齐：播放头在哪，新句就从哪开始', () => {
  const result = planCuePaste({
    at: 2.5,
    length: 1.0,
    cues: [cue(0, 1)],
    mediaDuration: 10,
  });
  assert.equal(result.ok, true);
  assert.equal(result.plan.start, 2.5);
  assert.equal(result.plan.end, 3.5);
});

test('片尾不够长：只收结束时间，并标记 clamped', () => {
  const result = planCuePaste({
    at: 5,
    length: 0.67,
    cues: [],
    mediaDuration: 5.5,
  });
  assert.equal(result.ok, true);
  assert.equal(result.plan.start, 5);
  assert.equal(result.plan.end, 5.5);
  assert.equal(result.plan.clamped, true);
});

test('片尾连 0.05 秒都放不下：拒绝', () => {
  const result = planCuePaste({
    at: 5.47,
    length: 0.67,
    cues: [],
    mediaDuration: 5.5,
  });
  assert.equal(result.ok, false);
  assert.match(result.reason, /片尾/);
});

test('播放头为负：夹到 0', () => {
  const result = planCuePaste({ at: -2, length: 0.8, cues: [cue(1, 2)] });
  assert.equal(result.ok, true);
  assert.equal(result.plan.start, 0);
  assert.equal(result.plan.index, 0);
});

test('与邻句重叠：允许，但把条数与最大重叠量报出来', () => {
  const result = planCuePaste({
    at: 0.5,
    length: 0.4,
    cues: [cue(0, 1)],
    mediaDuration: 10,
  });
  assert.equal(result.ok, true);
  assert.equal(result.plan.overlapCount, 1);
  assert.equal(result.plan.overlapSeconds, 0.4);
  assert.equal(result.plan.index, 1);
});

test('两条同时重叠：计数与最大重叠量分别正确', () => {
  const result = planCuePaste({
    at: 0.4,
    length: 1.0,
    cues: [cue(0, 0.6), cue(0.5, 1.2)],
    mediaDuration: 10,
  });
  assert.equal(result.ok, true);
  assert.equal(result.plan.overlapCount, 2);
  assert.equal(result.plan.overlapSeconds, 0.7);
});

test('插到末尾：播放头在所有字幕之后', () => {
  const result = planCuePaste({
    at: 9,
    length: 0.5,
    cues: [cue(0, 1), cue(2, 3)],
    mediaDuration: 10,
  });
  assert.equal(result.ok, true);
  assert.equal(result.plan.index, 2);
});

test('起点与现有句相同：插在它后面（严格大于才往前插）', () => {
  const result = planCuePaste({
    at: 2,
    length: 0.5,
    cues: [cue(1, 2), cue(2, 3)],
    mediaDuration: 10,
  });
  assert.equal(result.ok, true);
  assert.equal(result.plan.index, 2);
});

test('毫秒取整：不会留下 5.669999 这种时间码', () => {
  const result = planCuePaste({
    at: 5.12345,
    length: 0.66666,
    cues: [],
    mediaDuration: 10,
  });
  assert.equal(result.ok, true);
  assert.equal(result.plan.start, 5.123);
  assert.equal(result.plan.end, 5.79);
});

test('时长无效：拒绝', () => {
  assert.equal(planCuePaste({ at: 1, length: 0, cues: [] }).ok, false);
  assert.equal(planCuePaste({ at: 1, length: 0.04, cues: [] }).ok, false);
  assert.equal(planCuePaste({ at: 1, length: Number.NaN, cues: [] }).ok, false);
});

test('摘要：压成一行、带时长；有译文时标出来', () => {
  const plain = {
    text: '入って',
    duration: 0.67,
    translations: {},
    sourceStart: 344.355,
  };
  assert.equal(clipSummary(plain), '「入って」· 0.67s');

  const withTranslation = {
    ...plain,
    translations: { 'zh-Hans': { text: '吸气', base: '入って' } },
  };
  assert.equal(clipSummary(withTranslation), '「入って」· 0.67s · 含译文');
});
