#!/usr/bin/env node
/**
 * 「章节 / 时刻点标记 + 成片写入」无窗口回归（2026-11-20）。
 *
 * 覆盖：
 *   - 检查器「章节」页签：播放头插时刻点、选区设为章节（输入标题回车即添加）；
 *   - 波形顶部章节旗标 / 区间色条：数量、悬停标题、单击跳转；
 *   - 编辑标题（回车保存）→ ⌘Z 一次撤回（统一历史，不是第二套撤销栈）；
 *   - 导出页开关：有标记时默认勾选并显示数量；
 *   - 「仅封装」真实导出一次，用 ffprobe -show_chapters 读回章节（IINA 可跳转）。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现。断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_chapters.mjs                       # 截图停在核对台
 *   CHAPTERS_FINAL_VIEW=export node tools/shots/verify_chapters.mjs  # 截图停在导出页
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_chapters.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-chapters');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'chapters.mp4');
const FINAL_VIEW = process.env.CHAPTERS_FINAL_VIEW === 'export' ? 'export' : 'review';
const SHOT = path.join(BASE, `chapters-${FINAL_VIEW}.png`);
const DURATION = 60;

const CUES = [
  { start: 2.0, end: 6.0, text: '最初の場面です' },
  { start: 20.0, end: 24.0, text: '真ん中の台詞' },
  { start: 40.0, end: 44.0, text: '後半の台詞' },
];

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const waitFor = async (fn, ms = 20000) => {
      const t0 = Date.now();
      while (Date.now() - t0 < ms) {
        const value = fn();
        if (value) return value;
        await sleep(80);
      }
      return null;
    };
    const wave = () => document.querySelector('.wave-wrap');
    const timeValue = () => {
      const text = document.querySelector('.tp-time')?.textContent.trim() ?? '';
      const parts = text.split(':').map(Number);
      return parts.length === 3 ? parts[0] * 3600 + parts[1] * 60 + parts[2] : 0;
    };
    const pointAt = (t) => {
      const rect = wave().getBoundingClientRect();
      return { x: rect.left + (t / ${DURATION}) * rect.width, y: rect.top + 40 };
    };
    const clickAt = async (t) => {
      const p = pointAt(t);
      for (const type of ['pointerdown', 'pointerup']) {
        wave().dispatchEvent(
          new PointerEvent(type, {
            bubbles: true,
            clientX: p.x,
            clientY: p.y,
            pointerId: 1,
            button: 0,
            pointerType: 'mouse',
          }),
        );
      }
      await sleep(220);
    };
    const dragSelect = async (from, to) => {
      const a = pointAt(from);
      const b = pointAt(to);
      const base = { bubbles: true, clientY: a.y, pointerId: 9, button: 0, pointerType: 'mouse' };
      wave().dispatchEvent(new PointerEvent('pointerdown', { ...base, clientX: a.x }));
      await sleep(90);
      wave().dispatchEvent(new PointerEvent('pointermove', { ...base, clientX: b.x }));
      await sleep(90);
      wave().dispatchEvent(new PointerEvent('pointerup', { ...base, clientX: b.x }));
      await sleep(300);
    };
    const flags = () => [...document.querySelectorAll('.chapter-track .flag')];
    const ranges = () => [...document.querySelectorAll('.chapter-track .range')];
    const items = () => [...document.querySelectorAll('.chapters-panel .item')];
    const itemText = () => items().map((el) => el.textContent.replace(/\s+/g, ' ').trim());
    const buttonByText = (root, text) =>
      [...root.querySelectorAll('button')].find((el) => (el.textContent || '').includes(text));
    const tab = (label) =>
      [...document.querySelectorAll('.insp-tab')].find((el) =>
        (el.textContent || '').trim().startsWith(label),
      );
    const sidebar = (label) =>
      [...document.querySelectorAll('.sb-item')].find((el) =>
        (el.getAttribute('aria-label') || '').startsWith(label),
      );
    const press = async (key, opts = {}) => {
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
      await sleep(opts.wait ?? 220);
    };

    await waitFor(() => wave() && document.querySelector('video'));
    await sleep(600);

    // 1) 打开检查器「章节」页签
    tab('章节')?.click();
    await waitFor(() => document.querySelector('.chapters-panel'));
    const emptyText = document.querySelector('.chapters-panel .chapter-empty')?.textContent.trim() ?? '';

    // 2) 播放头插时刻点：输入标题 + 回车（回车 = 默认动作）
    await clickAt(12);
    const input = document.querySelector('.chapters-panel .ch-title');
    input.focus();
    input.value = '倒计时开始';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await press('Enter', { code: 'Enter', wait: 500 });
    await waitFor(() => items().length === 1);
    const afterPoint = { count: items().length, text: itemText(), flags: flags().length };

    // 3) 选区设为章节：先框选 20–34s，再点按钮
    await dragSelect(20, 34);
    const hasSelection = Boolean(document.querySelector('.sel-bar'));
    buttonByText(document.querySelector('.chapters-panel'), '选区设为章节')?.click();
    await waitFor(() => items().length === 2);
    await sleep(200);
    const afterRange = {
      count: items().length,
      text: itemText(),
      flags: flags().length,
      ranges: ranges().length,
    };

    // 4) 单击旗标跳转（第 1 个旗标 = 12s 的时刻点）
    flags()[0]?.click();
    await sleep(400);
    const timeAfterFlagClick = timeValue();
    const flagTitle = flags()[0]?.getAttribute('title') ?? '';

    // 5) 编辑标题 + 回车
    const firstItem = items().find((el) => el.textContent.includes('倒计时开始'));
    // 按 aria-label 找「编辑」，不按位置：时刻点行还多了「补起点 / 补终点」两枚按钮
    firstItem?.querySelector('[aria-label="编辑标记"]')?.click();
    await sleep(250);
    const editTitle = document.querySelector('.chapters-panel .e-title');
    editTitle.focus();
    editTitle.value = '发射点';
    editTitle.dispatchEvent(new Event('input', { bubbles: true }));
    await press('Enter', { code: 'Enter', wait: 600 });
    await sleep(300);
    const afterRename = itemText();

    // 6) ⌘Z 一次撤回重命名（统一历史）
    await press('z', { code: 'KeyZ', meta: true, wait: 700 });
    await sleep(300);
    const afterUndo = itemText();

    // 7) 清掉时间选区再去导出页：最后的截图里不该有一条与章节色条重叠的选框
    await press('Escape', { code: 'Escape', wait: 400 });

    // 8) 导出页：开关默认勾选、显示数量
    sidebar('导出')?.click();
    await waitFor(() => document.querySelector('.export-view'));
    await sleep(500);
    const chapterChk = [...document.querySelectorAll('.export-view label.chk')].find((el) =>
      (el.textContent || '').includes('写入章节标记'),
    );
    const exportToggle = {
      found: Boolean(chapterChk),
      checked: chapterChk?.querySelector('input')?.checked ?? null,
      label: (chapterChk?.textContent || '').replace(/\s+/g, ' ').trim(),
      disabled: chapterChk?.querySelector('input')?.disabled ?? null,
    };

    // 9) 仅封装导出一次（几秒），验证容器里真的有章节
    buttonByText(document.querySelector('.export-view'), '仅封装')?.click();
    await sleep(500);
    buttonByText(document.querySelector('.export-view'), '开始导出')?.click();
    const done = await waitFor(() => document.querySelector('.done-path'), 60000);
    const outPath = done?.getAttribute('title') ?? '';
    const doneMeta = document.querySelector('.done-card .done-meta')?.textContent.trim() ?? '';

    if ('${FINAL_VIEW}' === 'export') {
      await sleep(300);
      return JSON.stringify({
        emptyText,
        afterPoint,
        afterRange,
        hasSelection,
        timeAfterFlagClick,
        flagTitle,
        afterRename,
        afterUndo,
        exportToggle,
        outPath,
        doneMeta,
      });
    }

    // 10) 回到核对台，截图停在「有章节旗标 + 章节面板」的状态
    sidebar('核对台')?.click();
    await waitFor(() => wave());
    await sleep(700);
    tab('章节')?.click();
    await sleep(400);
    return JSON.stringify({
      emptyText,
      afterPoint,
      afterRange,
      hasSelection,
      timeAfterFlagClick,
      flagTitle,
      afterRename,
      afterUndo,
      exportToggle,
      outPath,
      doneMeta,
      finalFlags: flags().length,
      finalItems: items().length,
      geom: (() => {
        const track = document.querySelector('.chapter-track');
        const wrap = wave();
        if (!track || !wrap) return null;
        const t = track.getBoundingClientRect();
        const w = wrap.getBoundingClientRect();
        const firstFlag = flags()[0]?.getBoundingClientRect();
        return {
          wrap: [Math.round(w.left), Math.round(w.top), Math.round(w.width), Math.round(w.height)],
          track: [Math.round(t.left), Math.round(t.top), Math.round(t.width), Math.round(t.height)],
          flag: firstFlag ? [Math.round(firstFlag.left), Math.round(firstFlag.top)] : null,
        };
      })(),
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
    `color=c=0x2a3b4a:s=640x360:d=${DURATION}:r=24`,
    '-f',
    'lavfi',
    '-i',
    `sine=frequency=360:duration=${DURATION}`,
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
    KIKUSUB_SHOT_DELAY: '3200',
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
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 300_000 },
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

check('空态提示说明两种添加方式', (result.emptyText || '').includes('插时刻点'), result.emptyText);
check('回车在播放头添加时刻点', result.afterPoint.count === 1, result.afterPoint);
check(
  '时刻点显示为 ◆ 并带标题',
  (result.afterPoint.text[0] || '').includes('◆') &&
    (result.afterPoint.text[0] || '').includes('倒计时开始'),
  result.afterPoint,
);
check('时间轴出现章节旗标', result.afterPoint.flags === 1, result.afterPoint);
check('框选后可用「选区设为章节」', result.hasSelection === true);
check('选区添加为章节区间', result.afterRange.count === 2, result.afterRange);
check(
  '区间显示为 ▭ → 结束时间',
  (result.afterRange.text[1] || '').includes('▭') &&
    (result.afterRange.text[1] || '').includes('→'),
  result.afterRange,
);
check('两个旗标 + 两个区间色条', result.afterRange.flags === 2 && result.afterRange.ranges === 2, result.afterRange);
check('悬停旗标带标题与时间', (result.flagTitle || '').includes('倒计时开始'), result.flagTitle);
check('单击旗标跳到章节起点（≈12s）', Math.abs(result.timeAfterFlagClick - 12) < 0.6, {
  time: result.timeAfterFlagClick,
});
check(
  '标题可编辑（回车保存）',
  result.afterRename.some((text) => text.includes('发射点')),
  result.afterRename,
);
check(
  '⌘Z 一次撤回重命名（统一历史）',
  result.afterUndo.some((text) => text.includes('倒计时开始')) &&
    !result.afterUndo.some((text) => text.includes('发射点')),
  result.afterUndo,
);
check(
  '导出页有「写入章节标记」开关，默认开启并显示数量',
  result.exportToggle.found === true &&
    result.exportToggle.checked === true &&
    result.exportToggle.disabled === false &&
    (result.exportToggle.label || '').includes('2 个'),
  result.exportToggle,
);

// 容器级：ffprobe 读回章节（IINA 等播放器跳转的依据）
let probe = { chapters: [] };
if (result.outPath) {
  const raw = execFileSync(
    'ffprobe',
    ['-v', 'error', '-show_chapters', '-of', 'json', result.outPath],
    { encoding: 'utf8' },
  );
  probe = JSON.parse(raw || '{}');
}
const chapters = probe.chapters ?? [];
check('仅封装导出的成片存在', Boolean(result.outPath) && fs.existsSync(result.outPath), result.outPath);
check(
  'ffprobe 读到 3 个章节（首个标记晚于 0：自动补「开场」）',
  chapters.length === 3 &&
    chapters[0]?.tags?.title === '开场' &&
    chapters[1]?.tags?.title === '倒计时开始' &&
    chapters[2]?.tags?.title === '场景 00:20–00:34',
  chapters.map((c) => ({ title: c.tags?.title, start: c.start_time, end: c.end_time })),
);
check(
  '时刻点衔接到下一个标记、区间按声明结束、开场到真实起点',
  chapters.length === 3 &&
    Math.abs(Number(chapters[0].start_time) - 0) < 0.05 &&
    Math.abs(Number(chapters[0].end_time) - 12) < 0.05 &&
    Math.abs(Number(chapters[1].start_time) - 12) < 0.05 &&
    Math.abs(Number(chapters[1].end_time) - 20) < 0.05 &&
    Math.abs(Number(chapters[2].start_time) - 20) < 0.05 &&
    Math.abs(Number(chapters[2].end_time) - 34) < 0.05,
  chapters.map((c) => [c.start_time, c.end_time]),
);

if (FINAL_VIEW === 'review') {
  check('截图状态：旗标与面板都在', result.finalFlags === 2 && result.finalItems === 2, {
    flags: result.finalFlags,
    items: result.finalItems,
  });
  check(
    '章节色条贴在刻度条下沿（RULER_H=17）',
    result.geom && result.geom.track[1] - result.geom.wrap[1] === 17,
    result.geom,
  );
}

if (failures.length) {
  console.error(`\n${failures.length} 项断言失败：\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`\n截图：${SHOT}`);
