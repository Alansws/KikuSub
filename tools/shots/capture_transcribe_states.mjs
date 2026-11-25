#!/usr/bin/env node
/**
 * 转写页底部执行栏三态取证（运行中带进度条 / 失败报错 / 待开始）。
 *
 * 为什么单独一支：`capture_matrix.sh` 的 `transcribe` 状态只能截到「待开始」，
 * 而 2026-11-26 真机反馈的重点正是**运行中缺少直观的水平进度条**与**失败态**。
 * 这两个态要真跑一次模型才出现（Anime Whisper 冷加载 20–40s + 整片解码），
 * 截图不该付这个代价，所以走 `KIKUSUB_DEV_SEED` 的 `job` 字段灌一份任务快照：
 * 页面走的是真实的 `TranscribeView` → `RunDock` 渲染路径，只是任务数据是假的。
 *
 * 每次都在独立临时数据根里跑，桌面不出现窗口；断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/capture_transcribe_states.mjs --out /tmp/transcribe-states
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/capture_transcribe_states.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-transcribe-states');
const MEDIA = path.join(BASE, 'states.mp4');

function arg(name, fallback) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : fallback;
}
const OUT = path.resolve(arg('--out', path.join(BASE, 'out')));
const SIZE = arg('--size', '1360x838');
const THEME = arg('--theme', 'light');

const CUES = [
  { start: 0.4, end: 1.6, text: 'よう、久しぶり。' },
  { start: 1.8, end: 3.0, text: 'お前は変わったな、本当に。' },
  { start: 3.2, end: 4.4, text: 'ここで待っていたんだよ、ずっと。' },
  { start: 4.6, end: 5.8, text: '雨の日だけ、君はここに来る。' },
  { start: 6.0, end: 7.2, text: 'だから今日も来てみたんだ。' },
];

const STATES = {
  running: {
    file: 'transcribe-running',
    job: {
      status: 'running',
      percent: 47,
      stage: '第 5/12 段 · 正在解码（Anime Whisper）',
      target: 'alt',
      engine: 'whisper',
    },
  },
  error: {
    file: 'transcribe-error',
    job: {
      status: 'error',
      percent: 96,
      stage: '',
      error: "'NoneType' object is not callable",
      target: 'alt',
      engine: 'whisper',
    },
  },
  idle: { file: 'transcribe-idle', job: null },
};

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const waitFor = async (fn, ms = 20000) => {
      const t0 = Date.now();
      while (Date.now() - t0 < ms) {
        const value = fn();
        if (value) return value;
        await sleep(70);
      }
      return null;
    };
    const text = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim();
    const [w, h] = [__W__, __H__];
    document.documentElement.style.setProperty('--win-w', w + 'px');
    if (__THEME__ !== 'light') {
      document.documentElement.dataset.theme = __THEME__;
      localStorage.setItem('kikusub.appearance', __THEME__);
    }

    try {
      await waitFor(() => document.querySelector('.sb-item'));
      // 种子里 openMedia 会把视图落到核对台；等它落盘再切页
      await waitFor(() => document.querySelector('.wave-wrap'), 30000);
      await sleep(700);

      const sidebar = (label) =>
        [...document.querySelectorAll('.sb-item')].find((el) =>
          (el.getAttribute('aria-label') || '').startsWith(label),
        );
      sidebar('转写')?.click();
      await waitFor(() => document.querySelector('.dock'));
      await sleep(900);

      const dock = document.querySelector('.dock');
      const meter = dock?.querySelector('.meter');
      const status = dock?.querySelector('.status');
      const btn = dock?.querySelector('button.btn.primary, button.btn.danger');
      const dockBox = dock?.getBoundingClientRect();
      const bandBox = document.querySelector('.dock-wrap')?.getBoundingClientRect();
      const paneBox = document.querySelector('.pane')?.getBoundingClientRect();
      const inner = document.querySelector('.dock-inner')?.getBoundingClientRect();
      const page = document.querySelector('.page-wrap')?.getBoundingClientRect();
      const out = {
        dockFound: Boolean(dock),
        plan: text(dock?.querySelector('.plan')),
        detail: text(dock?.querySelector('.detail')),
        statusText: text(status),
        statusTone: status?.className ?? '',
        meter: meter
          ? {
              width: Math.round(meter.getBoundingClientRect().width),
              fill: Math.round(meter.querySelector('i')?.getBoundingClientRect().width || 0),
              now: meter.getAttribute('aria-valuenow'),
            }
          : null,
        button: text(btn),
        dock: dockBox
          ? { left: Math.round(dockBox.left), right: Math.round(dockBox.right), top: Math.round(dockBox.top), bottom: Math.round(dockBox.bottom) }
          : null,
        band: bandBox
          ? { left: Math.round(bandBox.left), right: Math.round(bandBox.right), bottom: Math.round(bandBox.bottom) }
          : null,
        pane: paneBox ? { left: Math.round(paneBox.left), right: Math.round(paneBox.right), bottom: Math.round(paneBox.bottom) } : null,
        inner: inner ? { left: Math.round(inner.left), right: Math.round(inner.right) } : null,
        page: page ? { left: Math.round(page.left), right: Math.round(page.right) } : null,
        viewport: { w: window.innerWidth, h: window.innerHeight },
      };
      return JSON.stringify(out);
    } catch (err) {
      return JSON.stringify({ error: String((err && err.message) || err) });
    }
  })()
`;

function ensureMedia() {
  fs.mkdirSync(BASE, { recursive: true });
  if (!fs.existsSync(MEDIA)) {
    execFileSync('ffmpeg', [
      '-y', '-v', 'error',
      '-f', 'lavfi', '-i', 'color=c=0x223344:s=640x360:d=8',
      '-f', 'lavfi', '-i', 'sine=frequency=320:duration=8',
      '-shortest', '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast',
      '-c:a', 'aac', '-b:a', '96k', MEDIA,
    ], { stdio: 'ignore' });
  }
}

let failed = 0;
function check(label, ok, detail) {
  if (ok) console.log(`✅ ${label}`);
  else {
    failed += 1;
    console.log(`❌ ${label}`);
    if (detail !== undefined) console.log('   ', JSON.stringify(detail));
  }
}

function shoot(name, state) {
  const profile = path.join(BASE, `profile-${name}`);
  fs.rmSync(profile, { recursive: true, force: true });
  const seedPath = path.join(BASE, `seed-${name}.json`);
  fs.writeFileSync(
    seedPath,
    JSON.stringify({ mediaPath: MEDIA, cues: CUES, job: state.job ?? null }, null, 1),
    'utf8',
  );
  const [w, h] = SIZE.split('x').map(Number);
  const shot = path.join(OUT, `${state.file}-${SIZE}${THEME === 'light' ? '' : `-${THEME}`}.png`);
  const args = ['.', '--no-sandbox', `--user-data-dir=${profile}`, `--screenshot=${shot}`];
  const extra = process.env.KIKUSUB_SHOT_ELECTRON_ARGS;
  if (extra) args.push(...extra.split(' '));
  const stdout = execFileSync('npx', ['electron', ...args], {
    cwd: path.join(ROOT, 'desktop'),
    env: {
      ...process.env,
      KIKUSUB_WIN_SIZE: SIZE,
      KIKUSUB_DEV_SEED: seedPath,
      KIKUSUB_SHOT_DELAY: '5600',
      KIKUSUB_DEV_EVAL: EVAL.replace('__W__', String(w))
        .replace('__H__', String(h))
        .replace(/__THEME__/g, JSON.stringify(THEME)),
      KIKUSUB_OUTPUT_DIR: path.join(BASE, 'outputs'),
      KIKUSUB_DATA_DIR: path.join(BASE, `data-${name}`),
      KIKUSUB_ALLOW_MULTIPLE: '1',
    },
    encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024,
  });
  const line = stdout.split('\n').reverse().find((l) => l.startsWith('[eval]'));
  if (!line) throw new Error(`[${name}] 渲染进程没有回传结果`);
  return { shot, data: JSON.parse(line.replace('[eval] ', '')) };
}

ensureMedia();
fs.mkdirSync(OUT, { recursive: true });
console.log(`输出目录 ${OUT} · 视口 ${SIZE} · 外观 ${THEME}`);

// --- 运行中 ---------------------------------------------------------------
{
  const { shot, data } = shoot('running', STATES.running);
  console.log(`\n[running] ${shot}`);
  check('底栏存在', data.dockFound === true, data);
  check('进度条存在', Boolean(data.meter), data);
  check('进度条 aria-valuenow = 47', data.meter?.now === '47', data.meter);
  check(
    '进度填充约 47%（±2%）',
    Math.abs((data.meter?.fill ?? 0) / (data.meter?.width || 1) - 0.47) < 0.02,
    data.meter,
  );
  check('状态行是「进行中」语气', data.statusTone.includes('status'), data.statusTone);
  check('按钮换成「中途打断」', data.button === '中途打断', data.button);
  check('底栏贴住内容区底缘', data.dock && data.pane && Math.abs(data.dock.bottom - data.pane.bottom) <= 1, {
    dock: data.dock,
    pane: data.pane,
  });
  check(
    '底栏内容列与页面内容列同一左缘（±1px）',
    data.inner && data.page && Math.abs(data.inner.left - data.page.left) <= 1,
    { inner: data.inner, page: data.page },
  );
  check(
    '色带通栏（与内容区左右同宽，不是内缩的贴片）',
    data.band && data.pane && Math.abs(data.band.left - data.pane.left) <= 1 &&
      Math.abs(data.band.right - data.pane.right) <= 1,
    { band: data.band, pane: data.pane },
  );
}

// --- 失败 -----------------------------------------------------------------
{
  const { shot, data } = shoot('error', STATES.error);
  console.log(`\n[error] ${shot}`);
  check('失败态有 .status.err', data.statusTone.includes('err'), data.statusTone);
  check('失败原因可见（不是空行）', (data.statusText || '').includes('NoneType'), data.statusText);
  check('失败态没有进度条（进度不再假装在跑）', !data.meter, data.meter);
  check('失败后主按钮仍在（可直接重跑）', data.button === '生成第二版', data.button);
}

// --- 待开始 ---------------------------------------------------------------
{
  const { shot, data } = shoot('idle', STATES.idle);
  console.log(`\n[idle] ${shot}`);
  check('待开始：没有状态行', !data.statusText, data.statusText);
  check('待开始：没有进度条', !data.meter, data.meter);
  check('待开始：复述「谁 × 哪一段 → 写到哪」', /Anime Whisper|转写/.test(data.plan), data.plan);
  check('待开始：主按钮是「开始转写」', data.button === '开始转写', data.button);
}

if (failed) {
  console.error(`\n${failed} 项失败`);
  process.exit(1);
}
console.log('\n全部通过。');
