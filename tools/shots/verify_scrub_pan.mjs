#!/usr/bin/env node
/**
 * 「播放头拖到边缘自动滚动」无窗口回归（2026-11-25）。
 *
 * 覆盖：
 *   - 单击刻度条（指针本来就在近缘热区）不会自己滚；
 *   - 把播放头拖到右缘外：视窗与播放头同步推进、播放头钉在右缘、缩放不变；
 *   - 松手立刻停，画面落在最终位置；
 *   - 往左对称；
 *   - 拖动中时间码单调递增（不是跳到视窗末端）。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现。断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_scrub_pan.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_scrub_pan.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-scrub-pan');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');
const SHOT = path.join(BASE, 'scrub-pan.png');

const CUES = [
  { start: 0.5, end: 1.5, text: '深呼吸して' },
  { start: 2.0, end: 3.0, text: '吸って' },
  { start: 4.0, end: 5.0, text: 'もう一回' },
];

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const waitFor = async (fn, ms = 10000) => {
      const t0 = Date.now();
      while (Date.now() - t0 < ms) {
        const value = fn();
        if (value) return value;
        await sleep(80);
      }
      return null;
    };
    const video = () => document.querySelector('video');
    const wave = () => document.querySelector('.wave-wrap');
    const rect = () => wave().getBoundingClientRect();
    const timeText = () => document.querySelector('.tp-time')?.textContent.trim() ?? '';
    const timeValue = () => {
      const parts = timeText().split(':').map(Number);
      return parts.length === 3 ? parts[0] * 3600 + parts[1] * 60 + parts[2] : 0;
    };
    const slider = () => document.querySelector('.zoom-slider')?.value ?? '';
    const playhead = () => {
      const el = document.querySelector('.ph');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return r.left + r.width / 2;
    };
    const pointer = (type, x, y, id) =>
      wave().dispatchEvent(
        new PointerEvent(type, {
          bubbles: true,
          cancelable: true,
          clientX: x,
          clientY: y,
          pointerId: id,
          pointerType: 'mouse',
          button: 0,
          buttons: type === 'pointerup' ? 0 : 1,
        }),
      );
    const seekTo = async (t) => {
      const r = rect();
      const x = r.left + (t / 8) * r.width;
      pointer('pointerdown', x, r.top + 40, 3);
      pointer('pointerup', x, r.top + 40, 3);
      await sleep(260);
    };
    const zoomAtPlayhead = async (times = 2) => {
      for (let i = 0; i < times; i += 1) {
        const r = rect();
        const x = playhead() ?? r.left + r.width / 2;
        wave().dispatchEvent(
          new WheelEvent('wheel', {
            bubbles: true,
            cancelable: true,
            deltaY: -120,
            ctrlKey: true,
            clientX: x,
            clientY: r.top + 60,
          }),
        );
        await sleep(120);
      }
      await sleep(200);
    };

    await waitFor(() => video() && document.querySelectorAll('.row').length === 3);
    await sleep(500);

    // 先定位到 2s，再以播放头为锚放大到亚秒视窗：区间内才有足够的推进空间
    await seekTo(2.0);
    await zoomAtPlayhead(2);
    const zoomed = { slider: slider(), time: timeValue() };

    // 1) 单击刻度条不会自己滚：指针就在近缘热区里，按住不动
    const r1 = rect();
    const edgeX = r1.left + r1.width - 20;
    pointer('pointerdown', edgeX, r1.top + 6, 11);
    await sleep(80);
    const clickStart = timeValue();
    await sleep(450);
    const clickHeld = timeValue();
    pointer('pointerup', edgeX, r1.top + 6, 11);
    await sleep(200);

    // 2) 拖到右缘外：播放头钉住、视窗与时间同步推进
    await seekTo(2.0);
    await sleep(150);
    const r2 = rect();
    const startX = playhead();
    const y2 = r2.top + 40;
    pointer('pointerdown', startX, y2, 12);
    await sleep(80);
    pointer('pointermove', r2.left + r2.width + 90, y2, 12);
    await sleep(120);
    const rightT1 = timeValue();
    const sliderDuring = slider();
    await sleep(650);
    const rightT2 = timeValue();
    await sleep(400);
    const rightT3 = timeValue();
    const rightPh = playhead();
    const r2b = rect();
    pointer('pointerup', r2b.left + r2b.width + 90, y2, 12);
    await sleep(120);
    const rightAfterUp = timeValue();
    const videoTime = video().currentTime;
    await sleep(500);
    const rightSettled = timeValue();

    // 3) 往左对称
    await seekTo(2.0);
    await sleep(150);
    const r3 = rect();
    const y3 = r3.top + 40;
    pointer('pointerdown', playhead(), y3, 13);
    await sleep(80);
    pointer('pointermove', r3.left - 90, y3, 13);
    await sleep(120);
    const leftT1 = timeValue();
    await sleep(650);
    const leftT2 = timeValue();
    const leftPh = playhead();
    const r3b = rect();
    pointer('pointerup', r3b.left - 90, y3, 13);
    await sleep(200);

    document.querySelector('.row[data-i="1"]')?.click();
    await sleep(300);

    return JSON.stringify({
      zoomed,
      click: { start: clickStart, held: clickHeld },
      right: {
        t1: rightT1,
        t2: rightT2,
        t3: rightT3,
        phX: rightPh,
        rightEdge: r2b.left + r2b.width,
        sliderBefore: zoomed.slider,
        sliderDuring,
        afterUp: rightAfterUp,
        settled: rightSettled,
        videoTime,
      },
      left: { t1: leftT1, t2: leftT2, phX: leftPh, leftEdge: r3b.left },
    });
  })()
`;

function ensureMedia() {
  fs.mkdirSync(BASE, { recursive: true });
  if (fs.existsSync(MEDIA)) fs.rmSync(MEDIA);
  execFileSync('ffmpeg', [
    '-y',
    '-v',
    'error',
    '-f',
    'lavfi',
    '-i',
    'color=c=0x223344:s=640x360:d=8:r=24',
    '-f',
    'lavfi',
    '-i',
    'sine=frequency=440:duration=8',
    '-pix_fmt',
    'yuv420p',
    '-c:v',
    'libx264',
    '-preset',
    'ultrafast',
    '-c:a',
    'aac',
    '-shortest',
    MEDIA,
  ]);
}

function ensureSeed() {
  const seedPath = path.join(BASE, 'seed.json');
  fs.writeFileSync(seedPath, JSON.stringify({ mediaPath: MEDIA, cues: CUES }, null, 2), 'utf8');
  return seedPath;
}

function run() {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  fs.rmSync(SHOT, { force: true });
  const profile = path.join(BASE, 'profile');
  fs.rmSync(profile, { recursive: true, force: true });
  fs.mkdirSync(profile, { recursive: true });

  const extra = (process.env.KIKUSUB_SHOT_ELECTRON_ARGS || '').split(/\s+/).filter(Boolean);
  const env = {
    ...process.env,
    KIKUSUB_ALLOW_MULTIPLE: '1',
    KIKUSUB_WIN_SIZE: '1360x838',
    KIKUSUB_SHOT_DELAY: '3000',
    KIKUSUB_OUTPUT_DIR: OUT,
    KIKUSUB_DATA_DIR: path.join(BASE, 'data'),
    KIKUSUB_PREFERENCES_PATH: path.join(BASE, 'prefs.json'),
    KIKUSUB_DEV_SEED: ensureSeed(),
    KIKUSUB_DEV_EVAL: EVAL,
  };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.NODE_OPTIONS;

  let stdout = '';
  try {
    stdout = execFileSync(
      'npx',
      ['electron', '.', `--user-data-dir=${profile}`, `--screenshot=${SHOT}`, ...extra],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 180_000 },
    ).toString();
  } catch (error) {
    stdout = `${error.stdout ?? ''}`;
    console.error(String(error.stderr ?? '').slice(-1200));
  }
  const evalError = stdout.split('\n').filter((row) => row.startsWith('[eval:error]')).pop();
  if (evalError) throw new Error(evalError);
  const line = stdout.split('\n').filter((row) => row.startsWith('[eval]')).pop();
  if (!line) throw new Error('渲染进程没有回传结果');
  return JSON.parse(line.slice('[eval] '.length));
}

const failures = [];
function check(name, condition, detail) {
  if (condition) {
    console.log(`✅ ${name}`);
    return;
  }
  failures.push(name);
  console.error(`❌ ${name}${detail === undefined ? '' : `\n   ${JSON.stringify(detail)}`}`);
}

ensureMedia();
const result = run();

check('放大后视窗到亚秒级', Number(result.right.sliderBefore) > 55, result.zoomed);
check(
  '单击刻度条不自动滚（指针在近缘热区也不动）',
  Math.abs(result.click.held - result.click.start) < 0.02,
  result.click,
);
check(
  '右缘拖动会继续推进（时间单调递增）',
  result.right.t2 > result.right.t1 + 0.03 && result.right.t3 > result.right.t2 + 0.03,
  result.right,
);
check(
  '推进时播放头钉在右缘',
  Math.abs(result.right.phX - result.right.rightEdge) <= 8,
  { phX: result.right.phX, edge: result.right.rightEdge },
);
check(
  '推进时缩放不变（只平移不缩放）',
  result.right.sliderDuring === result.right.sliderBefore,
  { before: result.right.sliderBefore, during: result.right.sliderDuring },
);
check(
  '松手立刻停',
  Math.abs(result.right.settled - result.right.afterUp) < 0.05,
  { afterUp: result.right.afterUp, settled: result.right.settled },
);
check(
  '松手后画面落在播放头位置',
  Math.abs(result.right.videoTime - result.right.afterUp) < 0.35,
  { videoTime: result.right.videoTime, time: result.right.afterUp },
);
check(
  '往左同样推进（对称）',
  result.left.t2 < result.left.t1 - 0.03,
  result.left,
);
check(
  '左缘推进时播放头钉在左缘',
  Math.abs(result.left.phX - result.left.leftEdge) <= 8,
  { phX: result.left.phX, edge: result.left.leftEdge },
);

console.log(`\n截图：${SHOT}`);
if (failures.length) {
  console.error(`\n${failures.length} 条失败：${failures.join('、')}`);
  process.exitCode = 1;
} else {
  console.log('全部通过');
}
