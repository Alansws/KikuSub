#!/usr/bin/env node
/**
 * 「章节区间端点拖动 + 边缘自动平移」无窗口回归（2026-11-25）。
 *
 * 覆盖：
 *   - 拖右端抓手改终点（一步历史，⌘Z 一次撤回）；
 *   - 拖旗标改起点（单击仍是跳转，4px 阈值）；
 *   - 拖到右缘外：指针不动也会继续推进（视窗跟着平移，端点在走）；
 *   - 时刻点没有抓手；
 *   - 拖动期间播放头不动（改标记不等于擦洗）。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现。断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_chapter_edge.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_chapter_edge.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-chapter-edge');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'edge.mp4');
const SHOT = path.join(BASE, 'chapter-edge.png');
const DURATION = 60;

const CUES = [
  { start: 12.0, end: 13.0, text: '最初の台詞' },
  { start: 41.0, end: 42.0, text: '後半の台詞' },
];

/** 一条 14→15 的区间（放大器要点得中） + 一条时刻点（40）验证「点没有抓手」。 */
const CHAPTERS = [
  { id: 'ch-1', start: 14, end: 15, title: '场景 1' },
  { id: 'ch-2', start: 40, end: null, title: '场景 2 结束' },
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
    const rect = () => wave().getBoundingClientRect();
    const timeText = () => document.querySelector('.tp-time')?.textContent.trim() ?? '';
    const timeValue = () => {
      const parts = timeText().split(':').map(Number);
      return parts.length === 3 ? parts[0] * 3600 + parts[1] * 60 + parts[2] : 0;
    };
    const pointAt = (t) => {
      const r = rect();
      return { x: r.left + (t / ${DURATION}) * r.width, y: r.top + 40 };
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
      await sleep(240);
    };
    const zoomAtPlayhead = async (times = 2) => {
      for (let i = 0; i < times; i += 1) {
        const r = rect();
        const el = document.querySelector('.ph');
        const ph = el ? el.getBoundingClientRect() : null;
        const x = ph ? ph.left + ph.width / 2 : r.left + r.width / 2;
        wave().dispatchEvent(
          new WheelEvent('wheel', {
            bubbles: true,
            cancelable: true,
            deltaY: -120,
            ctrlKey: true,
            clientX: x,
            clientY: r.top + 60,
          }),
        );
        await sleep(120);
      }
      await sleep(220);
    };
    const ranges = () => [...document.querySelectorAll('.chapter-track .range')];
    const rangeEl = () => ranges().find((el) => !el.classList.contains('point'));
    const flagEl = () => document.querySelector('.chapter-track .flag:not(.point)');
    const flagX = () => {
      const el = flagEl();
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return r.left + r.width / 2;
    };
    const gripEl = () => rangeEl()?.querySelector('.grip') ?? null;
    const gripPoint = () => {
      const el = gripEl();
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    };
    const dragTo = async (el, from, to, opts = {}) => {
      const base = {
        bubbles: true,
        pointerId: opts.id ?? 7,
        pointerType: 'mouse',
        button: 0,
        buttons: 1,
      };
      el.dispatchEvent(new PointerEvent('pointerdown', { ...base, clientX: from.x, clientY: from.y }));
      await sleep(70);
      el.dispatchEvent(
        new PointerEvent('pointermove', {
          ...base,
          clientX: to.x,
          clientY: to.y,
          buttons: 1,
        }),
      );
      if (opts.holdMs) await sleep(opts.holdMs);
      el.dispatchEvent(
        new PointerEvent('pointerup', {
          ...base,
          clientX: to.x,
          clientY: to.y,
          buttons: 0,
        }),
      );
      await sleep(opts.wait ?? 600);
    };
    const items = () => [...document.querySelectorAll('.chapters-panel .item')];
    const tab = (label) =>
      [...document.querySelectorAll('.insp-tab')].find((el) =>
        (el.textContent || '').trim().startsWith(label),
      );
    const press = async (key, opts = {}) => {
      const target = document.activeElement ?? window;
      target.dispatchEvent(
        new KeyboardEvent('keydown', {
          key,
          code: opts.code ?? '',
          metaKey: Boolean(opts.meta),
          bubbles: true,
          cancelable: true,
        }),
      );
      await sleep(opts.wait ?? 320);
    };
    const parseTc = (text) => {
      const m = (text || '').match(/(\d+):(\d+)\.(\d+)/);
      return m ? Number(m[1]) * 60 + Number(m[2]) + Number(m[3]) / 1000 : null;
    };
    /** 拖动中的精确端点时间：走向导气泡（列表只在松手后更新）。 */
    const tipTime = () =>
      parseTc(document.querySelector('.chapter-track .drag-tip')?.textContent ?? '');
    const timesOf = (index) => {
      const raw = (items()[index]?.querySelector('.times')?.textContent || '').trim();
      const parts = raw.split('→').map((piece) => {
        const m = piece.match(/(\d+):(\d+)\.(\d+)/);
        return m ? Number(m[1]) * 60 + Number(m[2]) + Number(m[3]) / 1000 : null;
      });
      return { raw, start: parts[0] ?? null, end: parts[1] ?? null };
    };

    await waitFor(() => wave() && document.querySelector('video'));
    await sleep(700);
    tab('章节')?.click();
    await sleep(400);

    let stage = 'initial';
    try {
    const initial = {
      items: items().length,
      grips: document.querySelectorAll('.chapter-track .grip').length,
      pointGrips: document.querySelectorAll('.chapter-track .range.point .grip').length,
      times: timesOf(0),
    };

    stage = 'zoom';
    // 放大器：让 1 秒的区间有点宽度，边缘还有可拖的空间
    await clickAt(14.5);
    await zoomAtPlayhead(2);
    const zoomed = { time: timeValue() };

    stage = 'endDrag';
    // 1) 拖右端抓手：30px 改终点，起点不动
    const g0 = gripPoint();
    const seekBefore = timeValue();
    await dragTo(gripEl(), g0, { x: g0.x + 30, y: g0.y }, { id: 21 });
    const afterEnd = timesOf(0);
    const playheadStill = timeValue();

    // 2) ⌘Z 一次退回 15
    await press('z', { code: 'KeyZ', meta: true, wait: 600 });
    const afterEndUndo = timesOf(0);

    stage = 'flagDrag';
    // 3) 拖旗标改起点：单击是跳转，拖过 4px 才是移动起点
    const beforeFlagDrag = timesOf(0);
    const f = { x: flagX(), y: (rangeEl()?.getBoundingClientRect().top ?? 0) + 3 };
    await dragTo(flagEl(), f, { x: f.x + 30, y: f.y }, { id: 22 });
    const afterStart = timesOf(0);

    stage = 'flagClick';
    // 4) ⌘Z 撤销起点，再单击旗标：必须仍然跳转到章节起点
    await press('z', { code: 'KeyZ', meta: true, wait: 600 });
    // 前面把视窗放大到 18× 又 seek 到章节之外，2.5s 窗口里旗标已经不在视野里，
    // 「单击仍跳转」和后面的 pan 阶段就都点不到它。先回全景把现场拉回来——
    // 断言本身没放宽：单击跳转、拖到右缘自动平移仍按原样验证。
    [...document.querySelectorAll('.mini-text')]
      .find((el) => (el.textContent || '').trim() === '全景')
      ?.click();
    await sleep(400);
    const beforeFlagClick = timesOf(0);
    await clickAt(40);
    flagEl()?.click();
    await sleep(500);
    const afterFlagClick = timeValue();

    stage = 'rezoom';
    // 全景复位只是为了让「单击旗标仍跳转」点得到旗标；全景下视窗已经铺满整片
    // （clampStart 无处可移），边缘自动平移必然不动。这里把视窗重新放大回窄窗，
    // 恢复 pan 阶段的前置现场——下面的断言本身没有放宽。
    await clickAt(14.5);
    await zoomAtPlayhead(2);

    stage = 'pan';
    // 5) 拖到右缘外并压住不动：端点要自己继续走（rAF 推进），视窗跟着平移
    const beforePan = timesOf(0);
    const g1 = gripPoint();
    const r = rect();
    const base = { bubbles: true, pointerId: 23, pointerType: 'mouse', button: 0 };
    gripEl().dispatchEvent(
      new PointerEvent('pointerdown', { ...base, buttons: 1, clientX: g1.x, clientY: g1.y }),
    );
    await sleep(70);
    gripEl().dispatchEvent(
      new PointerEvent('pointermove', {
        ...base,
        buttons: 1,
        clientX: r.left + r.width + 80,
        clientY: g1.y,
      }),
    );
    await sleep(140);
    const panEarly = { time: tipTime(), gripX: gripPoint().x, right: rect().left + rect().width };
    await sleep(900);
    const panLate = { time: tipTime(), gripX: gripPoint().x, right: rect().left + rect().width };
    gripEl().dispatchEvent(
      new PointerEvent('pointerup', {
        ...base,
        buttons: 0,
        clientX: r.left + r.width + 80,
        clientY: g1.y,
      }),
    );
    await sleep(700);
    const afterPan = timesOf(0);

    return JSON.stringify({
      initial,
      zoomed,
      seekBefore,
      afterEnd,
      playheadStill,
      afterEndUndo,
      beforeFlagDrag,
      afterStart,
      beforeFlagClick,
      afterFlagClick,
      beforePan,
      panEarly,
      panLate,
      afterPan,
    });
    } catch (err) {
      return JSON.stringify({ error: String(err), stage });
    }
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
    `color=c=0x223344:s=640x360:d=${DURATION}:r=24`,
    '-f',
    'lavfi',
    '-i',
    `sine=frequency=440:duration=${DURATION}`,
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
  fs.writeFileSync(
    seedPath,
    JSON.stringify({ mediaPath: MEDIA, cues: CUES, chapters: CHAPTERS }, null, 2),
    'utf8',
  );
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
    KIKUSUB_SHOT_DELAY: '3000',
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
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 180_000 },
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
const near = (a, b, tol = 0.35) => typeof a === 'number' && Math.abs(a - b) <= tol;

