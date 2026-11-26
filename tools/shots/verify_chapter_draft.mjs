#!/usr/bin/env node
/**
 * 「章节草稿：把时刻点补成区间」无窗口回归（2026-11-25）。
 *
 * 覆盖：
 *   - 章节面板「补起点」：把时刻点当章末 → 缩放到起点 → 按 I → 保存；
 *   - 反向「补终点」：把时刻点当章首 → 按 O → 保存；
 *   - 草稿期间时间轴上出现虚线预览色带；
 *   - 端点越界（终点早于起点）只提示、草稿不动；
 *   - Esc 撤草稿：列表不变、不产生历史；
 *   - 保存 = 一步历史，⌘Z 回到时刻点。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现。断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_chapter_draft.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_chapter_draft.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-chapter-draft');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'draft.mp4');
const SHOT = path.join(BASE, 'chapter-draft.png');
const DURATION = 60;

const CUES = [
  { start: 2.0, end: 6.0, text: '最初の場面です' },
  { start: 20.0, end: 24.0, text: '真ん中の台詞' },
  { start: 40.0, end: 44.0, text: '後半の台詞' },
];

/** 「场景结束在 50 秒、开始大约在 10 秒」——正是用户那套 14:06 / 0:10 的缩小版。 */
const CHAPTERS = [{ id: 'ch-1', start: 50, end: null, title: '场景 1 结束' }];

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
      await sleep(240);
    };
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
      await sleep(opts.wait ?? 260);
    };
    const tab = (label) =>
      [...document.querySelectorAll('.insp-tab')].find((el) =>
        (el.textContent || '').trim().startsWith(label),
      );
    const items = () => [...document.querySelectorAll('.chapters-panel .item')];
    const itemText = () => items().map((el) => el.textContent.replace(/\s+/g, ' ').trim());
    const pointCount = () => items().filter((el) => el.classList.contains('point')).length;
    const rangeCount = () => items().filter((el) => !el.classList.contains('point')).length;
    const ranges = () => [...document.querySelectorAll('.chapter-track .range')];
    const draftEl = () => document.querySelector('.chapters-panel .draft');
    const draftSlots = () =>
      [...document.querySelectorAll('.chapters-panel .draft-slot .v')].map((el) =>
        (el.textContent || '').trim(),
      );
    const bandCount = () => document.querySelectorAll('.chapter-track .draft-band').length;
    const toastText = () => document.querySelector('.toast')?.textContent.trim() ?? '';
    const opButton = (label) =>
      [...document.querySelectorAll('.chapters-panel .item button')].find(
        (el) => el.getAttribute('aria-label') === label,
      );
    const buttonByText = (text) =>
      [...document.querySelectorAll('.chapters-panel .draft button')].find((el) =>
        (el.textContent || '').includes(text),
      );
    const tc = (text) => {
      const m = (text || '').match(/(\d+):(\d+)\.(\d+)/);
      return m ? Number(m[1]) * 60 + Number(m[2]) + Number(m[3]) / 1000 : null;
    };
    const timesOf = (index) => {
      const nodes = items()[index]?.querySelectorAll('.times') ?? [];
      const raw = (nodes[0]?.textContent || '').trim();
      const parts = raw.split('→').map((piece) => tc(piece));
      return { raw, start: parts[0] ?? null, end: parts[1] ?? null };
    };

    await waitFor(() => wave() && document.querySelector('video'));
    await sleep(700);
    tab('章节')?.click();
    await sleep(400);

    const initial = { items: itemText(), points: pointCount(), ranges: rangeCount() };

    // 1) 没有草稿时按 I：只提示，不凭空建标记
    await press('i', { code: 'KeyI' });
    const noDraftToast = toastText();
    const afterNoDraft = items().length;

    // 2) 补起点：时刻点当章末，起点随播放头
    opButton('补起点')?.click();
    await sleep(300);
    const draftOpened = {
      exists: Boolean(draftEl()),
      slots: draftSlots(),
      band: bandCount(),
      item: timesOf(0),
    };

    await clickAt(10);
    await press('i', { code: 'KeyI' });
    const afterStart = { slots: draftSlots(), band: bandCount() };

    buttonByText('保存章节')?.click();
    await sleep(600);
    const saved = {
      items: itemText(),
      points: pointCount(),
      ranges: rangeCount(),
      track: ranges().length,
      times: timesOf(0),
      draft: Boolean(draftEl()),
      toast: toastText(),
    };

    // 3) ⌘Z 回到时刻点
    await press('z', { code: 'KeyZ', meta: true, wait: 500 });
    const undone = { items: itemText(), points: pointCount(), ranges: rangeCount(), times: timesOf(0) };

    // 4) 反向：补终点
    opButton('补终点')?.click();
    await sleep(300);
    const reverseOpened = { slots: draftSlots() };
    await clickAt(55);
    await press('o', { code: 'KeyO' });
    const reverseSet = { slots: draftSlots() };
    buttonByText('保存章节')?.click();
    await sleep(600);
    const reverseSaved = { times: timesOf(0), toast: toastText(), ranges: rangeCount() };

    // 5) 端点越界：终点早于起点 → 只提示，草稿不动
    await press('z', { code: 'KeyZ', meta: true, wait: 500 });
    opButton('补终点')?.click();
    await sleep(300);
    await clickAt(49);
    await press('o', { code: 'KeyO' });
    const rejected = { slots: draftSlots(), toast: toastText() };

    // 6) Esc 撤草稿：列表不变、色带消失
    await press('Escape', { code: 'Escape' });
    const cancelled = {
      draft: Boolean(draftEl()),
      band: bandCount(),
      items: itemText(),
      points: pointCount(),
    };

    return JSON.stringify({
      initial,
      noDraftToast,
      afterNoDraft,
      draftOpened,
      afterStart,
      saved,
      undone,
      reverseOpened,
      reverseSet,
      reverseSaved,
      rejected,
      cancelled,
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

const near = (a, b, tol = 0.25) => typeof a === 'number' && Math.abs(a - b) <= tol;
/** `mm:ss.mmm` → 秒；「待定」等非时间文本返回 null。 */
const tc = (text) => {
  const m = (text || '').match(/(\d+):(\d+)\.(\d+)/);
  return m ? Number(m[1]) * 60 + Number(m[2]) + Number(m[3]) / 1000 : null;
};

ensureMedia();
const result = run();

check('初始只有一条时刻点', result.initial.points === 1 && result.initial.ranges === 0, result.initial);
check(
  '没有草稿时按 I 只提示，不新建标记',
  result.noDraftToast.includes('草稿') && result.afterNoDraft === 1,
  { toast: result.noDraftToast, count: result.afterNoDraft },
);
check(
  '补起点：草稿出现、起点待定、终点是那个时刻点',
  result.draftOpened.exists &&
    result.draftOpened.slots[0] === '待定' &&
    near(tc(result.draftOpened.slots[1]), 50),
  result.draftOpened,
);
check('草稿期间时间轴出现预览色带', result.draftOpened.band === 1, result.draftOpened);
check(
  '按 I 把播放头定为起点',
  near(tc(result.afterStart.slots[0]), 10, 0.3) && near(tc(result.afterStart.slots[1]), 50),
  result.afterStart,
);
check(
  '保存后成为区间章节（10 → 50）',
  result.saved.ranges === 1 &&
    near(result.saved.times.start, 10, 0.3) &&
    near(result.saved.times.end, 50),
  result.saved,
);
check('保存后草稿关闭', result.saved.draft === false, result.saved);
check('时间轴出现区间色条', result.saved.track === 1, result.saved);
check(
  '⌘Z 一次退回时刻点',
  result.undone.points === 1 && result.undone.ranges === 0 && result.undone.times.end === null,
  result.undone,
);
check(
  '反向：补终点把时刻点当章首',
  near(tc(result.reverseOpened.slots[0]), 50) && result.reverseOpened.slots[1] === '待定',
  result.reverseOpened,
);
check(
  '按 O 把播放头定为终点',
  near(tc(result.reverseSet.slots[1]), 55, 0.3),
  result.reverseSet,
);
check(
  '反向保存成 50 → 55',
  result.reverseSaved.ranges === 1 &&
    near(result.reverseSaved.times.start, 50) &&
    near(result.reverseSaved.times.end, 55, 0.3),
  result.reverseSaved,
);
check(
  '终点早于起点只提示、草稿不动',
  result.rejected.slots[1] === '待定' && result.rejected.toast.includes('至少晚 0.2 秒'),
  result.rejected,
);
check(
  'Esc 撤掉草稿：色带消失、列表不变',
  result.cancelled.draft === false &&
    result.cancelled.band === 0 &&
    result.cancelled.points === 1 &&
    result.cancelled.items.length === 1,
  result.cancelled,
);

console.log(`\n截图：${SHOT}`);
if (failures.length) {
  console.error(`\n${failures.length} 条失败：${failures.join('、')}`);
  process.exitCode = 1;
} else {
  console.log('全部通过');
}
