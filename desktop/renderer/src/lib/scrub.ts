/**
 * 播放头擦洗 + 边缘自动滚动（从 `ReviewView.svelte` 抽出，行为不变）。
 *
 * 为什么单独一个文件：核对台的擦洗有三个入口（顶部刻度条、播放头两侧 8px、
 * 视频进度条）共用同一套「暂停 → 跟手写 play.time → 松手恢复播放」的状态机；
 * 而新增的「拖到边缘后继续推进」要读/改同一个 target，留在 2600 行的视图里会让
 * 这条唯一实现再分叉一份。
 *
 * 为什么**零运行时相对导入**：`desktop/test/*.test.mjs` 用 `node --test` 直接加载
 * `.ts`（Node 的类型剥离），而 Node 的 ESM 解析不会给无扩展名的相对路径补 `.ts`，
 * 这里的 `tsconfig` 又没开 `allowImportingTsExtensions`。`lib/` 里被单测覆盖的
 * 模块（`timelineView` / `cueSnap` / `findMatches` …）都遵守同一条：要么零导入，
 * 要么只有 `import type`（类型会被剥掉）。视窗 clamp 因此由调用方以 `clampStart`
 * 依赖注入，避免复制 `clampTimelineView`。
 *
 * 擦洗约定：
 * - `set()` 每 16ms 最多写一次 `video.currentTime`，避免一次拖动触发上百个 seek
 *   把解码器拖死；`play.time` 仍然每次都写（播放头数字必须跟手）。
 * - 外部定位（`seek()` / `seekNonce`）必须走 `cancel()`：在途擦洗要让位，且
 *   不能因为旧的 `resume` 标记把播放重新拉起来。
 *
 * 边缘滚动约定：
 * - 指针进入左右 `EDGE_PAN_ZONE` 热区后开始推进，越界越远越快；压住不动会二次
 *   加速。往左完全对称。
 * - **必须真的拖动过才滚**（`move()` 才武装）：单击刻度条时指针本来就在近缘
 *   热区里，按一下不该把画面自己带走。
 * - 视窗与播放头**同步**推进：播放头在屏幕上钉住不动，媒体时间继续走；
 *   到片头 / 片尾被 clamp 住之后不再推进。
 */

export interface ScrubDeps {
  /** 当前 `<video>`；媒体还没绑定时返回 null，擦洗只写数字不 seek。 */
  getVideo: () => HTMLVideoElement | null;
  /** 当前媒体时长；未就绪时返回 0。 */
  getDuration: () => number;
  /** 擦洗器是否该在松手后恢复播放（由 `play.playing` 决定，与 DOM 的 paused 同源）。 */
  getPlaying: () => boolean;
  /** 写工作区播放头时间（组件里是 `play.time = t; play.stopAt = 0`）。 */
  setTime: (t: number) => void;
  /** 松手后把最终位置带回视窗（组件里是 `revealPlayhead(t)`）。 */
  onFinish: (t: number) => void;
}

export interface Scrubber {
  /** 是否正在擦洗（拖动中）。 */
  readonly active: boolean;
  /** 当前擦洗目标时间；未被拖过时为 0。 */
  readonly target: number;
  /** 按下：暂停（如果在播）并立刻跟手。 */
  begin(t: number): void;
  /** 拖动中更新目标时间。 */
  set(t: number): void;
  /** 松手：落定 seek，按需恢复播放，再交给 `onFinish`。 */
  end(): void;
  /** 外部定位打断擦洗（不恢复播放）；可顺便把目标时间换成新的位置。 */
  cancel(t?: number): void;
}

