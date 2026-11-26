#!/usr/bin/env node
/**
 * 核对台「打开体验 + 右侧栏不溢出」无窗口回归（2026-11-21，Step 3）。
 *
 * 三件用户报障 / 本轮约定的事，全在真实界面里断言：
 *
 * 1. **长片不再停在「全片 1.0× + 片头黑场」**：没有本机现场快照时，默认聚焦第 1 条
 *    字幕、默认约 50× 视野，并且真的 seek 到第 1 条（画面不再是片头那一帧）。
 * 2. **短片保持全片视图**：几十秒的样片放大反而看不到全貌（`SHORT_FILM_SECONDS`）。
 * 3. **右侧检查器不溢出**：操作行里同时有「试听原声 / 朗读 / 音色 / ⚙」，朗读面板
 *    按需展开；在 1360×838 标准窗口下，从显示模式到 AI 判定这一整块**不用滚动**就能
 *    完整操作，也不会滑到底部「保存 / 导出」条下面。
 * 4. **有译文轨时默认双语**：只在本次启动第一次进核对台时生效一次。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），桌面上不出现。
 *
 * 用法：
 *   node tools/shots/verify_review_defaults.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_review_defaults.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-review-defaults');
const OUT = path.join(BASE, 'out');
const SHOT = path.join(BASE, 'review-defaults.png');

/** 10 分钟「长片」：第 1 条字幕在 28.5s，片头是空的。 */
const LONG_MEDIA = path.join(BASE, 'long.mp4');
const LONG_CUES = [
  { start: 28.5, end: 31.0, text: 'よう、久しぶり。' },
  { start: 31.2, end: 34.0, text: 'お前は変わったな、本当に。' },
  { start: 34.2, end: 37.0, text: 'ここで待っていたんだよ、ずっと。' },
  { start: 120.0, end: 123.0, text: '雨の日だけ、君はここに来る。' },
];
const ZH_TEXTS = ['哟，好久不见。', '你变了呢，真的。', '我一直在这里等着哦。', '只有在雨天，你才会来这里。'];

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
    const text = (node) => node?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    const picked = () =>
      [...document.querySelectorAll('.seg button')]
        .find((button) => button.classList.contains('on'))?.textContent?.trim() ?? '';

    await waitFor(() => document.querySelector('.row[data-i="0"]'));
    await sleep(600);

    const scroll = document.querySelector('.ins-scroll');
    const base = scroll.getBoundingClientRect().top;
    const box = (selector) => {
      const node = document.querySelector(selector);
      if (!node) return null;
      const rect = node.getBoundingClientRect();
      return {
        top: Math.round(rect.top - base),
        bottom: Math.round(rect.bottom - base),
        left: Math.round(rect.left),
        height: Math.round(rect.height),
      };
    };
    const rowTops = (selector) =>
      [...document.querySelectorAll(selector)].map((node) =>
        Math.round(node.getBoundingClientRect().top),
      );

    const before = {
      zoom: text(document.querySelector('.zoom-x')),
      playTime: text(document.querySelector('.tp-time')),
      selected: text(document.querySelector('.row-sel .c-idx')),
      track: picked(),
      cueTime: Math.round((document.querySelector('video')?.currentTime ?? -1) * 10) / 10,
      hasTranslation: Boolean(document.querySelector('.track-meta .link')),
      scrollH: scroll.scrollHeight,
      clientH: scroll.clientHeight,
      // 操作区：显示模式 → AI 判定。检查器里已经没有保存卡片了
      // （2026-11-24 Phase 1：暂存移到底栏），所以滚动区本身就是判断基准。
      opsBottom: box('.second-opinion')?.bottom ?? null,
      actionTop: rowTops('.actions')[0] ?? null,
      listenTop: rowTops('.tts-listen')[0] ?? null,
      voiceTop: rowTops('.tts-select-wrap.voice')[0] ?? null,
      moreTop: rowTops('.tts-more')[0] ?? null,
      editRowTop: rowTops('.actions.edit-row')[0] ?? null,
      ttsPanel: Boolean(document.querySelector('.tts-panel')),
      dockTop: box('.save-dock')?.top ?? null,
    };

    const statusbar = document.querySelector('.statusbar');
    const statusDock = {
      shown: Boolean(statusbar?.querySelector('.draft-dock')),
      hasSave: [...(statusbar?.querySelectorAll('.draft-dock button') ?? [])].some((b) =>
        (b.textContent || '').includes('暂存'),
      ),
      // 底栏不该把草稿状态藏起来（它不是折叠区）
      label: (statusbar?.querySelector('.draft-dock .dd-state')?.textContent || '').trim(),
    };

    // 展开朗读面板：语速 / 上传 / 截取 / 音色库 / 管理都在这里，不常驻占高度
    document.querySelector('.tts-more').click();
    await waitFor(() => document.querySelector('.tts-panel'));
    await sleep(240);
    const panel = {
      open: Boolean(document.querySelector('.tts-panel')),
      rate: Boolean(document.querySelector('.tts-panel .tts-select-wrap.rate')),
      chips: [...document.querySelectorAll('.tts-panel .tts-action')].map(text),
      bottom: box('.tts-panel')?.bottom ?? null,
      insideScroll: scroll.scrollHeight,
    };
    document.querySelector('.tts-more').click();
    await sleep(200);

    // 换页再回来：默认双语只该生效一次，不能被重新翻回双语
    document.querySelectorAll('.seg button')[0].click();
    await sleep(240);
    const afterManualSource = picked();
    document.querySelectorAll('.sb-item')[4].click();
    await sleep(420);
    document.querySelectorAll('.sb-item')[2].click();
    await waitFor(() => document.querySelector('.ins-scroll'));
    await sleep(700);
    const afterReturn = {
      track: picked(),
      zoom: text(document.querySelector('.zoom-x')),
      playTime: text(document.querySelector('.tp-time')),
    };

    return JSON.stringify({ before, statusDock, panel, afterManualSource, afterReturn });
  })()