ensureMedia();
const result = run();
if (process.env.KIKUSUB_VERIFY_DEBUG) console.error(JSON.stringify(result, null, 2));

check(
  '种子：一条区间 + 一条时刻点，只有区间有抓手',
  result.initial.items === 2 && result.initial.grips === 1 && result.initial.pointGrips === 0,
  result.initial,
);
check(
  '初始区间是 14 → 15',
  near(result.initial.times.start, 14) && near(result.initial.times.end, 15),
  result.initial.times,
);
check(
  '拖右端抓手把终点改大，起点不动',
  near(result.afterEnd.start, 14) && result.afterEnd.end > 15.05,
  result.afterEnd,
);
check(
  '拖动不移动播放头（改标记 ≠ 擦洗）',
  near(result.playheadStill, result.seekBefore, 0.05),
  { before: result.seekBefore, after: result.playheadStill },
);
check('⌘Z 一次退回原来的 15', near(result.afterEndUndo.end, 15), result.afterEndUndo);
check(
  '拖旗标改起点，终点不变',
  result.afterStart.start > result.beforeFlagDrag.start + 0.05 &&
    near(result.afterStart.end, result.beforeFlagDrag.end, 0.05),
  { before: result.beforeFlagDrag, after: result.afterStart },
);
check(
  '单击旗标仍是跳转（4px 阈值没吃掉单击）',
  near(result.afterFlagClick, result.beforeFlagClick.start, 0.4),
  { clicked: result.afterFlagClick, start: result.beforeFlagClick.start },
);
check(
  '拖到右缘外压住不动：端点自己继续推进（rAF 推进器在工作）',
  result.panLate.time > result.panEarly.time + 0.3 &&
    result.panLate.time > result.beforePan.end + 0.3,
  { before: result.beforePan, early: result.panEarly, late: result.panLate },
);
check(
  '推进时抓手钉在右缘（视窗跟着平移，端点不掉队）',
  Math.abs(result.panLate.gripX - result.panLate.right) <= 14,
  result.panLate,
);
check(
  '松手后保存的是拖动终点，起点不变',
  near(result.afterPan.start, 14) && near(result.afterPan.end, result.panLate.time, 0.3),
  { afterPan: result.afterPan, late: result.panLate },
);

console.log(`\n截图：${SHOT}`);
if (failures.length) {
  console.error(`\n${failures.length} 条失败：${failures.join('、')}`);
  process.exitCode = 1;
} else {
  console.log('全部通过');
}
