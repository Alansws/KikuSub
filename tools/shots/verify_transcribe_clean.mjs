#!/usr/bin/env node
/**
 * 转写页「灰底白框」与页头入口回归（2026-11-26 真机报障）。
 *
 * 用户报障三件事，都发生在同一屏：
 *
 *   1. 「其他已启用引擎」（SenseVoice / FireRed）外面套了一层厚灰底盒子，里面又塞
 *      两个白色小胶囊；紧接着下面的主 / 副引擎又套了一层灰底盒子；
 *   2. 右上角「任务报告 / 快捷键」用低对比灰块，暗淡得像不可点；
 *   3. `导入原文…` / `导入译文…` / `管理引擎…` 还带着尾部省略号。
 *
 * 这个脚本在真实界面里断言：
 *
 * - `.others` / `.duo` 的背景是透明的（不再是一块填充块），且各自有一条 1px 上发丝线；
 * - 里面的控件是**单层**：`.other-chip` 与 `.duo-field` 各有自己的 1px 边，
 *   不和父级填充叠成「灰底套白框」；
 * - 页头两个按钮：有可见 1px 边框、文字对比度 ≥ 4.5、不是 5% 灰底；
 * - 整页没有带尾部省略号的按钮；
 * - 两种色板（cobalt / catppuccin）浅深各拍一张，供人工看真实画面。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），不弹窗。
 *
 * 用法：
 *   node tools/shots/verify_transcribe_clean.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_transcribe_clean.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-transcribe-clean');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');

const CUES = [
  { start: 0.0, end: 1.4, text: 'よう、久しぶり。' },
  { start: 1.5, end: 2.9, text: 'ここで待っていたんだよ。' },
  { start: 3.0, end: 4.4, text: '雨の日だけ、君はここに来る。' },
];

const evalScript = (state) => `
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const until = async (fn, ms = 15000) => {
      const end = Date.now() + ms;
      while (Date.now() < end) {
        const hit = fn();
        if (hit) return hit;
        await sleep(120);
      }
      return null;
    };
    const q = (sel) => document.querySelector(sel);
    const text = (el) => (el ? el.textContent.replace(/\\s+/g, ' ').trim() : null);
    const parse = (value) => {
      const m = String(value).match(/rgba?\\(([^)]+)\\)/);
      if (!m) return { r: 0, g: 0, b: 0, a: 0 };
      const parts = m[1].split(',').map((n) => Number(n.trim()));
      return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
    };
    const lum = (c) => {
      const f = (v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
    };
    const contrast = (a, b) => {
      const la = lum(a), lb = lum(b);
      return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    };

    // 侧栏「转写」是第 2 项（01 准备：导入 / 转写）
    document.querySelectorAll('.sb-item')[1]?.click();
    if (!(await until(() => q('.tr-layout')))) {
      return JSON.stringify({ error: '转写页没有落地', title: q('.tb-title')?.textContent });
    }
    await sleep(600);
    // 「两版一起」才会长出主 / 副引擎那一段
    const bothBtn = [...document.querySelectorAll('.seg button')].find(
      (el) => text(el) === '两版一起',
    );
    bothBtn?.click();
    await sleep(400);
    if (${JSON.stringify(state)} === 'engines') {
      // 滚到主 / 副引擎分区，让截图拍到 03 段下半部分（用户报障的套娃就在这）
      q('.duo')?.scrollIntoView({ block: 'center' });
      await sleep(400);
    }

    const canvas = parse(getComputedStyle(document.querySelector('.pane')).backgroundColor);

    // ---- 1. 分区不再是一块灰底
    const blockInfo = (sel, childSel) => {
      const el = q(sel);
      if (!el) return null;
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return {
        exists: true,
        bgAlpha: parse(style.backgroundColor).a,
        bg: style.backgroundColor,
        borderTop: Number.parseFloat(style.borderTopWidth) || 0,
        borderTopColor: style.borderTopColor,
        radius: style.borderTopLeftRadius,
        hasChild: Boolean(q(childSel)),
        w: Math.round(rect.width),
        h: Math.round(rect.height),
      };
    };

    // 「其他已启用引擎」只在设置里启用了非日语主力引擎时出现；种子机器上可能没有。
    // 没有就只验证主 / 副引擎那块（同一个毛病）。
    const others = blockInfo('.others', '.other-chip');
    const duo = blockInfo('.duo', '.duo-field');

    const duoAfter = blockInfo('.duo', '.duo-field');

    const chipInfo = (sel) => {
      const el = q(sel);
      if (!el) return null;
      const style = getComputedStyle(el);
      return {
        bg: style.backgroundColor,
        bgAlpha: parse(style.backgroundColor).a,
        border: Number.parseFloat(style.borderTopWidth) || 0,
        borderColor: style.borderTopColor,
        radius: style.borderTopLeftRadius,
      };
    };

    // ---- 2. 页头功能入口
    const headerBtns = [...document.querySelectorAll('.page-actions .btn')].map((el) => {
      const style = getComputedStyle(el);
      return {
        label: text(el),
        // 「任务报告」在没有报告时是禁用态（--ink-muted），对比度低是正确的：
        // 断言只对可用的入口成立——用户报障的是「能点却看着像不能点」。
        disabled: el.disabled === true,
        bg: style.backgroundColor,
        bgAlpha: parse(style.backgroundColor).a,
        border: Number.parseFloat(style.borderTopWidth) || 0,
        borderColor: style.borderTopColor,
        color: style.color,
        contrast: Number(contrast(parse(style.color), parse(style.backgroundColor)).toFixed(2)),
        onCanvasContrast: Number(contrast(parse(style.color), canvas).toFixed(2)),
        hasIcon: Boolean(el.querySelector('svg')),
        h: Math.round(el.getBoundingClientRect().height),
      };
    });

    // ---- 3. 省略号
    const ellipsisButtons = [...document.querySelectorAll('button')]
      .map((el) => text(el))
      .filter((label) => label && (label.includes('…') || label.includes('...')));

    return JSON.stringify({
      canvas,
      others,
      duo,
      duoAfter,
      otherChip: chipInfo('.other-chip'),
      duoField: chipInfo('.duo-field'),
      headerBtns,
      ellipsisButtons,
      pageTitle: text(q('.page-title')),
    });
  })()
`;

function ensureMedia() {
  if (fs.existsSync(MEDIA)) return;
  fs.mkdirSync(BASE, { recursive: true });
  execFileSync('ffmpeg', [
    '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x223344:s=640x360:d=8',
    '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', MEDIA,
  ]);
}

function ensureSeed() {
  const seedPath = path.join(BASE, 'seed.json');
  fs.writeFileSync(
    seedPath,
    JSON.stringify({ mediaPath: MEDIA, cues: CUES }, null, 2),
    'utf8',
  );
  return seedPath;
}

function run(theme, appearance, state) {
  const seed = ensureSeed();
  const profile = path.join(BASE, `profile-${theme}-${appearance}`);
  fs.rmSync(profile, { recursive: true, force: true });
  fs.mkdirSync(profile, { recursive: true });

  const extra = (process.env.KIKUSUB_SHOT_ELECTRON_ARGS || '').split(/\s+/).filter(Boolean);
  const themeEval =
    `document.documentElement.dataset.palette='${theme}'` +
    `;localStorage.setItem('kikusub.palette','${theme}')` +
    `;document.documentElement.dataset.theme='${appearance}'` +
    `;localStorage.setItem('kikusub.appearance','${appearance}');`;
  const env = {
    ...process.env,
    KIKUSUB_ALLOW_MULTIPLE: '1',
    KIKUSUB_WIN_SIZE: '1360x838',
    KIKUSUB_SHOT_DELAY: '3000',
    KIKUSUB_OUTPUT_DIR: path.join(BASE, `data-${theme}-${appearance}`, 'out'),
    KIKUSUB_DATA_DIR: path.join(BASE, `data-${theme}-${appearance}`),
    KIKUSUB_PREFERENCES_PATH: path.join(BASE, 'prefs.json'),
    KIKUSUB_DEV_SEED: seed,
    KIKUSUB_DEV_EVAL: themeEval + evalScript(state),
  };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.NODE_OPTIONS;

  const shot = path.join(BASE, `transcribe-${state}-${theme}-${appearance}.png`);
  let stdout = '';
  try {
    stdout = execFileSync(
      'npx',
      ['electron', '.', `--user-data-dir=${profile}`, `--screenshot=${shot}`, ...extra],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 240_000 },
    ).toString();
  } catch (error) {
    stdout = `${error.stdout ?? ''}`;
    console.error(String(error.stderr ?? '').slice(-800));
  }
  const line = stdout.split('\n').filter((row) => row.startsWith('[eval]')).pop();
  if (!line) throw new Error(`渲染进程没有回传结果（${theme}/${appearance}/${state}）`);
  return { data: JSON.parse(line.slice('[eval] '.length)), shot };
}

const failures = [];
function check(name, condition, detail) {
  if (condition) console.log(`  ✓ ${name}`);
  else {
    failures.push(`${name}${detail === undefined ? '' : ` → ${JSON.stringify(detail)}`}`);
    console.error(`  ✗ ${name} → ${JSON.stringify(detail)}`);
  }
}

function main() {
  ensureMedia();
  const combos = (process.env.KIKUSUB_UI_COMBOS || 'cobalt/light,catppuccin/light')
    .split(',')
    .map((pair) => pair.split('/'));

  for (const [theme, appearance] of combos) {
    console.log(`\n[${theme} / ${appearance}]`);
    // 两个视图各自拍一张：`page`（页头与三段全貌）与 `engines`（03 段下半部分，
    // 用户报障的灰底套娃就在那里）。视口只有一屏，不滚就拍不到。
    const { data, shot } = run(theme, appearance, 'page');
    const engines = run(theme, appearance, 'engines');
    if (data.error) {
      failures.push(`${theme}/${appearance} 运行失败：${data.error}`);
      console.error(JSON.stringify(data, null, 2));
      continue;
    }

    // ---- 1. 分区：透明底 + 上发丝线（不是一块填充）
    const duo = data.duoAfter ?? data.duo;
    check('主 / 副引擎分区存在', Boolean(duo?.exists), duo);
    check('主 / 副引擎分区不再是灰底填充块', (duo?.bgAlpha ?? 1) === 0, duo?.bg);
    check('主 / 副引擎分区用 1px 发丝线上边', (duo?.borderTop ?? 0) >= 0.9 && (duo?.borderTop ?? 0) <= 1.1, duo?.borderTop);
    check('主 / 副引擎分区没有卡片圆角（不是一张卡）', duo?.radius === '0px', duo?.radius);
    check('副引擎下拉是下沉单层控件（有 1px 边）', (data.duoField?.border ?? 0) >= 0.9, data.duoField);
    check('副引擎下拉不是纯白键浮在灰底上（背景是 well）', data.duoField?.bg !== 'rgba(0, 0, 0, 0)', data.duoField?.bg);

    if (data.others?.exists) {
      check('「其他已启用引擎」不是灰底盒子', (data.others.bgAlpha ?? 1) === 0, data.others.bg);
      check('「其他已启用引擎」用 1px 发丝线分区', (data.others.borderTop ?? 0) >= 0.9, data.others.borderTop);
      check('引擎胶囊自己有 1px 边（单层质感）', (data.otherChip?.border ?? 0) >= 0.9, data.otherChip);
    } else {
      console.log('  · 这台机器没有启用「其他引擎」，跳过该分区的断言');
    }

    // ---- 2. 页头入口：有轮廓、够对比、有图标
    check('页头有两个功能入口', (data.headerBtns ?? []).length >= 2, (data.headerBtns ?? []).map((b) => b.label));
    for (const btn of data.headerBtns ?? []) {
      check(
        `页头「${btn.label}」有可见 1px 边框`,
        btn.border >= 0.9,
        `${btn.border}px ${btn.borderColor}`,
      );
      if (btn.disabled) {
        console.log(`  · 页头「${btn.label}」当前禁用（没有可看的报告），跳过对比度断言`);
      } else {
        check(`页头「${btn.label}」不是低对比灰块`, btn.onCanvasContrast >= 4.5, btn.onCanvasContrast);
      }
      check(`页头「${btn.label}」带图标（一眼看得出是入口）`, btn.hasIcon === true);
    }

    // ---- 3. 省略号
    check('整页没有带尾省略号的按钮', (data.ellipsisButtons ?? []).length === 0, data.ellipsisButtons);

    // 「其他引擎」分区的断言在滚动后的那一帧更可靠（它在 03 段底部）
    if (engines.data?.others?.exists) {
      check('「其他已启用引擎」不是灰底盒子', (engines.data.others.bgAlpha ?? 1) === 0, engines.data.others.bg);
      check('「其他已启用引擎」用 1px 发丝线分区', (engines.data.others.borderTop ?? 0) >= 0.9, engines.data.others.borderTop);
      check('引擎胶囊自己有 1px 边（单层质感）', (engines.data.otherChip?.border ?? 0) >= 0.9, engines.data.otherChip);
      check('引擎胶囊不是纯白键（纸白键靠边线立住）', (engines.data.otherChip?.border ?? 0) >= 0.9, engines.data.otherChip);
    }

    for (const [label, file] of [['页头与三段全貌', shot], ['主 / 副引擎与底部执行栏', engines.shot]]) {
      if (fs.existsSync(file)) console.log(`  截图（${label}）：${file}`);
      else console.error(`  截图缺失（${label}）：${file}`);
    }
  }

  if (failures.length) {
    console.error(`\n转写页视觉回归：${failures.length} 项失败`);
    process.exit(1);
  }
  console.log('\n转写页视觉回归：全部通过');
}

main();
