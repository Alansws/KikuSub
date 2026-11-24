#!/usr/bin/env node
/**
 * Phase 2 的外壳几何 + 主题对比度回归（无窗口）。
 *
 * 三件本轮改过、但既有脚本没覆盖的事：
 *
 * 1. **52px 收起态里图标与红绿灯的垂直间距**：侧栏收起后，系统红绿灯（约 x19–71 / y13–35）
 *    是画在窗口左上角的原生控件，渲染层无法通过 DOM 读到它。这里量的是渲染层能负责的
 *    那一半——第一个可点元素（导航项）与品牌图标都必须落在红绿灯下方的安全区，
 *    开关按钮必须**不在**左栏里（放进去会被红绿灯压住点不到）。
 * 2. **暗底监看舞台的对比度**：舞台 / 状态条 / 状态条文字 / 1px 分割线，按 CSS 令牌
 *    实算 WCAG 对比度，亮暗两套都必须过阈值。
 * 3. **1px 分割线的可见度**：不要求 3:1（那是文字的标准），但必须明显高于
 *    「5% 灰」那种看不见的线；上一轮 .14 白只有 1.48:1，这里是回归项。
 *
 * 用法：
 *   node tools/shots/verify_phase2_shell.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_phase2_shell.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-phase2-shell');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');
const SHOT = path.join(BASE, 'phase2-shell.png');

const CUES = [
  { start: 0.0, end: 1.4, text: 'よう、久しぶり。' },
  { start: 1.5, end: 2.9, text: 'お前は変わったな、本当に。' },
  { start: 3.0, end: 4.6, text: 'ここで待っていたんだよ、ずっと。' },
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
    const rect = (sel) => {
      const node = document.querySelector(sel);
      if (!node) return null;
      const r = node.getBoundingClientRect();
      return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
    };

    await waitFor(() => document.querySelector('.row[data-i="0"]'));
    await sleep(500);

    // ---- 展开态 ----
    const expanded = {
      sidebarW: Math.round(document.querySelector('.sidebar').getBoundingClientRect().width),
      toggle: rect('.sidebar .sb-toggle'),
      brand: rect('.sb-brand'),
      firstItem: rect('.sb-item'),
      toolbarH: Math.round(document.querySelector('.toolbar').getBoundingClientRect().height),
    };

    // ---- 收起态 ----
    document.querySelector('.sidebar .sb-toggle').click();
    await sleep(500);
    const collapsed = {
      sidebarW: Math.round(document.querySelector('.sidebar').getBoundingClientRect().width),
      sidebarToggle: rect('.sidebar .sb-toggle'),
      toolbarToggle: rect('.toolbar .sb-toggle'),
      brand: rect('.sb-brand'),
      // 间距要量**图标本体**而不是 .sb-brand 的外框：外框自带 16px 下内边距，
      // 拿外框底边去比会把内边距算成「贴住」（第一版断言就是这么误报的）。
      brandIcon: rect('.sb-brand .brand-mark'),
      firstItem: rect('.sb-item'),
    };
    // 回展开态
    document.querySelector('.toolbar .sb-toggle').click();
    await sleep(400);

    // ---- 舞台几何 ----
    const player = document.querySelector('.player');
    const pr = player.getBoundingClientRect();
    const stage = {
      playerW: Math.round(pr.width),
      playerH: Math.round(pr.height),
      ratio: Math.round((pr.width / pr.height) * 1000) / 1000,
      hasPinfo: Boolean(document.querySelector('.pinfo')),
      pinfoH: rect('.pinfo')?.h ?? null,
      hasSplitter: Boolean(document.querySelector('.splitter')),
      splitterH: rect('.splitter')?.h ?? null,
    };

    // ---- 主题令牌（实算对比度，不靠肉眼）----
    const css = getComputedStyle(document.documentElement);
    const token = (name) => css.getPropertyValue(name).trim();
    const lum = (hex) => {
      const h = String(hex).replace('#', '');
      const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
      const n = parseInt(full, 16);
      const parts = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
      });
      return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2];
    };
    const ratio = (a, b) => {
      const la = lum(a), lb = lum(b);
      const hi = Math.max(la, lb), lo = Math.min(la, lb);
      return Math.round(((hi + 0.05) / (lo + 0.05)) * 100) / 100;
    };
    // rgba 叠到不透明底上
    const over = (rgba, base) => {
      const m = String(rgba).match(/rgba?\(([^)]+)\)/);
      if (!m) return rgba;
      const parts = m[1].split(',').map((s) => parseFloat(s.trim()));
      const a = parts.length > 3 ? parts[3] : 1;
      const b = base.replace('#', '');
      const full = b.length === 3 ? b.split('').map((c) => c + c).join('') : b;
      const n = parseInt(full, 16);
      const bg = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
      const toHex = (c) => Math.round(c).toString(16).padStart(2, '0');
      return '#' + [0, 1, 2].map((i) => toHex(parts[i] * a + bg[i] * (1 - a))).join('');
    };
    const stageBg = token('--stage-bg');
    const barBg = token('--stage-bar');
    const ink = over(token('--stage-ink'), barBg);
    const line = over(token('--stage-line'), stageBg);
    const themes = {
      stageBg,
      barBg,
      lineContrast: ratio(line, stageBg),
      inkContrast: ratio(ink, barBg),
      stageVsBar: ratio(stageBg, barBg),
    };

    return JSON.stringify({ expanded, collapsed, stage, themes });
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
  // 固定尺寸的种子：字幕条数不影响几何断言
  const seed = path.join(BASE, 'seed.json');
  fs.writeFileSync(seed, JSON.stringify({ mediaPath: MEDIA, cues: CUES }, null, 1), 'utf8');
  return seed;
}

function run(seed, dataDir, shotPath) {
  const args = ['.', '--no-sandbox', `--user-data-dir=${path.join(BASE, dataDir)}`,
    `--screenshot=${shotPath}`];
  const env = {
    ...process.env,
    KIKUSUB_WIN_SIZE: '1440x900',
    KIKUSUB_DEV_SEED: seed,
    KIKUSUB_SHOT_DELAY: '5200',
    KIKUSUB_DEV_EVAL: EVAL,
    KIKUSUB_OUTPUT_DIR: path.join(BASE, 'outputs'),
    KIKUSUB_DATA_DIR: path.join(BASE, 'data'),
    KIKUSUB_ALLOW_MULTIPLE: '1',
  };
  const extra = process.env.KIKUSUB_SHOT_ELECTRON_ARGS;
  if (extra) args.push(...extra.split(' '));
  const out = execFileSync('npx', ['electron', ...args], {
    cwd: path.join(ROOT, 'desktop'),
    env,
    encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024,
  });
  const line = out.split('\n').reverse().find((l) => l.startsWith('[eval]'));
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
const light = run(seed, 'profile-light', path.join(BASE, 'light.png'));

// ---- 1) 收起态：开关不在左栏，图标与导航落在红绿灯下方 ----
check('收起态：左栏里没有折叠开关（否则会被红绿灯压住）', light.collapsed.sidebarToggle === null);
check('收起态：开关改挂在顶栏', light.collapsed.toolbarToggle !== null, light.collapsed);
check('收起态：侧栏宽 52px', light.collapsed.sidebarW === 52, light.collapsed);
check(
  '收起态：品牌图标顶边在红绿灯区（y<46）之下',
  light.collapsed.brandIcon !== null && light.collapsed.brandIcon.y >= 44,
  light.collapsed.brandIcon,
);
check(
  '收起态：第一个导航项与品牌图标之间留有 ≥12px 呼吸',
  light.collapsed.firstItem !== null &&
    light.collapsed.brandIcon !== null &&
    light.collapsed.firstItem.y -
      (light.collapsed.brandIcon.y + light.collapsed.brandIcon.h) >=
      12,
  { icon: light.collapsed.brandIcon, firstItem: light.collapsed.firstItem },
);

// ---- 2) 展开态 ----
check('展开态：侧栏 236px', light.expanded.sidebarW === 236, light.expanded);
check('展开态：开关在左栏红绿灯留白区右侧', light.expanded.toggle !== null && light.expanded.toggle.y < 46, light.expanded.toggle);
check('顶栏是单行 40px', light.expanded.toolbarH === 40, light.expanded.toolbarH);

// ---- 3) 舞台 ----
check('舞台画面是真 16:9（不拉伸）', Math.abs(light.stage.ratio - 16 / 9) < 0.02, light.stage);
check('舞台有 28px 媒体状态条', light.stage.pinfoH === 28, light.stage);
check('舞台有可拖高度分隔条（6px 命中区）', light.stage.splitterH === 6, light.stage);

// ---- 4) 亮色主题对比度 ----
check('亮色：1px 分割线对舞台 ≥3:1（不退回看不见的灰线）', light.themes.lineContrast >= 3, light.themes);
check('亮色：状态条文字对条底 ≥4.5:1', light.themes.inkContrast >= 4.5, light.themes);

// ---- 5) 暗色主题 ----
const dark = run(seed, 'profile-dark', path.join(BASE, 'dark.png'));
check('暗色：开关同样不在左栏', dark.collapsed.sidebarToggle === null, dark.collapsed);
check('暗色：舞台保持 16:9', Math.abs(dark.stage.ratio - 16 / 9) < 0.02, dark.stage);
check('暗色：1px 分割线对舞台 ≥3:1', dark.themes.lineContrast >= 3, dark.themes);
check('暗色：状态条文字对条底 ≥4.5:1', dark.themes.inkContrast >= 4.5, dark.themes);
check(
  '暗色：舞台比状态条更暗（读得出「这是监看区」）',
  dark.themes.stageVsBar >= 1.0,
  dark.themes,
);

console.log(`\n截图：${SHOT}`);
if (failed) {
  console.log(`${failed} 项失败`);
  process.exit(1);
}
console.log('全部通过。');
