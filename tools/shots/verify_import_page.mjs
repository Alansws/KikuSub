#!/usr/bin/env node
/**
 * 导入页结构回归（第二阶段 Batch 1，2026-11-26）。
 *
 * 用户拿老版与本版并排对比后拍板：导入页的核心心智只有「拖入新片源或字幕」。
 * 第一阶段那张「继续核对 ⌘3 / 换片…」卡把主视觉挤掉了，已整张删除。这个脚本把
 * **新融合口径**冻成断言，避免下一次又「按有片 / 无片」分叉出第二套骨架：
 *
 *   1. 有片（种子）时**大拖放区仍在**，宽度就是 `--measure-card` 760，不被收窄；
 *   2. `.resume`（继续当前工程卡）与 `.drop-hint`（12px 换片提示）都不存在；
 *   3. 区块顺序：拖放区 → 导出文件夹 → 最近打开；
 *   4. 拖放区里是「拖入视频或字幕」+ 五个扩展名 chip；
 *   5. 本页按钮**不带尾部省略号**（`导入原文…` → `导入原文`）；
 *   6. 「最近打开」的列表 / 网格切换仍然可用。
 *
 * 走主进程自带的 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现，跑完自己退出。**不点任何会开原生对话框的按钮**（§0.5 无窗口铁律）。
 *
 * 用法：
 *   node tools/shots/verify_import_page.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_import_page.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-import-verify');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');

/** 有片状态才考验「拖放区会不会被继续卡挤掉」，所以种一份 3 条的稿。 */
const CUES = [
  { start: 0.0, end: 1.4, text: 'よう、久しぶり。' },
  { start: 1.5, end: 2.9, text: 'ここで待っていたんだよ。' },
  { start: 3.0, end: 4.4, text: '雨の日だけ、君はここに来る。' },
];

const EXPECT = {
  measure: 760,
  title: '拖入视频或字幕',
  chips: ['.mkv', '.mp4', '.mov', '.srt', '.vtt'],
  heads: ['导出文件夹', '最近打开'],
  exportButtons: ['打开文件夹', '导入原文'],
};

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const until = async (fn, ms = 12000) => {
      const end = Date.now() + ms;
      while (Date.now() < end) {
        const hit = fn();
        if (hit) return hit;
        await sleep(90);
      }
      return null;
    };
    const text = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : null);
    const q = (sel) => document.querySelector(sel);
    const box = (sel) => {
      const el = q(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
    };

    // 侧栏点「导入」，等拖放区落地（种子会先有片，才能验证「有片时仍是大拖放区」）
    const nav = document.querySelectorAll('.sb-item')[0];
    nav?.click();
    if (!(await until(() => q('.dropzone') && document.querySelectorAll('.recent-row').length))) {
      return JSON.stringify({ error: '导入页没有落地', title: q('.tb-title')?.textContent });
    }
    await sleep(500);

    const out = {
      width: innerWidth,
      hasMedia: Boolean(q('.pane') && document.querySelectorAll('.recent-row').length),
      dropzone: box('.dropzone'),
      existingResume: Boolean(q('.resume')),
      existingDropHint: Boolean(q('.drop-hint')),
      title: text(q('.dz-title')),
      chips: [...document.querySelectorAll('.dz-sub code')].map((el) => text(el)),
      heads: [...document.querySelectorAll('.pane .section-h')].map((el) => text(el)),
      exportButtons: [...document.querySelectorAll('.export-card button')].map((el) => text(el)),
      ellipsisButtons: [...document.querySelectorAll('.pane button')]
        .map((el) => text(el))
        .filter((label) => label && label.includes('…')),
      order: [...document.querySelectorAll('.pane > *')].map((el) => ({
        tag: el.tagName.toLowerCase(),
        cls: el.className && typeof el.className === 'string' ? el.className : '',
        y: Math.round(el.getBoundingClientRect().y),
      })),
      exportTop: box('.export-card')?.y ?? null,
      recentTop: box('.recent')?.y ?? null,
    };

    // 列表 / 网格切换仍然可用（不涉及原生对话框）
    const gridBtn = document.querySelector('[aria-label="图标视图"]');
    gridBtn?.click();
    await until(() => document.querySelectorAll('.gcard').length);
    await sleep(260);
    out.gridCards = document.querySelectorAll('.gcard').length;
    out.gridCover = box('.gcard .cover');

    const listBtn = document.querySelector('[aria-label="列表视图"]');
    listBtn?.click();
    await until(() => document.querySelectorAll('.recent-row').length);
    await sleep(260);
    out.listRows = document.querySelectorAll('.recent-row').length;
    return JSON.stringify(out);
  })()
