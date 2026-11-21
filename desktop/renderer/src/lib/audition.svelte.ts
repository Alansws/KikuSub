/**
 * 双引擎复核的行内试听：一个**不挂到界面上**的媒体元素，只播一段音窗。
 *
 * 为什么另起一个元素而不是复用核对台的 `<video>`：复核页没有播放器，切回核对台
 * 试听会把用户从「正在比较的这一行」带走——那就不是页内闭环了。这里的工作方式是：
 *
 * - 懒创建 `document.createElement('video')`，不 append 到 DOM（Chromium 照常解码
 *   音轨）。src 与核对台**完全同一份** `/media/{id}`：有代理走代理，否则原片；
 * - 只播 `[start, end]`，`requestAnimationFrame` 盯着 `currentTime` 到点就停；
 * - 容器解不开（MKV / HEVC 且没有代理）时 `<video>` 会 `error`：收掉播放状态并
 *   给一句可执行的提示，不假装在播；
 * - 换一行 / 离开页面 / 再点一次都先 `stop()`，绝不留后台声音。
 *
 * 纯前端状态，不进 50 步历史，也不碰服务端。
 */

import { toast } from './store.svelte';

/** 起播提前量：A 的入点常常正好压在开口帧上，留 30ms 才不会吃掉第一个假名。 */
const LEAD_IN = 0.03;

/** 解不开时的统一说法（与核对台黑框里的「压制 480p 代理」引导同一套动作）。 */
const UNPLAYABLE_HINT = '这个容器解不开原声（MKV / HEVC 需要先压制 480p 代理）';

export const audition = $state({
  /** 正在试听的行 key（DualView 的 `rowKey`）；空串 = 没在播。 */
  key: '',
});

let el: HTMLVideoElement | null = null;
let src = '';
let raf = 0;
/** 这一段的结束时间；0 表示不自动停。 */
let stopAt = 0;
/** 卡死看门狗：解不开的容器既不 error 也不推进 currentTime，只能按时间判。 */
let watchdog = 0;

function ensureEl(): HTMLVideoElement {
  if (el) return el;
  const node = document.createElement('video');
  node.preload = 'auto';
  node.muted = false;
  node.addEventListener('error', () => {
    stopAudition();
    toast(UNPLAYABLE_HINT, 'warn');
  });
  node.addEventListener('ended', () => {
    // 解不开的容器有时直接以「播完」收场（duration=NaN / currentTime 一直 0）：
    // 那不是播完，是没播起来，得说清楚。
    const started = Number.isFinite(node.duration) && node.currentTime > 0.02;
    stopAudition();
    if (!started) toast(UNPLAYABLE_HINT, 'warn');
  });
  el = node;
  return node;
}

function tick() {
  const node = el;
  if (!node || !audition.key) return;
  if (stopAt > 0 && node.currentTime >= stopAt) {
    stopAudition();
    return;
  }
  raf = requestAnimationFrame(tick);
}

function cancelRaf() {
  if (raf) cancelAnimationFrame(raf);
  raf = 0;
  if (watchdog) window.clearTimeout(watchdog);
  watchdog = 0;
}

/**
 * 1.5 秒内 `currentTime` 没动、也没缓冲到可播：判定这个容器解不开。
 *
 * 为什么必须有这一步：MKV / HEVC 喂给 `<video>` 时 Chromium 可能既不派发 `error`
 * 也不推进时间轴（卡在 readyState=0），只靠 `error` 事件会留一个永远「停止中」的按钮。
 */
function armWatchdog(node: HTMLVideoElement, from: number) {
  if (watchdog) window.clearTimeout(watchdog);
  watchdog = window.setTimeout(() => {
    watchdog = 0;
    if (el !== node || !audition.key) return;
    if (node.currentTime > from + 0.001 || node.readyState >= 3) return;
    stopAudition();
    toast(UNPLAYABLE_HINT, 'warn');
  }, 1500);
}

/** 停掉试听（幂等）。`keepKey` 供内部换行时复用。 */
export function stopAudition() {
  cancelRaf();
  audition.key = '';
  stopAt = 0;
  if (!el) return;
  try {
    el.pause();
  } catch {
    /* 元素已被回收时忽略 */
  }
}

/**
 * 试听某个时间窗。
 *
 * 同一个 key 再点一次 = 停止（按钮在播放时显示「停止」）。
 * `mediaSrc` 变化（换片 / 刚压好代理）时重设 `src` 并重新加载。
 */
export function auditionRange(
  key: string,
  start: number,
  end: number,
  mediaSrc: string,
  opts: { unplayable?: boolean } = {},
): void {
  if (audition.key === key) {
    stopAudition();
    return;
  }
  if (!mediaSrc) {
    toast('还没有媒体可以试听', 'warn');
    return;
  }
  // 服务端已经知道这个容器 / 编码解不开：别让用户点了才看到一个假播放态。
  // 判定沿用核对台黑框的同一份口径（`lib/videoFallback.ts`）。
  if (opts.unplayable) {
    toast(UNPLAYABLE_HINT, 'warn');
    return;
  }
  const node = ensureEl();
  if (src !== mediaSrc) {
    src = mediaSrc;
    node.src = mediaSrc;
  }
  stopAudition();
  audition.key = key;
  stopAt = Math.max(start + LEAD_IN, Number(end) || 0);
  node.currentTime = Math.max(0, Number(start) - LEAD_IN);
  armWatchdog(node, node.currentTime);
  const started = node.play();
  // 浏览器拒绝自动播放时如实收掉状态，别留一个「在播」的假按钮。
  if (started && typeof started.catch === 'function') {
    started.catch(() => {
      stopAudition();
      toast('无法播放这段音频（试试先压制 480p 代理）', 'warn');
    });
  }
  raf = requestAnimationFrame(tick);
}
