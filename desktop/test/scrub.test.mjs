import assert from 'node:assert/strict';
import test from 'node:test';

// 擦洗器在浏览器里用 rAF 节流 seek；node 没有这个全局，用定时器顶替。
globalThis.requestAnimationFrame ??= (cb) => setTimeout(() => cb(performance.now()), 0);
globalThis.cancelAnimationFrame ??= (id) => clearTimeout(id);

import {
  EDGE_PAN_BASE,
  EDGE_PAN_HOLD_FULL_MS,
  EDGE_PAN_HOLD_GAIN,
  EDGE_PAN_RAMP,
  EDGE_PAN_SCREENS,
  EDGE_PAN_ZONE,
  createScrubPan,
  createScrubber,
  edgePanVelocity,
} from '../renderer/src/lib/scrub.ts';

// ------------------------------------------------------------ 边缘滚动速度（纯函数）

const WIDTH = 1000;
const ZONE = EDGE_PAN_ZONE;
const MAX = 10;
const RAM = ZONE * EDGE_PAN_RAMP;

const at = (x, extra = {}) => edgePanVelocity({ x, width: WIDTH, zone: ZONE, maxSpeed: MAX, ...extra });

test('指针在中间不动', () => {
  assert.deepEqual(at(500), { dir: 0, speed: 0 });
  assert.deepEqual(at(ZONE), { dir: 0, speed: 0 });
  assert.deepEqual(at(WIDTH - ZONE), { dir: 0, speed: 0 });
});

test('进入右缘热区才开始往右，方向与位置对称', () => {
  const right = at(WIDTH - ZONE + 2);
  assert.equal(right.dir, 1);
  assert.ok(right.speed > 0);
  const left = at(ZONE - 2);
  assert.equal(left.dir, -1);
  assert.ok(Math.abs(left.speed - right.speed) < 1e-12);
});

test('刚越过边缘就有一档爬行速度（窗口最大化时推不远也能滚）', () => {
  const justOver = at(WIDTH - ZONE + 1);
  assert.equal(justOver.dir, 1);
  assert.ok(justOver.speed >= MAX * EDGE_PAN_BASE * 0.98, justOver.speed);
  assert.ok(justOver.speed < at(WIDTH - ZONE + 40).speed);
});

test('越界越远越快，到满速封顶，再远也不超', () => {
  const near = at(WIDTH - ZONE + 10);
  const mid = at(WIDTH - ZONE + 60);
  const far = at(WIDTH - ZONE + RAM);
  assert.ok(near.speed < mid.speed, `${near.speed} < ${mid.speed}`);
  assert.ok(mid.speed < far.speed, `${mid.speed} < ${far.speed}`);
  assert.ok(Math.abs(far.speed - MAX) < 1e-9, far.speed);
  assert.ok(Math.abs(at(WIDTH + 2000).speed - MAX) < 1e-9);
  assert.ok(Math.abs(at(-2000).speed - MAX) < 1e-9);
});

test('压住不动会二次加速，到顶后不再变', () => {
  const fresh = at(WIDTH - ZONE + RAM, { holdMs: 0 });
  const half = at(WIDTH - ZONE + RAM, { holdMs: EDGE_PAN_HOLD_FULL_MS / 2 });
  const full = at(WIDTH - ZONE + RAM, { holdMs: EDGE_PAN_HOLD_FULL_MS });
  const longer = at(WIDTH - ZONE + RAM, { holdMs: EDGE_PAN_HOLD_FULL_MS * 4 });
  assert.ok(fresh.speed < half.speed, `${fresh.speed} < ${half.speed}`);
  assert.ok(Math.abs(full.speed - MAX * (1 + EDGE_PAN_HOLD_GAIN)) < 1e-9, full.speed);
  assert.ok(Math.abs(longer.speed - full.speed) < 1e-9);
});

test('holdMs 永远不改变方向', () => {
  assert.equal(at(500, { holdMs: 5000 }).dir, 0);
  assert.equal(at(WIDTH - ZONE + 40, { holdMs: 5000 }).dir, 1);
});

test('非法输入一律不滚（宽度 / 热区 / 满速 / NaN）', () => {
  assert.deepEqual(edgePanVelocity({ x: 10, width: 0, zone: ZONE, maxSpeed: MAX }), { dir: 0, speed: 0 });
  assert.deepEqual(edgePanVelocity({ x: 10, width: WIDTH, zone: 0, maxSpeed: MAX }), { dir: 0, speed: 0 });
  assert.deepEqual(edgePanVelocity({ x: 10, width: WIDTH, zone: ZONE, maxSpeed: 0 }), { dir: 0, speed: 0 });
  assert.deepEqual(edgePanVelocity({ x: Number.NaN, width: WIDTH, zone: ZONE, maxSpeed: MAX }), {
    dir: 0,
    speed: 0,
  });
});

// ------------------------------------------------------------ 边缘滚动推进器

function harness(init = {}) {
  const state = {
    mode: 'playhead',
    view: { start: 100, span: 10 },
    duration: 1000,
    rect: { left: 0, width: 1000 },
    advanced: 0,
    ...init,
  };
  const pan = createScrubPan({
    isDragging: () => state.mode === 'playhead',
    getRect: () => state.rect,
    getView: () => ({ ...state.view }),
    getDuration: () => state.duration,
    clampStart: (start, span) => Math.max(0, Math.min(start, state.duration - span)),
    setView: (start) => {
      state.view.start = start;
    },
    advance: (delta) => {
      state.advanced += delta;
    },
  });
  return { state, pan };
}

