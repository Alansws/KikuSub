/**
 * 断句重排的分段坐标系（`lib/reshapePlan.ts`）。
 *
 * 这些用例钉的是 2026-11-15 那次「4 段变 3 段」的三条根因：
 * 1. 切的段是原稿坐标，覆盖后靠 delta 平移，不能按当前条数重切；
 * 2. 段的身份是原稿起条号，不是展示区间（挪过之后展示区间会漂）；
 * 3. 已覆盖计数只数当前计划里真的存在的那几段，不数僵尸 key。
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { planSegments } from '../renderer/src/lib/aiSegments.ts';
import {
  appliedCount,
  clampIndex,
  expectedTotal,
  markFor,
  planKey,
  rangeFor,
  remapApplied,
  sameSegments,
  segmentKey,
  shiftFor,
  undoCandidate,
} from '../renderer/src/lib/reshapePlan.ts';

/** 照着 501 条 / 150 条一段切出来的样子造一份分段。 */
function plan(segments, baseTotal) {
  return {
    id: 1,
    key: planKey({ mediaId: 'film-a', mode: 'rewrite', altId: 1700000000, hasCues: true }),
    longMode: true,
    segments,
    baseTotal,
    baseRevision: 0,
    reason: '进页',
  };
}

function seg(from, to) {
  return { from, to, start: from * 3, end: to * 3, count: to - from + 1 };
}

const SEGMENTS = [seg(1, 160), seg(161, 327), seg(328, 478), seg(479, 501)];

test('planKey 只由「哪一份工作」决定：不含条数，换第二版才换键', () => {
  const base = { mediaId: 'film-a', mode: 'rewrite', altId: 1, hasCues: true };
  assert.equal(planKey(base), planKey({ ...base }));
  assert.notEqual(planKey(base), planKey({ ...base, altId: 2 }));
  assert.notEqual(planKey(base), planKey({ ...base, mediaId: 'film-b' }));
  assert.notEqual(planKey(base), planKey({ ...base, hasCues: false }));
  // 键入参只有四个字段：条数与单源/双源都不是它的输入，构造上就进不来。
  assert.equal(Object.keys(base).includes('source'), false);
});

test('段的身份是原稿起条号，平移之后也不变', () => {
  const p = plan(SEGMENTS, 501);
  assert.equal(segmentKey(SEGMENTS[2]), '328');
  // 覆盖前两段：第一段 160→120（-40），第二段 167→150（-17）
  const applied = {
    '1': markFor({ from: 1, to: 160, replaced: 160, inserted: 120 }, 1),
    '161': markFor({ from: 121, to: 287, replaced: 167, inserted: 150 }, 2),
  };
  assert.equal(shiftFor(applied, p, SEGMENTS[2]), -57);
  assert.deepEqual(rangeFor(applied, p, SEGMENTS[2]), { from: 271, to: 421 });
  // 起条号没变：段轨的勾、在途草稿都还认得出这一段的身份
  assert.equal(segmentKey(SEGMENTS[2]), '328');
});

test('shiftFor 不把自己那一段的 delta 算到自己头上', () => {
  const p = plan(SEGMENTS, 501);
  const applied = { '328': markFor({ from: 328, to: 478, replaced: 151, inserted: 90 }, 1) };
  assert.equal(shiftFor(applied, p, SEGMENTS[2]), 0);
  assert.deepEqual(rangeFor(applied, p, SEGMENTS[3]), { from: 418, to: 440 });
});

test('已覆盖计数只数当前计划里的段，不数旧计划留下的僵尸 key', () => {
  const p = plan(SEGMENTS, 501);
  const applied = {
    '1': markFor({ from: 1, to: 160, replaced: 160, inserted: 160 }, 1),
    '161': markFor({ from: 161, to: 327, replaced: 167, inserted: 167 }, 2),
    // 旧计划（"1-141" 那套）留下的僵尸：不该算进 2/4
    '328-478': markFor({ from: 328, to: 478, replaced: 151, inserted: 151 }, 3),
  };
  assert.equal(appliedCount(applied, p), 2);
  assert.equal(appliedCount({}, p), 0);
});

test('整片（不分段）模式的段 key 恒为 "1"：覆盖后条数变了也还认得出', () => {
  const p = plan([], 501);
  p.longMode = false;
  assert.equal(appliedCount({ '1': markFor({ from: 1, to: 501, replaced: 501, inserted: 400 }, 1) }, p), 1);
  assert.equal(appliedCount({ '1-501': markFor({ from: 1, to: 501, replaced: 501, inserted: 400 }, 1) }, p), 0);
});

