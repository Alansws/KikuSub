/**
 * 核对台播放传输：逐帧 / 逐秒、暂停与倍速。
 *
 * 为什么单独一个模块：`store.svelte.ts` 有行数预算（红线 11），而 `<video>` 引用只
 * 属于核对屏。`ReviewView.bindVideo()` 把元素交给这里，动作层不需要知道组件内部。
 *
 * 关键约定（2026-11-17 用户要求）：
 * - **高速连按以 `play.time` 为基准**：`seekTo()` 会同步更新 `play.time`，而
 *   `video.currentTime` 在异步 seek 完成前还是旧值；用后者会让连按原地踏步。
 * - 步进前先暂停并清掉 `stopAt`，再走统一 `seekTo()`（不另写 seek 路径）。
 */

import { app, play, seekTo, toast } from './store.svelte';
import { FALLBACK_FPS, normalizeFps, stepFrameTime, stepSecondTime } from './frameStep';

export const transport = $state({
  video: null as HTMLVideoElement | null,
  /** 当前倍速；Phase 3 由 1/2/3 调整。 */
  rate: 1,
});

/** 绑定 `<video>`：新元素（例如切代理后重建）沿用当前倍速。 */
export function attachVideo(node: HTMLVideoElement): void {
  transport.video = node;
  node.playbackRate = transport.rate;
  node.preservesPitch = true;
}

export function detachVideo(node: HTMLVideoElement): void {
  if (transport.video === node) transport.video = null;
}

function mediaDuration(): number {
  const videoDuration = transport.video?.duration;
  return (
    play.duration ||
    app.media?.duration ||
    (typeof videoDuration === 'number' && Number.isFinite(videoDuration) ? videoDuration : 0) ||
    0
  );
}

function pauseForStep(): void {
  const video = transport.video;
  if (video && !video.paused) video.pause();
  play.playing = false;
  play.stopAt = 0;
}

function requireMedia(): boolean {
  if (app.media) return true;
  toast('先导入媒体', 'warn');
  return false;
}

/**
 * 后退 / 前进一帧。
 *
 * 基准永远是同步更新后的 `play.time`——上一次 `seekTo()` 已经把它写成目标值，
 * 即使视频还在解码，下一次按键也不会读到旧 `currentTime`。
 */
export function stepFrames(direction: -1 | 1): void {
  if (!requireMedia()) return;
  pauseForStep();
  const fps = normalizeFps(app.media?.video_fps) || FALLBACK_FPS;
  seekTo(stepFrameTime(play.time, direction, fps, mediaDuration()));
}

/** 后退 / 前进一秒。 */
export function stepSeconds(direction: -1 | 1): void {
  if (!requireMedia()) return;
  pauseForStep();
  seekTo(stepSecondTime(play.time, direction, mediaDuration()));
}

/** 当前媒体的有效帧率；界面提示用。 */
export function effectiveFps(): number {
  return normalizeFps(app.media?.video_fps) || FALLBACK_FPS;
}