test('没拖动过就不滚：单击刻度条不会把画面带走', () => {
  const { pan } = harness();
  pan.arm(1000 - ZONE + 20);
  assert.equal(pan.step(1000), false);
  assert.equal(pan.step(1016), false);
  assert.equal(pan.step(1600), false);
});

test('拖到右缘外：第二帧开始推进，视窗与播放头同步走', () => {
  const { state, pan } = harness();
  pan.arm(500);
  pan.move(1100);
  assert.equal(pan.step(1000), false); // 首帧只记时间
  assert.equal(pan.step(1016), true);
  assert.ok(state.view.start > 100, state.view.start);
  assert.ok(state.advanced > 0, state.advanced);
  // 推进量 ≈ 速度 × dt，不超过 满速 × 二次加速上限 × dt
  const limit = state.view.span * EDGE_PAN_SCREENS * (1 + EDGE_PAN_HOLD_GAIN) * 0.05;
  assert.ok(state.advanced <= limit + 1e-9, `${state.advanced} <= ${limit}`);
});

test('往左同样能滚，方向相反', () => {
  const { state, pan } = harness();
  pan.arm(500);
  pan.move(-100);
  pan.step(1000);
  assert.equal(pan.step(1016), true);
  assert.ok(state.view.start < 100, state.view.start);
  assert.ok(state.advanced < 0, state.advanced);
});

test('拖回中间后停止推进', () => {
  const { state, pan } = harness();
  pan.arm(500);
  pan.move(1100);
  pan.step(1000);
  pan.step(1016);
  const moved = state.advanced;
  pan.move(500);
  assert.equal(pan.step(1032), false);
  assert.equal(pan.step(1048), false);
  assert.equal(state.advanced, moved);
});

test('片头 / 片尾夹住后不再推进', () => {
  const tail = harness({ view: { start: 990, span: 10 } });
  tail.pan.arm(500);
  tail.pan.move(1200);
  tail.pan.step(1000);
  assert.equal(tail.pan.step(1016), false);
  assert.equal(tail.state.view.start, 990);

  const head = harness({ view: { start: 0, span: 10 } });
  head.pan.arm(500);
  head.pan.move(-200);
  head.pan.step(1000);
  assert.equal(head.pan.step(1016), false);
  assert.equal(head.state.view.start, 0);
});

test('松手 reset 之后不再推进', () => {
  const { state, pan } = harness();
  pan.arm(500);
  pan.move(1100);
  pan.step(1000);
  pan.step(1016);
  const moved = state.advanced;
  pan.reset();
  assert.equal(pan.step(1032), false);
  assert.equal(state.advanced, moved);
});

test('只认播放头拖动，其它拖拽模式不滚', () => {
  const { pan } = harness({ mode: 'select' });
  pan.arm(500);
  pan.move(1100);
  assert.equal(pan.step(1000), false);
  assert.equal(pan.step(1016), false);
});

test('无矩形 / 时长未就绪时不滚', () => {
  const noRect = harness({ rect: null });
  noRect.pan.arm(500);
  noRect.pan.move(1100);
  assert.equal(noRect.pan.step(1000), false);

  const noDuration = harness({ duration: 0 });
  noDuration.pan.arm(500);
  noDuration.pan.move(1100);
  assert.equal(noDuration.pan.step(1000), false);
});

// ------------------------------------------------------------ 擦洗器

function fakeVideo(init = {}) {
  const video = {
    currentTime: 0,
    duration: 100,
    paused: false,
    ended: false,
    played: 0,
    pausedCount: 0,
    play() {
      video.paused = false;
      video.played += 1;
      return Promise.resolve();
    },
    pause() {
      video.paused = true;
      video.pausedCount += 1;
    },
    ...init,
  };
  return video;
}

function scrubberHarness(video = fakeVideo()) {
  const written = [];
  const scrub = createScrubber({
    getVideo: () => video,
    getDuration: () => video.duration,
    getPlaying: () => !video.paused,
    setTime: (t) => written.push(t),
    onFinish: (t) => written.push(`end:${t}`),
  });
  return { video, written, scrub };
}

test('擦洗：按下暂停、跟手写时间、松手 seek 并恢复播放', () => {
  const { video, written, scrub } = scrubberHarness();
  scrub.begin(3.2);
  assert.equal(scrub.active, true);
  assert.equal(video.paused, true);
  assert.equal(written.at(-1), 3.2);
  scrub.set(4.5);
  assert.equal(scrub.target, 4.5);
  scrub.end();
  assert.equal(scrub.active, false);
  assert.equal(video.currentTime, 4.5);
  assert.equal(video.played, 1);
  assert.equal(written.at(-1), 'end:4.5');
});

test('擦洗：静止的播放器松手后不会被拉起来', () => {
  const { video, scrub } = scrubberHarness(fakeVideo({ paused: true }));
  scrub.begin(1);
  scrub.end();
  assert.equal(video.played, 0);
});

test('擦洗：时间夹进 [0, duration]', () => {
  const { scrub } = scrubberHarness();
  scrub.begin(-5);
  assert.equal(scrub.target, 0);
  scrub.set(999);
  assert.equal(scrub.target, 100);
});

test('擦洗：外部定位打断后不恢复播放', () => {
  const { video, scrub } = scrubberHarness();
  scrub.begin(3);
  scrub.cancel(7);
  assert.equal(scrub.active, false);
  assert.equal(scrub.target, 7);
  assert.equal(video.played, 0);
});
