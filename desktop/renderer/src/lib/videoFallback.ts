/**
 * 核对台黑屏时的代理提示判定（纯逻辑，不碰 DOM）。
 *
 * 判定只看「画面是不是真的出不来」，不替用户决定要不要压：
 *
 * - `<video>` 触发 `error`：容器/编码不支持，最确定的一条；
 * - `container` / `codec` 原因时，从媒体就绪起等一小段时间仍没解出首帧。
 *   计时**不挂在 `loadedmetadata` 上**：容器卡死时它可能永远不触发，
 *   所以调用方在拿到媒体/切换 src 时就开始计时；
 * - `bitrate` 原因只是「能播但拖动可能卡」，永远不弹提示——这种片子
 *   交给工具栏「⋯ → 压制代理」手动处理。
 *
 * 提示出现后，一旦首帧到达（`onloadeddata`）调用方会把状态清掉，
 * 所以慢盘上的误判最多闪一下，不会产生任务。
 */

export type VideoGateState = 'none' | 'offer-proxy' | 'proxy-busy' | 'proxy-unavailable';

export interface VideoGateInput {
  hasMedia: boolean;
  hasVideo: boolean;
  /** `MediaInfo.proxy_reason`：container / codec / bitrate / 空串。 */
  proxyReason: string;
  proxyReady: boolean;
  proxyBusy: boolean;
  /** `<video>` 的 `onerror` 已触发。 */
  failed: boolean;
  /** 兜底计时已到，仍没有解出首帧。 */
  blankTimedOut: boolean;
}

/** 2.5 秒：容器卡住时足够长到不误判，又不会让用户盯着黑屏等太久。 */
export const BLANK_FRAME_TIMEOUT_MS = 2500;

function isUnplayableReason(reason: string): boolean {
  return reason === 'container' || reason === 'codec';
}

/**
 * 是否真的解出了画面。
 *
 * 不能只看 `readyState`：容器能读、元数据也齐、`readyState` 甚至到 4，但视频轨道
 * 解不出来时 `videoWidth` 仍是 0（ProRes MOV、部分 10-bit 片源就是这种黑屏）。
 */
export function hasDecodedFrame(readyState: number, videoWidth: number): boolean {
  return readyState >= 2 && videoWidth > 0;
}

/** 是否值得为这个媒体启动「多久都没出首帧」的兜底计时。 */
export function needsBlankFrameWatch(input: {
  hasMedia: boolean;
  hasVideo: boolean;
  proxyReason: string;
  proxyReady: boolean;
}): boolean {
  return (
    input.hasMedia &&
    input.hasVideo &&
    !input.proxyReady &&
    isUnplayableReason(input.proxyReason)
  );
}

/**
 * 画面中央该显示哪种提示。
 *
 * - `proxy-unavailable`：代理已经就绪但画面仍然出不来，只能提示去看日志/换代理；
 * - `proxy-busy`：用户已经点了压制，画面保持黑屏，进度只由顶部工具栏展示；
 * - `offer-proxy`：可以点按钮开始压制。
 */
export function videoGateState(input: VideoGateInput): VideoGateState {
  if (!input.hasMedia || !input.hasVideo) return 'none';
  const black = input.failed || (isUnplayableReason(input.proxyReason) && input.blankTimedOut);
  if (!black) return 'none';
  if (input.proxyReady) return 'proxy-unavailable';
  return input.proxyBusy ? 'proxy-busy' : 'offer-proxy';
}

/** 画面提示里的一句原因说明；不写「无法解码」这种绝对结论。 */
export function proxyReasonLabel(reason: string): string {
  switch (reason) {
    case 'container':
      return '这个视频的容器格式无法直接播放';
    case 'codec':
      return '这个视频的编码无法直接播放';
    default:
      return '这个视频的画面无法加载';
  }
}