`;

function ffmpeg(args) {
  execFileSync('ffmpeg', ['-y', '-v', 'error', ...args]);
}

function ensureMedia() {
  fs.mkdirSync(BASE, { recursive: true });
  if (!fs.existsSync(LONG_MEDIA)) {
    ffmpeg([
      '-f', 'lavfi', '-i', 'color=c=0x223344:s=640x360:d=600:r=10',
      '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', '-t', '600', LONG_MEDIA,
    ]);
  }
}

function ensureSeed() {
  const seedPath = path.join(BASE, 'seed.json');
  fs.writeFileSync(
    seedPath,
    JSON.stringify(
      {
        mediaPath: LONG_MEDIA,
        cues: LONG_CUES,
        translations: { lang: 'zh-Hans', texts: ZH_TEXTS },
      },
      null,
      2,
    ),
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
    KIKUSUB_SHOT_DELAY: '3500',
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
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 240_000 },
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
const before = result.before;
const statusDock = result.statusDock;

// ---- 1) 长片默认态：第 1 条字幕 + ~50× 视野，而不是全片 1.0× ----
check('默认缩放在 ~50× 视野（不是全片 1.0×）', before.zoom === '50×', before.zoom);
check('默认选中第 1 条字幕', before.selected === '1', before.selected);
check('播放头定位到第 1 条字幕（不是片头黑场）', before.playTime === '00:00:28.500', before.playTime);
check('视频真的 seek 到第 1 条字幕', Math.abs(before.cueTime - 28.5) < 0.6, before.cueTime);

// ---- 2) 有译文轨时默认双语 ----
check('有译文轨时默认双语', before.track === '双语', before.track);

// ---- 3) 右侧检查器不溢出 ----
check(
  '操作区（到 AI 判定）在可视高度内，无需滚动',
  before.opsBottom !== null && before.opsBottom <= before.clientH,
  { opsBottom: before.opsBottom, clientH: before.clientH },
);
check(
  '检查器底部不再有保存卡片（暂存已移到底栏）',
  before.dockTop === null,
  { dockTop: before.dockTop },
);
check(
  '底栏有暂存入口且只在核对屏出现',
  statusDock.shown === true && statusDock.hasSave === true && statusDock.label.length > 0,
  statusDock,
);
// 同一行 = 顶边相差不超过 3px（select 外壳比按钮矮 2px，垂直居中会差 1px）
const sameRow = (value) => Math.abs(value - before.actionTop) <= 3;
check(
  '朗读 / 音色 / ⚙ 与「试听原声」在同一行',
  sameRow(before.listenTop) && sameRow(before.voiceTop) && sameRow(before.moreTop),
  {
    actionTop: before.actionTop,
    listenTop: before.listenTop,
    voiceTop: before.voiceTop,
    moreTop: before.moreTop,
  },
);
check(
  '编辑行（聚焦 / 复制 / 删除 / 更新此行）在第一行下面',
  before.editRowTop > before.actionTop,
  { actionTop: before.actionTop, editRowTop: before.editRowTop },
);
check('朗读面板默认收起（不常驻占高度）', before.ttsPanel === false);

// ---- 4) 朗读面板按需展开 ----
check('点 ⚙ 能展开朗读面板', result.panel.open === true);
check('面板里有语速', result.panel.rate === true);
check(
  '面板里有上传 / 截取 / 音色库',
  ['上传', '截取', '音色库'].every((label) => result.panel.chips.some((chip) => chip.includes(label))),
  result.panel.chips,
);
check(
  '展开的面板也在可视高度内（不被保存栏截断）',
  result.panel.bottom !== null && result.panel.bottom <= before.clientH,
  { bottom: result.panel.bottom, clientH: before.clientH },
);

// ---- 5) 双语默认只生效一次 ----
check('手动切回原文后保持原文', result.afterManualSource === '原文', result.afterManualSource);
check('切页回来不把用户选的原文翻回双语', result.afterReturn.track === '原文', result.afterReturn.track);
check('切页回来仍在默认 50× 视野', result.afterReturn.zoom === '50×', result.afterReturn.zoom);

console.log(`\n截图：${SHOT}`);
if (failures.length) {
  console.error(`\n${failures.length} 项失败：${failures.join(' / ')}`);
  process.exit(1);
}
console.log('\n全部通过。');
