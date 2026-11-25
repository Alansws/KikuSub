#!/usr/bin/env node
/**
 * 双语核对的两条 2026-11-25 用户报障回归：
 *
 *   1. 「清理标点 / 只改标点」不该把译文轨标成「原文已改」；
 *   2. 局部转写新加一条原文后，译文轨不能整条消失，新句应是「待译」
 *      并能用本地单句模型补一句、看一眼再采纳。
 *
 * 全程走真实界面 + 真实接口：字幕与译文轨用 dev seed 灌入，AI 那一跳指向脚本
 * 自己起的假 OpenAI 兼容服务（返回固定 JSON），所以**不需要** LM Studio 或网络。
 * 通过主进程的 `--screenshot` 静默路径跑，桌面上不出现窗口。
 *
 * 用法：
 *   node tools/shots/verify_translation_flow.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_translation_flow.mjs
 */

import { execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-translation-flow');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');

const CUES = [
  { start: 0.0, end: 1.4, text: 'よう、久しぶり。' },
  { start: 1.5, end: 2.9, text: 'お前は変わったな、本当に。' },
  { start: 3.0, end: 4.6, text: 'ここで待っていたんだよ、ずっと。' },
  { start: 4.7, end: 6.2, text: '雨の日だけ、君はここに来る。' },
];
// 第 2 / 4 条故意留空 → 「待译」
const ZH = ['哟，好久不见。', '', '我一直在这里等着你。', ''];
const FAKE_TEXT = ['他一直在这里等着。', '只有下雨的日子你才会来这里。'];

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const until = async (fn, ms = 8000) => {
      const end = Date.now() + ms;
      while (Date.now() < end) {
        const hit = fn();
        if (hit) return hit;
        await sleep(80);
      }
      return null;
    };
    const text = (el) => (el ? el.textContent.trim() : null);
    const rows = () => [...document.querySelectorAll('.row')];
    // Step 4.2.1：整轨读数并成一条状态条（.track-bar），断言仍按「一段文字里包含某句」检查
    const meta = () => {
      const bar = document.querySelector('.track-bar .tb-status');
      const value = bar ? bar.textContent.replace(/\s+/g, ' ').trim() : '';
      return value ? [value] : [];
    };
    const subLine = (i) => text(rows()[i]?.querySelector('.line.sub'));
    const setVal = (el, value) => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    };

    if (!(await until(() => rows().length >= 4 && meta().length === 1))) {
      return JSON.stringify({ error: '种子没有落地', rows: rows().length, meta: meta() });
    }
    await sleep(400);

    const out = { initialMeta: meta(), initialSub: [subLine(1), subLine(3)] };

    const commitBtn = () => document.querySelector('.actions .commit');

    // ---- 1) 只改标点：base 静默对齐，不出现「原文已改」
    rows()[0].click();
    await sleep(200);
    const src = document.querySelector('.cue-card textarea:not(.sub)');
    setVal(src, 'よう久しぶり');
    await sleep(120);
    out.commitEnabled = !commitBtn()?.disabled;
    commitBtn()?.click();
    await sleep(900);
    out.afterPunctMeta = meta();
    out.afterPunctStale = document.querySelectorAll('.row .line.sub.stale').length;

    // ---- 2) 真改字：这一条才该进「原文已改」
    rows()[2].click();
    await sleep(250);
    const src2 = document.querySelector('.cue-card textarea:not(.sub)');
    setVal(src2, 'ここで待っていたんだよ、ずっと待ってた。');
    await sleep(120);
    commitBtn()?.click();
    await sleep(1100);
    out.afterSemanticMeta = meta();
    out.staleRows = document.querySelectorAll('.row .line.sub.stale').length;

    // ---- 3) 待译句：AI 补译 → 草稿进输入框 → 采纳
    rows()[1].click();
    await sleep(250);
    out.translateButton = text(document.querySelector('.ai-btn'));
    out.gapHint = text(document.querySelector('.cue-card .edit-hint'));
    const errs = [];
    window.addEventListener('error', (e) => errs.push(String(e.message)));
    window.addEventListener('unhandledrejection', (e) => errs.push(String(e.reason)));
    document.querySelector('.ai-btn').click();
    await sleep(1200);
    out.btnAfter = text(document.querySelector('.ai-btn'));
    out.btnDisabled = document.querySelector('.ai-btn')?.disabled;
    out.errs = errs;
    const draft = await until(() => document.querySelector('.ai-draft'), 6000);
    if (!draft) out.aiError = text(document.querySelector('.cue-card .edit-hint'));
    out.draftTag = text(draft);
    out.draftValue = document.querySelector('.cue-card textarea.sub')?.value ?? '';
    const accept = [...document.querySelectorAll('.ai-link')].find(
      (b) => b.textContent.trim() === '采纳',
    );
    accept?.click();
    await until(() => !document.querySelector('.ai-draft'));
    await sleep(700);
    out.afterAcceptMeta = meta();
    out.afterAcceptSub = subLine(1);
    out.afterAcceptValue = document.querySelector('.cue-card textarea.sub')?.value ?? '';

    // ---- 4) 再给另一条待译句要一份草稿，停在「AI 草稿」态截图
    rows()[3].click();
    await sleep(250);
    document.querySelector('.ai-btn').click();
    await until(() => document.querySelector('.ai-draft'));
    await sleep(300);
    out.finalMeta = meta();
    out.finalDraft = document.querySelector('.cue-card textarea.sub')?.value ?? '';
    out.finalTag = text(document.querySelector('.ai-draft'));
    // 等「已采纳」的 toast 自己淡出，截图里别让它压住第 4 条字幕
    await sleep(3400);
    return JSON.stringify(out);
  })()
