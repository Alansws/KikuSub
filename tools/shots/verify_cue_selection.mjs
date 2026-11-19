#!/usr/bin/env node
/**
 * 核对台「点行 / 点底部字幕块 = 选中该句时间」回归。
 *
 * 用户报障：点表格里的字幕只跳播放头，不产生时间选区，想「转写选区 / 同步到
 * 转写页」还得手动再框一次；底部字幕块的纯单击也一样。这个脚本在真实界面里断言：
 *
 *   1. 点第 3 行 → 选区工具条出现且范围 = 这一句的精确 start/end；
 *   2. 点第 5 行 → 选区跟着换；
 *   3. Esc 只清时间选区，当前行仍是第 5 行；
 *   4. 点底部字幕块的纯单击（未拖拽）也写入选区。
 *
 * 走 `--screenshot` 静默路径，不弹窗口；断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_cue_selection.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_cue_selection.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-cue-selection');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');

const CUES = [
  { start: 0.4, end: 1.6, text: 'おはようございます' },
  { start: 1.8, end: 3.0, text: '今日はいい天気ですね' },
  { start: 3.2, end: 4.8, text: 'もっとぐちゅぐちゅになっちゃう' },
  { start: 5.0, end: 6.4, text: 'ちょっと待ってください' },
  { start: 6.6, end: 8.0, text: 'もう一回お願いします' },
  { start: 8.2, end: 9.6, text: 'ありがとうございました' },
];

const EXPECT = {
  third: '00:03.200 → 00:04.800',
  fifth: '00:06.600 → 00:08.000',
};

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const waitFor = async (fn, timeout = 8000) => {
      const start = Date.now();
      while (Date.now() - start < timeout) {
        const value = fn();
        if (value) return value;
        await sleep(80);
      }
      return null;
    };
    const text = (el) => (el ? el.textContent.trim() : null);
    const bar = () => document.querySelector('.sel-bar');
    const range = () => text(document.querySelector('.sel-range'));
    const selected = () => {
      const row = document.querySelector('.row-sel');
      return row ? Number(row.getAttribute('data-i')) : -1;
    };

    await waitFor(() => document.querySelector('.row[data-i="2"]'));
    const out = {};

    document.querySelector('.row[data-i="2"]').click();
    await sleep(220);
    out.third = { bar: Boolean(bar()), range: range(), selected: selected() };

    document.querySelector('.row[data-i="4"]').click();
    await sleep(220);
    out.fifth = { bar: Boolean(bar()), range: range(), selected: selected() };

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    await sleep(200);
    out.escape = { bar: Boolean(bar()), selected: selected() };

    // 底部字幕轨道：在 full-view 下按时间换算 x，点块体中部（不拖）。
    const cue = { start: 3.2, end: 4.8 };
    const wrap = document.querySelector('.wave-wrap');
    const rect = wrap.getBoundingClientRect();
    const duration = 10;
    const x = rect.left + (cue.start + (cue.end - cue.start) / 2) / duration * rect.width;
    const y = rect.top + rect.height - 8;
    const opts = { bubbles: true, cancelable: true, button: 0, clientX: x, clientY: y, pointerId: 1, pointerType: 'mouse' };
    wrap.dispatchEvent(new PointerEvent('pointerdown', opts));
    await sleep(60);
    wrap.dispatchEvent(new PointerEvent('pointerup', opts));
    await sleep(220);
    out.block = { bar: Boolean(bar()), range: range(), selected: selected() };

    return JSON.stringify(out);
  })()
`;

function ensureMedia() {
  if (fs.existsSync(MEDIA)) return;
  fs.mkdirSync(BASE, { recursive: true });
  execFileSync('ffmpeg', [
    '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x334455:s=640x360:d=10',
    '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', MEDIA,
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
  const profile = path.join(BASE, 'profile');
  fs.rmSync(profile, { recursive: true, force: true });
  fs.mkdirSync(profile, { recursive: true });

  const extra = (process.env.KIKUSUB_SHOT_ELECTRON_ARGS || '').split(/\s+/).filter(Boolean);
  const env = {
    ...process.env,
    KIKUSUB_ALLOW_MULTIPLE: '1',
    KIKUSUB_WIN_SIZE: '1360x838',
    KIKUSUB_SHOT_DELAY: '2500',
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
      [
        'electron',
        '.',
        `--user-data-dir=${profile}`,
        `--screenshot=${path.join(BASE, 'cue-selection.png')}`,
        ...extra,
      ],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 180_000 },
    ).toString();
  } catch (error) {
    stdout = `${error.stdout ?? ''}`;
    console.error(String(error.stderr ?? '').slice(-800));
  }
  const line = stdout.split('\n').filter((row) => row.startsWith('[eval]')).pop();
  if (!line) throw new Error('渲染进程没有回传结果');
  return JSON.parse(line.slice('[eval] '.length));
}

const failures = [];
function check(name, condition, detail) {
  if (condition) console.log(`  ✓ ${name}`);
  else {
    failures.push(`${name}${detail ? ` → ${detail}` : ''}`);
    console.error(`  ✗ ${name}${detail ? ` → ${detail}` : ''}`);
  }
}

function main() {
  ensureMedia();
  const data = run();

  check('点第 3 行出现选区工具条', data.third?.bar === true);
  check('第 3 行选区是精确 start→end', data.third?.range === EXPECT.third, data.third?.range);
  check('第 3 行仍是当前行', data.third?.selected === 2, String(data.third?.selected));

  check('点第 5 行选区跟着换', data.fifth?.range === EXPECT.fifth, data.fifth?.range);
  check('第 5 行仍是当前行', data.fifth?.selected === 4, String(data.fifth?.selected));

  check('Esc 清掉时间选区', data.escape?.bar === false);
  check('Esc 不丢当前行', data.escape?.selected === 4, String(data.escape?.selected));

  check('纯单击底部字幕块也写入选区', data.block?.bar === true);
  check('底部块选区是精确 start→end', data.block?.range === EXPECT.third, data.block?.range);

  const shot = path.join(BASE, 'cue-selection.png');
  if (fs.existsSync(shot)) console.log(`\n截图：${shot}`);
  else console.error('\n截图缺失（--screenshot 没跑通？）');

  if (failures.length) {
    console.error(`\n${failures.length} 项失败`);
    process.exit(1);
  }
  console.log('\n全部通过');
}

main();
