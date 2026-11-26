#!/usr/bin/env node
/**
 * 「章节页重做 + 自动命名 + 加入转写选区」无窗口回归（2026-11-25）。
 *
 * 覆盖：
 *   - 页面结构：新建区 + 行内操作，底部不再有大段说明文字；
 *   - 自动命名：时刻点补成区间 → 「章节二」（按位置）；再在前面插一章 → 不重名，顺延成「章节三」；
 *   - 加入转写选区：跳到转写页，两个时间输入框就是这一章的起止；
 *   - 设置里的模板（场景{num}）真的生效，新章节叫「场景四」。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现。断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_chapter_panel.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_chapter_panel.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-chapter-panel');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'panel.mp4');
const SHOT = path.join(BASE, 'chapter-panel.png');
const DURATION = 60;

const CUES = [
  { start: 2.0, end: 6.0, text: '最初の場面です' },
  { start: 20.0, end: 24.0, text: '真ん中の台詞' },
  { start: 40.0, end: 44.0, text: '後半の台詞' },
];

/** 一条已有章节 + 一个待补起点的时刻点（正是用户那套 14:06 / 0:10 的缩小版）。 */
const CHAPTERS = [
  { id: 'ch-1', start: 5, end: 8, title: '开场' },
  { id: 'ch-2', start: 50, end: null, title: '时刻点 00:50' },
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
    const dragSelect = async (from, to) => {
      const a = pointAt(from);
      const b = pointAt(to);
      const base = { bubbles: true, clientY: a.y, pointerId: 9, button: 0, pointerType: 'mouse' };
      wave().dispatchEvent(new PointerEvent('pointerdown', { ...base, clientX: a.x }));
      await sleep(90);
      wave().dispatchEvent(new PointerEvent('pointermove', { ...base, clientX: b.x }));
      await sleep(90);
      wave().dispatchEvent(new PointerEvent('pointerup', { ...base, clientX: b.x }));
      await sleep(320);
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
    const sidebar = (label) =>
      [...document.querySelectorAll('.sb-item')].find((el) =>
        (el.getAttribute('aria-label') || '').startsWith(label),
      );
    const panel = () => document.querySelector('.chapters-panel');
    const items = () => [...document.querySelectorAll('.chapters-panel .item')];
    const itemText = () => items().map((el) => el.textContent.replace(/\s+/g, ' ').trim());
    const button = (root, label) =>
      [...(root?.querySelectorAll('button') ?? [])].find(
        (el) =>
          el.getAttribute('aria-label') === label ||
          (el.textContent || '').replace(/\s+/g, '').includes(label),
      );
    const openChapters = async () => {
      tab('章节')?.click();
      await waitFor(() => panel());
      await sleep(300);
    };
    const addRangeChapter = async (from, to) => {
      await dragSelect(from, to);
      button(panel(), '选区章节')?.click();
      await sleep(600);
    };
    const toastText = () => document.querySelector('.toast')?.textContent.trim() ?? '';

    await waitFor(() => wave() && document.querySelector('video'));
    await sleep(700);
    await openChapters();

    const layout = {
      hint: document.querySelectorAll('.chapters-panel .hint').length,
      compose: Boolean(document.querySelector('.chapters-panel .compose')),
      composeButtons: [...document.querySelectorAll('.chapters-panel .compose button')].map((el) =>
        (el.textContent || '').replace(/\s+/g, ''),
      ),
    };
    const initialItems = itemText();

    // 1) 时刻点补起点 → 自动命名「章节二」（前面已经有一条区间章节）
    button(panel(), '补起点')?.click();
    await sleep(300);
    await clickAt(30);
    await press('i', { code: 'KeyI' });
    button(panel(), '保存章节')?.click();
    await sleep(700);
    const afterDraft = { items: itemText(), toast: toastText() };

    // 2) 加入转写选区：跳到转写页，时间框 = 这一章
    const draftItem = items().find((el) => el.textContent.includes('章节二'));
    button(draftItem, '加入转写选区')?.click();
    await sleep(700);
    const startInput = document.querySelector('input[aria-label="起始时间"]');
    const endInput = document.querySelector('input[aria-label="结束时间"]');
    const transcribe = {
      view: Boolean(startInput && endInput && document.querySelector('.pane')),
      start: startInput?.value ?? '',
      end: endInput?.value ?? '',
      toast: toastText(),
    };

    // 3) 回核对台，在中间插一章：位置算出「章节二」但已被占用 → 顺延「章节三」
    sidebar('核对台')?.click();
    await waitFor(() => wave());
    await sleep(600);
    await openChapters();
    await addRangeChapter(20, 25);
    const afterInsert = itemText();

    // 4) 设置里把模板改成「场景{num}」，再新建一章 → 「场景四」
    sidebar('设置')?.click();
    await sleep(700);
    document.querySelector('#set-tab-appearance')?.click();
    await sleep(500);
    const nameInput = document.querySelector('.name-input');
    if (nameInput) {
      nameInput.value = '场景{num}';
      nameInput.dispatchEvent(new Event('input', { bubbles: true }));
      await sleep(150);
    }
    const previewText = document
      .querySelector('.name-input')
      ?.closest('.set-row')
      ?.querySelector('.set-row-desc')?.textContent;
    [...document.querySelectorAll('.settings button')]
      .find((el) => (el.textContent || '').trim() === '保存')
      ?.click();
    await sleep(900);
    const savedToast = toastText();

    sidebar('核对台')?.click();
    await waitFor(() => wave());
    await sleep(700);
    await openChapters();
    await addRangeChapter(55, 58);
    const afterTemplate = itemText();

    return JSON.stringify({
      layout,
      initialItems,
      afterDraft,
      transcribe,
      afterInsert,
      previewText,
      savedToast,
      afterTemplate,
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
  // 每次从干净设置开始：这一轮会把「章节命名模板」改成 场景{num}，
  // 不隔离的话上一轮的模板会漏到下一次运行（以前踩过：第二次跑名字直接是「场景二」）。
  fs.rmSync(path.join(BASE, 'settings.json'), { force: true });

  const extra = (process.env.KIKUSUB_SHOT_ELECTRON_ARGS || '').split(/\s+/).filter(Boolean);
  const env = {
    ...process.env,
    KIKUSUB_ALLOW_MULTIPLE: '1',
    KIKUSUB_WIN_SIZE: '1360x838',
    KIKUSUB_SHOT_DELAY: '3000',
    KIKUSUB_OUTPUT_DIR: OUT,
    KIKUSUB_DATA_DIR: path.join(BASE, 'data'),
    KIKUSUB_PREFERENCES_PATH: path.join(BASE, 'prefs.json'),
    KIKUSUB_SETTINGS_PATH: path.join(BASE, 'settings.json'),
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

ensureMedia();
const result = run();

check(
  '布局：新建区在，底部没有大段说明文字',
  result.layout.compose === true && result.layout.hint === 0,
  result.layout,
);
check(
  '新建区两枚动作：时刻点 / 选区章节',
  result.layout.composeButtons.some((text) => text.includes('时刻点')) &&
    result.layout.composeButtons.some((text) => text.includes('选区章节')),
  result.layout.composeButtons,
);
check(
  '种子：一条章节 + 一个时刻点',
  result.initialItems.length === 2 && result.initialItems[1].includes('时刻点'),
  result.initialItems,
);
check(
  '补起点后自动命名「章节二」（按片中位置）',
  result.afterDraft.items.some((text) => text.includes('章节二')),
  result.afterDraft,
);
check(
  '加入转写选区：跳到转写页，时间就是这一章',
  result.transcribe.view === true &&
    result.transcribe.start.startsWith('00:30') &&
    result.transcribe.end.startsWith('00:50'),
  result.transcribe,
);
check(
  '中间插一章不与已有名字重复：顺延「章节三」',
  result.afterInsert.some((text) => text.includes('章节三')) &&
    !result.afterInsert.some((text) => text.includes('章节二 00:20')),
  result.afterInsert,
);
check(
  '设置模板改「场景{num}」并保存',
  String(result.previewText || '').includes('场景三') && result.savedToast.includes('设置已保存'),
  { preview: result.previewText, toast: result.savedToast },
);
check(
  '新模板生效：下一章叫「场景四」',
  result.afterTemplate.some((text) => text.includes('场景四')),
  result.afterTemplate,
);

console.log(`\n截图：${SHOT}`);
if (failures.length) {
  console.error(`\n${failures.length} 条失败：${failures.join('、')}`);
  process.exitCode = 1;
} else {
  console.log('全部通过');
}
