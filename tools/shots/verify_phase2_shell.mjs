#!/usr/bin/env node
/**
 * 外壳几何 + 主题对比度回归（无窗口）。2026-11-25 按 Cue Script 外壳重写。
 *
 * 三件事：
 * 1. **标题栏横跨整窗、红绿灯只落在它里面**：这是本轮外壳的结构前提。
 *    之前标题栏从侧栏右缘起，得靠 `--tl-safe-x` 反算内边距 + 侧栏顶部铺一条
 *    「连续顶带」才能避免竖线穿过黄绿灯；现在侧栏从 y=44 开始，几何上不可能
 *    再碰到原生控件。这里量的是这条不变量，而不是某一版的补丁值。
 * 2. **底栏 24px 只读**：底栏里不许出现 .btn（关键动作已经进菜单：⌘S 暂存/导出）。
 * 3. **舞台与 1px 分割线的对比度**：按 CSS 令牌实算，亮暗两套都必须过阈值。
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
    // 外观由 KIKUSUB_VERIFY_THEME 注入（light / dark）：这个脚本要跑亮 / 暗两轮。
    const THEME = '__THEME__';
    if (THEME && THEME !== 'auto') {
      document.documentElement.dataset.theme = THEME;
      try { localStorage.setItem('kikusub.appearance', THEME); } catch {}
      await new Promise((r) => setTimeout(r, 400));
    }
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

    // 红绿灯的几何由主进程 trafficLightPosition 决定（原生绘制，DOM 读不到）。
    // 这里用同一份常量反算，不写死 87：改了窗口参数必须改这里，脚本会红。
    const TL_X = 19;
    const TL_Y = 16;
    const TL_W = 3 * 12 + 2 * 8; // 三颗 12px 灯 + 两个 8px 间距 = 52
    const TL_H = 12;
    const TL_RIGHT = TL_X + TL_W;
    const TL_MID = TL_Y + TL_H / 2;
    const tlSafeX = Number.parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue('--tl-safe-x'),
    );
    const topbarH = Number.parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue('--topbar-h'),
    );

    // ---- 展开态 ----
    const titlebar = document.querySelector('.titlebar');
    const expanded = {
      viewport: { w: window.innerWidth, h: window.innerHeight },
      titlebar: rect('.titlebar'),
      sidebarW: Math.round(document.querySelector('.sidebar').getBoundingClientRect().width),
      sidebarTop: Math.round(document.querySelector('.sidebar').getBoundingClientRect().top),
      toggle: rect('.titlebar .sb-toggle'),
      doc: rect('.titlebar .doc'),
      crumb: rect('.titlebar .crumb'),
      brand: rect('.sb-brand'),
      firstItem: rect('.sb-item'),
      topbarH,
      tlSafeX,
      // 标题栏里第一个可点元素必须让到红绿灯右缘 + 16
      toggleLeft: rect('.titlebar .sb-toggle')?.x ?? -1,
      tl: { x: TL_X, y: TL_Y, right: TL_RIGHT, mid: TL_MID },
      // 侧栏在标题栏下方：不重叠红绿灯
      overlap: (() => {
        const sb = document.querySelector('.sidebar').getBoundingClientRect();
        const overlapsX = sb.left < TL_RIGHT;
        const overlapsY = sb.top < TL_Y + TL_H;
        return overlapsX && overlapsY;
      })(),
      titlebarBg: getComputedStyle(titlebar).backgroundColor,
      statusbarH: rect('.statusbar')?.h ?? null,
      statusbarButtons: document.querySelectorAll('.statusbar .btn').length,
    };

    // ---- 收起态 ----
    document.querySelector('.titlebar .sb-toggle').click();
    await sleep(500);
    const collapsed = {
      sidebarW: Math.round(document.querySelector('.sidebar').getBoundingClientRect().width),
      sidebarTop: Math.round(document.querySelector('.sidebar').getBoundingClientRect().top),
      // 收起后左栏里不该再有第二颗开关
      sidebarToggle: rect('.sidebar .sb-toggle'),
      brandIcon: rect('.sb-brand .brand-mark'),
      firstItem: rect('.sb-item'),
    };
    document.querySelector('.titlebar .sb-toggle').click();
    await sleep(400);

    // ---- 舞台几何 ----
    // .player 只负责「这一屏给监看区多高」，16:9 的画面本体是 .frame。
    const frame = document.querySelector('.frame');
    const fr = frame.getBoundingClientRect();
    const stageBox = document.querySelector('.stage').getBoundingClientRect();
    const stage = {
      playerW: Math.round(fr.width),
      playerH: Math.round(fr.height),
      ratio: Math.round((fr.width / fr.height) * 1000) / 1000,
      frameW: Math.round(fr.width),
      frameH: Math.round(fr.height),
      frameBorder: getComputedStyle(frame).boxShadow,
      stageBg: getComputedStyle(document.querySelector('.stage')).backgroundColor,
      stageW: Math.round(stageBox.width),
      stageH: Math.round(stageBox.height),
      sideGap: Math.round((stageBox.width - fr.width) / 2),
      bottomGap: Math.round(stageBox.height - fr.height),
      hasPinfo: Boolean(document.querySelector('.pinfo')),
      hasSplitter: Boolean(document.querySelector('.splitter')),
      splitterH: rect('.splitter')?.h ?? null,
    };

    // ---- 主题令牌（实算对比度，不靠肉眼）----
    //
    // 2026-11-26 Batch 3：派生令牌改成 color-mix()，色板由 data-palette 接管。
    // 读取令牌后先用一个隐藏探测元素让浏览器把 color-mix / var() 解析成具体的
    // rgb()/rgba()，否则这里拿到的是 CSS 表达式，算不出亮度。
    const rootEl = document.documentElement;
    const originalTheme = rootEl.dataset.theme || '';
    const originalPalette = rootEl.dataset.palette || '';
    const css = getComputedStyle(rootEl);
    const colorProbe = document.createElement('span');
    colorProbe.style.display = 'none';
    colorProbe.setAttribute('aria-hidden', 'true');
    document.body.appendChild(colorProbe);
    const resolveColor = (raw) => {
      if (!raw) return '';
      colorProbe.style.color = '';
      colorProbe.style.color = raw;
      let value = getComputedStyle(colorProbe).color || '';
      const srgb = value.match(
        /^color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+))?\)$/i,
      );
      if (srgb) {
        const [r, g, b] = [srgb[1], srgb[2], srgb[3]].map((n) => Math.round(Number(n) * 255));
        value = 'rgba(' + r + ', ' + g + ', ' + b + ', ' + (srgb[4] ?? 1) + ')';
      }
      return value;
    };
    const token = (name) => resolveColor(css.getPropertyValue(name).trim());
    const parseColor = (color) => {
      const text = String(color).trim();
      const rgb = text.match(/^rgba?\(([^)]+)\)$/i);
      if (rgb) {
        const parts = rgb[1].split(',').map((s) => parseFloat(s.trim()));
        return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
      }
      let h = text.replace('#', '');
      if (h.length === 3) h = h.split('').map((c) => c + c).join('');
      const n = parseInt(h, 16);
      return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255, a: 1 };
    };
    const composite = (fg, bg) => {
      const f = parseColor(fg);
      const b = parseColor(bg);
      const a = f.a;
      const mix = (x, y) => Math.round(x * a + y * (1 - a));
      return 'rgb(' + mix(f.r, b.r) + ', ' + mix(f.g, b.g) + ', ' + mix(f.b, b.b) + ')';
    };
    const lumOf = (color) => {
      const { r, g, b } = parseColor(color);
      const parts = [r, g, b].map((v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
      });
      return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2];
    };
    const ratio = (fg, bg) => {
      const la = lumOf(composite(fg, bg));
      const lb = lumOf(bg);
      const hi = Math.max(la, lb), lo = Math.min(la, lb);
      return Math.round(((hi + 0.05) / (lo + 0.05)) * 100) / 100;
    };
    const round3 = (value) => Math.round(value * 1000) / 1000;

    /**
     * 量一套色板 × 一个明暗。
     * 断言分三类：正文/标签/强调文字对比度、明度方向（raise 抬 / well 沉）、
     * 输入控件边线可见性（框形凹陷在任意纸面上都要看得出形状）。
     */
    const measure = (palette, theme) => {
      const stageBg = token('--stage-bg');
      const paper = token('--paper');
      const canvas = token('--canvas');
      const surface = token('--surface');
      const raise = token('--raise');
      const well = token('--well');
      const ink = token('--ink');
      const ink3 = token('--ink-3');
      const accentText = token('--accent-text');
      const btnBg = token('--btn-bg');
      const wellLine = token('--well-line');
      return {
        palette,
        theme,
        canvas,
        paper,
        surface,
        raise,
        well,
        ink,
        accent: token('--accent'),
        accentText,
        stageBg,
        stageLum: round3(lumOf(stageBg)),
        lineContrast: ratio(token('--stage-line'), stageBg),
        frameEdgeContrast: ratio(token('--stage-frame'), stageBg),
        bodyInk: ratio(ink, paper),
        labelInk: ratio(ink3, paper),
        labelOnWell: ratio(ink3, well),
        labelOnSurface: ratio(ink3, surface),
        accentInkPaper: ratio(accentText, paper),
        accentInkCanvas: ratio(accentText, canvas),
        accentInkSurface: ratio(accentText, surface),
        // 兼容第一阶段的断言字段名（同一组比值，只是别名）
        accentInk: ratio(accentText, paper),
        accentOnSheet: ratio(accentText, surface),
        accentOnCanvas: ratio(accentText, canvas),
        onAccent: ratio(token('--on-accent'), token('--accent')),
        onAccentHover: ratio(token('--on-accent'), token('--btn-primary-hover')),
        onPrimaryHover: ratio(token('--on-accent'), token('--btn-primary-hover')),
        dangerPaper: ratio(token('--danger'), paper),
        dangerSurface: ratio(token('--danger'), surface),
        warnPaper: ratio(token('--warn'), paper),
        successPaper: ratio(token('--success'), paper),
        hairline: ratio(token('--line'), paper),
        rule: ratio(token('--rule'), canvas),
        wellLinePaper: ratio(wellLine, paper),
        wellLineWell: ratio(wellLine, well),
        btnLineBtn: ratio(token('--btn-line'), btnBg),
        wellAlpha: parseColor(wellLine).a,
        wellVsCanvas: round3(lumOf(well) - lumOf(canvas)),
        wellVsPaper: round3(lumOf(well) - lumOf(paper)),
        raiseVsCanvas: round3(lumOf(raise) - lumOf(canvas)),
        raiseVsSurface: round3(lumOf(raise) - lumOf(surface)),
        surfaceVsCanvas: round3(lumOf(surface) - lumOf(canvas)),
        panelVsCanvas: round3(lumOf(surface) - lumOf(canvas)),
        primary: token('--btn-primary-bg'),
        primaryHover: token('--btn-primary-hover'),
      };
    };

    // 先量当前注入的明暗 + 默认 cobalt（兼容下面原有的亮/暗断言）
    rootEl.dataset.palette = 'cobalt';
    const themes = measure('cobalt', THEME === 'dark' ? 'dark' : 'light');

    // 一次性遍历 6 套色板 × 2 个明暗（同一渲染进程内改 data 属性即可，
    // 不必为 12 种组合各开一次 Electron）。这量的是真实计算样式，不是 CSS 文本。
    const PALETTES = [
      'cobalt', 'nord', 'rose-pine', 'everforest', 'catppuccin', 'cinema-amber',
    ];
    const paletteMatrix = [];
    for (const palette of PALETTES) {
      for (const theme of ['light', 'dark']) {
        rootEl.dataset.palette = palette;
        rootEl.dataset.theme = theme;
        // 强制一次样式重算，确保 token() 读到的是新色板
        void css.getPropertyValue('--canvas');
        paletteMatrix.push(measure(palette, theme));
      }
    }
    rootEl.dataset.palette = originalPalette;
    rootEl.dataset.theme = originalTheme;

    const bar = document.querySelector('.statusbar');
    const barBg = bar ? getComputedStyle(bar).backgroundColor : '';
    const specNode = document.querySelector('.statusbar .st-spec');
    const specInk = specNode ? getComputedStyle(specNode).color : '';
    const relocated = {
      statusSpec: (specNode?.textContent || '').trim(),
      toolbarProxy: (document.querySelector('.titlebar .proxy-state')?.textContent || '').trim(),
      statusInk: barBg && specInk ? ratio(specInk, token('--paper')) : 0,
    };

    return JSON.stringify({
      theme: THEME || 'auto',
      activeTheme: originalTheme,
      expanded,
      collapsed,
      stage,
      themes,
      paletteMatrix,
      relocated,
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
  // 固定尺寸的种子：字幕条数不影响几何断言
  const seed = path.join(BASE, 'seed.json');
  fs.writeFileSync(seed, JSON.stringify({ mediaPath: MEDIA, cues: CUES }, null, 1), 'utf8');
  return seed;
}

function run(seed, dataDir, shotPath, theme = 'light', size = '1440x900') {
  const args = ['.', '--no-sandbox', `--user-data-dir=${path.join(BASE, dataDir)}`,
    `--screenshot=${shotPath}`];
  const env = {
    ...process.env,
    KIKUSUB_WIN_SIZE: size,
    KIKUSUB_DEV_SEED: seed,
    KIKUSUB_SHOT_DELAY: '5200',
    KIKUSUB_DEV_EVAL: EVAL.replace('__THEME__', theme),
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
const light = run(seed, 'profile-light', path.join(BASE, 'light.png'), 'light');

// ---- 1) 结构：标题栏横跨整窗，侧栏从它下面开始 ----
check('标题栏横跨整窗（x=0、宽=视口）', light.expanded.titlebar.x === 0 && light.expanded.titlebar.w === light.expanded.viewport.w, light.expanded);
check('标题栏 44px', light.expanded.titlebar.h === 44, light.expanded.titlebar);
check('侧栏从标题栏底边（y=44）开始', light.expanded.sidebarTop === 44, light.expanded.sidebarTop);
check('侧栏与红绿灯不重叠（结构上不可能再压到原生控件）', light.expanded.overlap === false, light.expanded);
check('侧栏宽 232px', light.expanded.sidebarW === 232, light.expanded.sidebarW);
check('--topbar-h 与标题栏实测一致', light.expanded.topbarH === 44, light.expanded.topbarH);
check(
  '侧栏开关在红绿灯右缘 + 16px 呼吸之后',
  light.expanded.toggleLeft >= light.expanded.tl.right + 16,
  { toggle: light.expanded.toggle, tl: light.expanded.tl },
);
check(
  '侧栏开关与三颗灯同一水平线（中线差 ≤2px）',
  Math.abs(light.expanded.toggle.y + light.expanded.toggle.h / 2 - light.expanded.tl.mid) <= 2,
  { toggle: light.expanded.toggle, tlMid: light.expanded.tl.mid },
);
check(
  '--tl-safe-x 与主进程红绿灯常量一致（19 + 52 + 16）',
  light.expanded.tlSafeX === light.expanded.tl.right + 16,
  light.expanded.tlSafeX,
);
check('面包屑在标题栏中间（文档区之后、动作区之前）', light.expanded.crumb.x > light.expanded.doc.x && light.expanded.crumb.w > 0, light.expanded.crumb);

// ---- 1b) 收起态：52px 图标条，开关仍在标题栏 ----
check('收起态：侧栏 52px', light.collapsed.sidebarW === 52, light.collapsed.sidebarW);
check('收起态：左栏里没有第二颗开关', light.collapsed.sidebarToggle === null, light.collapsed.sidebarToggle);
check(
  '收起态：品牌图标与第一个导航项之间留 ≥12px 呼吸',
  light.collapsed.brandIcon !== null &&
    light.collapsed.firstItem !== null &&
    light.collapsed.firstItem.y - (light.collapsed.brandIcon.y + light.collapsed.brandIcon.h) >= 12,
  { icon: light.collapsed.brandIcon, firstItem: light.collapsed.firstItem },
);

// ---- 2) 底栏：24px 只读 ----
check('底栏 24px', light.expanded.statusbarH === 24, light.expanded.statusbarH);
check('底栏里没有 .btn（关键动作进菜单 / 标题栏）', light.expanded.statusbarButtons === 0, light.expanded.statusbarButtons);
check(
  '媒体规格在底栏（分辨率 · fps）',
  /\d+×\d+/.test(light.relocated.statusSpec) && /fps/i.test(light.relocated.statusSpec),
  light.relocated,
);
check('代理状态在标题栏文件信息旁', light.relocated.toolbarProxy.length > 0, light.relocated);
check('舞台有可拖高度分隔条（6px 命中区）', light.stage.splitterH === 6, light.stage);
check('舞台上没有自己的状态条', light.stage.hasPinfo === false, light.stage);

// ---- 3) 舞台与对比度（亮色） ----
check('舞台画面是真 16:9（不拉伸）', Math.abs(light.stage.ratio - 16 / 9) < 0.02, light.stage);
check('舞台画面保持 640px 设计宽（默认态）', light.stage.frameW === 640, light.stage);
check('亮色：舞台是浅灰画布而不是黑（亮度 ≥0.7）', light.themes.stageLum >= 0.7, light.themes);
check(
  '亮色：画面两侧留白对称（画面在舞台里居中）',
  light.stage.sideGap >= 0 && Math.abs(light.stage.frameW + light.stage.sideGap * 2 - light.stage.stageW) <= 1,
  light.stage,
);
check(
  '亮色：画面本体有 1px 细边（inset box-shadow，可见但极轻）',
  /inset/.test(light.stage.frameBorder) && light.themes.frameEdgeContrast >= 1.2,
  { border: light.stage.frameBorder, contrast: light.themes.frameEdgeContrast },
);
check('亮色：1px 分割线对舞台 ≥3:1', light.themes.lineContrast >= 3, light.themes);
check('亮色：底栏文字对底栏底色 ≥4.5:1', light.relocated.statusInk >= 4.5, light.relocated);
check('亮色：正文墨对纸面 ≥7:1', light.themes.bodyInk >= 7, light.themes);
check('亮色：11px 标签墨对纸面 ≥4.5:1', light.themes.labelInk >= 4.5, light.themes);
check('亮色：蓝铅笔文字对纸面 ≥4.5:1', light.themes.accentInk >= 4.5, light.themes);
check('亮色：蓝铅笔文字对台本 ≥4.5:1', light.themes.accentOnSheet >= 4.5, light.themes);
check('亮色：蓝铅笔文字对画布 ≥4.5:1', light.themes.accentOnCanvas >= 4.5, light.themes);
check('亮色：主按钮白字对强调底 ≥4.5:1', light.themes.onAccent >= 4.5, light.themes);
console.log('    亮色实算：', JSON.stringify(light.themes));
check('亮色：发丝线可见（≥1.25:1，不回退到看不见的 5% 灰）', light.themes.hairline >= 1.25, light.themes);
// 2026-11-26：凹陷必下沉、抬升必凸起 —— 两条方向断言把「凹槽提亮」这类回归钉死。
check('亮色：凹陷暗槽比台面更暗（well 沉在纸下）', light.themes.wellVsCanvas < -0.005, light.themes);
check('亮色：凹陷暗槽比铬件更暗', light.themes.wellVsPaper < 0, light.themes);
check(
  '亮色：按钮 / 浮层不比台面暗（抬升层凸起）',
  light.themes.raiseVsCanvas >= 0,
  light.themes,
);

// ---- 4) 暗色：同一套结构，另一套令牌 ----
const dark = run(seed, 'profile-dark', path.join(BASE, 'dark.png'), 'dark');
check(
  '暗色：这一轮真的跑在暗色上（不是把亮色当暗色量）',
  dark.activeTheme === 'dark',
  { theme: dark.theme, activeTheme: dark.activeTheme },
);
check('暗色：标题栏同样横跨整窗、侧栏同样从 y=44 开始', dark.expanded.titlebar.x === 0 && dark.expanded.sidebarTop === 44, dark.expanded);
check('暗色：舞台保持 16:9', Math.abs(dark.stage.ratio - 16 / 9) < 0.02, dark.stage);
check('暗色：舞台保持深色（亮度 <0.1）', dark.themes.stageLum < 0.1, dark.themes);
check('暗色：画面本体仍有 1px 细边', /inset/.test(dark.stage.frameBorder), dark.stage);
check('暗色：1px 分割线对舞台 ≥3:1', dark.themes.lineContrast >= 3, dark.themes);
check('暗色：底栏文字对底栏底色 ≥4.5:1', dark.relocated.statusInk >= 4.5, dark.relocated);
check('暗色：正文墨对纸面 ≥7:1', dark.themes.bodyInk >= 7, dark.themes);
check('暗色：11px 标签墨对纸面 ≥4.5:1', dark.themes.labelInk >= 4.5, dark.themes);
check('暗色：蓝铅笔文字对纸面 ≥4.5:1', dark.themes.accentInk >= 4.5, dark.themes);
// 暗色必须是「炭黑阶梯 + 下沉暗槽」：灯下最亮的只能是画面与抬升层。
check('暗色：凹陷暗槽沉在画布以下（不再泛白提亮）', dark.themes.wellVsCanvas < -0.001, dark.themes);
check('暗色：凹陷暗槽沉在铬件以下', dark.themes.wellVsPaper < 0, dark.themes);
check('暗色：按钮 / 浮层比画布亮一档（抬升层凸起）', dark.themes.raiseVsCanvas > 0.01, dark.themes);
check('暗色：面板层比画布亮一档', dark.themes.panelVsCanvas > 0.004, dark.themes);
// 用户给的暗色悬停值 #4274F2 配白字只有 4.19:1；实现里压到 #3B6DEE（4.56:1）。
check(
  '暗色：主按钮悬停底仍能配白字（≥4.5:1）',
  dark.themes.onPrimaryHover >= 4.5,
  { primary: dark.themes.primary, hover: dark.themes.primaryHover, ratio: dark.themes.onPrimaryHover },
);

// ---- 4b) 色板矩阵：6 套 × 2 明暗 = 12 种真实计算样式 ----
//
// 2026-11-26 Batch 3：配色从"写死的一套蓝灰"升级为"基色 × 明暗 × 色板"三层正交。
// 这一组断言不看截图，直接在渲染进程里改 data-palette / data-theme 后读计算样式，
// 把每一套色板的正文、11px 标签、强调文字、主按钮、输入控件边线与明度方向全部量一遍。
const matrix = light.paletteMatrix || [];
check('色板矩阵：6 套 × 2 明暗 = 12 种组合', matrix.length === 12, matrix.length);
const combos = new Set(matrix.map((m) => `${m.palette}/${m.theme}`));
check('色板矩阵：12 种组合互不重复', combos.size === 12, [...combos]);

const failures = {
  body: [],
  labels: [],
  accent: [],
  buttons: [],
  status: [],
  borders: [],
  direction: [],
  stage: [],
};
for (const m of matrix) {
  const label = `${m.palette}/${m.theme}`;
  // 用户给的六套基色以 4.5:1 为校准下限；cobalt 的 7:1 仍然由上面两条单独守着。
  if (m.bodyInk < 4.5) failures.body.push(`${label} ${m.bodyInk}`);
  if (m.labelInk < 4.5 || m.labelOnWell < 4.5 || m.labelOnSurface < 4.5) {
    failures.labels.push(`${label} paper ${m.labelInk} / well ${m.labelOnWell} / surface ${m.labelOnSurface}`);
  }
  if (m.accentInkPaper < 4.5 || m.accentInkCanvas < 4.5 || m.accentInkSurface < 4.5) {
    failures.accent.push(`${label} paper ${m.accentInkPaper} / canvas ${m.accentInkCanvas} / surface ${m.accentInkSurface}`);
  }
  if (m.onAccent < 4.5 || m.onAccentHover < 4.5) {
    failures.buttons.push(`${label} ${m.onAccent} / hover ${m.onAccentHover}`);
  }
  if (m.dangerPaper < 4.5 || m.dangerSurface < 4.5 || m.warnPaper < 4.5 || m.successPaper < 4.5) {
    failures.status.push(
      `${label} danger ${m.dangerPaper}/${m.dangerSurface} warn ${m.warnPaper} success ${m.successPaper}`,
    );
  }
  if (m.wellAlpha < 0.1 || m.wellLinePaper < 1.15 || m.btnLineBtn < 1.15) {
    failures.borders.push(
      `${label} alpha ${m.wellAlpha} paper ${m.wellLinePaper} btn ${m.btnLineBtn}`,
    );
  }
  const sinkLimit = m.theme === 'dark' ? -0.001 : -0.005;
  if (m.wellVsCanvas >= sinkLimit || m.wellVsPaper >= 0) {
    failures.direction.push(`${label} well-canvas ${m.wellVsCanvas} well-paper ${m.wellVsPaper}`);
  } else if (m.theme === 'dark') {
    if (m.raiseVsSurface <= 0.004 || m.surfaceVsCanvas <= 0.004) {
      failures.direction.push(
        `${label} raise-surface ${m.raiseVsSurface} surface-canvas ${m.surfaceVsCanvas}`,
      );
    }
  } else if (m.raiseVsCanvas < -0.001 || m.surfaceVsCanvas < -0.001) {
    failures.direction.push(
      `${label} raise-canvas ${m.raiseVsCanvas} surface-canvas ${m.surfaceVsCanvas}`,
    );
  }
  if (m.theme === 'dark' ? m.stageLum >= 0.1 : m.stageLum < 0.7) {
    failures.stage.push(`${label} stageLum ${m.stageLum}`);
  }
  if (m.lineContrast < 3 || m.hairline < 1.25 || m.rule < 1.1) {
    failures.stage.push(`${label} line ${m.lineContrast} hairline ${m.hairline} rule ${m.rule}`);
  }
}

check('12 组合：正文墨对纸面 ≥4.5:1（cobalt 另守 7:1）', failures.body.length === 0, failures.body);
check('12 组合：11px 标签墨对纸 / 凹陷 / 台本 ≥4.5:1', failures.labels.length === 0, failures.labels);
check('12 组合：强调文字对纸 / 画布 / 台本 ≥4.5:1', failures.accent.length === 0, failures.accent);
check('12 组合：主按钮白字（常态 + 悬停）≥4.5:1', failures.buttons.length === 0, failures.buttons);
check('12 组合：朱 / 警示 / 通过文字 ≥4.5:1', failures.status.length === 0, failures.status);
check(
  '12 组合：输入框 / 下拉边线可见（alpha ≥0.10、对纸 ≥1.15、按钮边线 ≥1.15）',
  failures.borders.length === 0,
  failures.borders,
);
check(
  '12 组合：明度方向正确（well 沉在 canvas 下；暗色 raise > surface > canvas）',
  failures.direction.length === 0,
  failures.direction,
);
check('12 组合：舞台明度方向 + 发丝线 / 规则线可见', failures.stage.length === 0, failures.stage);

console.log('    色板矩阵实算（正文 / 标签 / 强调 / 主按钮常态+悬停 / well+按钮边线 / 方向）：');
for (const m of matrix) {
  console.log(
    `      ${m.palette.padEnd(13)} ${m.theme.padEnd(5)} ` +
      `body ${String(m.bodyInk).padEnd(5)} label ${String(m.labelInk).padEnd(5)} ` +
      `accent ${String(m.accentInkPaper).padEnd(5)} on ${m.onAccent}/${m.onAccentHover} ` +
      `well-line ${m.wellLinePaper}/${m.btnLineBtn} ` +
      `well-canvas ${m.wellVsCanvas} raise-surface ${m.raiseVsSurface}`,
  );
}

// ---- 5) 紧凑模式（窗口 ≤900px）：同一套结构 ----
// 触发条件是 CSS 视口宽度，不是缩放：本应用没有缩放菜单（AGENTS.md 红线 14），
// 拿 200% 缩放做验收只会稳定报假红。
const compact = run(seed, 'profile-compact', path.join(BASE, 'compact.png'), 'light', '880x838');
check('紧凑模式：侧栏 52px 图标条', compact.expanded.sidebarW === 52, compact.expanded.sidebarW);
check('紧凑模式：标题栏仍横跨整窗', compact.expanded.titlebar.w === compact.expanded.viewport.w, compact.expanded);
check('紧凑模式：侧栏仍在标题栏下方', compact.expanded.sidebarTop === 44, compact.expanded.sidebarTop);

if (failed) {
  console.log(`\n${failed} 项失败`);
  process.exit(1);
}
console.log('\n全部通过。');