test('expectedTotal = 原稿条数 + 各段 delta', () => {
  const p = plan(SEGMENTS, 501);
  const applied = {
    '1': markFor({ from: 1, to: 160, replaced: 160, inserted: 120 }, 1),
    '161': markFor({ from: 121, to: 287, replaced: 167, inserted: 150 }, 2),
  };
  assert.equal(expectedTotal(p, applied), 444);
  assert.equal(expectedTotal(p, {}), 501);
});

test('markFor 记下「覆盖前被换掉的区间」与「覆盖后实际占的区间」', () => {
  const mark = markFor({ from: 328, to: 478, replaced: 151, inserted: 96 }, 123);
  assert.equal(mark.delta, -55);
  assert.equal(mark.at, 123);
  assert.equal(mark.wasFrom, 328);
  assert.equal(mark.wasTo, 478);
  assert.equal(mark.atFrom, 328);
  assert.equal(mark.atTo, 423);
});

test('⌘Z：靠 redo 标签里的被换区间认出是哪一段', () => {
  const applied = {
    '1': markFor({ from: 1, to: 160, replaced: 160, inserted: 120 }, 1),
    '161': markFor({ from: 121, to: 287, replaced: 167, inserted: 150 }, 2),
  };
  assert.equal(undoCandidate('断句重排：覆盖第 121–287 条（150 条）', applied), '161');
  // 不是断句重排的标签 / 区间对不上 → 认不出来，交给「计划失效」横幅
  assert.equal(undoCandidate('AI 建议：采纳第 3 条', applied), null);
  assert.equal(undoCandidate('断句重排：覆盖第 400–450 条（30 条）', applied), null);
  // 整份覆盖的标签不带区间：只有唯一一段时才没有歧义
  assert.equal(undoCandidate('断句重排：整份覆盖（400 条）', { '1': applied['1'] }), '1');
  assert.equal(undoCandidate('断句重排：整份覆盖（400 条）', applied), null);
});

test('重新分段：已覆盖区域完整落在新段内才保留勾选，跨边界的一律重做', () => {
  const oldMarks = {
    '1': markFor({ from: 1, to: 160, replaced: 160, inserted: 120 }, 1), // 现在占 1–120
    '161': markFor({ from: 121, to: 287, replaced: 167, inserted: 150 }, 2), // 现在占 121–270
  };
  // 新计划把 1–120 完整包住、把 121–270 从中间切开
  const remapped = remapApplied([seg(1, 130), seg(131, 260), seg(261, 500)], oldMarks);
  assert.deepEqual(Object.keys(remapped), ['1']);
  // 新计划与旧的边界一致时，两个勾都还在
  const same = remapApplied([seg(1, 120), seg(121, 270), seg(271, 500)], oldMarks);
  assert.deepEqual(Object.keys(same).sort(), ['1', '121']);
});

test('sameSegments 只比边界，不比时间', () => {
  assert.equal(sameSegments(SEGMENTS, SEGMENTS.map((s) => ({ ...s, start: 0, end: 0 }))), true);
  assert.equal(sameSegments(SEGMENTS, [seg(1, 161), seg(162, 327), seg(328, 478), seg(479, 501)]), false);
  assert.equal(sameSegments(SEGMENTS, SEGMENTS.slice(0, 3)), false);
});

test('clampIndex 把段号夹在计划范围内', () => {
  assert.equal(clampIndex(2, 4), 2);
  assert.equal(clampIndex(9, 4), 3);
  assert.equal(clampIndex(-1, 4), 0);
  assert.equal(clampIndex(3, 0), 0);
});

/**
 * 这条不是测 `reshapePlan.ts`，而是把「为什么不能重切」钉成回归：
 * 同一套分段参数，501 条切成 4 段，掉到 432 条就只剩 3 段。
 * 只要覆盖过一段，表条数就变了；此时任何一次静默重切都会换掉整页的坐标系。
 */
test('为什么不能重切：条数一变，同一套参数切出来的段数就变了', () => {
  const opts = { targetCues: 150, toleranceCues: 20, toleranceSeconds: 120, maxCues: 600, maxChars: 60_000 };
  const mk = (count) => {
    const out = [];
    let t = 0;
    for (let i = 0; i < count; i += 1) {
      out.push({ start: t, end: t + 2.2, text: 'セリフ' });
      t += 3.2;
    }
    return out;
  };
  const at501 = planSegments(mk(501), mk(516), opts);
  const at432 = planSegments(mk(432), mk(516), opts);
  assert.equal(at501.length, 4);
  assert.equal(at432.length, 3);
  assert.equal(sameSegments(at501, at432), false);
});
