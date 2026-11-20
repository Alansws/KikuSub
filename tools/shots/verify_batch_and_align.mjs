#!/usr/bin/env node
/**
 * 「手动分批 + 译文时间轴对齐 + 断句重排局部替换」无窗口回归（2026-11-20）。
 *
 * 用户场景：
 *   1. 润色页在章节范围内手动切 1–2 / 3–4 两批，复制提示词只含本批，粘贴 3 条到
 *      2 条的批次会被拒绝（润色仍严格 1:1）；
 *   2. 翻译页默认允许带时间轴的译文条数不同：4 条原文贴 3 条，其中一条跨 #1/#2，
 *      第三条落在范围外 → 合并覆盖 / 空缺 / 范围外都要高亮；应用只写本批；
 *      勾上「严格要求条数一致」后同样的粘贴回到 422；
 *   3. 断句重排页接入同一处理范围 + 批次；粘贴 3 条替换章节内 4 条，范围外 #5/#6
 *      不动，尾部译文跟着平移（toast 明确回报），总条数 6 → 5。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），桌面上
 * 不出现。断言失败退出码非 0。
 *
 * 用法：
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_batch_and_align.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-batch-align');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'batch-align.mp4');
const SHOT = path.join(BASE, 'batch-align.png');
const DURATION = 30;
const CUES = [
  { start: 1.0, end: 2.0, text: 'おはよう' },
  { start: 4.0, end: 5.0, text: '今日は雨だ' },
  { start: 6.0, end: 7.0, text: '行ってきます' },
  { start: 9.0, end: 10.0, text: '気をつけて' },
  { start: 12.0, end: 13.0, text: 'またね' },
  { start: 15.0, end: 16.0, text: 'さようなら' },
];
const CHAPTERS = [{ id: 'scene-1', start: 0.5, end: 10.5, title: '章节1' }];

const POLISH_BATCH_SRT = `1
00:00:06,000 --> 00:00:07,000
路上小心

2
00:00:09,000 --> 00:00:10,000
小心点
`;
const POLISH_MISMATCH_SRT = `1
00:00:06,000 --> 00:00:07,000
路上小心

2
00:00:09,000 --> 00:00:10,000
小心点

3
00:00:12,000 --> 00:00:13,000
回头见
`;
const TRANSLATE_ALIGN_SRT = `1
00:00:00,800 --> 00:00:05,000
早上好，今天下雨

2
00:00:05,900 --> 00:00:07,100
路上小心

3
00:00:20,000 --> 00:00:21,000
跑到范围外
`;
const RESHAPE_SRT = `1
00:00:01,000 --> 00:00:02,000
早上好

2
00:00:04,000 --> 00:00:05,000
今天下雨

3
00:00:20,000 --> 00:00:21,000
跑出本段
`;

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
    const sidebar = (label) =>
      [...document.querySelectorAll('.sb-item')].find((el) =>
        (el.getAttribute('aria-label') || '').startsWith(label),
      );
    const buttonByText = (root, text) =>
      [...(root?.querySelectorAll('button') ?? [])].find((el) => (el.textContent || '').includes(text));
    const text = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim();
    const fill = (el, value) => {
      el.value = value;
      el.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const commitInput = async (el) => {
      el.dispatchEvent(new FocusEvent('blur'));
      await sleep(400);
    };
    const toastText = () => text(document.querySelector('.toast'));
    const recordToasts = () => {
      const list = [];
      const timer = setInterval(() => {
        const current = toastText();
        if (current && list[list.length - 1] !== current) list.push(current);
      }, 70);
      return { list, stop: () => clearInterval(timer) };
    };
    const batchInputs = (root) => [...(root?.querySelectorAll('.batch-no') ?? [])];
    const setPicker = async (root, valueText) => {
      const sel = root.querySelector('.clip-select');
      const option = [...sel.options].find((item) => (item.textContent || '').includes(valueText));
      sel.value = option.value;
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      await sleep(900);
    };

    try {
      await waitFor(() => document.querySelector('.app-shell, .sidebar, .sb-item'));
      await sleep(900);

      // ------------------------------------------------------------------ 润色
      sidebar('润色')?.click();
      await waitFor(() => document.querySelector('.aiw-page'));
      await sleep(1000);
      await setPicker(document.querySelector('.aiw-title-row'), '章节1');
      await sleep(500);
      const polishInitialRows = document.querySelectorAll('.aiw-row').length;
      const initialBatch = batchInputs(document.querySelector('.aiw-subbar')).map((el) => el.value);

      // 手动批 1–2
      let inputs = batchInputs(document.querySelector('.aiw-subbar'));
      fill(inputs[0], '1');
      fill(inputs[1], '2');
      await commitInput(inputs[1]);
      const polishTwoRows = document.querySelectorAll('.aiw-row').length;
      const batchText = text(document.querySelector('.aiw-subbar .cue-batch'));

      // 下一批 → 3–4
      const nextButton = buttonByText(document.querySelector('.aiw-subbar .cue-batch'), '下一批');
      nextButton?.click();
      await sleep(700);
      inputs = batchInputs(document.querySelector('.aiw-subbar'));
      const nextBatch = inputs.map((el) => el.value);
      const polishNextRows = document.querySelectorAll('.aiw-row').length;
      const copiedIndexes = [...document.querySelectorAll('.aiw-row .aiw-idx')].map((el) => text(el));

      // 复制提示词 → 只含本批 2 条
      buttonByText(document.querySelector('.aiw-launch'), '复制本批提示词')?.click();
      await sleep(900);
      const copyToast = toastText();
      const pasteBox = await waitFor(() => document.querySelector('.polish .paste-box'));
      const copyCount = pasteBox ? 1 : 0;

      // 粘回 2 条 → 成功
      fill(pasteBox, ${JSON.stringify(POLISH_BATCH_SRT)});
      await sleep(200);
      buttonByText(document.querySelector('.polish .paste'), '解析并回填本批')?.click();
      await sleep(1400);
      const polishPasteToast = toastText();
      const polishPasteRows = document.querySelectorAll('.aiw-row').length;

      // 再粘 3 条到 2 条批次 → 润色仍拒绝
      buttonByText(document.querySelector('.aiw-launch'), '粘贴回复')?.click();
      await sleep(500);
      const pasteBox2 = document.querySelector('.polish .paste-box');
      fill(pasteBox2, ${JSON.stringify(POLISH_MISMATCH_SRT)});
      await sleep(200);
      buttonByText(document.querySelector('.polish .paste'), '解析并回填本批')?.click();
      await sleep(1200);
      const polishMismatchToast = toastText();

      // ------------------------------------------------------------------ 翻译
      sidebar('翻译')?.click();
      await waitFor(() => document.querySelector('.ai'));
      await sleep(1000);
      // 批次从润色页带过来（3–4），回到整段做 1–4 的对齐测试
      if (document.querySelector('.ai .batch-reset')) {
        document.querySelector('.ai .batch-reset').click();
        await sleep(700);
      }
      buttonByText(document.querySelector('.ai'), '粘贴结果')?.click();
      await sleep(500);
      const strictCheckbox = document.querySelector('.ai .paste .chk input');
      const strictDefault = strictCheckbox ? strictCheckbox.checked : null;
      fill(document.querySelector('.ai .paste-box'), ${JSON.stringify(TRANSLATE_ALIGN_SRT)});
      await sleep(200);
      buttonByText(document.querySelector('.ai .paste'), '解析成建议')?.click();
      await sleep(1800);
      const translateRows = document.querySelectorAll('.ai .list .row').length;
      const translateToast = toastText();
      const mergedTags = document.querySelectorAll('.ai .align-tag.merged').length;
      const missingTags = document.querySelectorAll('.ai .align-tag.missing').length;
      const alignBanner = text(document.querySelector('.ai .note.warn'));
      const mergedEmpty = text(document.querySelector('.ai .align-empty'));

      // 应用（只写本批 1–4）
      buttonByText(document.querySelector('.ai .head'), '应用')?.click();
      await sleep(1400);
      const applyToast = toastText();

      // 严格条数开关：同一份 3 条贴回 4 条批次 → 422
      buttonByText(document.querySelector('.ai .head'), '粘贴结果')?.click();
      await sleep(500);
      const strictBox = document.querySelector('.ai .paste .chk input');
      if (strictBox && !strictBox.checked) {
        strictBox.click();
        await sleep(200);
      }
      fill(document.querySelector('.ai .paste-box'), ${JSON.stringify(TRANSLATE_ALIGN_SRT)});
      await sleep(200);
      buttonByText(document.querySelector('.ai .paste'), '解析成建议')?.click();
      await sleep(1500);
      const strictToast = toastText();

      // ------------------------------------------------------------------ 断句重排
      sidebar('断句重排')?.click();
      await waitFor(() => document.querySelector('.reshape'));
      await sleep(1200);
      const reshapeHasPicker = Boolean(document.querySelector('.reshape .aiw-title-row .clip-scope'));
      const reshapeHasBatch = Boolean(document.querySelector('.reshape .aiw-title-row .cue-batch'));
      const reshapeRangeLabel = text(document.querySelector('.reshape .aiw-card .aiw-card-sub'));

      const reshapeBox = await waitFor(() =>
        document.querySelector('.reshape textarea[aria-label="粘贴重排后的 SRT"]'),
      );
      fill(reshapeBox, ${JSON.stringify(RESHAPE_SRT)});
      await sleep(200);
      buttonByText(document.querySelector('.reshape'), '解析并预检')?.click();
      await sleep(1800);
      const rangeWarn = text(document.querySelector('.reshape .range-warn'));
      const warningVisible = Boolean(document.querySelector('.reshape .range-warn'));

      const toastRecorder = recordToasts();
      buttonByText(document.querySelector('.reshape'), '覆盖第 1–4 条')?.click();
      await sleep(1800);
      toastRecorder.stop();
      const reshapeToasts = toastRecorder.list;
      const reshapeApplyToast = reshapeToasts.join(' | ');
      const reshapeCoverToast = reshapeToasts.find((item) => item.includes('已覆盖第 1–4 条')) || '';
      const reshapeHeadCount = text(document.querySelector('.reshape .aiw-head-end'));
      const reshapeRowsAfter = document.querySelectorAll('.reshape .preview-row').length;

      return JSON.stringify({
        polishInitialRows,
        initialBatch,
        polishTwoRows,
        batchText,
        nextBatch,
        polishNextRows,
        copiedIndexes,
        copyToast,
        copyCount,
        polishPasteToast,
        polishPasteRows,
        polishMismatchToast,
        strictDefault,
        translateRows,
        translateToast,
        mergedTags,
        missingTags,
        alignBanner,
        mergedEmpty,
        applyToast,
        strictToast,
        reshapeHasPicker,
        reshapeHasBatch,
        reshapeRangeLabel,
        warningVisible,
        rangeWarn,
        reshapeApplyToast,
        reshapeCoverToast,
        reshapeHeadCount,
        reshapeRowsAfter,
      });
    } catch (err) {
      return JSON.stringify({ error: String((err && err.message) || err), stack: String((err && err.stack) || '') });
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
    `color=c=0x2a3b4a:s=640x360:d=${DURATION}:r=24`,
    '-f',
    'lavfi',
    '-i',
    `sine=frequency=360:duration=${DURATION}`,
    '-g',
    '12',
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
    console.error(String(error.stderr ?? '').slice(-1600));
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
if (result.error) {
  console.error(result.stack || result.error);
  process.exit(1);
}

// ---- 润色：手动批次 ----
check('润色页默认批次覆盖整个章节 4 条', result.polishInitialRows === 4 && result.initialBatch.join('~') === '1~4', result);
check('手动改成 1–2 后表格只剩 2 行', result.polishTwoRows === 2, result);
check('批次条显示当前区间与命中数', /1–2/.test(result.batchText) && /2\/6/.test(result.batchText), result.batchText);
check('点「下一批」切到 3–4', result.nextBatch.join('~') === '3~4' && result.polishNextRows === 2, result);
check('表格行号就是本批 3 / 4', result.copiedIndexes.join(',') === '#3,#4', result.copiedIndexes);
check('复制提示词只含本批 2 条', /本批第 3–4 条/.test(result.copyToast) && /2 条字幕/.test(result.copyToast), result.copyToast);
check('复制后自动展开粘贴框', result.copyCount === 1, result);
check('粘回 2 条成功且表格仍是本批 2 行', /已解析 2 条修改/.test(result.polishPasteToast) && result.polishPasteRows === 2, result);
check('润色粘回 3 条仍被条数强校验拦住', /条数对不上/.test(result.polishMismatchToast), result.polishMismatchToast);

// ---- 翻译：时间轴对齐 ----
check('翻译页严格条数开关默认关闭', result.strictDefault === false, result);
check('4 条原文贴 3 条不再整批拒绝', /已解析 4 条译文/.test(result.translateToast) && /粘贴 3 条/.test(result.translateToast), result.translateToast);
check('翻译表格仍是本批 4 行', result.translateRows === 4, result);
check('合并覆盖行有明显状态标记', result.mergedTags >= 1, result.mergedTags);
check('未匹配原句有明显状态标记', result.missingTags >= 1, result.missingTags);
check('对齐横幅给出合并 / 空缺 / 范围外说明', /合并覆盖/.test(result.alignBanner) && /范围外/.test(result.alignBanner), result.alignBanner);
check('被合并覆盖的槽位显示空位说明', /合并覆盖/.test(result.mergedEmpty), result.mergedEmpty);
check('应用只写本批 1–4 条译文', /局部应用第 1–4 条/.test(result.applyToast), result.applyToast);
check('打开严格条数后同样的粘贴被拒绝', /条数对不上/.test(result.strictToast), result.strictToast);

// ---- 断句重排：处理范围 + 局部替换 ----
check('断句重排页有统一的处理范围选择器', result.reshapeHasPicker === true, result);
check('断句重排页有本次批次控件', result.reshapeHasBatch === true, result);
check('局部范围显示「第 1–4 条 · 全片 6 条」', /第 1–4 条/.test(result.reshapeRangeLabel) && /全片 6 条/.test(result.reshapeRangeLabel), result.reshapeRangeLabel);
check('新稿时间戳超出本段时出现高亮警告', result.warningVisible === true && /明显超出/.test(result.rangeWarn), result.rangeWarn);
check('覆盖只替换本段 1–4 条', /已覆盖第 1–4 条/.test(result.reshapeCoverToast), result.reshapeApplyToast);
check('范围外尾部译文保持对齐（不整轨清空）', /译文轨已保持对齐/.test(result.reshapeApplyToast), result.reshapeApplyToast);
check('总条数 6 → 5（只动了本段）', /共\s*5\s*条/.test(result.reshapeHeadCount), result.reshapeHeadCount);
check('覆盖后右栏只剩仍在本段时间范围内的新稿 2 条', result.reshapeRowsAfter === 2, result.reshapeRowsAfter);

if (failures.length) {
  console.error(`\n手动分批 / 时间轴对齐回归失败 ${failures.length} 项。`);
  process.exit(1);
}
console.log(`\n截图：${SHOT}`);
console.log('手动分批 / 时间轴对齐 / 局部重排回归全部通过。');
