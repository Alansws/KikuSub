#!/usr/bin/env node
/**
 * 核对台浮层（右键菜单 / 新建音色）无窗口回归。
 *
 * Step 4.1 把这两个浮层从 `ReviewView.svelte` 搬到
 * `components/review/ReviewContextMenu.svelte` 与 `ReviewVoiceDialog.svelte`，
 * 并共用 `lib/portal.ts`。这个脚本守住三件事：
 *
 *   1. 右键字幕行能打开菜单，菜单项齐全（切割 / 新建音色 / 试听 / 添加）；
 *   2. 「以此句音频新建音色」能打开浮层，名字与参考文本预填、焦点在输入框；
 *   3. Esc / 点遮罩能关掉浮层，不把状态留在页面上。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现。断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_review_overlays.mjs --mode menu
 *   node tools/shots/verify_review_overlays.mjs --mode dialog
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node ...
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const MODE = process.argv.includes('--mode')
  ? process.argv[process.argv.indexOf('--mode') + 1]
  : 'dialog';
if (MODE !== 'menu' && MODE !== 'dialog') {
  console.error('--mode 只支持 menu / dialog');
  process.exit(2);
}

const BASE = path.join(os.tmpdir(), 'kikusub-review-overlays');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');
const SHOT = path.join(BASE, `overlays-${MODE}.png`);

const CUES = [
  { start: 0.5, end: 1.5, text: '深呼吸して' },
  { start: 2.0, end: 3.0, text: '吸って' },
  { start: 4.0, end: 5.0, text: 'もう一回' },
];

const EVAL = String.raw`
  (async () => {
    const MODE = '__MODE__';
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
    const openMenu = async () => {
      // 在波形主体 1.0s 处右键：落在第 1 条（0.5–1.5）内部，菜单才会给出
      // 「切割字幕」（canSplitAt 要求离两端都超过 MIN_CUE_LENGTH）。
      const wave = document.querySelector('.wave-wrap');
      const r = wave.getBoundingClientRect();
      wave.dispatchEvent(
        new MouseEvent('contextmenu', {
          bubbles: true,
          cancelable: true,
          clientX: r.left + (1.0 / 6) * r.width,
          clientY: r.top + 40,
        }),
      );
      await sleep(220);
      return document.querySelector('.ctx-menu');
    };

    await waitFor(() => document.querySelector('.row[data-i="0"]'));
    await sleep(500);

    const out = {};
    const menu = await openMenu();
    out.menuOpen = Boolean(menu);
    out.items = [...document.querySelectorAll('.ctx-menu .ctx-label')].map((n) =>
      n.textContent.trim(),
    );
    out.hasSplit = out.items.includes('切割字幕');
    // 2026-11-26 起动作标签不带尾部省略号（口径见 tests/test_ui_label_hygiene.py）���
    out.hasVoice = out.items.includes('以此句音频新建音色');
    out.hasAudition = out.items.includes('试听这句原声');
    out.hasAdd = out.items.includes('添加字幕');

    const voiceBtn = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((b) =>
      b.textContent.includes('新建音色'),
    );
    voiceBtn?.click();
    await sleep(320);
    out.dialogOpen = Boolean(document.querySelector('.vd'));
    out.name = document.querySelector('.vd input')?.value ?? '';
    out.refText = document.querySelector('.vd textarea')?.value ?? '';
    out.focusInName = document.activeElement === document.querySelector('.vd input');

    // Esc 关浮层
    document.activeElement?.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
    );
    await sleep(220);
    out.dialogClosedByEsc = !document.querySelector('.vd');

    // 点遮罩关菜单
    await openMenu();
    document.querySelector('.ctx-backdrop')?.click();
    await sleep(180);
    out.menuClosedByBackdrop = !document.querySelector('.ctx-menu');

    if (MODE === 'menu') {
      await openMenu();
      out.leftOpenForShot = Boolean(document.querySelector('.ctx-menu'));
    } else {
      await openMenu();
      const btn = [...document.querySelectorAll('.ctx-menu .ctx-item')].find((b) =>
        b.textContent.includes('新建音色'),
      );
      btn?.click();
      await sleep(300);
      out.leftOpenForShot = Boolean(document.querySelector('.vd'));
    }

    return JSON.stringify(out);
  })()
`;

function ensureMedia() {
  fs.mkdirSync(BASE, { recursive: true });
  fs.mkdirSync(OUT, { recursive: true });
  if (!fs.existsSync(MEDIA)) {
    execFileSync(
      'ffmpeg',
      [
        '-y',
        '-v',
        'error',
        '-f',
        'lavfi',
        '-i',
        'color=c=0x223344:s=640x360:d=6',
        '-pix_fmt',
        'yuv420p',
        '-c:v',
        'libx264',
        '-preset',
        'ultrafast',
        MEDIA,
      ],
      { stdio: 'ignore' },
    );
  }
  const seed = path.join(BASE, 'seed.json');
  fs.writeFileSync(seed, JSON.stringify({ mediaPath: MEDIA, cues: CUES }, null, 1), 'utf8');
  return seed;
}

function run(seed) {
  const profile = path.join(BASE, `profile-${MODE}`);
  fs.rmSync(profile, { recursive: true, force: true });
  const args = [
    '.',
    '--no-sandbox',
    `--user-data-dir=${profile}`,
    `--screenshot=${SHOT}`,
  ];
  const env = {
    ...process.env,
    KIKUSUB_WIN_SIZE: '1440x900',
    KIKUSUB_DEV_SEED: seed,
    KIKUSUB_SHOT_DELAY: '5200',
    KIKUSUB_DEV_EVAL: EVAL.replace('__MODE__', MODE),
    KIKUSUB_OUTPUT_DIR: path.join(BASE, 'outputs'),
    KIKUSUB_DATA_DIR: path.join(BASE, 'data'),
    KIKUSUB_ALLOW_MULTIPLE: '1',
  };
  const extra = process.env.KIKUSUB_SHOT_ELECTRON_ARGS;
  if (extra) args.push(...extra.split(' '));
  const stdout = execFileSync('npx', ['electron', ...args], {
    cwd: path.join(ROOT, 'desktop'),
    env,
    encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024,
  });
  const line = stdout
    .split('\n')
    .reverse()
    .find((l) => l.startsWith('[eval]'));
  if (!line) throw new Error('渲染进程没有回传结果');
  return JSON.parse(line.replace('[eval] ', ''));
}

let failed = 0;
function check(label, ok, detail) {
  if (ok) {
    console.log(`✅ ${label}`);
  } else {
    failed += 1;
    console.log(`❌ ${label}`);
    if (detail !== undefined) console.log('   ', JSON.stringify(detail));
  }
}

const seed = ensureMedia();
const r = run(seed);

check('右键字幕行打开菜单', r.menuOpen === true, r);
check('菜单含「切割字幕」', r.hasSplit === true, r.items);
check('菜单含「以此句音频新建音色」（不带尾省略号）', r.hasVoice === true, r.items);
check('菜单含「试听这句原声」', r.hasAudition === true, r.items);
check('菜单含「添加字幕」', r.hasAdd === true, r.items);
check('「新建音色」打开浮层', r.dialogOpen === true, r);
check('音色名预填「角色 N」', /^角色\s*\d+$/.test(r.name), r.name);
check('参考文本预填当前句原文', r.refText === '深呼吸して', r.refText);
check('浮层打开后焦点在名字输入框', r.focusInName === true, r);
check('Esc 关闭浮层', r.dialogClosedByEsc === true, r);
check('点遮罩关闭菜单', r.menuClosedByBackdrop === true, r);
check('截图前浮层仍打开（用于目检）', r.leftOpenForShot === true, r);

console.log(`截图：${SHOT}`);
if (failed) {
  console.error(`\n${failed} 项失败`);
  process.exit(1);
}
console.log('\n全部通过。');
