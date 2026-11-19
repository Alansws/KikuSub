#!/usr/bin/env node
/**
 * 单句 AI 判定卡片回归：真实界面里的第三版、采用与 B 版徽章。
 *
 * 用 `KIKUSUB_DEV_SEED` 灌 A/B 与第三版，避免为看卡片加载本地模型；
 * 走 `--screenshot` 静默路径，不弹窗口。断言失败退出码非 0。
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-arbitration');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');

const CUES = [
  { start: 0.4, end: 1.6, text: 'おはようございます' },
  { start: 1.8, end: 3.0, text: '今日はいい天気ですね' },
  { start: 3.2, end: 4.8, text: 'もっとぐちゅぐちゅになっちゃう' },
  { start: 5.0, end: 6.4, text: 'ちょっと待ってください' },
  { start: 6.6, end: 8.0, text: 'もう一回お願いします' },
];

const SAME_B = process.env.ARB_SAME_B === '1';
const AI_TEXT = SAME_B ? 'もっとぐもぐもになっちゃう' : 'もっとぐちゅぐちゅになっちゃうよ';
const B_TEXT = 'もっとぐもぐもになっちゃう';

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const waitFor = async (fn, timeout = 8000) => {
      const start = Date.now();
      while (Date.now() - start < timeout) {
        const value = fn();
        if (value) return value;
        await sleep(80);
      }
      return null;
    };
    const text = (el) => (el ? el.textContent.trim() : null);
    const card = () => document.querySelector('.arb-card');

    await waitFor(() => document.querySelector('.row[data-i="2"]'));
    document.querySelector('.row[data-i="2"]').click();
    await sleep(350);
    await waitFor(card);
    const out = { hasCard: Boolean(card()) };
    out.head = text(document.querySelector('.arb-head b'));
    out.badge = text(document.querySelector('.arb-badge'));
    out.text = text(document.querySelector('.arb-text'));
    out.note = text(document.querySelector('.arb-note'));
    out.buttons = [...(card()?.querySelectorAll('button') || [])].map((b) => text(b));
    out.hasTts = out.buttons.some((label) => label === '朗读');
    out.hasAdopt = out.buttons.some((label) => (label || '').includes('采用'));
    return JSON.stringify(out);
  })()
`;

function ensureMedia() {
  if (fs.existsSync(MEDIA)) return;
  fs.mkdirSync(BASE, { recursive: true });
  execFileSync('ffmpeg', [
    '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x334455:s=640x360:d=10',
    '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', MEDIA,
  ]);
}

function ensureSeed() {
  const seedPath = path.join(BASE, 'seed.json');
  fs.writeFileSync(
    seedPath,
    JSON.stringify(
      {
        mediaPath: MEDIA,
        cues: CUES,
        secondOpinion: { engine: 'qwen', index: 2, text: B_TEXT },
        arbitration: { index: 2, text: AI_TEXT, note: 'B 的「もぐもぐ」不符合上下文', model: 'deepseek-chat' },
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
  const profile = path.join(BASE, 'profile');
  fs.rmSync(profile, { recursive: true, force: true });
  fs.mkdirSync(profile, { recursive: true });

  const extra = (process.env.KIKUSUB_SHOT_ELECTRON_ARGS || '').split(/\s+/).filter(Boolean);
  const env = {
    ...process.env,
    KIKUSUB_ALLOW_MULTIPLE: '1',
    KIKUSUB_WIN_SIZE: '1360x838',
    KIKUSUB_SHOT_DELAY: '2500',
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
        `--screenshot=${path.join(BASE, 'arbitration.png')}`,
        ...extra,
      ],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 180_000 },
    ).toString();
  } catch (error) {
    stdout = `${error.stdout ?? ''}`;
    console.error(String(error.stderr ?? '').slice(-800));
  }
  const line = stdout.split('\n').filter((row) => row.startsWith('[eval]')).pop();
  if (!line) throw new Error('渲染进程没有回传结果');
  return JSON.parse(line.slice('[eval] '.length));
}

const failures = [];
function check(name, condition, detail) {
  if (condition) console.log(`  ✓ ${name}`);
  else {
    failures.push(`${name}${detail ? ` → ${detail}` : ''}`);
    console.error(`  ✗ ${name}${detail ? ` → ${detail}` : ''}`);
  }
}

function main() {
  ensureMedia();
  const data = run();
  check('AI 判定卡出现', data.hasCard === true);
  check('卡片标题是 AI 判定', data.head === 'AI 判定', data.head);
  check(
    SAME_B ? '与 B 相同的徽章' : '第三版徽章',
    SAME_B ? (data.badge || '').includes('相同') : (data.badge || '').includes('第三版'),
    data.badge,
  );
  check(SAME_B ? 'AI 文本与 B 相同' : 'AI 文本是第三版', data.text === AI_TEXT, data.text);
  check('理由可见', (data.note || '').includes('もぐもぐ'), data.note);
  check('有朗读按钮', data.hasTts === true, JSON.stringify(data.buttons));
  check(
    SAME_B ? '同 B 版仍保留采用按钮' : '有采用 AI 版按钮',
    data.hasAdopt === true,
    JSON.stringify(data.buttons),
  );

  const shot = path.join(BASE, 'arbitration.png');
  if (fs.existsSync(shot)) console.log(`\n截图：${shot}`);
  else console.error('\n截图缺失（--screenshot 没跑通？）');

  if (failures.length) {
    console.error(`\n${failures.length} 项失败`);
    process.exit(1);
  }
  console.log('\n全部通过');
}

main();
