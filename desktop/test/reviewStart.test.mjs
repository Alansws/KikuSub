import assert from 'node:assert/strict';
import test from 'node:test';

const {
  INITIAL_VIEW_ZOOM,
  SHORT_FILM_SECONDS,
  MIN_INITIAL_SPAN,
  claimTranslationDefault,
  planInitialReviewView,
  resetTranslationDefault,
} = await import('../renderer/src/lib/reviewStart.ts');

const cues = (...starts) => starts.map((start, i) => ({ start, end: start + 1.4, id: i }));

test('没有快照时默认聚焦第 1 条字幕，而不是全片 1.0×', () => {
  // 2 小时片：全片视图下 1px 好几十秒，第 1 条字幕根本拖不住
  const plan = planInitialReviewView(7200, cues(18.5, 22, 25), 0.5);
  assert.ok(plan);
  assert.equal(plan.cueIndex, 0);
  assert.equal(plan.seekTo, 18.5);
  assert.equal(plan.span, 7200 / INITIAL_VIEW_ZOOM);
  // 第 1 条字幕落在窗口偏左，左边留一点上下文，并且不越出片头
  assert.ok(plan.viewStart >= 0);
  assert.ok(plan.viewStart <= 18.5);
  assert.ok(plan.viewStart + plan.span <= 7200);
});

test('第 1 条字幕在片头时视窗贴着 0，不出现负起点', () => {
  const plan = planInitialReviewView(600, cues(0, 3.2), 0.5);
  assert.ok(plan);
  assert.equal(plan.viewStart, 0);
  // 已经停在片头：不必再多 seek 一次
  assert.equal(plan.seekTo, null);
  assert.ok(plan.span > 0 && plan.span < 600);
});

test('短片保持全片视图：几十秒的样片放大反而是看不到全貌', () => {
  const plan = planInitialReviewView(3, cues(0.4), 0.5);
  assert.ok(plan);
  assert.equal(plan.span, 3);
  assert.equal(plan.viewStart, 0);

  const mid = planInitialReviewView(SHORT_FILM_SECONDS, cues(23), 0.5);
  assert.ok(mid);
  assert.equal(mid.span, SHORT_FILM_SECONDS);
  assert.equal(mid.viewStart, 0);
});

test('长片的默认窗口有下限，不会因为 50× 得到 0.3 秒', () => {
  const plan = planInitialReviewView(120, cues(40), 0.5);
  assert.ok(plan);
  assert.equal(plan.span, 120 / INITIAL_VIEW_ZOOM); // 2.4s
  const plan2 = planInitialReviewView(70, cues(40), 0.5);
  assert.ok(plan2);
  assert.equal(plan2.span, MIN_INITIAL_SPAN); // 70/50 = 1.4 → 抬到下限
  // 第 1 条字幕超出片长时夹到片尾内，不许出现空窗口
  assert.ok(plan2.viewStart <= 70 - MIN_INITIAL_SPAN);
});

test('没有字幕 / 没有时长时不给默认态（保持全片更安全）', () => {
  assert.equal(planInitialReviewView(600, [], 0.5), null);
  assert.equal(planInitialReviewView(0, cues(0), 0.5), null);
  assert.equal(planInitialReviewView(Number.NaN, cues(1), 0.5), null);
});

test('「有译文轨就默认双语」只在本次启动生效一次', () => {
  resetTranslationDefault();
  assert.equal(claimTranslationDefault(), true);
  // 换片 / 切页回来不再抢用户自己选的显示模式
  assert.equal(claimTranslationDefault(), false);
  resetTranslationDefault();
  assert.equal(claimTranslationDefault(), true);
});
