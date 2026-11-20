#!/usr/bin/env node
/**
 * 「复制 / 粘贴字幕」无窗口回归（2026-11-17）。
 *
 * 用户场景：气声句子（吸って / 入って）很轻，局部转写经常空结果；偶尔转对一条，
 * 就想把它原样搬到第二个、第三个播放头位置。这个脚本在**真实界面**里断言：
 *
 *   1. 选中第 2 条 → 检查器复制按钮 → 出现字幕剪贴板条，内容是原文 + 时长；
 *   2. 点波形跳到 4.0s → 粘贴 → 4 条字幕，新句 04.000→04.600，文本一致；
 *   3. 粘贴后选中新句，但播放头停在 4.0s、缩放值不变；
 *   4. 再跳到 5.2s 粘一次 → 5 条；工具栏「撤回」标题带粘贴时间；
 *   5. ⌘Z 一次回到 4 条（说明只压了一步历史）。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现，跑完自己退出。断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_cue_clipboard.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_cue_clipboard.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-cue-clipboard');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');
const SHOT = path.join(BASE, 'cue-clipboard.png');

/** 8 秒片；第 2 条就是要复制的气声句，4.0 / 5.2 是两处空白目标。 */
const CUES = [
  { start: 0.5, end: 1.2, text: '深呼吸して' },
  { start: 2.0, end: 2.6, text: '吸って' },
  { start: 6.5, end: 7.2, text: 'もう一回' },
];

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const waitFor = async (fn, ms = 8000) => {
      const t0 = Date.now();
      while (Date.now() - t0 < ms) {
        const value = fn();
        if (value) return value;
        await sleep(80);
      }
      return null;
    };
    const rows = () => [...document.querySelectorAll('.row')];
    const rowInfo = () =>
      rows().map((row) => ({
        i: row.dataset.i,
        start: row.querySelectorAll('.c-t')[0]?.textContent.trim() ?? '',
        end: row.querySelectorAll('.c-t')[1]?.textContent.trim() ?? '',
        dur: row.querySelector('.c-dur')?.textContent.trim() ?? '',
        text: row.querySelector('.c-text')?.textContent.trim() ?? '',
        sel: row.classList.contains('row-sel'),
      }));
    const play = () => document.querySelector('.tp-time')?.textContent.trim() ?? '';
    const toast = () => document.querySelector('.toast')?.textContent.trim() ?? '';
    const wave = document.querySelector('.wave-wrap');
    const seekTo = async (t) => {
      const rect = wave.getBoundingClientRect();
      const x = rect.left + (t / 8) * rect.width;
      const y = rect.top + 40;
      for (const type of ['pointerdown', 'pointerup']) {
        wave.dispatchEvent(
          new PointerEvent(type, {
            bubbles: true,
            clientX: x,
            clientY: y,
            pointerId: 1,
            button: 0,
            pointerType: 'mouse',
          }),
        );
      }
      await sleep(320);
    };

    await waitFor(() => document.querySelector('.row[data-i="1"]'));
    const zoomBefore = document.querySelector('.zoom-slider')?.value ?? '';
    const press = (key, code) =>
      window.dispatchEvent(
        new KeyboardEvent('keydown', {
          key,
          code,
          metaKey: true,
          shiftKey: true,
          bubbles: true,
          cancelable: true,
        }),
      );
    const undoButtonNow = () =>
      [...document.querySelectorAll('button')].find((button) =>
        (button.title || '').startsWith('撤回：'),
      );

    // 0) 快捷键路径：文本框里改到一半（不 blur），按 ⌘⇧C 必须先 commit 再复制
    document.querySelector('.row[data-i="1"]').click();
    await sleep(260);
    const draftEl = document.querySelector('.inspector .cue-text');
    draftEl.focus();
    draftEl.value = '吸って!';
    draftEl.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(80);
    press('C', 'KeyC');
    await sleep(900);
    const shortcutClip =
      document.querySelector('.clip-strip')?.textContent.replace(/\s+/g, ' ').trim() ?? '';
    const shortcutRow =
      document.querySelector('.row[data-i="1"] .c-text')?.textContent.trim() ?? '';
    undoButtonNow()?.click();
    await sleep(600);
    const restoredRow =
      document.querySelector('.row[data-i="1"] .c-text')?.textContent.trim() ?? '';

    // 0b) 快捷键粘贴：⌘⇧V 也走同一条插入路径，粘完仍可一次撤回
    await seekTo(3.0);
    press('V', 'KeyV');
    await waitFor(() => rows().length === 4);
    await sleep(500);
    const shortcutPasted = rowInfo().find((row) => row.start === '00:03.000');
    const rowsAfterShortcutPaste = rows().length;
    undoButtonNow()?.click();
    await waitFor(() => rows().length === 3);
    await sleep(320);
    const rowsAfterShortcutUndo = rows().length;

    // 1) 选中第 2 条，复制
    document.querySelector('.row[data-i="1"]').click();
    await sleep(260);
    document.querySelector('[data-copy-cue]').click();
    await waitFor(() => document.querySelector('.clip-strip'));
    await sleep(260);
    const clip = document
      .querySelector('.clip-strip')
      ?.textContent.replace(/\s+/g, ' ')
      .trim() ?? '';
    const beforeRows = rowInfo();
    const playBefore = play();

    // 2) 播放头到 4.0s，粘贴
    await seekTo(4.0);
    const playAt4 = play();
    document.querySelector('[data-paste-cue]').click();
    await waitFor(() => rows().length === 4);
    await sleep(420);
    const afterFirst = {
      rows: rowInfo(),
      play: play(),
      toast: toast(),
    };

    // 3) 播放头到 5.2s，再粘一次
    await seekTo(5.2);
    document.querySelector('[data-paste-cue]').click();
    await waitFor(() => rows().length === 5);
    await sleep(420);
    const undoButton = [...document.querySelectorAll('button')].find((button) =>
      (button.title || '').startsWith('撤回：'),
    );
    const afterSecond = {
      rows: rowInfo(),
      undoTitle: undoButton?.title ?? '',
      play: play(),
    };

    // 4) 工具栏撤回一次：两次粘贴里最近的一步只应退掉 5.2s 那条
    undoButton?.click();
    await waitFor(() => rows().length === 4);
    await sleep(360);
    const afterUndo = { rows: rowInfo(), toast: toast() };

    // 截图停在「粘贴出的 4.0s 那条被选中」的状态
    document.querySelector('.row[data-i="2"]')?.click();
    await sleep(360);
    const zoomAfter = document.querySelector('.zoom-slider')?.value ?? '';

    return JSON.stringify({
      shortcutClip,
      shortcutRow,
      restoredRow,
      shortcutPasted,
      rowsAfterShortcutPaste,
      rowsAfterShortcutUndo,
      clip,
      beforeRows,
      playBefore,
      playAt4,
      afterFirst,
      afterSecond,
      afterUndo,
      zoomBefore,
      zoomAfter,
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
      [
        'electron',
        '.',
        `--user-data-dir=${profile}`,
        `--screenshot=${SHOT}`,
        ...extra,
      ],
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

const pasted = result.afterFirst?.rows?.find((row) => row.i === '2');
const second = result.afterSecond?.rows?.find((row) => row.i === '3');

check(
  '快捷键复制前先提交草稿（行文本已更新）',
  result.shortcutRow === '吸って!',
  result.shortcutRow,
);
check('快捷键复制到的是提交后的文本', result.shortcutClip.includes('吸って!'), result.shortcutClip);
check('撤回草稿提交后恢复原文本', result.restoredRow === '吸って', result.restoredRow);
check(
  '快捷键粘贴生成同文同时间的新句',
  result.shortcutPasted?.text === '吸って!' && result.shortcutPasted?.start === '00:03.000',
  result.shortcutPasted,
);
check('快捷键粘贴后是 4 条', result.rowsAfterShortcutPaste === 4, result.rowsAfterShortcutPaste);
check('快捷键粘贴可一次撤回', result.rowsAfterShortcutUndo === 3, result.rowsAfterShortcutUndo);
check('复制后出现剪贴板条', result.clip.includes('吸って'), result.clip);
check('剪贴板带时长', result.clip.includes('0.60s'), result.clip);
check('复制不改变原有 3 条', result.beforeRows?.length === 3, result.beforeRows);
check('粘贴后是 4 条', result.afterFirst?.rows?.length === 4, result.afterFirst?.rows);
check(
  '新句文本与时间正确',
  pasted?.text === '吸って' && pasted?.start === '00:04.000' && pasted?.end === '00:04.600',
  pasted,
);
check('拼接后第 3 条被选中', pasted?.sel === true, pasted);
check('粘贴不移动播放头', result.afterFirst?.play === result.playAt4, {
  before: result.playAt4,
  after: result.afterFirst?.play,
});
check('第二次粘贴后是 5 条', result.afterSecond?.rows?.length === 5, result.afterSecond?.rows);
check('5.2s 的新句起点正确', second?.start === '00:05.200', second);
check(
  '撤回标题显示粘贴时间',
  result.afterSecond?.undoTitle?.includes('粘贴字幕到 00:05.200'),
  result.afterSecond?.undoTitle,
);
check('一次撤回只退掉最近一条（回到 4 条）', result.afterUndo?.rows?.length === 4, result.afterUndo?.rows);
check('粘贴不改变缩放', result.zoomBefore === result.zoomAfter, {
  before: result.zoomBefore,
  after: result.zoomAfter,
});

console.log(`\n检查器截图：${SHOT}`);
if (failures.length) {
  console.error(`\n${failures.length} 项失败：${failures.join(' / ')}`);
  process.exit(1);
}
console.log('全部通过。');
