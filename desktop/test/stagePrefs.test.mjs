import assert from 'node:assert/strict';
import test from 'node:test';

const {
  STAGE_MIN_H,
  STAGE_MAX_RATIO,
  clampStageHeight,
  stageMaxHeight,
  proxyLabel,
  mediaResolution,
} = await import('../renderer/src/lib/stagePrefs.ts');

// ---- 高度夹取 ----

test('0 表示「恢复默认」，不会被当成 0 像素高', () => {
  assert.equal(clampStageHeight(0, 900), 0);
  assert.equal(clampStageHeight(-40, 900), 0);
  assert.equal(clampStageHeight(Number.NaN, 900), 0);
});

test('拖得再小也不低于最小高度', () => {
  assert.equal(clampStageHeight(10, 900), STAGE_MIN_H);
});

test('拖高上限跟着窗口走，留出时间轴与表格', () => {
  const cap = stageMaxHeight(900);
  assert.equal(cap, Math.round(900 * STAGE_MAX_RATIO));
  assert.equal(clampStageHeight(9999, 900), cap);
  // 窗口更矮，上限更低
  assert.ok(stageMaxHeight(600) < cap);
});

test('上限不会低于最小高度（极矮窗口下仍有可用画面）', () => {
  assert.ok(stageMaxHeight(100) >= STAGE_MIN_H);
});

test('合法高度原样取整，不被夹变形', () => {
  assert.equal(clampStageHeight(412.6, 900), 413);
});

// ---- 状态条文案 ----

test('代理状态三种口径', () => {
  assert.equal(proxyLabel({ proxy_ready: true }), '480p 监看代理已就绪');
  assert.equal(proxyLabel({ needs_proxy: true }), '建议压制监看代理');
  assert.equal(proxyLabel({}), '原始画面');
  assert.equal(proxyLabel(null), '');
});

test('就绪优先于「需要代理」：已压好的片子不该再催一次', () => {
  assert.equal(proxyLabel({ proxy_ready: true, needs_proxy: true }), '480p 监看代理已就绪');
});

test('分辨率与编码拼成一段，缺项不留下多余的分隔符', () => {
  assert.equal(mediaResolution({ video_width: 1920, video_height: 1080, video_codec: 'h264' }), '1920×1080 · H264');
  assert.equal(mediaResolution({ video_width: 1920, video_height: 1080 }), '1920×1080');
  assert.equal(mediaResolution({ video_codec: 'hevc' }), 'HEVC');
  assert.equal(mediaResolution({}), '');
  assert.equal(mediaResolution(null), '');
});