`;

function ensureMedia() {
  fs.mkdirSync(BASE, { recursive: true });
  if (fs.existsSync(MEDIA)) return;
  execFileSync('ffmpeg', [
    '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x223344:s=640x360:d=5',
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
      ['electron', '.', `--user-data-dir=${profile}`, `--screenshot=${path.join(BASE, 'import.png')}`, ...extra],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 180_000 },
    ).toString();
  } catch (error) {
    stdout = `${error.stdout ?? ''}`;
    console.error(String(error.stderr ?? '').slice(-800));
  }
  if (process.env.KIKUSUB_VERIFY_DEBUG) console.error(stdout.slice(-4000));
  const line = stdout.split('\n').filter((row) => row.startsWith('[eval]')).pop();
  if (!line) throw new Error('渲染进程没有回传结果');
  return JSON.parse(line.slice('[eval] '.length));
}

const failures = [];
let passed = 0;
function check(name, condition, detail) {
  if (condition) {
    passed += 1;
    console.log(`  ✓ ${name}`);
  }
  else {
    const tail = detail ? ` → ${typeof detail === 'string' ? detail : JSON.stringify(detail)}` : '';
    failures.push(`${name}${tail}`);
    console.error(`  ✗ ${name}${tail}`);
  }
}

function main() {
  ensureMedia();
  const data = run();
  if (data.error) throw new Error(`${data.error}（${JSON.stringify(data)}）`);

  // ---- 1. 主视觉：有片也必须是同一块大拖放区
  check('拖放区存在', Boolean(data.dropzone), data.dropzone);
  check(
    `拖放区宽度 = ${EXPECT.measure}（不被继续卡挤窄）`,
    data.dropzone?.w === EXPECT.measure,
    data.dropzone,
  );
  check('拖放区是首屏主视觉（高 ≥ 180）', (data.dropzone?.h ?? 0) >= 180, data.dropzone?.h);
  check('标题是「拖入视频或字幕」', data.title === EXPECT.title, data.title);
  check(
    '五个扩展名 chip 齐全',
    JSON.stringify(data.chips) === JSON.stringify(EXPECT.chips),
    data.chips,
  );

  // ---- 2. 第一阶段那张卡与提示条必须彻底消失
  check('没有「继续当前工程」卡（.resume）', data.existingResume === false);
  check('没有 12px 换片提示条（.drop-hint）', data.existingDropHint === false);

  // ---- 3. 顺序：拖放区 → 代理说明 → 导出文件夹 → 最近打开
  const firstBlocks = (data.order ?? []).filter((row) => row.cls && row.cls !== 'page-head');
  check(
    '导出文件夹在最近打开之前',
    data.exportTop != null && data.recentTop != null && data.exportTop < data.recentTop,
    { exportTop: data.exportTop, recentTop: data.recentTop },
  );
  check(
    '拖放区在导出文件夹之前',
    data.dropzone != null && data.exportTop != null && data.dropzone.y < data.exportTop,
    { drop: data.dropzone?.y, exportTop: data.exportTop },
  );
  check(
    '分区标题顺序 = 导出文件夹 / 最近打开',
    JSON.stringify(data.heads) === JSON.stringify(EXPECT.heads),
    { heads: data.heads, blocks: firstBlocks },
  );

  // ---- 4. 按钮去省略号
  check(
    '导出文件夹两个按钮：打开文件夹 / 导入原文',
    JSON.stringify(data.exportButtons) === JSON.stringify(EXPECT.exportButtons),
    data.exportButtons,
  );
  check(
    '整页没有带尾省略号的按钮',
    Array.isArray(data.ellipsisButtons) && data.ellipsisButtons.length === 0,
    data.ellipsisButtons,
  );

  // ---- 5. 列表 / 网格切换仍在
  check('网格视图有封面卡', (data.gridCards ?? 0) > 0, data.gridCards);
  check('网格封面保持 16:9（宽 > 高）', (data.gridCover?.w ?? 0) > (data.gridCover?.h ?? 0), data.gridCover);
  check('切回列表视图仍有一行', (data.listRows ?? 0) > 0, data.listRows);

  if (failures.length) {
    console.error(`\n导入页结构回归：${failures.length} 项失败`);
    process.exit(1);
  }
  console.log(`\n导入页结构回归：${passed}/${passed} 通过`);
}

main();