`;

function ensureMedia() {
  if (fs.existsSync(MEDIA)) return;
  fs.mkdirSync(BASE, { recursive: true });
  execFileSync('ffmpeg', [
    '-y', '-v', 'error',
    '-f', 'lavfi', '-i', 'color=c=0x223344:s=640x360:d=8',
    // 带一条极轻的正弦音轨：没有音频流时波形接口会直接 400，日志里全是 ffmpeg 噪音
    '-f', 'lavfi', '-i', 'sine=frequency=220:sample_rate=16000:duration=8',
    '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast',
    '-c:a', 'aac', '-shortest',
    MEDIA,
  ]);
}

/** 假模型必须在**独立进程**里：父进程跑 electron 时是阻塞的，同进程的 http 服务会饿死。 */
function fakeModelSource() {
  return `
const http = require('http');
const fs = require('fs');
const [port, logPath, textsJson] = process.argv.slice(2);
const texts = JSON.parse(textsJson);
let seq = 0;
const server = http.createServer((req, res) => {
  let body = '';
  req.on('data', (chunk) => (body += chunk));
  req.on('end', () => {
    if (req.url && req.url.endsWith('/chat/completions')) {
      const answer = texts[Math.min(seq, texts.length - 1)];
      seq += 1;
      fs.appendFileSync(logPath, body + '\\n');
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ choices: [{ message: { role: 'assistant', content: JSON.stringify({ text: answer }) } }] }));
      return;
    }
    res.writeHead(404, { 'content-type': 'application/json' });
    res.end('{"error":"not lm studio"}');
  });
});
server.listen(Number(port), '127.0.0.1', () => console.log('ready'));
`;
}

function freePort() {
  return new Promise((resolve) => {
    const probe = net.createServer();
    probe.listen(0, '127.0.0.1', () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

async function startFakeModel() {
  const port = await freePort();
  const script = path.join(BASE, 'fake-model.cjs');
  const logPath = path.join(BASE, 'requests.jsonl');
  fs.mkdirSync(BASE, { recursive: true });
  fs.rmSync(logPath, { force: true });
  fs.writeFileSync(script, fakeModelSource(), 'utf8');
  const child = spawn(process.execPath, [script, String(port), logPath, JSON.stringify(FAKE_TEXT)], {
    stdio: ['ignore', 'pipe', 'inherit'],
  });
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('假模型没有启动')), 5000);
    child.stdout.on('data', (chunk) => {
      if (String(chunk).includes('ready')) {
        clearTimeout(timer);
        resolve();
      }
    });
    child.on('exit', (code) => reject(new Error(`假模型退出：${code}`)));
  });
  return {
    port,
    stop: () => child.kill(),
    requests: () =>
      fs.existsSync(logPath)
        ? fs
            .readFileSync(logPath, 'utf8')
            .split('\n')
            .filter(Boolean)
            .map((line) => JSON.parse(line))
        : [],
  };
}

function writeSettings(port) {
  fs.writeFileSync(
    path.join(BASE, 'settings.json'),
    JSON.stringify(
      {
        enabled_engines: ['whisper', 'qwen'],
        ai_enabled: true,
        ai_base_url: `http://127.0.0.1:${port}/v1`,
        ai_model: 'fake-remote',
        ai_arbitrate_base_url: `http://127.0.0.1:${port}/v1`,
        ai_arbitrate_model: 'fake-local',
        ai_local_context: 2048,
        ai_auto_arbitrate: false,
      },
      null,
      2,
    ),
    'utf8',
  );
}