export function createScrubber(deps: ScrubDeps): Scrubber {
  let active = false;
  let target = 0;
  let raf = 0;
  let resume = false;
  let lastSeekAt = 0;

  function clampTime(t: number): number {
    const max = deps.getDuration() || deps.getVideo()?.duration || Number.POSITIVE_INFINITY;
    return Math.max(0, Math.min(max, t));
  }

  function flush(): void {
    raf = 0;
    const video = deps.getVideo();
    if (!video) return;
    if (Math.abs(video.currentTime - target) < 0.004) return;
    try {
      video.currentTime = target;
    } catch {
      /* 媒体还没就绪：播放头数字照样跟手 */
    }
  }

  function set(t: number): void {
    const value = clampTime(t);
    deps.setTime(value);
    target = value;
    // 每帧最多写一次 currentTime；窗口被遮挡时 rAF 会被节流，
    // 所以再加一条 16ms 的“立即写”分支，保证拖动时画面真的跟手。
    const now = performance.now();
    if (now - lastSeekAt >= 16) {
      lastSeekAt = now;
      flush();
    } else if (!raf) {
      raf = requestAnimationFrame(flush);
    }
  }

  function begin(t: number): void {
    const video = deps.getVideo();
    if (!active) {
      resume = Boolean(video && !video.paused && !video.ended && deps.getPlaying());
      if (resume) video?.pause();
    }
    active = true;
    set(t);
  }

  function end(): void {
    if (!active) return;
    active = false;
    if (raf) {
      cancelAnimationFrame(raf);
      raf = 0;
    }
    const video = deps.getVideo();
    if (video) {
      try {
        video.currentTime = target;
      } catch {
        /* ignore */
      }
    }
    if (resume) {
      resume = false;
      void video?.play().catch(() => {});
    }
    // 擦洗期间不自动平移（手还在拖）；松手后把最终位置带回视窗
    deps.onFinish(target);
  }

  function cancel(t?: number): void {
    active = false;
    if (raf) {
      cancelAnimationFrame(raf);
      raf = 0;
    }
    if (t !== undefined) target = clampTime(t);
  }

  return {
    get active() {
      return active;
    },
    get target() {
      return target;
    },
    begin,
    set,
    end,
    cancel,
  };
}

// ---------------------------------------------------------------- 边缘自动滚动

export interface EdgePanInput {
  /** 指针相对时间轴左缘的像素（`clientX - rect.left`，可以越界为负 / 超过 width）。 */
  x: number;
  /** 时间轴可视宽度（px）。 */
  width: number;
  /** 左右各自的热区宽度（px）。 */
  zone: number;
  /** 满速：每秒推进多少「秒」（由调用方按当前视窗换算）。 */
  maxSpeed: number;
  /** 指针进入热区后已停留的毫秒数：压得越久，额外加速越多。 */
  holdMs?: number;
}

export interface EdgePan {
  /** -1 = 往左滚，+1 = 往右滚，0 = 不动。 */
  dir: -1 | 0 | 1;
  /** 每秒推进的秒数（相对媒体时间轴）。 */
  speed: number;
}

/** 越过热区再多 2 倍热区宽度才到满速：近缘处足够慢，能停在某一帧附近。 */
export const EDGE_PAN_RAMP = 2;
/** 刚越过边缘就有一档「爬行」速度：窗口最大化时指针推不出多远，不能因此滚不动。 */
export const EDGE_PAN_BASE = 0.12;
/** 压住 1200ms 后二次加速到顶。 */
export const EDGE_PAN_HOLD_FULL_MS = 1200;
/** 二次加速最多再快 1.2 倍（合计 2.2×）。 */
export const EDGE_PAN_HOLD_GAIN = 1.2;
/** 左右热区宽度（px）。 */
export const EDGE_PAN_ZONE = 56;
/** 满速 = 当前视窗每秒滚过多少屏。 */
export const EDGE_PAN_SCREENS = 0.6;

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

/**
 * 计算这一刻的边缘滚动速度。
 *
 * - 指针在中间（两侧热区之外）→ `{dir:0, speed:0}`。
 * - 越界距离按 `EDGE_PAN_RAMP` 归一化后取 1.5 次幂，并留 `EDGE_PAN_BASE` 的起步
 *   速度：刚压过边缘是"爬行"，推得越远越接近满速。窗口最大化时指针推不出多远，
 *   靠的就是这一档起步速度。
 * - `holdMs` 只做额外放大，不改变方向；0 表示刚进热区。
 */
