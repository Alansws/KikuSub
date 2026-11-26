import assert from 'node:assert/strict';
import test from 'node:test';

const { ROW_H, OVERSCAN, FALLBACK_VIEW_H, rowHeightFor, virtualWindow, revealScrollTop } =
  await import('../renderer/src/lib/reviewTable.ts');

// ---- 行高 ----

test('双语是固定双行高，其他模式是单行', () => {
  assert.equal(rowHeightFor('both'), ROW_H * 2);
  assert.equal(rowHeightFor('source'), ROW_H);
  assert.equal(rowHeightFor('target'), ROW_H);
  // 单行 30px 是界面预算（2026-11-21 定下）：再高就少显示两行
  assert.equal(ROW_H, 30);
});

// ---- 虚拟窗口 ----

test('在顶部时从第 0 行开始，并只留可视行 + 上下 overscan', () => {
  const w = virtualWindow({ scrollTop: 0, viewH: 600, total: 500, rowH: 30 });
  assert.equal(w.start, 0);
  assert.equal(w.end, Math.ceil(600 / 30) + OVERSCAN * 2);
  assert.equal(w.padTop, 0);
  assert.equal(w.padBottom, (500 - w.end) * 30);
});

test('上下占位高度加起来正好等于未渲染的行高和', () => {
  const w = virtualWindow({ scrollTop: 3000, viewH: 600, total: 500, rowH: 30 });
  const rendered = (w.end - w.start) * 30;
  assert.equal(w.padTop + rendered + w.padBottom, 500 * 30);
});

test('滚动后窗口跟着下移，且顶部不再是 0', () => {
  const top = virtualWindow({ scrollTop: 0, viewH: 600, total: 500, rowH: 30 });
  const mid = virtualWindow({ scrollTop: 3000, viewH: 600, total: 500, rowH: 30 });
  assert.ok(mid.start > top.start);
  assert.ok(mid.padTop > 0);
});

test('双语模式按双行高算：同样滚动位置渲染的行数减半', () => {
  const single = virtualWindow({ scrollTop: 3000, viewH: 600, total: 500, rowH: 30 });
  const dual = virtualWindow({ scrollTop: 3000, viewH: 600, total: 500, rowH: 60 });
  assert.ok(dual.end - dual.start < single.end - single.start);
});

test('总数小于一屏时 end 夹到总数，底部占位为 0', () => {
  const w = virtualWindow({ scrollTop: 0, viewH: 600, total: 3, rowH: 30 });
  assert.equal(w.end, 3);
  assert.equal(w.padBottom, 0);
});

test('空表给空窗口，底部占位不会变成负数', () => {
  const w = virtualWindow({ scrollTop: 0, viewH: 600, total: 0, rowH: 30 });
  assert.equal(w.start, 0);
  assert.equal(w.end, 0);
  assert.equal(w.padBottom, 0);
});

test('滚动位置是负数 / NaN 时按顶部处理，不抛错', () => {
  for (const scrollTop of [-100, Number.NaN]) {
    const w = virtualWindow({ scrollTop, viewH: 600, total: 500, rowH: 30 });
    assert.equal(w.start, 0);
    assert.equal(w.padTop, 0);
  }
});

test('还没测量到可视高度时用兜底值，不会只渲染几行', () => {
  const w = virtualWindow({ scrollTop: 0, viewH: 0, total: 500, rowH: 30 });
  assert.equal(w.end, Math.ceil(FALLBACK_VIEW_H / 30) + OVERSCAN * 2);
});

test('同样的输入永远给同样的窗口（纯函数）', () => {
  const input = { scrollTop: 1234, viewH: 480, total: 300, rowH: 30 };
  assert.deepEqual(virtualWindow(input), virtualWindow({ ...input }));
});

// ---- 滚到某一行 ----

test('已经在可视区中间就不滚（播放时每句都不抖）', () => {
  const target = revealScrollTop({ index: 10, scrollTop: 0, viewH: 1200, rowH: 30 });
  assert.equal(target, null);
});

test('目标在下方视窗外时滚到可视区约 40% 处', () => {
  const target = revealScrollTop({ index: 100, scrollTop: 0, viewH: 600, rowH: 30 });
  assert.equal(target, (100 - Math.floor((600 * 0.4) / 30)) * 30);
});

test('目标在顶部视窗外时滚回去，不会是负数', () => {
  const target = revealScrollTop({ index: 0, scrollTop: 6000, viewH: 600, rowH: 30 });
  assert.equal(target, 0);
});

test('贴边一行不会触发滚动（阈值是上下各两行）', () => {
  // 第 2 行起点 = 60，视窗顶 0 + 2 行 = 60，正好在阈值内
  assert.equal(revealScrollTop({ index: 2, scrollTop: 0, viewH: 600, rowH: 30 }), null);
});
