#!/usr/bin/env node
/**
 * 「片段范围」无窗口回归（2026-11-20）：润色 / 翻译 / 导出三段共用同一份范围。
 *
 * 用户场景：长片只处理一段（章节 `1:00 → 1:13`），润色 / 翻译只看这一段，
 * 导出成片与字幕都只出这一段，且字幕、章节全部平移到 0 起。
 *
 * 覆盖：
 *   - 导出页「导出范围」选择器：选区间章节后字幕条数变成 `4 / 5 条`；
 *   - 「仅封装」+ 片段 → 出现「按关键帧切片」说明；切回软字幕后说明消失；
 *   - 字幕单独导出：文件名带片段标签，SRT 里的时间已归零（node 侧真读文件）；
 *   - 成片导出：ffprobe 验证时长 = 12s、章节「发射点」= 8.5s（node 侧真读容器）；
 *   - 润色页 / 翻译页：表格只剩这一段 4 行、计数与页头选择器一致；
 *   - 章节面板「仅处理此片段」：一键把这个章节设为处理范围。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现。断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_clip_scope.mjs
 *   KIKUSUB_FINAL_VIEW=polish node tools/shots/verify_clip_scope.mjs   # 截图停在润色页
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_clip_scope.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-clip-scope');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'clip-scope.mp4');
const SHOT = path.join(BASE, 'clip-scope.png');
const FINAL_VIEW = ['polish', 'translate', 'export'].includes(process.env.KIKUSUB_FINAL_VIEW || '')
  ? process.env.KIKUSUB_FINAL_VIEW
  : 'export';

const DURATION = 14;
const CUES = [
  { start: 1.5, end: 2.5, text: '跨界句' },
  { start: 3.0, end: 4.0, text: '第二句' },
  { start: 6.0, end: 7.0, text: '第三句' },
  { start: 10.0, end: 12.0, text: '尾部句' },
  { start: 13.0, end: 14.0, text: '片段之后' },
];
// 区间章节 1.0 → 13.0：命中 4 条；片段内时刻点 9.5 → 平移后 8.5。
const CHAPTERS = [
  { id: 'scene-1', start: 1.0, end: 13.0, title: '章节1' },
  { id: 'point-1', start: 9.5, end: null, title: '发射点' },
  { id: 'outside', start: 13.0, end: null, title: '片段之后' },
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
    const sidebar = (label) =>
      [...document.querySelectorAll('.sb-item')].find((el) =>
        (el.getAttribute('aria-label') || '').startsWith(label),
      );
    const buttonByText = (root, text) =>
      [...(root?.querySelectorAll('button') ?? [])].find((el) => (el.textContent || '').includes(text));
    const text = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim();
    const picker = () => document.querySelector('.range-row .clip-select');
    const pickChapter = async () => {
      const sel = picker();
      const option = [...sel.options].find((item) => (item.textContent || '').includes('章节1'));
      sel.value = option.value;
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      await sleep(700);
    };

    try {
    await waitFor(() => document.querySelector('.app-shell, .sidebar, .sb-item'));
    await sleep(900);

    // 1) 导出页：选章节 1 → 13
    sidebar('导出')?.click();
    await waitFor(() => document.querySelector('.export-view'));
    await sleep(600);
    const pickerFound = Boolean(picker());
    const pickerOptions = [...(picker()?.options ?? [])].map((o) => text(o));
    await pickChapter();
    await sleep(900);
    const cueCount = text(document.querySelector('.subtitle-sec .cue-count'));
    const rangeHint = text(document.querySelector('.range-hint'));
    const scopeMetrics = text(document.querySelector('.metrics'));
    const subtitleButton = buttonByText(document.querySelector('.subtitle-sec'), '导出本段字幕');
    const subtitleButtonLabel = text(subtitleButton);

    // 2) 仅封装：出现关键帧说明；切回软字幕后消失
    buttonByText(document.querySelector('.export-view'), '仅封装')?.click();
    await sleep(900);
    const copyHint = text(document.querySelector('.clip-copy-hint'));
    buttonByText(document.querySelector('.export-view'), '软字幕')?.click();
    await sleep(900);
    const copyHintGone = !document.querySelector('.clip-copy-hint');

    // 3) 字幕单独导出（片段）：拿路径，node 侧读文件验证时间已归零
    buttonByText(document.querySelector('.subtitle-sec'), '导出本段字幕')?.click();
    const lastSub = await waitFor(() => document.querySelector('.subtitle-sec .path-link'), 30000);
    const subtitlePath = lastSub?.getAttribute('title') ?? '';

    // 4) 成片导出（软字幕）：拿路径，node 侧 ffprobe 验证时长与章节
    buttonByText(document.querySelector('.export-view'), '开始导出')?.click();
    const done = await waitFor(() => document.querySelector('.done-path'), 90000);
    const videoPath = done?.getAttribute('title') ?? '';
    const doneName = text(done);
    const doneMeta = text(document.querySelector('.done-card .done-meta'));
    const doneSub = text(document.querySelector('.done-card .done-sub'));

    // 5) 润色页：表格只剩这一段 4 行
    sidebar('润色')?.click();
    await waitFor(() => document.querySelector('.aiw-page'));
    await sleep(1200);
    const polishRows = document.querySelectorAll('.aiw-row').length;
    const polishPicker = Boolean(document.querySelector('.aiw-title-row .clip-scope'));
    const polishSubbar = text(document.querySelector('.aiw-title-row .clip-scope'));

    // 6) 翻译页：同样只有 4 行
    sidebar('翻译')?.click();
    await waitFor(() => document.querySelector('.ai'));
    await sleep(1000);
    const translateRows = document.querySelectorAll('.ai .list .row').length;
    const translateSubbar = text(document.querySelector('.ai .aiw-title-row .clip-scope'));
    const translatePicker = Boolean(document.querySelector('.ai .aiw-title-row .clip-scope'));

    // 7) 章节面板「仅处理此片段」：先换回全片，再一键带入
    sidebar('核对台')?.click();
    await waitFor(() => document.querySelector('.wave-wrap'));
    await sleep(700);
    const chapterTab = [...document.querySelectorAll('.insp-tab')].find((el) =>
      (el.textContent || '').trim().startsWith('章节'),
    );
    chapterTab?.click();
    const panel = await waitFor(() => document.querySelector('.chapters-panel'));
    const useButtons = [...(panel?.querySelectorAll('button[aria-label="仅处理此片段"]') ?? [])];
    // 回全片（导出页那个选择器还在页面外，这里用章节按钮之前先经导出页改回全片）
    sidebar('导出')?.click();
    await waitFor(() => document.querySelector('.export-view'));
    await sleep(400);
    const fullSel = picker();
    fullSel.value = 'full';
    fullSel.dispatchEvent(new Event('change', { bubbles: true }));
    await sleep(700);
    const cueCountFull = text(document.querySelector('.subtitle-sec .cue-count'));
    sidebar('核对台')?.click();
    await waitFor(() => document.querySelector('.wave-wrap'));
    await sleep(500);
    [...document.querySelectorAll('.insp-tab')]
      .find((el) => (el.textContent || '').trim().startsWith('章节'))
      ?.click();
    await waitFor(() => document.querySelector('.chapters-panel .item'));
    await sleep(400);
    const panelItems = [...document.querySelectorAll('.chapters-panel .item')];
    const panelText = text(document.querySelector('.chapters-panel'));
    const rangeItems = panelItems.filter((el) => (el.textContent || '').includes('章节1'));
    const useButton = rangeItems[0]?.querySelector('button[aria-label="仅处理此片段"]');
    const useButtonFound = Boolean(useButton);
    useButton?.click();
    await sleep(800);
    const toastAfterUse = text(document.querySelector('.toast, .toasts, .toast-stack'));
    sidebar('导出')?.click();
    await waitFor(() => document.querySelector('.export-view'));
    await sleep(900);
    const afterOneClickCount = text(document.querySelector('.subtitle-sec .cue-count'));
    const afterOneClickSelection = text(picker()?.selectedOptions?.[0]);

    // 8) 收尾截图停在指定页面
    if ('${FINAL_VIEW}' === 'polish') {
      sidebar('润色')?.click();
      await waitFor(() => document.querySelector('.aiw-page'));
    } else if ('${FINAL_VIEW}' === 'translate') {
      sidebar('翻译')?.click();
      await waitFor(() => document.querySelector('.ai'));
    } else {
      sidebar('导出')?.click();
      await waitFor(() => document.querySelector('.export-view'));
    }
    await sleep(800);

    return JSON.stringify({
      pickerFound,
      pickerOptions,
      cueCount,
      rangeHint,
      scopeMetrics,
      subtitleButtonLabel,
      copyHint,
      copyHintGone,
      subtitlePath,
      videoPath,
      doneName,
      doneMeta,
      doneSub,
      polishRows,
      polishPicker,
      polishSubbar,
      translateRows,
      translateTranslate: translatePicker,
      translateSubbar,
      useButtons: useButtons.length,
      panelItems: panelItems.length,
      panelText: panelText.slice(0, 300),
      useButtonFound,
      toastAfterUse,
      cueCountFull,
      afterOneClickCount,
      afterOneClickSelection,
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
    KIKUSUB_SHOT_DELAY: '3600',
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

function probe(pathname, what) {
  return JSON.parse(
    execFileSync('ffprobe', ['-v', 'error', what, '-of', 'json', pathname]).toString() || '{}',
  );
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

// ---- 选择器 ----
check('导出页有「导出范围」选择器', result.pickerFound === true, result);
check(
  '选项含全片 / 区间章节 / 自定义',
  result.pickerOptions.some((o) => o.includes('全片')) &&
    result.pickerOptions.some((o) => o.includes('章节1')) &&
    result.pickerOptions.some((o) => o.includes('自定义')),
  result.pickerOptions,
);
check('时刻点不单独成项', !result.pickerOptions.some((o) => o.includes('发射点')), result.pickerOptions);
check('选章节后字幕条数显示 4 / 5', result.cueCount.includes('4 / 5'), result.cueCount);
check('范围说明解释归零与防覆盖', result.rangeHint.includes('平移到 0'), result.rangeHint);
check('规划里显示片段时长', result.scopeMetrics.includes('片段'), result.scopeMetrics);
check('字幕按钮变成「导出本段字幕」', result.subtitleButtonLabel.includes('导出本段字幕'), result);

// ---- 仅封装说明 ----
check('仅封装 + 片段给出关键帧说明', result.copyHint.includes('关键帧'), result.copyHint);
check('切回软字幕说明消失', result.copyHintGone === true, result);

// ---- 字幕文件 ----
check('字幕导出落在片段文件名', /章节1-00m01s-00m13s/.test(result.subtitlePath), result.subtitlePath);
const srtText = fs.existsSync(result.subtitlePath)
  ? fs.readFileSync(result.subtitlePath, 'utf8')
  : '';
check('片段字幕只含 4 条', (srtText.match(/-->/g) || []).length === 4, srtText.slice(0, 300));
check('片段字幕首条从 0 起', srtText.includes('00:00:00,500 --> 00:00:01,500'), srtText.slice(0, 200));
check('片段字幕末条在 11s 前', srtText.includes('00:00:09,000 --> 00:00:11,000'), srtText.slice(-200));
check('范围外字幕没有进文件', !srtText.includes('片段之后'), srtText);

// ---- 成片 ----
check('成片导出完成', Boolean(result.videoPath) && fs.existsSync(result.videoPath), result);
if (result.videoPath && fs.existsSync(result.videoPath)) {
  const format = probe(result.videoPath, '-show_format').format ?? {};
  const chapters = probe(result.videoPath, '-show_chapters').chapters ?? [];
  check('成片时长 = 12s（帧级裁剪）', Math.abs(Number(format.duration) - 12) < 0.2, format.duration);
  check('成片文件名带片段标签', /章节1-00m01s-00m13s/.test(result.videoPath), result.videoPath);
  check('章节两条且标题正确', chapters.map((c) => c.tags?.title).join('|') === '章节1|发射点', chapters);
  check(
    '「发射点」平移到 8.5s',
    Math.abs(Number(chapters[1]?.start_time ?? -1) - 8.5) < 0.05,
    chapters[1],
  );
  check('片段之后不在章节里', !chapters.some((c) => c.tags?.title === '片段之后'), chapters);
}

// ---- 润色 / 翻译 ----
check('润色页有范围选择器', result.polishPicker === true, result);
check('润色表格只剩片段 4 行', result.polishRows === 4, result.polishRows);
check('润色状态条显示命中 4 / 5', result.polishSubbar.includes('4 / 5'), result.polishSubbar);
check('翻译页有范围选择器', result.translateTranslate === true, result);
check('翻译页选择器显示命中 4 / 5', result.translateSubbar.includes('4 / 5'), result.translateSubbar);

// ---- 章节面板一键带入 ----
check('区间章节有「仅处理此片段」', result.useButtons >= 1, result.useButtons);
check('切回全片后计数恢复 5 条', result.cueCountFull.includes('5 条'), result.cueCountFull);
check(
  '一键带入后范围回到章节1',
  result.afterOneClickCount.includes('4 / 5') && result.afterOneClickSelection.includes('章节1'),
  {
    count: result.afterOneClickCount,
    selected: result.afterOneClickSelection,
    useButtonFound: result.useButtonFound,
    panelItems: result.panelItems,
    panelText: result.panelText,
    toast: result.toastAfterUse,
  },
);

console.log(`\n截图：${SHOT}`);
if (failures.length) {
  console.error(`\n${failures.length} 项失败：${failures.join('、')}`);
  process.exit(1);
}
console.log('\n片段范围回归全部通过。');
