import assert from 'node:assert/strict';
import test from 'node:test';

// Node 的 localStorage 视版本可能不存在（也可能需要 flag）：测试里换成内存实现，
// 模块内部是懒取的，所以只要在首次调用前挂上就行。
class MemoryStorage {
  constructor() {
    this.map = new Map();
  }
  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null;
  }
  setItem(key, value) {
    this.map.set(String(key), String(value));
  }
  removeItem(key) {
    this.map.delete(key);
  }
  clear() {
    this.map.clear();
  }
}

globalThis.localStorage = new MemoryStorage();

const {
  MAX_PEAK_ENTRIES,
  MAX_VIEWPORTS,
  cachedPeaks,
  clearPeakCache,
  clearViewportStore,
  forgetViewport,
  markExplicitJump,
  normalizeViewport,
  peakCacheKey,
  planViewportRestore,
  readViewport,
  readViewportForRestore,
  rememberViewport,
  resetExplicitJump,
  resolveCueIndex,
  storePeaks,
  takeExplicitJump,
} = await import('../renderer/src/lib/reviewViewport.ts');

const snapshot = (over = {}) => ({
  cueIndex: 3,
  cueTime: 12,
  playhead: 12.5,
  viewStart: 8,
  span: 20,
  selection: { start: 11, end: 14 },
  ...over,
});

test('每部影片的现场按路径分开存，换片不串', () => {
  clearViewportStore();
  rememberViewport('/movies/a.mp4', snapshot());
  rememberViewport('/movies/b.mp4', snapshot({ playhead: 99, cueIndex: 7 }));

  assert.equal(readViewport('/movies/a.mp4').playhead, 12.5);
  assert.equal(readViewport('/movies/b.mp4').playhead, 99);
  assert.equal(readViewport('/movies/c.mp4'), null);
});

test('同一位置重复写不再落盘（核对台每 2 秒会调一次）', () => {
  clearViewportStore();
  assert.equal(rememberViewport('/movies/a.mp4', snapshot()), true);
  assert.equal(rememberViewport('/movies/a.mp4', snapshot()), false);
  // 播放头真的动了才写
  assert.equal(rememberViewport('/movies/a.mp4', snapshot({ playhead: 13.4 })), true);
});

test('LRU 只保留最近 50 部', () => {
  clearViewportStore();
  for (let i = 0; i < MAX_VIEWPORTS + 5; i += 1) {
    rememberViewport(`/movies/${i}.mp4`, snapshot({ playhead: i + 1 }));
  }
  assert.equal(readViewport('/movies/0.mp4'), null, '最旧的应该被淘汰');
  assert.equal(readViewport('/movies/4.mp4'), null);
  assert.ok(readViewport(`/movies/${MAX_VIEWPORTS + 4}.mp4`), '最新的必须还在');
});

test('forgetViewport 只删一部', () => {
  clearViewportStore();
  rememberViewport('/movies/a.mp4', snapshot());
  rememberViewport('/movies/b.mp4', snapshot());
  forgetViewport('/movies/a.mp4');
  assert.equal(readViewport('/movies/a.mp4'), null);
  assert.ok(readViewport('/movies/b.mp4'));
});

test('损坏 / 半截数据安全降级为「没有现场」', () => {
  assert.equal(normalizeViewport(null), null);
  assert.equal(normalizeViewport({}), null);
  assert.equal(normalizeViewport({ playhead: 'x', span: 'y' }), null);
  // 倒序选区被丢掉，其余字段仍可用
  const bad = normalizeViewport({ playhead: 5, selection: { start: 9, end: 2 } });
  assert.equal(bad.selection.start, 2);
  assert.equal(bad.selection.end, 9);
});

test('恢复：播放头/视窗/选区都按片长 clamp', () => {
  const plan = planViewportRestore(snapshot({ playhead: 500, viewStart: 400, span: 300 }), 100, 0.5);
  assert.equal(plan.seekTo, 100, '播放头夹到片尾');
  assert.equal(plan.span, 100, '跨度不能超过片长');
  assert.equal(plan.viewStart, 0);
});

