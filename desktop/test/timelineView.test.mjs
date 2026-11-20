import assert from 'node:assert/strict';
import test from 'node:test';

import {
  clampTimelineView,
  focusTimelineSpan,
  revealTimelineView,
  sliderToSpan,
  spanToSlider,
  toggleFitView,
} from '../renderer/src/lib/timelineView.ts';

test('clampTimelineView 把视窗夹进媒体范围', () => {
  assert.deepEqual(clampTimelineView(-5, 10, 100, 0.5), { start: 0, span: 10 });
  assert.deepEqual(clampTimelineView(95, 10, 100, 0.5), { start: 90, span: 10 });
  assert.deepEqual(clampTimelineView(10, 10, 0, 0.5), { start: 0, span: 10 });
});

test('focusTimelineSpan 固定 duration/69，未就绪时退回 2–12 秒', () => {
  assert.equal(focusTimelineSpan(100, 10, 0.5, 69), 100 / 69);
  assert.equal(focusTimelineSpan(0, 60, 0.5, 69), 10);
  assert.equal(focusTimelineSpan(0, 1, 0.5, 69), 2);
});

test('缩放滑杆值与跨度可以往返', () => {
  for (const span of [0.5, 1, 10, 60]) {
    const value = spanToSlider(span, 100, 0.5);
    const back = sliderToSpan(value, 100, 0.5);
    assert.ok(Math.abs(back - span) < 1e-6, `${span} → ${value} → ${back}`);
  }
});

test('全片适应切换记住并恢复上一次缩放', () => {
  const zoomed = { start: 10, span: 5 };
  const fit = toggleFitView(zoomed, null, 100, 0.5);
  assert.deepEqual(fit.view, { start: 0, span: 100 });
  assert.deepEqual(fit.saved, zoomed);
  assert.equal(fit.fitted, true);

  const restored = toggleFitView(fit.view, fit.saved, 100, 0.5);
  assert.deepEqual(restored.view, zoomed);
  assert.equal(restored.saved, null);
  assert.equal(restored.fitted, false);
});

test('没有记住的缩放时，已经在全片就 no-op', () => {
  const fit = toggleFitView({ start: 0, span: 100 }, null, 100, 0.5);
  assert.deepEqual(fit.view, { start: 0, span: 100 });
  assert.equal(fit.saved, null);
});

test('跟随定位：关闭 / 已在视窗内不动；出界才平移', () => {
  const view = { start: 10, span: 10 };
  assert.deepEqual(revealTimelineView(view, 5, 100, 0.5, false), view);
  assert.deepEqual(revealTimelineView(view, 15, 100, 0.5, true), view);
  assert.deepEqual(revealTimelineView(view, 30, 100, 0.5, true), {
    start: 21.5,
    span: 10,
  });
});
