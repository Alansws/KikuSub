#!/usr/bin/env node
/**
 * 补译批次（gap fill）的静默回归：2026-11-25 用户工作流。
 *
 *   1. 双语逐句核对完一章，只剩两条待译；
 *   2. 检查器/翻译页的「补译 2 条」只把这两条复制出去；
 *   3. 粘回回复 → 只出现这两条；取消勾选一条 → 只写一条；
 *   4. 再补剩下那一条 → 两条落轨，**其余条目的译文一字未动**。
 *
 * 全程走真实界面 + 真实接口：不调模型（补译是外部手动通道），也不需要网络。
 * 通过主进程的 `--screenshot` 静默路径跑，桌面上不出现窗口。
 *
 * 用法：
 *   node tools/shots/verify_gap_fill.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_gap_fill.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-gap-fill');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');

const CUES = [
  { start: 0.0, end: 1.0, text: 'おはよう' },
  { start: 1.0, end: 2.0, text: '今日は雨だ' },
  { start: 2.0, end: 3.0, text: 'またね' },
  { start: 3.0, end: 4.0, text: '気をつけて' },
];
// 第 2 / 4 条故意留空 → 待译
const ZH = ['早上好', '', '再见', ''];

const REPLY = `2
00:00:01,000 --> 00:00:02,000
今天下雨了

4
00:00:03,000 --> 00:00:04,000
小心点
`;

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const until = async (fn, ms = 10000) => {
      const end = Date.now() + ms;
      while (Date.now() < end) {
        const hit = fn();
        if (hit) return hit;
        await sleep(80);
      }
      return null;
    };
    const text = (el) => (el ? el.textContent.trim() : null);
    const toast = () => text(document.querySelector('.toast'));
    const toastHas = (part) => (toast() ?? '').includes(part);
    const rows = () => [...document.querySelectorAll('.row')];
    const subLine = (i) => text(rows()[i]?.querySelector('.line.sub'));
    const nav = (label) =>
      [...document.querySelectorAll('.sb-item')].find(
        (b) => (b.getAttribute('aria-label') ?? '').startsWith(label),
      );
    const card = () => document.querySelector('.gap-card');
    const cardStat = () => text(card()?.querySelector('.gap-stat'));
    const gapButtons = () => [...(card()?.querySelectorAll('button') ?? [])];
    const byText = (part) => gapButtons().find((b) => b.textContent.includes(part));
    const setArea = (el, value) => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    };

    if (!(await until(() => rows().length >= 4))) {
      return JSON.stringify({ error: '种子没有落地', rows: rows().length });
    }
    await sleep(300);

    const out = { initialSub: [subLine(1), subLine(3)] };

    // ---- 1) 进翻译页：卡片只报两条待译
    nav('双语翻译')?.click();
    const shown = await until(() => card());
    if (!shown) return JSON.stringify({ error: '补译卡片没出现' });
    await sleep(250);
    out.cardStat = cardStat();
    out.copyLabel = text(byText('复制待译'));

    // ---- 2) 复制（不真正读剪贴板，验证请求成功 + 粘贴框展开）
    byText('复制待译')?.click();
    const copied = await until(() => toastHas('已复制'));
    out.copyToast = copied ? toast() : null;
    const pasteBox = await until(() => document.querySelector('.gap-box'));
    out.pasteOpen = Boolean(pasteBox);
    if (!pasteBox) return JSON.stringify({ ...out, error: '粘贴框没展开' });

    // ---- 3) 粘回两条，取消勾选第 2 条 → 只写一条
    setArea(pasteBox, ${JSON.stringify(REPLY)});
    await sleep(150);
    byText('解析并回填')?.click();
    const list = await until(() => document.querySelectorAll('.gap-item').length === 2);
    if (!list) return JSON.stringify({ ...out, error: '解析后没有出现两条', toast: toast() });
    out.parsed = [...document.querySelectorAll('.gap-item')].map((row) => ({
      idx: text(row.querySelector('.gap-idx')),
      before: text(row.querySelector('.gap-before')),
      after: row.querySelector('.gap-input')?.value ?? '',
    }));
    const pins = [...document.querySelectorAll('.gap-item .pin')];
    pins[1]?.click();
    await sleep(150);
    out.applyLabelAfterUncheck = text(byText('应用补译'));
    byText('应用补译')?.click();
    const applied1 = await until(() => toastHas('已补译 1 条'));
    out.applyToast1 = applied1 ? toast() : null;
    await sleep(500);
    out.afterFirstSub = [subLine(1), subLine(3)];

    // ---- 4) 回翻译页补最后一条
    nav('双语翻译')?.click();
    if (!(await until(() => card()))) {
      return JSON.stringify({ ...out, error: '回翻译页后卡片没出现' });
    }
    await sleep(250);
    out.cardStat2 = cardStat();
    out.copyLabel2 = text(byText('复制待译'));
    byText('复制待译')?.click();
    if (!(await until(() => document.querySelector('.gap-box')))) {
      return JSON.stringify({ ...out, error: '第二次粘贴框没展开' });
    }
    setArea(document.querySelector('.gap-box'), "1\n00:00:03,000 --> 00:00:04,000\n小心点\n");
    await sleep(150);
    byText('解析并回填')?.click();
    if (!(await until(() => document.querySelectorAll('.gap-item').length === 1))) {
      return JSON.stringify({ ...out, error: '第二次解析失败', toast: toast() });
    }
    byText('应用补译')?.click();
    const applied2 = await until(() => toastHas('已补译 1 条'));
    out.applyToast2 = applied2 ? toast() : null;
    await sleep(500);
    out.finalSub = [subLine(0), subLine(1), subLine(2), subLine(3)];
    return JSON.stringify(out);
  })()
`;

function ensureMedia() {
  if (fs.existsSync(MEDIA)) return;
  fs.mkdirSync(BASE, { recursive: true });
  execFileSync('ffmpeg', [
    '-y', '-v', 'error',
    '-f', 'lavfi', '-i', 'color=c=0x223344:s=640x360:d=8',
    '-f', 'lavfi', '-i', 'sine=frequency=220:sample_rate=16000:duration=8',
    '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast',
    '-c:a', 'aac', '-shortest',
    MEDIA,
  ]);
}

function writeSettings() {
  fs.writeFileSync(
    path.join(BASE, 'settings.json'),
    JSON.stringify({ enabled_engines: ['whisper', 'qwen'], ai_enabled: false }, null, 2),
    'utf8',
  );
}

function run() {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  const profile = path.join(BASE, 'profile');
  fs.rmSync(profile, { recursive: true, force: true });
  fs.mkdirSync(profile, { recursive: true });

  const seedPath = path.join(BASE, 'seed.json');
  fs.writeFileSync(
    seedPath,
    JSON.stringify(
      { mediaPath: MEDIA, cues: CUES, translations: { lang: 'zh-Hans', texts: ZH }, qaOpen: false },
      null,
      2,
    ),
    'utf8',
  );
  writeSettings();

  const extra = (process.env.KIKUSUB_SHOT_ELECTRON_ARGS || '').split(/\s+/).filter(Boolean);
  const env = {
    ...process.env,
    KIKUSUB_ALLOW_MULTIPLE: '1',
    KIKUSUB_WIN_SIZE: '1360x838',
    KIKUSUB_SHOT_DELAY: '3000',
    KIKUSUB_OUTPUT_DIR: OUT,
    KIKUSUB_DATA_DIR: path.join(BASE, 'data'),
    KIKUSUB_PREFERENCES_PATH: path.join(BASE, 'prefs.json'),
    KIKUSUB_DEV_SEED: seedPath,
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
        `--screenshot=${path.join(BASE, 'gap-fill.png')}`,
        ...extra,
      ],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 240_000 },
    ).toString();
  } catch (error) {
    stdout = `${error.stdout ?? ''}`;
    console.error(String(error.stderr ?? '').slice(-1200));
  }
  if (process.env.KIKUSUB_VERIFY_DEBUG) console.error(stdout.slice(-4000));
  const line = stdout
    .split('\n')
    .filter((row) => row.startsWith('[eval]'))
    .pop();
  if (!line) throw new Error('渲染进程没有回传结果');
  return JSON.parse(line.slice('[eval] '.length));
}

const failures = [];
function check(name, condition, detail) {
  if (condition) console.log(`  ✓ ${name}`);
  else {
    failures.push(`${name}${detail !== undefined ? ` → ${JSON.stringify(detail)}` : ''}`);
    console.error(`  ✗ ${name}${detail !== undefined ? ` → ${JSON.stringify(detail)}` : ''}`);
  }
}
const has = (value, part) => String(value ?? '').includes(part);

function main() {
  ensureMedia();
  const data = run();
  if (data.error) throw new Error(`${data.error}（${JSON.stringify(data)}）`);

  check('初始：第 2 条是待译', data.initialSub?.[0] === '待译', data.initialSub);
  check('初始：第 4 条是待译', data.initialSub?.[1] === '待译', data.initialSub);
  check('卡片只报两条待译', has(data.cardStat, '2') && has(data.cardStat, '待译'), data.cardStat);
  check('复制按钮写明条数', has(data.copyLabel, '2'), data.copyLabel);
  check('复制成功并展开粘贴框', data.pasteOpen === true && has(data.copyToast, '已复制'), {
    toast: data.copyToast,
    open: data.pasteOpen,
  });
  check(
    '解析：两条、按全片条号落位',
    data.parsed?.length === 2 &&
      data.parsed[0].idx === '#2' &&
      data.parsed[1].idx === '#4' &&
      data.parsed[0].before === '今日は雨だ' &&
      data.parsed[0].after === '今天下雨了',
    data.parsed,
  );
  check('取消勾选后只写 1 条', has(data.applyLabelAfterUncheck, '1 条'), data.applyLabelAfterUncheck);
  check(
    '第一次应用：只补第 2 条，第 4 条仍待译',
    has(data.applyToast1, '已补译 1 条') &&
      data.afterFirstSub?.[0] === '今天下雨了' &&
      data.afterFirstSub?.[1] === '待译',
    { toast: data.applyToast1, sub: data.afterFirstSub },
  );
  check('回翻译页：只剩 1 条待译', has(data.cardStat2, '1') && has(data.cardStat2, '待译'), data.cardStat2);
  check(
    '第二次应用：4 条全部有译文',
    has(data.applyToast2, '已补译 1 条') &&
      data.finalSub?.length === 4 &&
      data.finalSub.every((line) => line && line !== '待译'),
    { toast: data.applyToast2, sub: data.finalSub },
  );
  check(
    '已核对的译文没被改动',
    data.finalSub?.[0] === '早上好' && data.finalSub?.[2] === '再见',
    data.finalSub,
  );

  if (failures.length) {
    console.error(`\n补译回归失败（${failures.length} 项）`);
    process.exit(1);
  }
  console.log('\n补译回归全部通过');
}

main();
