#!/usr/bin/env node
/**
 * 「核对台工作现场持久化」无窗口回归（2026-11-20）。
 *
 * 覆盖三件事：
 *   1. 波形 peaks 进程内缓存：切去别的页面再回来，**不重新请求** /peaks、不闪白；
 *   2. 每部影片的现场快照（播放头 / 缩放 / 选区）切页面后按原样恢复；
 *   3. 快照真的落进 localStorage（按媒体路径为 key），重启后才有东西可恢复。
 *
 * 显式跳转优先（`focusRange` → `takeExplicitJump`）由
 * `desktop/test/reviewViewport.test.mjs` 的纯函数用例与
 * `tools/shots/verify_review_viewport.mjs` 的现场断言共同覆盖——UI 侧只验证
 * 「切页面回来恢复」这一条主动线，避免脚本去点别的页面的空状态。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现。断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_review_viewport.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_review_viewport.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-review-viewport');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'viewport.mp4');
const SHOT = path.join(BASE, 'review-viewport.png');
const DURATION = 120;

const CUES = [
  { start: 2.0, end: 5.0, text: '最初の台詞です' },
  { start: 28.0, end: 31.0, text: '真ん中の台詞' },
  { start: 60.0, end: 63.0, text: '後半の台詞' },
];

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const waitFor = async (fn, ms = 15000) => {
      const t0 = Date.now();
      while (Date.now() - t0 < ms) {
        const value = fn();
        if (value) return value;
        await sleep(80);
      }
      return null;
    };

    // 从现在起统计 /peaks 请求：判断「切页面回来是否又拉了一次波形」
    const peakRequests = [];
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      if (url.includes('/peaks')) peakRequests.push(url);
      return originalFetch(input, init);
    };

    const wave = () => document.querySelector('.wave-wrap');
    const sliderValue = () => document.querySelector('.zoom-slider')?.value ?? '';
    const zoomText = () => document.querySelector('.zoom-x')?.textContent.trim() ?? '';
    const timeText = () => document.querySelector('.tp-time')?.textContent.trim() ?? '';
    const timeValue = () => {
      const parts = timeText().split(':').map(Number);
      return parts.length === 3 ? parts[0] * 3600 + parts[1] * 60 + parts[2] : 0;
    };
    const hasSelection = () => Boolean(document.querySelector('.sel-bar'));
    const sidebar = (label) =>
      [...document.querySelectorAll('.sb-item')].find((el) =>
        (el.getAttribute('aria-label') || '').startsWith(label),
      );
    const clickSidebar = async (label) => {
      sidebar(label)?.click();
      await sleep(650);
    };
    const pointAt = (t) => {
      const rect = wave().getBoundingClientRect();
      return {
        x: rect.left + (t / ${DURATION}) * rect.width,
        y: rect.top + 40,
      };
    };
    const clickAt = async (t) => {
      const p = pointAt(t);
      for (const type of ['pointerdown', 'pointerup']) {
        wave().dispatchEvent(
          new PointerEvent(type, {
            bubbles: true,
            clientX: p.x,
            clientY: p.y,
            pointerId: 1,
            button: 0,
            pointerType: 'mouse',
          }),
        );
      }
      await sleep(280);
    };
    const dragSelect = async (from, to) => {
      const a = pointAt(from);
      const b = pointAt(to);
      const base = { bubbles: true, clientY: a.y, pointerId: 9, button: 0, pointerType: 'mouse' };
      wave().dispatchEvent(new PointerEvent('pointerdown', { ...base, clientX: a.x }));
      await sleep(90);
      wave().dispatchEvent(new PointerEvent('pointermove', { ...base, clientX: b.x }));
      await sleep(90);
      wave().dispatchEvent(new PointerEvent('pointerup', { ...base, clientX: b.x }));
      await sleep(320);
    };

    await waitFor(() => wave() && document.querySelector('video'));
    // 首次载入：等防抖 + 首次 /peaks 回来，画布稳定
    await waitFor(() => peakRequests.length >= 1);
    await sleep(600);
    const requestsAfterLoad = peakRequests.length;
    const fullZoom = sliderValue();

    // 1) 放大两级 + 放到 30s 附近 + 框选一段：这就是「工作现场」
    document.querySelector('.zbtn[aria-label="放大波形"]')?.click();
    await sleep(160);
    document.querySelector('.zbtn[aria-label="放大波形"]')?.click();
    await sleep(500);
    const zoomBeforeSwitch = sliderValue();
    const zoomTextBefore = zoomText();
    await clickAt(30);
    await dragSelect(22, 36);
    const timeBeforeSwitch = timeValue();
    const selectionBefore = hasSelection();
    await sleep(1900); // 等一次 1.5s 的定时落盘

    const storedKeys = (() => {
      try {
        const raw = JSON.parse(localStorage.getItem('kikusub.reviewViewports') || 'null');
        return Object.keys(raw?.entries ?? {});
      } catch {
        return [];
      }
    })();
    const mediaPath = localStorage.getItem('kikusub.lastMedia') || '';
    const stored = (() => {
      try {
        const raw = JSON.parse(localStorage.getItem('kikusub.reviewViewports') || 'null');
        return raw?.entries?.[mediaPath] ?? null;
      } catch {
        return null;
      }
    })();

    // 2) 切去双引擎复核再切回核对台（视图会被整体重建）
    await clickSidebar('双引擎复核');
    const leftReview = !wave();
    const requestsBeforeReturn = peakRequests.length;
    await clickSidebar('核对台');
    await waitFor(() => wave() && document.querySelector('video'));
    await sleep(1400);

    const zoomAfterReturn = sliderValue();
    const zoomTextAfter = zoomText();
    const timeAfterReturn = timeValue();
    const selectionAfter = hasSelection();
    const requestsAfterReturn = peakRequests.length - requestsBeforeReturn;

    await sleep(200);
    return JSON.stringify({
      mediaPath,
      storedKeys,
      stored,
      fullZoom,
      zoomBeforeSwitch,
      zoomTextBefore,
      timeBeforeSwitch,
      selectionBefore,
      leftReview,
      zoomAfterReturn,
      zoomTextAfter,
      timeAfterReturn,
      selectionAfter,
      requestsAfterLoad,
      requestsBeforeReturn,
      requestsAfterReturn,
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
    `color=c=0x223344:s=640x360:d=${DURATION}:r=24`,
    '-f',
    'lavfi',
    '-i',
    `sine=frequency=330:duration=${DURATION}`,
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
    KIKUSUB_SHOT_DELAY: '3200',
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
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 240_000 },
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

// 1) 现场真的按路径落进了 localStorage
check('快照按媒体路径为 key 写入 localStorage', result.storedKeys.includes(result.mediaPath), {
  keys: result.storedKeys,
  mediaPath: result.mediaPath,
});
check(
  '快照记录了播放头 / 缩放 / 选区',
  result.stored &&
    Math.abs(Number(result.stored.playhead) - result.timeBeforeSwitch) < 0.6 &&
    Number(result.stored.span) > 0 &&
    result.stored.selection !== null,
  result.stored,
);

// 2) 切页面回来恢复现场
check('切去别的页面后核对台真的卸载了', result.leftReview === true);
check(
  '切回来恢复缩放',
  Math.abs(Number(result.zoomAfterReturn) - Number(result.zoomBeforeSwitch)) < 0.6,
  { before: result.zoomBeforeSwitch, after: result.zoomAfterReturn, text: result.zoomTextAfter },
);
check(
  '切回来恢复播放头',
  Math.abs(result.timeAfterReturn - result.timeBeforeSwitch) < 0.6,
  { before: result.timeBeforeSwitch, after: result.timeAfterReturn },
);
check('切回来恢复时间选区', result.selectionAfter === result.selectionBefore && result.selectionAfter, {
  before: result.selectionBefore,
  after: result.selectionAfter,
});

// 3) 波形包络走内存缓存：回来时没有重新请求
check('切回核对台没有重新请求 /peaks', result.requestsAfterReturn === 0, {
  before: result.requestsBeforeReturn,
  after: result.requestsAfterReturn,
});

if (failures.length) {
  console.error(`\n${failures.length} 项断言失败：\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`\n截图：${SHOT}`);
