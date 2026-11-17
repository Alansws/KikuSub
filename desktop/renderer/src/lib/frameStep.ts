/**
 * 逐帧 / 逐秒步进的纯逻辑。
 *
 * - 视频帧率来自服务端 ffprobe（`MediaInfo.video_fps`）；纯音频 / 未知帧率回落到
 *   30fps 等价步长（33.3ms）。
 * - 逐帧用「帧号」而不是「每次加一个浮点步长」：连续按 100 次不会累计漂移。
 * - 这里不碰 DOM、不读 store，`node --test` 可直接加载。
 *
 * VFR（可变帧率）注意：`video_fps` 是平均帧率，帧边界不是等距的，逐帧是时间轴上的
 * 近似帧网格；HTML5 `<video>` 没有「跳到下一真实帧」的 API。
 */

/** 纯音频 / 未知帧率的兜底帧率。33.333ms 一帧。 */
export const FALLBACK_FPS = 30;
export const MIN_FPS = 1;
export const MAX_FPS = 240;

/** 只接受合理范围内的有限帧率；其余按未知处理（返回 0）。 */
export function normalizeFps(raw?: number | null): number {
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return 0;
  if (raw < MIN_FPS || raw > MAX_FPS) return 0;
  return raw;
}

/** 一帧对应多少秒；未知帧率用 30fps 兜底。 */
export function frameStepSeconds(fps?: number | null): number {
  return 1 / (normalizeFps(fps) || FALLBACK_FPS);
}

function clampTime(time: number, duration: number): number {
  const lower = Math.max(0, time);
  return duration > 0 ? Math.min(lower, duration) : lower;
}

/**
 * 后退 / 前进一帧。
 *
 * 以 `Math.round(time / step)` 得到当前帧号，再加减 1；即使传入的时间不在帧边界上，
 * 也会落到最近的帧网格。`duration <= 0` 时只保证非负，上限交给播放器。
 */
export function stepFrameTime(
  time: number,
  direction: -1 | 1,
  fps: number | null | undefined,
  duration: number,
): number {
  const step = frameStepSeconds(fps);
  const frame = Math.round(Math.max(0, time) / step);
  return clampTime((frame + direction) * step, duration);
}

/** 后退 / 前进一秒。 */
export function stepSecondTime(
  time: number,
  direction: -1 | 1,
  duration: number,
): number {
  return clampTime(Math.max(0, time) + direction, duration);
}
