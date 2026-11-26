#!/usr/bin/env node
/**
 * AI 工作台工具栏控件可见性回归（第二阶段 Batch 2，2026-11-26）。
 *
 * 用户报障的原话是「甚至下拉框只看得见一个三角」。根因不是某一个组件忘了
 * 描边，而是令牌层：亮色 `--well-line` 是 `transparent`，而 `--well #F2F2F7`
 * 与工具栏的 `--paper #F5F5F7` 只差两个色阶 —— 下拉框、数字框在灰底上等于隐身。
 * 同一轮还把页内命令栏从 `--paper` 挪回了 `--canvas`（灰底白框按钮的根源）。
 *
 * 这个脚本不看截图、不靠肉眼，直接在渲染进程里读**计算样式**：
 *
 *   1. `--well-line` 非透明，且在亮暗两套都必须有足够 alpha；
 *   2. `.aiw-head` / `.aiw-cmd-row` 与页面台面同色（页内工具栏不再是铬件灰）；
 *   3. `.aiw-head` 内每个 `<select>` / `<input>` / `<textarea>` 都有可见边界：
 *      1px 以上、alpha ≥ 0.10 的边线，或与「实际台面」有 ≥ 0.025 的明度差；
 *   4. 工具栏里的 `.btn` 同样有可见边线（白键落在白台面上也必须看得出形状）；
 *   5. 下拉框与按钮同高（28px）—— 一行控件的顶边/底边对齐；
 *   6. AI 三页的动作按钮不再带尾部省略号。
 *
 * 走主进程自带的 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现；不点任何会开原生对话框的按钮（§0.5 无窗口铁律）。
 *
 * 用法：
 *   node tools/shots/verify_ai_toolbar_controls.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_ai_toolbar_controls.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-ai-controls-verify');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');

const CUES = [
  { start: 0.0, end: 1.4, text: 'よう、久しぶり。' },
  { start: 1.5, end: 2.9, text: 'お前は変わったな、本当に。' },
  { start: 3.0, end: 4.6, text: 'ここで待っていたんだよ、ずっと。' },
  { start: 4.7, end: 6.2, text: '雨の日だけ、君はここに来る。' },
  { start: 6.3, end: 7.8, text: 'だから今日も来てみたんだ。' },
  { start: 7.9, end: 9.4, text: '話したいことがある。' },
  { start: 9.5, end: 11.0, text: 'それは……とても大事な話。' },
  { start: 11.1, end: 12.6, text: 'でも、うまく言えない。' },
  { start: 12.7, end: 14.2, text: '少しだけ、時間をくれないか。' },
  { start: 14.3, end: 15.8, text: 'ああ、構わないよ。' },
  { start: 15.9, end: 17.4, text: 'じゃあ、一緒に歩こう。' },
  { start: 17.5, end: 19.0, text: '……ありがとう。' },
];

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const until = async (fn, ms = 12000) => {
      const end = Date.now() + ms;
      while (Date.now() < end) {
        const hit = fn();
        if (hit) return hit;
        await sleep(80);
      }
      return null;
    };
    const THEME = '__THEME__';
    document.documentElement.dataset.theme = THEME;
    try { localStorage.setItem('kikusub.appearance', THEME); } catch {}
    await sleep(400);

    const parse = (value) => {
      const m = String(value || '').match(/rgba?\(([^)]+)\)/i);
      if (!m) return { r: 0, g: 0, b: 0, a: 0 };
      const parts = m[1].split(',').map((v) => Number.parseFloat(v.trim()));
      return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
    };
    const lum = ({ r, g, b }) => {
      const f = [r, g, b].map((v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
      });
      return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
    };
    const hexToRgb = (hex) => {
      const h = String(hex || '').trim().replace('#', '');
      if (h.length !== 6) return { r: 0, g: 0, b: 0, a: 1 };
      return {
        r: Number.parseInt(h.slice(0, 2), 16),
        g: Number.parseInt(h.slice(2, 4), 16),
        b: Number.parseInt(h.slice(4, 6), 16),
        a: 1,
      };
    };
    // 控件真正压在什么颜色上：往上找第一层不透明的背景。
    const surfaceOf = (el) => {
      let node = el;
      while (node && node !== document.documentElement) {
        const color = parse(getComputedStyle(node).backgroundColor);
        if (color.a > 0.02) return color;
        node = node.parentElement;
      }
      return parse(getComputedStyle(document.body).backgroundColor);
    };
    const describe = (el) => {
      const cs = getComputedStyle(el);
      const bg = parse(cs.backgroundColor);
      const surface = surfaceOf(el);
      const border = parse(cs.borderTopColor);
      const borderW = Number.parseFloat(cs.borderTopWidth) || 0;
      const bgLum = bg.a > 0.02 ? lum(bg) : lum(surface);
      const delta = Math.abs(bgLum - lum(surface));
      return {
        tag: el.tagName.toLowerCase(),
        cls: typeof el.className === 'string' ? el.className : '',
        value: el.tagName === 'SELECT' ? el.value : el.value,
        h: Math.round(el.getBoundingClientRect().height * 10) / 10,
        borderW,
        borderAlpha: border.a,
        bgAlpha: bg.a,
        bgLum: Math.round(bgLum * 1000) / 1000,
        surfaceLum: Math.round(lum(surface) * 1000) / 1000,
        delta: Math.round(delta * 1000) / 1000,
        visible: (borderW >= 1 && border.a >= 0.1) || delta >= 0.025,
        why: borderW >= 1 && border.a >= 0.1 ? 'border' : delta >= 0.025 ? 'background' : 'none',
      };
    };

    const nav = document.querySelectorAll('.sb-item');
    nav[4]?.click(); // 03 原文 → 锁轴润色
    if (!(await until(() => document.querySelector('.aiw-head') && document.querySelector('.aiw-cmd-row')))) {
      return JSON.stringify({ error: '锁轴润色页没有落地', title: document.querySelector('.tb-title')?.textContent });
    }
    // 模板下拉在提示词库读回来之后才渲染；等两个 select 都到位再量，
    // 否则偶发只量到「处理范围」一个，28px 断言会假红。
    await until(() => document.querySelectorAll('.aiw-head select').length >= 2, 10000);
    await sleep(500);

    const css = getComputedStyle(document.documentElement);
    const token = (name) => css.getPropertyValue(name).trim();
    const wellLine = parse(css.getPropertyValue('--well-line'));
    const canvas = hexToRgb(css.getPropertyValue('--canvas'));

    const head = document.querySelector('.aiw-head');
    const page = document.querySelector('.aiw-page');
    const cmd = document.querySelector('.aiw-cmd-row');
    const controls = [...head.querySelectorAll('select, input, textarea')].map(describe);
    // ghost 是「已经和可见父级成组」的低调动作，允许无框；这里检查的是
    // 默认的纸白键（secondary），它必须在白台面上仍有形状。
    const buttons = [...cmd.querySelectorAll('.btn:not(.ghost):not(.primary)')].map(describe);
    const selects = [...head.querySelectorAll('select')].map((el) =>
      Math.round(el.getBoundingClientRect().height * 10) / 10,
    );
    const rowButtons = [...cmd.querySelectorAll('.btn:not(.ghost)')].map((el) =>
      Math.round(el.getBoundingClientRect().height * 10) / 10,
    );
    const labels = [...document.querySelectorAll('.aiw-cmd-row button, .aiw-title-row button')]
      .map((el) => el.textContent.replace(/\s+/g, ' ').trim())
      .filter(Boolean);

    return JSON.stringify({
      theme: THEME,
      viewport: { w: innerWidth, h: innerHeight },
      tokens: {
        wellLine: { a: wellLine.a, raw: token('--well-line') },
        canvas,
        paper: hexToRgb(token('--paper')),
        cueFont: token('--font-cue').replace(/\s+/g, ' '),
      },
      pageBg: parse(getComputedStyle(page).backgroundColor),
      headBg: parse(getComputedStyle(head).backgroundColor),
      cmdBg: parse(getComputedStyle(cmd).backgroundColor),
      cmdBorderTop: Number.parseFloat(getComputedStyle(cmd).borderTopWidth) || 0,
      headBorderBottom: Number.parseFloat(getComputedStyle(head).borderBottomWidth) || 0,
      controls,
      buttons,
      selects,
      rowButtons,
      labels,
      ellipsisButtons: labels.filter((label) => label.includes('…')),
    });
  })()
`;

function ensureMedia() {
  fs.mkdirSync(BASE, { recursive: true });
  if (fs.existsSync(MEDIA)) return;
  execFileSync('ffmpeg', [
    '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x223344:s=640x360:d=5',
    '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', MEDIA,
  ]);
}

function ensureSeed() {
  const seedPath = path.join(BASE, 'seed.json');
  fs.writeFileSync(seedPath, JSON.stringify({ mediaPath: MEDIA, cues: CUES }, null, 2), 'utf8');
  return seedPath;
}

function run(theme) {
  const profile = path.join(BASE, `profile-${theme}`);
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
    KIKUSUB_DEV_EVAL: EVAL.replace('__THEME__', theme),
  };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.NODE_OPTIONS;

  let stdout = '';
  try {
    stdout = execFileSync(
      'npx',
      ['electron', '.', `--user-data-dir=${profile}`, `--screenshot=${path.join(BASE, `controls-${theme}.png`)}`, ...extra],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 180_000 },
    ).toString();
  } catch (error) {
    stdout = `${error.stdout ?? ''}`;
    console.error(String(error.stderr ?? '').slice(-800));
  }
  if (process.env.KIKUSUB_VERIFY_DEBUG) console.error(stdout.slice(-4000));
  const line = stdout.split('\n').filter((row) => row.startsWith('[eval]')).pop();
  if (!line) throw new Error(`渲染进程没有回传结果（${theme}）`);
  return JSON.parse(line.slice('[eval] '.length));
}

const failures = [];
let passed = 0;
function check(name, condition, detail) {
  if (condition) {
    passed += 1;
    console.log(`  ✓ ${name}`);
  } else {
    const tail = detail ? ` → ${typeof detail === 'string' ? detail : JSON.stringify(detail)}` : '';
    failures.push(`${name}${tail}`);
    console.error(`  ✗ ${name}${tail}`);
  }
}

function main() {
  ensureMedia();
  fs.mkdirSync(OUT, { recursive: true });
  const results = ['light', 'dark'].map((theme) => run(theme));

  for (const data of results) {
    const theme = data.theme;
    if (data.error) throw new Error(`${data.error}（${theme}）`);
    const label = theme === 'light' ? '亮色' : '暗色';
    const tone = (color) => `${color.r},${color.g},${color.b}`;

    // ---- 1. 令牌本身：--well-line 不许隐身
    check(
      `${label} · --well-line 不是 transparent（alpha ${data.tokens.wellLine.a}）`,
      data.tokens.wellLine.a >= 0.1,
      data.tokens.wellLine,
    );

    // ---- 1b. 字幕字体：日文字体必须排在 PingFang 前面
    check(
      `${label} · --font-cue 以 Hiragino Sans 起头`,
      /^["']?Hiragino Sans["']?/i.test(data.tokens.cueFont),
      data.tokens.cueFont,
    );

    // ---- 2. 页内命令栏回到台面，不再是 --paper 灰带
    check(
      `${label} · .aiw-page 与 .aiw-head 同台面色`,
      tone(data.pageBg) === tone(data.headBg) && tone(data.headBg) === tone(data.tokens.canvas),
      { page: data.pageBg, head: data.headBg, canvas: data.tokens.canvas },
    );
    check(
      `${label} · .aiw-cmd-row 背景透明（不另铺灰条）`,
      data.cmdBg.a <= 0.02,
      data.cmdBg,
    );
    check(
      `${label} · 命令栏用 1px 发丝线分隔`,
      data.cmdBorderTop >= 1 && data.headBorderBottom >= 1,
      { cmd: data.cmdBorderTop, head: data.headBorderBottom },
    );

    // ---- 3. 每个表单控件都有自己的可见边界
    const hidden = data.controls.filter((row) => !row.visible);
    check(
      `${label} · ${data.controls.length} 个下拉/输入控件全部有可见边界`,
      data.controls.length >= 5 && hidden.length === 0,
      { hidden, controls: data.controls },
    );
    const transparentBorder = data.controls.filter(
      (row) => row.borderW < 1 || row.borderAlpha < 0.1,
    );
    check(
      `${label} · 控件边线 ≥1px 且 alpha ≥0.10（不再只有一枚三角）`,
      transparentBorder.length === 0,
      transparentBorder,
    );

    // ---- 4. 白键在台面上也有形状
    const invisibleButtons = data.buttons.filter((row) => !row.visible);
    check(
      `${label} · 工具栏 ${data.buttons.length} 颗纸白键都有可见边线`,
      data.buttons.length >= 1 && invisibleButtons.length === 0,
      invisibleButtons,
    );
    const btnOnGray = data.buttons.some(
      (row) => Math.abs(row.bgLum - data.tokens.canvas.r) < 0.02 && row.borderAlpha < 0.1,
    );
    check(`${label} · 没有「白键无边框」贴在台面上`, btnOnGray === false);

    // ---- 5. 对齐：下拉框与按钮同高
    check(
      `${label} · 工具栏下拉框与按钮同为 28px`,
      data.selects.length >= 2 &&
        data.selects.every((h) => Math.abs(h - 28) < 0.5) &&
        data.rowButtons.every((h) => Math.abs(h - 28) < 0.5),
      { selects: data.selects, buttons: data.rowButtons },
    );

    // ---- 6. 动作文案没有尾部省略号
    check(
      `${label} · 工具栏按钮没有尾部省略号`,
      data.ellipsisButtons.length === 0,
      data.ellipsisButtons,
    );
  }

  if (failures.length) {
    console.error(`\nAI 工具栏控件回归：${failures.length} 项失败`);
    process.exit(1);
  }
  console.log(`\nAI 工具栏控件回归：${passed}/${passed} 通过`);
}

main();