export function edgePanVelocity(input: EdgePanInput): EdgePan {
  const { x, width, zone, maxSpeed } = input;
  if (!(width > 0) || !(zone > 0) || !(maxSpeed > 0) || !Number.isFinite(x)) {
    return { dir: 0, speed: 0 };
  }
  const holdMs = Math.max(0, input.holdMs ?? 0);
  const rightOver = x - (width - zone);
  const leftOver = zone - x;
  const dir: -1 | 0 | 1 = rightOver > 0 ? 1 : leftOver > 0 ? -1 : 0;
  if (!dir) return { dir: 0, speed: 0 };
  const over = dir === 1 ? rightOver : leftOver;
  const k = clamp01(over / (zone * EDGE_PAN_RAMP));
  const base = maxSpeed * (EDGE_PAN_BASE + (1 - EDGE_PAN_BASE) * Math.pow(k, 1.5));
  const gain = 1 + clamp01(holdMs / EDGE_PAN_HOLD_FULL_MS) * EDGE_PAN_HOLD_GAIN;
  return { dir, speed: base * gain };
}

export interface ScrubPanDeps {
  /** 拖拽是否还在进行；false 时任何 step 都不推进（防止松手后自己漂）。 */
  isDragging: () => boolean;
  /** 时间轴可视矩形；元素还没挂上时返回 null。 */
  getRect: () => { left: number; width: number } | null;
  getView: () => { start: number; span: number };
  getDuration: () => number;
  /** 视窗起点 clamp（组件里用 `clampTimelineView`，保证只有一份实现）。 */
  clampStart: (start: number, span: number) => number;
  /** 写回视窗起点（跨度不变）。 */
  setView: (start: number) => void;
  /** 播放头随视窗推进同样的秒数。 */
  advance: (deltaSeconds: number) => void;
}

export interface ScrubPan {
  /** 按下播放头：记下指针位置，但先不武装。 */
  arm(clientX: number): void;
  /** 收到 pointermove：记位置并武装。 */
  move(clientX: number): void;
  /** 松手 / 外部定位：全部复位。 */
  reset(): void;
  /** 每帧调用；返回这一帧是否真的推进了。 */
  step(now?: number): boolean;
}

export function createScrubPan(deps: ScrubPanDeps): ScrubPan {
  let pointerX = 0;
  let armed = false;
  /** 指针进入热区的时刻；0 = 不在热区。 */
  let since = 0;
  let lastAt = 0;

  function reset(): void {
    armed = false;
    since = 0;
    lastAt = 0;
  }

  function step(now = performance.now()): boolean {
    if (!armed || !deps.isDragging()) return false;
    const rect = deps.getRect();
    const view = deps.getView();
    const duration = deps.getDuration();
    if (!rect || !(rect.width > 0) || !(view.span > 0) || !(duration > 0)) return false;
    const pan = edgePanVelocity({
      x: pointerX - rect.left,
      width: rect.width,
      zone: EDGE_PAN_ZONE,
      maxSpeed: view.span * EDGE_PAN_SCREENS,
      holdMs: since ? now - since : 0,
    });
    if (!pan.dir || !(pan.speed > 0)) {
      since = 0;
      lastAt = now;
      return false;
    }
    if (!since) since = now;
    // 第一帧只记时间：不知道距上一帧多久，硬推进会跳一下
    const dt = lastAt ? Math.min(0.05, (now - lastAt) / 1000) : 0;
    lastAt = now;
    if (!(dt > 0)) return false;
    const next = deps.clampStart(view.start + pan.dir * pan.speed * dt, view.span);
    const moved = next - view.start;
    // 片头 / 片尾：视窗夹住之后播放头也不该继续滑
    if (!moved) return false;
    deps.setView(next);
    deps.advance(moved);
    return true;
  }

  return {
    arm(clientX: number) {
      pointerX = clientX;
      reset();
    },
    move(clientX: number) {
      pointerX = clientX;
      armed = true;
    },
    reset,
    step,
  };
}
