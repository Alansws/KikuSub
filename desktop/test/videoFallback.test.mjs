import assert from 'node:assert/strict';
import test from 'node:test';

import {
  BLANK_FRAME_TIMEOUT_MS,
  hasDecodedFrame,
  needsBlankFrameWatch,
  proxyReasonLabel,
  videoGateState,
} from '../renderer/src/lib/videoFallback.ts';

const base = {
  hasMedia: true,
  hasVideo: true,
  proxyReason: '',
  proxyReady: false,
  proxyBusy: false,
  failed: false,
  blankTimedOut: false,
};

test('正常播放的高码率视频不弹提示（bitrate 只建议手动处理）', () => {
  assert.equal(
    videoGateState({ ...base, proxyReason: 'bitrate', blankTimedOut: true }),
    'none',
  );
  assert.equal(videoGateState({ ...base, proxyReason: 'bitrate', failed: true }), 'offer-proxy');
});

test('容器/编码原因：error 立即进入提示，兜底计时到也进入', () => {
  assert.equal(videoGateState({ ...base, proxyReason: 'container', failed: true }), 'offer-proxy');
  assert.equal(videoGateState({ ...base, proxyReason: 'codec', blankTimedOut: true }), 'offer-proxy');
  // 没有 error、也没到计时：继续让画面加载
  assert.equal(videoGateState({ ...base, proxyReason: 'codec' }), 'none');
});

test('压制中只切换按钮态，暂停/失败后回到可点击的 offer', () => {
  assert.equal(videoGateState({ ...base, proxyReason: 'codec', failed: true, proxyBusy: true }), 'proxy-busy');
  // 任务失败/取消后 job 状态离开 running/queued，proxyBusy 归 false
  assert.equal(videoGateState({ ...base, proxyReason: 'codec', failed: true }), 'offer-proxy');
});

test('代理已就绪但画面仍出不来：只提示，不再提供压制入口', () => {
  assert.equal(
    videoGateState({ ...base, proxyReason: 'codec', failed: true, proxyReady: true }),
    'proxy-unavailable',
  );
  // 代理正常播放时没有任何浮层
  assert.equal(videoGateState({ ...base, proxyReason: 'codec', proxyReady: true }), 'none');
});

test('纯音频 / 没有媒体不出提示', () => {
  assert.equal(videoGateState({ ...base, hasVideo: false, failed: true }), 'none');
  assert.equal(videoGateState({ ...base, hasMedia: false, failed: true }), 'none');
});

test('兜底计时只挂在 container/codec 且没有代理的片子上', () => {
  assert.equal(
    needsBlankFrameWatch({ hasMedia: true, hasVideo: true, proxyReason: 'container', proxyReady: false }),
    true,
  );
  assert.equal(
    needsBlankFrameWatch({ hasMedia: true, hasVideo: true, proxyReason: 'codec', proxyReady: false }),
    true,
  );
  assert.equal(
    needsBlankFrameWatch({ hasMedia: true, hasVideo: true, proxyReason: 'bitrate', proxyReady: false }),
    false,
  );
  assert.equal(
    needsBlankFrameWatch({ hasMedia: true, hasVideo: true, proxyReason: 'container', proxyReady: true }),
    false,
  );
  assert.equal(
    needsBlankFrameWatch({ hasMedia: true, hasVideo: false, proxyReason: 'container', proxyReady: false }),
    false,
  );
});

test('兜底等待在 2～3 秒区间', () => {
  assert.ok(BLANK_FRAME_TIMEOUT_MS >= 2000 && BLANK_FRAME_TIMEOUT_MS <= 3000);
});

test('原因文案不把「编码不支持」写死成结论', () => {
  assert.match(proxyReasonLabel('container'), /容器/);
  assert.match(proxyReasonLabel('codec'), /编码/);
  assert.match(proxyReasonLabel(''), /画面/);
});

test('readyState 够但没有 videoWidth 不算解出画面（ProRes / 10-bit 黑屏回归）', () => {
  assert.equal(hasDecodedFrame(4, 0), false);
  assert.equal(hasDecodedFrame(1, 640), false);
  assert.equal(hasDecodedFrame(2, 640), true);
});
