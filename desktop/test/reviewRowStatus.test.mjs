import assert from 'node:assert/strict';
import test from 'node:test';

const { groupOf, pendingItems, overlaps, rowStatuses, ROW_STATUS_LABEL, rowStatusTitle } =
  await import('../renderer/src/lib/reviewRowStatus.ts');

const cues = [
  { start: 0.0, end: 1.5 },
  { start: 2.0, end: 3.0 },
  { start: 4.0, end: 5.0 },
];

// ---- 分组口径 ----

test('质检项分组与 QaPanel 同口径：coverage 归 miss，其余归 low', () => {
  assert.equal(groupOf({ kind: 'coverage' }), 'miss');
  assert.equal(groupOf({ kind: 'missed' }), 'low');
  // 显式 group 优先
  assert.equal(groupOf({ kind: 'coverage', group: 'low' }), 'low');
  assert.equal(groupOf({ kind: 'anything', group: 'miss' }), 'miss');
});

// ---- 待核筛选 ----

test('已核对 / 已跳过的项不再参与报警', () => {
  const items = [
    { id: 'a', kind: 'dropped', start: 0, end: 1 },
    { id: 'b', kind: 'dropped', start: 2, end: 3 },
  ];
  const statuses = { a: { status: 'done' }, b: { status: 'pending' } };
  assert.deepEqual(
    pendingItems(items, statuses).map((i) => i.id),
    ['b'],
  );
});

test('没有 statuses 时全部按 pending', () => {
  const items = [{ id: 'a', kind: 'dropped' }];
  assert.equal(pendingItems(items, undefined).length, 1);
});

// ---- 重叠 ----

test('端点相接算重叠（质检项贴着句子边界也要提醒）', () => {
  assert.equal(overlaps(0, 1.5, 0, 1.5), true);
  assert.equal(overlaps(0, 1.5, 1.5, 2), true);
  assert.equal(overlaps(0, 1.4, 1.5, 2), false);
});

// ---- 行状态 ----

test('没有待核项时每一行都是 null（绝大多数行不该有徽标）', () => {
  assert.deepEqual(rowStatuses(cues, []), [null, null, null]);
});

test('按时间窗把待核项落到对应字幕行', () => {
  const rows = rowStatuses(cues, [{ id: 'x', kind: 'dropped', start: 2.1, end: 2.8 }]);
  assert.deepEqual(rows, [null, { kind: 'low', count: 1 }, null]);
});

test('漏句（miss）压过低置信（low），同一行只出一个徽标', () => {
  const rows = rowStatuses(cues, [
    { id: 'a', kind: 'dropped', start: 2.0, end: 3.0 },
    { id: 'b', kind: 'coverage', start: 2.2, end: 2.6 },
  ]);
  assert.deepEqual(rows[1], { kind: 'miss', count: 1 });
});

test('同一行多条同类项会累加计数', () => {
  const rows = rowStatuses(cues, [
    { id: 'a', kind: 'dropped', start: 2.0, end: 3.0 },
    { id: 'b', kind: 'suspect', start: 2.5, end: 2.9 },
  ]);
  assert.deepEqual(rows[1], { kind: 'low', count: 2 });
});

test('一条质检项跨多句时每一句都标上', () => {
  const rows = rowStatuses(cues, [{ id: 'a', kind: 'dropped', start: 0, end: 5 }]);
  assert.equal(rows.filter(Boolean).length, 3);
});

test('译文过期在没有任何质检项时才出现（不与待核抢位置）', () => {
  const rows = rowStatuses(cues, [{ id: 'a', kind: 'dropped', start: 0.2, end: 0.8 }], new Set([0, 2]));
  assert.deepEqual(rows[0], { kind: 'low', count: 1 });
  assert.deepEqual(rows[1], null);
  assert.deepEqual(rows[2], { kind: 'stale', count: 0 });
});

test('坏的 start / end 不会把整行标红（按 0 处理，仍要能跑）', () => {
  const rows = rowStatuses(cues, [{ id: 'a', kind: 'dropped', start: 'x', end: undefined }]);
  assert.deepEqual(rows[0], { kind: 'low', count: 1 });
});

// ---- 文案 ----

test('徽标文字短、可读，且不含假精度', () => {
  assert.equal(ROW_STATUS_LABEL.miss, '漏句待核');
  assert.equal(ROW_STATUS_LABEL.low, '待核');
  assert.equal(ROW_STATUS_LABEL.stale, '译文过期');
  for (const label of Object.values(ROW_STATUS_LABEL)) {
    assert.ok(label.length <= 6, `${label} 太长，会挤掉字幕文本`);
    assert.ok(!/[0-9]/.test(label), `${label} 不该出现数字（没有可靠到小数位的置信度）`);
  }
});

test('title 说清原因与去哪儿处理', () => {
  assert.match(rowStatusTitle({ kind: 'miss', count: 3 }), /3 条漏句.*质检待核/);
  assert.match(rowStatusTitle({ kind: 'low', count: 1 }), /1 条低置信/);
  assert.match(rowStatusTitle({ kind: 'stale', count: 0 }), /过期/);
});
