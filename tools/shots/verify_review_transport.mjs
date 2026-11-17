#!/usr/bin/env node
/**
 * 「核对台专业剪辑操作」无窗口回归。
 *
 * 覆盖：
 *   - 视频 fps 探测（24fps 片源，时间码 title 显示 24.000 fps）；
 *   - ← / → 逐帧（自动暂停、帧网格、片头片尾 clamp）；
 *   - ⌘← / ⌘→ 逐秒；
 *   - Q / E 入点 / 出点对齐播放头，服务端一步历史；
 *   - W 在播放头切割，⌘Z 一次还原；
 *   - ⇧Space 试听当前句，到句末自动停；
 *   - ← / → 不改变 URL / history；
 *   - 文本框聚焦时方向键让位；
 *   - 播放按钮获得焦点时方向键仍然生效（allowOnControls）；
 *   - N 磁吸 / ⇧Z 全片切换 / 数字键 1、2、3 倍速（Phase 2–3）。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现。断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_review_transport.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_review_transport.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-review-transport');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');
const SHOT = path.join(BASE, 'review-transport.png');

/** 3 条字幕；第 2 条 2.0–3.0 是主测试句，1.3–1.9 给入出点/试听用。 */
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
    const rows = () => [...document.querySelectorAll('.row')];
    const rowInfo = () =>
      rows().map((row) => ({
        i: row.dataset.i,
        start: row.querySelectorAll('.c-t')[0]?.textContent.trim() ?? '',
        end: row.querySelectorAll('.c-t')[1]?.textContent.trim() ?? '',
        text: row.querySelector('.c-text')?.textContent.trim() ?? '',
        sel: row.classList.contains('row-sel'),
      }));
    const timeText = () => document.querySelector('.tp-time')?.textContent.trim() ?? '';
    const timeValue = () => {
      const parts = timeText().split(':').map(Number);
      return parts.length === 3
        ? parts[0] * 3600 + parts[1] * 60 + parts[2]
        : 0;
    };
    const video = () => document.querySelector('video');
    const wave = () => document.querySelector('.wave-wrap');
    const toast = () => document.querySelector('.toast')?.textContent.trim() ?? '';
    const press = async (key, opts = {}) => {
      // 在「当前焦点元素」上派发：真实键盘事件 target 是焦点元素，直接发到 window
      // 会绕过输入框让位规则（测试会误判）。
      const target = document.activeElement ?? window;
      target.dispatchEvent(
        new KeyboardEvent('keydown', {
          key,
          code: opts.code ?? '',
          metaKey: Boolean(opts.meta),
          shiftKey: Boolean(opts.shift),
          bubbles: true,
          cancelable: true,
        }),
      );
      await sleep(opts.wait ?? 180);
    };
    const seekTo = async (t) => {
      const rect = wave().getBoundingClientRect();
      const x = rect.left + (t / 8) * rect.width;
      const y = rect.top + 40;
      for (const type of ['pointerdown', 'pointerup']) {
        wave().dispatchEvent(
          new PointerEvent(type, {
            bubbles: true,
            clientX: x,
            clientY: y,
            pointerId: 1,
            button: 0,
            pointerType: 'mouse',
          }),
        );
      }
      await sleep(260);
    };
    const undo = async () => {
      await press('z', { meta: true, code: 'KeyZ' });
      await sleep(320);
    };

    await waitFor(() => rows().length === 3 && document.querySelector('video'));
    await sleep(400);
    const initialTitle = document.querySelector('.tp-time')?.getAttribute('title') ?? '';
    const urlBefore = location.href;
    const historyBefore = history.length;

    // 1) 逐帧：2.0s → 2.0417s（24fps），自动暂停
    await seekTo(2.0);
    await press('ArrowRight', { code: 'ArrowRight' });
    const afterForward = { time: timeValue(), paused: video().paused, raw: timeText() };
    await press('ArrowLeft', { code: 'ArrowLeft' });
    const afterBack = { time: timeValue(), paused: video().paused, raw: timeText() };

    // 2) ⌘→ 逐秒：2.0 → 3.0
    await seekTo(2.0);
    await press('ArrowRight', { code: 'ArrowRight', meta: true });
    const afterSecond = { time: timeValue(), raw: timeText() };

    // 3) 高速连按：必须以上一次同步写回的 play.time 推进，不能读异步旧的 currentTime
    await seekTo(0);
    for (let i = 0; i < 10; i += 1) await press('ArrowRight', { code: 'ArrowRight', wait: 20 });
    await sleep(500);
    const afterBurst = { time: timeValue(), paused: video().paused };

    // 4) 片头后退 / 片尾前进 clamp
    await seekTo(0);
    await press('ArrowLeft', { code: 'ArrowLeft' });
    const atHead = timeValue();
    await seekTo(7.96);
    for (let i = 0; i < 6; i += 1) await press('ArrowRight', { code: 'ArrowRight', wait: 80 });
    const atTail = timeValue();

    // 4) 文本框让位：聚焦检查器文本框后按 →，播放头不动
    await seekTo(2.0);
    const inputBefore = timeValue();
    const textarea = document.querySelector('.inspector .cue-text');
    textarea?.focus();
    await press('ArrowRight', { code: 'ArrowRight' });
    const afterInput = { time: timeValue(), focused: document.activeElement === textarea };

    // 5) 播放按钮焦点仍可步进（allowOnControls）
    document.querySelector('.playbtn')?.focus();
    const beforeButton = timeValue();
    await press('ArrowRight', { code: 'ArrowRight' });
    const afterButton = { time: timeValue(), focused: document.activeElement?.className ?? '' };

    // 6) 切割：第 2 条 2.5s → 4 条；一次 ⌘Z 回到 3 条
    //    先选行再 seek：selectCue 会把播放头带到句首 +0.02，顺序反了会切在 2.02s。
    document.querySelector('.row[data-i="1"]')?.click();
    await sleep(120);
    await seekTo(2.5);
    await press('w', { code: 'KeyW' });
    await waitFor(() => rows().length === 4);
    const afterSplit = { rows: rowInfo(), toast: toast() };
    await undo();
    const afterSplitUndo = { rows: rowInfo(), toast: toast() };

    // 7) 入点 / 出点：第 1 条 0.5–1.5 → 0.2–1.2
    document.querySelector('.row[data-i="0"]')?.click();
    await sleep(120);
    await seekTo(0.2);
    await press('q', { code: 'KeyQ' });
    await seekTo(1.2);
    await press('e', { code: 'KeyE' });
    const afterTrim = rowInfo()[0];

    // 8) 试听：从 0.2s 播到 1.2s 自动停
    await press(' ', { code: 'Space', shift: true, wait: 120 });
    await sleep(1500);
    const afterAudition = { paused: video()?.paused, time: timeValue() };

    // 9) URL / history 没有被方向键带走
    const urlAfter = location.href;
    const historyAfter = history.length;

    // 截图停在有字幕、时间正常的核对台
    document.querySelector('.row[data-i="1"]')?.click();
    await sleep(300);

    return JSON.stringify({
      initialTitle,
      afterForward,
      afterBack,
      afterSecond,
      afterBurst,
      atHead,
      atTail,
      inputBefore,
      afterInput,
      beforeButton,
      afterButton,
      afterSplit,
      afterSplitUndo,
      afterTrim,
      afterAudition,
      urlBefore,
      urlAfter,
      historyBefore,
      historyAfter,
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

check('时间码 title 显示 24.000 fps', result.initialTitle.includes('24.000 fps'), result.initialTitle);
check(
  '→ 前进 1 帧 = 2.0417s',
  Math.abs(result.afterForward.time - 2.0417) < 0.003,
  result.afterForward,
);
check('逐帧后自动暂停', result.afterForward.paused === true, result.afterForward);
check(
  '← 后退 1 帧回到 2.000s',
  Math.abs(result.afterBack.time - 2.0) < 0.003,
  result.afterBack,
);
check('⌘→ 前进 1 秒 = 3.000s', Math.abs(result.afterSecond.time - 3.0) < 0.02, result.afterSecond);
check(
  '高速连按 10 次 → 前进 10 帧（不读异步旧 currentTime）',
  Math.abs(result.afterBurst.time - 10 / 24) < 0.02,
  result.afterBurst,
);
check('片头后退 clamp 到 0', result.atHead === 0, result.atHead);
check('片尾前进 clamp 到 duration', result.atTail >= 7.99, result.atTail);
check('文本框聚焦时方向键让位（播放头不动）', result.afterInput.time === result.inputBefore, {
  before: result.inputBefore,
  after: result.afterInput,
});
check('文本框仍保持焦点', result.afterInput.focused === true, result.afterInput);
check(
  '播放按钮焦点时 → 仍然步进',
  result.afterButton.time > result.beforeButton,
  result.afterButton,
);
check('W 切割后是 4 条', result.afterSplit.rows.length === 4, result.afterSplit.rows);
check('⌘Z 一次回到 3 条', result.afterSplitUndo.rows.length === 3, result.afterSplitUndo.rows);
check(
  'Q 入点对齐播放头',
  result.afterTrim.start === '00:00.200',
  result.afterTrim,
);
check(
  'E 出点对齐播放头',
  result.afterTrim.end === '00:01.200',
  result.afterTrim,
);
check('⇧Space 播到句末自动暂停', result.afterAudition.paused === true, result.afterAudition);
check(
  '试听停在出点附近',
  Math.abs(result.afterAudition.time - 1.2) < 0.08,
  result.afterAudition,
);
check('方向键没有改变 URL', result.urlAfter === result.urlBefore, {
  before: result.urlBefore,
  after: result.urlAfter,
});
check('方向键没有新增 history', result.historyAfter === result.historyBefore, {
  before: result.historyBefore,
  after: result.historyAfter,
});

console.log(`\n截图：${SHOT}`);
if (failures.length) {
  console.error(`\n${failures.length} 项失败：${failures.join(' / ')}`);
  process.exit(1);
}
console.log('全部通过。');
