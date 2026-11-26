#!/usr/bin/env node
/**
 * 色板取证截图（无窗口）。2026-11-26 第二阶段 Batch 3。
 *
 * 拍两组图：
 * 1. 设置 → 外观与朗读：六张色板缩略卡在浅色 / 深色下各一张；
 * 2. 代表色板（rose-pine / nord / cinema-amber）的核对台，明暗各一张。
 *
 * 全部走主进程自带的 `--screenshot`（透明窗口 + capturePage + app.exit），
 * 桌面上不出现任何窗口。截图落盘后由人 / 智能体用 read_image 自检。
 *
 * 用法：
 *   node tools/shots/capture_palettes.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/capture_palettes.mjs
 *   node tools/shots/capture_palettes.mjs --out /tmp/palettes --size 1440x900
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-palette-shots');
const DEFAULT_OUT = path.join(ROOT, 'docs', 'images', 'refactor-2026-11');

const args = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const OUT = path.resolve(arg('--out', DEFAULT_OUT));
const SIZE = arg('--size', '1440x900');
const MEDIA = path.join(BASE, 'media.mp4');

const CUES = [
  { start: 0.0, end: 1.4, text: 'よう、久しぶり。' },
  { start: 1.5, end: 2.9, text: 'お前は変わったな、本当に。' },
  { start: 3.0, end: 4.6, text: 'ここで待っていたんだよ、ずっと。' },
];

/** 在渲染进程里：切到外观页、选主题、选色板，必要时再切回核对台。 */
const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const waitFor = async (fn, ms = 12000) => {
      const t0 = Date.now();
      while (Date.now() - t0 < ms) {
        const value = fn();
        if (value) return value;
        await sleep(80);
      }
      return null;
    };
    const view = '__VIEW__';
    const theme = '__THEME__';
    const palette = '__PALETTE__';
    const paletteIds = ['cobalt', 'nord', 'rose-pine', 'everforest', 'catppuccin', 'cinema-amber'];

    // 走真实交互：设置页的按钮 -> store -> data-theme / data-palette。
    // 只改 DOM 属性不会让 Svelte 的 resolved 预览跟着翻面，截出来会自相矛盾。
    const openSettings = async () => {
      const items = document.querySelectorAll('.sb-item');
      items[9]?.click();
      await waitFor(() => document.querySelector('#set-tab-appearance'));
      document.querySelector('#set-tab-appearance')?.click();
      await waitFor(() => document.querySelector('.palette-grid'));
      await sleep(250);
    };

    const selectTheme = async () => {
      const cards = document.querySelectorAll('.appearance-card');
      cards[theme === 'dark' ? 2 : 1]?.click();
      await sleep(300);
    };

    const selectPalette = async () => {
      const index = paletteIds.indexOf(palette);
      document.querySelectorAll('.palette-card')[index]?.click();
      await sleep(300);
    };

    await openSettings();
    await selectTheme();
    await selectPalette();

    if (view === 'settings') {
      document.querySelector('.palette-grid')?.closest('.set-section')?.scrollIntoView({ block: 'center' });
      await sleep(500);
    } else {
      const items = document.querySelectorAll('.sb-item');
      items[2]?.click();
      await waitFor(() => document.querySelector('.row[data-i="0"]'));
      await sleep(900);
    }

    return JSON.stringify({
      view,
      theme: document.documentElement.dataset.theme,
      palette: document.documentElement.dataset.palette,
      rows: document.querySelectorAll('.row').length,
      appearanceOn: document.querySelector('.appearance-card.on .card-name')?.textContent?.trim(),
      paletteOn: document.querySelector('.palette-card.on .card-name')?.textContent?.trim(),
    });
  })()
`;

function ensureMedia() {
  fs.mkdirSync(BASE, { recursive: true });
  fs.mkdirSync(OUT, { recursive: true });
  if (!fs.existsSync(MEDIA)) {
    execFileSync(
      'ffmpeg',
      ['-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x223344:s=640x360:d=6',
        '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', MEDIA],
      { stdio: 'ignore' },
    );
  }
  const seed = path.join(BASE, 'seed.json');
  fs.writeFileSync(seed, JSON.stringify({ mediaPath: MEDIA, cues: CUES }, null, 1), 'utf8');
  return seed;
}

function shot(seed, { name, palette, theme, view }) {
  const profile = path.join(BASE, `profile-${name}`);
  const data = path.join(BASE, 'data');
  const out = path.join(OUT, `p2-palette-${name}.png`);
  fs.rmSync(profile, { recursive: true, force: true });
  const electronArgs = ['.', '--no-sandbox', `--user-data-dir=${profile}`, `--screenshot=${out}`];
  const extra = process.env.KIKUSUB_SHOT_ELECTRON_ARGS;
  if (extra) electronArgs.push(...extra.split(' '));
  const env = {
    ...process.env,
    KIKUSUB_WIN_SIZE: SIZE,
    KIKUSUB_DEV_SEED: seed,
    KIKUSUB_SHOT_DELAY: '5600',
    KIKUSUB_DEV_EVAL: EVAL.replace('__VIEW__', view)
      .replace('__THEME__', theme)
      .replace('__PALETTE__', palette),
    KIKUSUB_OUTPUT_DIR: path.join(BASE, 'outputs'),
    KIKUSUB_DATA_DIR: data,
    KIKUSUB_ALLOW_MULTIPLE: '1',
  };
  const stdout = execFileSync('npx', ['electron', ...electronArgs], {
    cwd: path.join(ROOT, 'desktop'),
    env,
    encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024,
  });
  const line = stdout.split('\n').reverse().find((l) => l.startsWith('[eval]'));
  if (!line) throw new Error(`${name}: 渲染进程没有回传结果`);
  const info = JSON.parse(line.replace('[eval] ', ''));
  if (!fs.existsSync(out)) throw new Error(`${name}: 没有生成截图 ${out}`);
  console.log(`✅ ${name}: ${info.theme}/${info.palette} · ${info.rows} 行 · ${path.basename(out)}`);
}

const seed = ensureMedia();

// 设置页：六张色板卡在一屏里，明暗各一张
shot(seed, { name: 'settings-light', palette: 'cobalt', theme: 'light', view: 'settings' });
shot(seed, { name: 'settings-dark', palette: 'cobalt', theme: 'dark', view: 'settings' });

// 代表色板的核对台：暖纸 / 冷夜 / 暗房琥珀，各明暗一张
for (const palette of ['rose-pine', 'nord', 'cinema-amber']) {
  for (const theme of ['light', 'dark']) {
    shot(seed, { name: `${palette}-${theme}`, palette, theme, view: 'review' });
  }
}

console.log(`\n截图目录：${OUT}`);
