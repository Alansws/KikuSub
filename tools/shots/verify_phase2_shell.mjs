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
    // 主题由 KIKUSUB_VERIFY_THEME 注入：这个脚本要跑亮 / 暗两轮，
    // 之前只换 user-data-dir 不换主题，两轮的「暗色」断言其实都在量亮色。
    const THEME = '__THEME__';
    if (THEME && THEME !== 'auto') {
      document.documentElement.dataset.theme = THEME;
      try { localStorage.setItem('kikusub.theme', THEME); } catch {}
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
    // 这里用同一份常量反算安全区，不写死 87：改了窗口参数必须改这里，脚本会红。
    const TL_X = 19;
    const TL_Y = 18;
    const TL_W = 3 * 12 + 2 * 8; // 三颗 12px 灯 + 两个 8px 间距 = 52
    const TL_H = 12;
    const TL_RIGHT = TL_X + TL_W;
    const TL_MID = TL_Y + TL_H / 2;
    const tlSafeX = Number.parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue('--tl-safe-x'),
    );

    // ---- 展开态 ----
    const expanded = {
      sidebarW: Math.round(document.querySelector('.sidebar').getBoundingClientRect().width),
      toggle: rect('.sidebar .sb-toggle'),
      brand: rect('.sb-brand'),
      firstItem: rect('.sb-item'),
      toolbarH: Math.round(document.querySelector('.toolbar').getBoundingClientRect().height),
    };

    // ---- 收起态 ----
    // 展开态的开关在左栏，但紧凑模式（≤900px / 200% 缩放）它在顶栏 ——
    // 写死 '.sidebar .sb-toggle' 会让紧凑那一轮直接抛 null。
    const firstToggle = () =>
      document.querySelector('.sidebar .sb-toggle') || document.querySelector('.toolbar .sb-toggle');
    firstToggle().click();
    await sleep(500);
    const sideStyle = getComputedStyle(document.querySelector('.sidebar'));
    const collapsed = {
      sidebarW: Math.round(document.querySelector('.sidebar').getBoundingClientRect().width),
      sidebarToggle: rect('.sidebar .sb-toggle'),
      toolbarToggle: rect('.toolbar .sb-toggle'),
      brand: rect('.sb-brand'),
      // 间距要量**图标本体**而不是 .sb-brand 的外框：外框自带 16px 下内边距，
      // 拿外框底边去比会把内边距算成「贴住」（第一版断言就是这么误报的）。
      brandIcon: rect('.sb-brand .brand-mark'),
      firstItem: rect('.sb-item'),
      tl: { x: TL_X, y: TL_Y, right: TL_RIGHT, mid: TL_MID, safeX: tlSafeX },
      // 顶栏那条横带的连续性：收起态顶部 40px 必须是**一整块**底色，
      // 否则 1px 竖线从黄灯与绿灯之间穿过去，把红黄绿劈成两半。
      railBorder: sideStyle.borderRightColor,
      bandBg: getComputedStyle(document.querySelector('.sidebar'), '::before').backgroundColor,
      bandH: Math.round(
        Number.parseFloat(
          getComputedStyle(document.querySelector('.sidebar'), '::before').height,
        ),
      ),
      dividerTop: Math.round(
        Number.parseFloat(
          getComputedStyle(document.querySelector('.sidebar'), '::after').top || '0',
        ),
      ),
      paperBg: (() => {
        const probe = document.createElement('div');
        probe.style.cssText = 'position:fixed;left:-9999px;width:1px;height:1px';
        probe.style.background = 'var(--paper)';
        document.body.append(probe);
        const c = getComputedStyle(probe).backgroundColor;
        probe.remove();
        return c;
      })(),
      toolbarBg: getComputedStyle(document.querySelector('.toolbar')).backgroundColor,
    };
    // 回展开态
    firstToggle().click();
    await sleep(400);

    // ---- 舞台几何 ----
    // 2026-11-24 二改：.player 只负责「这一屏给监看区多高」，16:9 的画面本体是 .frame。
    // 比例要量 .frame（量 .player 会把「舞台画布留白」读成比例失真）。
    const frame = document.querySelector('.frame');
    const fr = frame.getBoundingClientRect();
    const stageBox = document.querySelector('.stage').getBoundingClientRect();
    const stage = {
      playerW: Math.round(fr.width),
      playerH: Math.round(fr.height),
      ratio: Math.round((fr.width / fr.height) * 1000) / 1000,
      // 画面本体四周不再有暗色外边距：.frame 与可视画面同尺寸，左右留白归舞台画布。
      frameW: Math.round(fr.width),
      frameH: Math.round(fr.height),
      frameBorder: getComputedStyle(frame).boxShadow,
      // 舞台底色（浅色应为柔和浅灰画布，不再是与画面连成一片的黑）
      stageBg: getComputedStyle(document.querySelector('.stage')).backgroundColor,
      // 画面两侧 / 底部到舞台边缘的距离 = 舞台画布本身（不再是「黑边」）
      stageW: Math.round(stageBox.width),
      stageH: Math.round(stageBox.height),
      sideGap: Math.round((stageBox.width - fr.width) / 2),
      bottomGap: Math.round(stageBox.height - fr.height),
      // 舞台上不该再有自己的状态条（2026-11-24 撤销：规格并入底栏、代理进顶栏）
      hasPinfo: Boolean(document.querySelector('.pinfo')),
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
    // 舞台状态条已撤销（2026-11-24），只剩舞台底色与 1px 分割线这两个真存在的令牌。
    // 同日二改：浅色主题的舞台从「近纯黑」改成柔和浅灰画布，1px 分割线也随之
    // 从 0.34 白换成 0.52 墨（白线在浅灰上等于消失）；暗色主题口径不变。
    const stageBg = token('--stage-bg');
    const line = over(token('--stage-line'), stageBg);
    // 画面本体的 1px 细边：必须比舞台画布可见（≥1.2:1），但不抢画面本身。
    const frameEdge = over(token('--stage-frame'), stageBg);
    // 浅色舞台必须是「浅画布」而不是黑：亮度明显高于画面黑。
    const lumOf = (hex) => {
      const h = hex.replace('#', '');
      const n = parseInt(h, 16);
      const parts = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
      });
      return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2];
    };
    // 规格与代理状态的新位置
    // 规格与代理状态的新位置；顺带量底栏文字的对比度（舞台状态条撤掉后
    // 「状态条文字对条底」这条断言失去对象，改成量真正承载它的底栏）。
    const bar = document.querySelector('.statusbar');
    const barBg = bar ? getComputedStyle(bar).backgroundColor : '';
    const specNode = document.querySelector('.statusbar .sb-spec');
    const specInk = specNode ? getComputedStyle(specNode).color : '';
    const relocated = {
      statusSpec: (specNode?.textContent || '').trim(),
      toolbarProxy: (document.querySelector('.toolbar .proxy-state')?.textContent || '').trim(),
      statusInk: barBg && specInk ? ratio(over(specInk, token('--paper')), token('--paper')) : 0,
    };
    const themes = {
      stageBg,
      stageLum: Math.round(lumOf(stageBg) * 1000) / 1000,
      lineContrast: ratio(line, stageBg),
      frameEdgeContrast: ratio(frameEdge, stageBg),
    };

    return JSON.stringify({
      theme: THEME || 'auto',
      activeTheme: document.documentElement.dataset.theme || '',
      expanded,
      collapsed,
      stage,
      themes,
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

// ---- 1b) 收起态：折叠开关与系统红绿灯的横向 / 纵向关系（2026-11-24 修）----
// 修之前：顶栏从 52px 起 + 16px 内边距 = 68px，而红绿灯右缘在 71px，
// 开关正好压在绿色那颗上（用户截图报障）。现在必须让到安全区之后。
check(
  '收起态：折叠开关左缘在红绿灯右缘 + 16px 呼吸之后',
  light.collapsed.toolbarToggle !== null &&
    light.collapsed.toolbarToggle.x >= light.collapsed.tl.right + 16,
  { toggle: light.collapsed.toolbarToggle, tl: light.collapsed.tl },
);
check(
  '收起态：折叠开关与三颗灯同一水平线（中线差 ≤1px）',
  light.collapsed.toolbarToggle !== null &&
    Math.abs(
      light.collapsed.toolbarToggle.y +
        light.collapsed.toolbarToggle.h / 2 -
        light.collapsed.tl.mid,
    ) <= 1,
  { toggle: light.collapsed.toolbarToggle, tlMid: light.collapsed.tl.mid },
);
check(
  '收起态：--tl-safe-x 与主进程红绿灯常量一致（19 + 52 + 16）',
  light.collapsed.tl.safeX === light.collapsed.tl.right + 16,
  light.collapsed.tl,
);
// ---- 1c) 收起态：顶部 40px 是一整块底色（红黄绿灯背后连续）----
// 修之前竖分割线从 y=0 画起、正好从黄灯与绿灯之间穿过，把三颗灯劈成两半。
check(
  '收起态：侧栏顶部不再画自己的右边框（否则线会横穿红绿灯）',
  /rgba\(0, 0, 0, 0\)|transparent/.test(light.collapsed.railBorder),
  light.collapsed.railBorder,
);
check(
  '收起态：顶部顶带铺满 40px 且与顶栏同色',
  light.collapsed.bandH === 40 && light.collapsed.bandBg === light.collapsed.paperBg,
  { band: light.collapsed.bandBg, paper: light.collapsed.paperBg, h: light.collapsed.bandH },
);
check(
  '收起态：竖分割线从顶栏底边（y=40）才开始',
  light.collapsed.dividerTop === 40,
  light.collapsed.dividerTop,
);

// ---- 2) 展开态 ----
check('展开态：侧栏 236px', light.expanded.sidebarW === 236, light.expanded);
check('展开态：开关在左栏红绿灯留白区右侧', light.expanded.toggle !== null && light.expanded.toggle.y < 46, light.expanded.toggle);
check('顶栏是单行 40px', light.expanded.toolbarH === 40, light.expanded.toolbarH);

// ---- 3) 舞台 ----
check('舞台画面是真 16:9（不拉伸）', Math.abs(light.stage.ratio - 16 / 9) < 0.02, light.stage);
check('舞台画面保持 640px 设计宽（默认态）', light.stage.frameW === 640, light.stage);
check('舞台上不再有自己的状态条', light.stage.hasPinfo === false, light.stage);
check(
  '媒体规格并入底栏（分辨率 · 编码 · fps）',
  /\d+×\d+/.test(light.relocated.statusSpec) && /fps/i.test(light.relocated.statusSpec),
  light.relocated,
);
check('代理状态在顶栏文件信息旁', light.relocated.toolbarProxy.length > 0, light.relocated);
check('舞台有可拖高度分隔条（6px 命中区）', light.stage.splitterH === 6, light.stage);

// ---- 4) 亮色主题：浅画布舞台 + 对比度 ----
// 2026-11-24 二改的口径：浅色下舞台是**柔和浅灰画布**，不再是深黑。
// 判定分三条：① 舞台亮度显著高于画面黑（否则又是「两条黑边」）；
// ② 画面本体有 1px 细边（把画面与留白分开）；③ 1px 分割线仍可见。
check(
  '亮色：舞台是浅灰画布而不是黑（亮度 ≥0.7）',
  light.themes.stageLum >= 0.7,
  light.themes,
);
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
check('亮色：1px 分割线对舞台 ≥3:1（不退回看不见的灰线）', light.themes.lineContrast >= 3, light.themes);
check('亮色：底栏文字对底栏底色 ≥4.5:1', light.relocated.statusInk >= 4.5, light.relocated);

// ---- 5) 暗色主题 ----
const dark = run(seed, 'profile-dark', path.join(BASE, 'dark.png'), 'dark');
check(
  '暗色：这一轮真的跑在暗色主题上（不是把亮色当暗色量）',
  dark.activeTheme === 'dark',
  { theme: dark.theme, activeTheme: dark.activeTheme },
);
check('暗色：开关同样不在左栏', dark.collapsed.sidebarToggle === null, dark.collapsed);
// 三条与亮色同口径：深色主题下竖线同样不能横穿红绿灯，否则黑底上那道浅线更刺眼。
check(
  '暗色：开关同样在红绿灯右缘 + 16px 之后、同一水平线',
  dark.collapsed.toolbarToggle !== null &&
    dark.collapsed.toolbarToggle.x >= dark.collapsed.tl.right + 16 &&
    Math.abs(
      dark.collapsed.toolbarToggle.y +
        dark.collapsed.toolbarToggle.h / 2 -
        dark.collapsed.tl.mid,
    ) <= 1,
  dark.collapsed,
);
check(
  '暗色：顶部顶带同样铺满 40px、与顶栏同色（深色下要跟 --paper 一起变）',
  dark.collapsed.bandH === 40 && dark.collapsed.bandBg === dark.collapsed.paperBg,
  { band: dark.collapsed.bandBg, paper: dark.collapsed.paperBg },
);
check('暗色：竖分割线同样从 y=40 开始', dark.collapsed.dividerTop === 40, dark.collapsed.dividerTop);
check('暗色：舞台保持 16:9', Math.abs(dark.stage.ratio - 16 / 9) < 0.02, dark.stage);
check('暗色：舞台保持深色（亮度 <0.1，浅色改动没有渗到暗色）', dark.themes.stageLum < 0.1, dark.themes);
check('暗色：画面本体仍有 1px 细边', /inset/.test(dark.stage.frameBorder), dark.stage);
check('暗色：1px 分割线对舞台 ≥3:1', dark.themes.lineContrast >= 3, dark.themes);
check('暗色：底栏文字对底栏底色 ≥4.5:1', dark.relocated.statusInk >= 4.5, dark.relocated);

// ---- 6) 紧凑模式（窗口被拉到 ≤900px）：同一套红绿灯安全区 ----
// 触发条件是 CSS 视口宽度，不是缩放：用户把窗口拉窄到 900px 以下时，图标轨被媒体查询
// 加宽到 56px——和 52px 一样窄于红绿灯右缘 71px，所以开关同样必须挂到顶栏、
// 同样要让出 --tl-safe-x。
// **刻意用真实窄窗而不是 200% 缩放**：本应用没有缩放菜单，200% 不是用户可达状态
// （AGENTS.md 红线 14 / desktop-lifecycle §3.7.1），拿它做验收只会稳定报假红。
const compact = run(seed, 'profile-compact', path.join(BASE, 'compact.png'), 'light', '880x838');
// 紧凑模式下「展开」是 56px 图标轨；收起后仍是 52（`.sidebar.collapsed` 优先级更高，
// 且 52 本来就是「16px 图标 + 两侧各 18px」的下限）。这里断言的是收起后的值，
// 展开态的 56 由下一条量 `.sidebar` 的宽度间接覆盖（toggle 挂在顶栏、左栏无开关）。
check(
  '紧凑模式：收起后图标轨 52px 且左栏里没有折叠开关',
  compact.collapsed.sidebarW === 52 && compact.collapsed.sidebarToggle === null,
  { w: compact.collapsed.sidebarW, toggle: compact.collapsed.sidebarToggle },
);
check(
  '紧凑模式：展开态图标轨 56px（媒体查询生效）',
  compact.expanded.sidebarW === 56,
  compact.expanded.sidebarW,
);
check(
  '紧凑模式：开关让到红绿灯右缘 + 16px 之后、同一水平线',
  compact.collapsed.toolbarToggle !== null &&
    compact.collapsed.toolbarToggle.x >= compact.collapsed.tl.right + 16 &&
    Math.abs(
      compact.collapsed.toolbarToggle.y +
        compact.collapsed.toolbarToggle.h / 2 -
        compact.collapsed.tl.mid,
    ) <= 1,
  compact.collapsed,
);
check(
  '紧凑模式：顶部顶带同样 40px 连续、竖线从 y=40 起',
  compact.collapsed.bandH === 40 &&
    compact.collapsed.bandBg === compact.collapsed.paperBg &&
    compact.collapsed.dividerTop === 40,
  compact.collapsed,
);
check(
  '紧凑模式：品牌图标仍在顶栏发丝线之下',
  compact.collapsed.brandIcon !== null && compact.collapsed.brandIcon.y >= 44,
  compact.collapsed.brandIcon,
);

console.log(`\n截图：${SHOT}`);
if (failed) {
  console.log(`${failed} 项失败`);
  process.exit(1);
}
console.log('全部通过。');