test('恢复：很靠前的播放头不打扰用户（不 seek）', () => {
  const plan = planViewportRestore(snapshot({ playhead: 0.05 }), 100, 0.5);
  assert.equal(plan.seekTo, null);
});

test('恢复：没有跨度的旧现场不覆盖当前视窗', () => {
  const plan = planViewportRestore(
    { cueIndex: -1, cueTime: 0, playhead: 42, viewStart: 0, span: 0, selection: null, updatedAt: 0 },
    100,
    0.5,
  );
  assert.equal(plan.span, 0);
  assert.equal(plan.seekTo, 42);
});

test('显式跳转优先：本次恢复计划为 null', () => {
  clearViewportStore();
  rememberViewport('/movies/a.mp4', snapshot());
  markExplicitJump('/movies/a.mp4');
  assert.equal(takeExplicitJump('/movies/a.mp4'), true);
  const plan = planViewportRestore(readViewport('/movies/a.mp4'), 100, 0.5, { explicit: true });
  assert.equal(plan, null);
  // 消费后不会影响下一次
  assert.equal(takeExplicitJump('/movies/a.mp4'), false);
});

test('显式跳转只对同一部片生效', () => {
  resetExplicitJump();
  markExplicitJump('/movies/a.mp4');
  assert.equal(takeExplicitJump('/movies/b.mp4'), false);
  assert.equal(takeExplicitJump('/movies/a.mp4'), true);
});

test('恢复选中行：下标错位时按 cueTime 找最近的一句', () => {
  const cues = [
    { start: 0, end: 1 },
    { start: 10, end: 11 },
    { start: 20, end: 21 },
  ];
  assert.equal(resolveCueIndex(cues, { cueIndex: 1, cueTime: 10 }), 1);
  // 重新转写后下标 1 变成了 10s 以外的东西：按时间找
  assert.equal(resolveCueIndex(cues, { cueIndex: 2, cueTime: 9.8 }), 1);
  assert.equal(resolveCueIndex([], { cueIndex: 0, cueTime: 0 }), null);
});

test('旧版「上次播放头」迁移成现场快照', () => {
  clearViewportStore();
  localStorage.setItem('kikusub.lastPosition', JSON.stringify({ path: '/movies/legacy.mp4', time: 33 }));
  const restored = readViewportForRestore('/movies/legacy.mp4');
  assert.equal(restored.playhead, 33);
  assert.equal(restored.span, 0, '旧格式没有视窗，交给当前视图');
  assert.equal(readViewportForRestore('/movies/other.mp4'), null);
});

test('波形缓存：命中即 LRU 提升，超上限淘汰最旧', () => {
  clearPeakCache();
  const key = peakCacheKey('m1', 0, 60, 900);
  assert.equal(cachedPeaks(key), null);
  storePeaks(key, [0.1, 0.2]);
  assert.deepEqual(cachedPeaks(key), [0.1, 0.2]);

  for (let i = 0; i < MAX_PEAK_ENTRIES; i += 1) {
    storePeaks(peakCacheKey('m1', i, 10, 100), [i]);
  }
  // 最早的 key 被淘汰
  assert.equal(cachedPeaks(key), null);
});

test('波形缓存键区分视窗与采样点数', () => {
  assert.notEqual(peakCacheKey('m1', 0, 60, 900), peakCacheKey('m1', 0, 60, 901));
  assert.notEqual(peakCacheKey('m1', 0, 60, 900), peakCacheKey('m1', 1, 59, 900));
  assert.notEqual(peakCacheKey('m1', 0, 60, 900), peakCacheKey('m2', 0, 60, 900));
  // 浮点误差不该制造第二个缓存项
  assert.equal(peakCacheKey('m1', 0.00001, 60, 900), peakCacheKey('m1', 0, 60, 900));
});