function run(port) {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  const profile = path.join(BASE, 'profile');
  fs.rmSync(profile, { recursive: true, force: true });
  fs.mkdirSync(profile, { recursive: true });

  const seedPath = path.join(BASE, 'seed.json');
  fs.writeFileSync(
    seedPath,
    JSON.stringify(
      {
        mediaPath: MEDIA,
        cues: CUES,
        translations: { lang: 'zh-Hans', texts: ZH },
        qaOpen: false,
      },
      null,
      2,
    ),
    'utf8',
  );
  writeSettings(port);

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
        `--screenshot=${path.join(BASE, 'translation-flow.png')}`,
        ...extra,
      ],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 240_000 },
    ).toString();
  } catch (error) {
    stdout = `${error.stdout ?? ''}`;
    console.error(String(error.stderr ?? '').slice(-1200));
  }
  if (process.env.KIKUSUB_VERIFY_DEBUG) console.error(stdout.slice(-4000));
  const line = stdout.split('\n').filter((row) => row.startsWith('[eval]')).pop();
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
const has = (list, part) => (list ?? []).some((item) => String(item).includes(part));

async function main() {
  ensureMedia();
  const fake = await startFakeModel();
  let data;
  try {
    data = run(fake.port);
  } finally {
    fake.stop();
  }
  const requests = fake.requests();

  if (data.error) throw new Error(data.error);

  check('初始：两条待译', has(data.initialMeta, '2 条待译'), data.initialMeta);
  check('表格：第 2 条显示「待译」', data.initialSub?.[0] === '待译', data.initialSub);
  check('表格：第 4 条显示「待译」', data.initialSub?.[1] === '待译', data.initialSub);

  check('只改标点后没有「原文已改」', !has(data.afterPunctMeta, '原文已改'), data.afterPunctMeta);
  check('只改标点后待译仍是 2 条', has(data.afterPunctMeta, '2 条待译'), data.afterPunctMeta);
  check('只改标点不会把行标黄', data.afterPunctStale === 0, data.afterPunctStale);

  check('真改字后出现「1 条原文已改」', has(data.afterSemanticMeta, '1 条原文已改'), data.afterSemanticMeta);
  check('真改字后恰好一行标黄', data.staleRows === 1, data.staleRows);

  check('待译句的按钮是「AI 补译」', data.translateButton === 'AI 补译', data.translateButton);
  check('待译句有说明文案', String(data.gapHint || '').includes('还没有译文'), data.gapHint);
  check('AI 草稿提示出现', String(data.draftTag || '').includes('AI 草稿'), data.draftTag);
  check('草稿填进了译文输入框', data.draftValue === FAKE_TEXT[0], data.draftValue);
  check('采纳后待译只剩 1 条', has(data.afterAcceptMeta, '1 条待译'), data.afterAcceptMeta);
  check('采纳后表格第 2 条是译文', data.afterAcceptSub === FAKE_TEXT[0], data.afterAcceptSub);
  check('采纳后输入框仍是译文', data.afterAcceptValue === FAKE_TEXT[0], data.afterAcceptValue);
  check('截图态仍是草稿（未采纳）', String(data.finalTag || '').includes('AI 草稿'), data.finalTag);
  check('截图态草稿是第二句', data.finalDraft === FAKE_TEXT[1], data.finalDraft);

  check('只发起了 2 次补译请求', requests.length === 2, requests.length);
  const first = JSON.parse(requests[0]?.messages?.[1]?.content || '{}');
  check('请求带的是选中那一句', first.target?.text === 'お前は変わったな、本当に。', first.target);
  check('请求带前文（已按标点清理后的原文）', (first.context_before ?? []).includes('よう久しぶり'), first.context_before);
  check('请求带邻居已有译文当参考', (first.references ?? []).some((r) => r.dst === '哟，好久不见。'), first.references);
  check('system 提示要求只输出 JSON', String(requests[0]?.messages?.[0]?.content || '').includes('只输出 JSON'));
  check('没有任何时间码', !String(requests[0]?.messages?.[1]?.content || '').includes('-->'));
  check('渲染进程没有异常', (data.errs ?? []).length === 0, data.errs);

  const shot = path.join(BASE, 'translation-flow.png');
  if (fs.existsSync(shot)) console.log(`\n截图：${shot}`);
  else console.error('\n截图缺失（--screenshot 没跑通？）');

  if (failures.length) {
    console.error(`\n${failures.length} 项失败`);
    process.exit(1);
  }
  console.log('\n全部通过');
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
