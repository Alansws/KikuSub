#!/usr/bin/env node
/**
 * 外部提案刷新回归：模拟 CLI 往 sidecar 写一份润色提案，界面应在 2 秒内
 * 弹提示并自动载入，不需要用户切页或重启。
 *
 * 走 `--screenshot` 静默路径（透明窗口取帧），不弹窗口。断言失败退出码非 0。
 */

import { execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-external-proposals');
const OUT = path.join(BASE, 'out');
const DATA = path.join(BASE, 'data');
const MEDIA = path.join(BASE, 'media.mp4');

const CUES = [
  { start: 0.2, end: 1.8, text: 'おはようございます' },
  { start: 4.0, end: 6.0, text: '今日はいい天気ですね' },
  { start: 8.0, end: 10.0, text: 'ちゅぷっ、ちゅぱっ' },
];

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const out = { steps: [] };
    const sidecar = await window.kikusub.getSidecar();
    if (!sidecar?.port) return { error: 'no sidecar' };
    const sid = localStorage.getItem('kikusub.sid') || '';
    const headers = {
      Authorization: 'Bearer ' + sidecar.token,
      'X-Kikusub-Session': sid,
      'Content-Type': 'application/json',
    };
    const base = 'http://127.0.0.1:' + sidecar.port;
    const cues = await (await fetch(base + '/api/cues', { headers })).json();
    const texts = cues.cues.map((c) => c.text);
    const proposal = {
      version: 1,
      kind: 'polish',
      src_lang: 'ja',
      source: { path: cues.cues.length ? '/dev' : '', count: texts.length, digest: cues.digest },
      model: 'external-agent-test',
      entry: 'cli',
      created_at: 1,
      chunks: 1,
      items: texts.map((text, index) => ({
        i: index + 1,
        before: text,
        after: index === 0 ? 'おはようございます！' : text,
        note: index === 0 ? '测试外部提案' : '',
      })),
    };
    const saved = await fetch(base + '/api/ai/proposal', {
      method: 'POST',
      headers,
      body: JSON.stringify({ kind: 'polish', proposal }),
    });
    out.saved = saved.status;
    out.steps.push('posted ' + saved.status);
    // 轮询间隔 2s：连续采样 6s，别错过只显示 ~3.6s 的 toast
    let toast = '';
    const deadline = Date.now() + 6000;
    while (Date.now() < deadline) {
      const text = (document.querySelector('.toast')?.textContent || '').trim();
      if (text.includes('外部 Agent')) {
        toast = text;
        break;
      }
      await sleep(120);
    }
    out.toast = toast;
    // 回润色页确认提案真的进了工作区（不是只弹了个提示）
    const nav = [...document.querySelectorAll('.sb-item')].find((el) => el.textContent.includes('润色'));
    if (nav) nav.click();
    await sleep(700);
    out.rowTexts = [...document.querySelectorAll('.aiw-row .txt')].map((el) => el.textContent.trim()).slice(0, 6);
    out.entry = document.querySelector('.aiw-page')?.textContent?.includes('external-agent-test') || false;
    return out;
  })()
`;

function ensureMedia() {
  if (fs.existsSync(MEDIA)) return;
  fs.mkdirSync(BASE, { recursive: true });
  execFileSync(
    'ffmpeg',
    [
      '-hide_banner',
      '-loglevel',
      'error',
      '-f',
      'lavfi',
      '-i',
      'testsrc=size=320x180:rate=15:duration=12',
      '-f',
      'lavfi',
      '-i',
      'sine=frequency=440:duration=12',
      '-shortest',
      '-c:v',
      'libx264',
      '-pix_fmt',
      'yuv420p',
      '-c:a',
      'aac',
      '-y',
      MEDIA,
    ],
    { stdio: 'ignore' },
  );
}

function seed() {
  const file = path.join(BASE, 'seed.json');
  fs.writeFileSync(
    file,
    JSON.stringify({
      mediaPath: MEDIA,
      cues: CUES,
    }),
  );
  return file;
}

function run() {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  fs.rmSync(DATA, { recursive: true, force: true });
  fs.mkdirSync(DATA, { recursive: true });
  const profile = path.join(BASE, 'profile');
  fs.rmSync(profile, { recursive: true, force: true });
  fs.mkdirSync(profile, { recursive: true });

  const extra = (process.env.KIKUSUB_SHOT_ELECTRON_ARGS || '')
    .split(/\s+/)
    .filter(Boolean);
  const env = {
    ...process.env,
    KIKUSUB_ALLOW_MULTIPLE: '1',
    KIKUSUB_WIN_SIZE: '1360x838',
    KIKUSUB_SHOT_DELAY: '6500',
    KIKUSUB_OUTPUT_DIR: path.join(DATA, 'outputs'),
    KIKUSUB_SETTINGS_PATH: path.join(DATA, 'settings.json'),
    KIKUSUB_PREFERENCES_PATH: path.join(DATA, 'preferences.json'),
    KIKUSUB_DEV_SEED: seed(),
    KIKUSUB_DEV_EVAL: EVAL,
  };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.NODE_OPTIONS;

  return new Promise((resolve, reject) => {
    const child = spawn(
      'npx',
      [
        'electron',
        '.',
        `--user-data-dir=${profile}`,
        `--screenshot=${path.join(BASE, 'external-proposals.png')}`,
        ...extra,
      ],
      { cwd: path.join(ROOT, 'desktop'), env },
    );
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error('electron 超时'));
    }, 180_000);
    child.on('exit', (code) => {
      clearTimeout(timer);
      const line = stdout
        .split('\n')
        .filter((row) => row.startsWith('[eval]'))
        .pop();
      if (!line) {
        reject(new Error(`渲染进程没有回传结果（exit=${code}）\n${stderr.slice(-800)}`));
        return;
      }
      try {
        resolve(JSON.parse(line.slice('[eval] '.length)));
      } catch (err) {
        reject(new Error(`无法解析 eval 结果：${err.message}`));
      }
    });
  });
}

const failures = [];
function check(name, condition, detail) {
  if (condition) console.log(`  ✓ ${name}`);
  else {
    failures.push(name);
    console.error(`  ✗ ${name}${detail ? ` → ${detail}` : ''}`);
  }
}

async function main() {
  ensureMedia();
  const data = await run();
  console.log(JSON.stringify(data));
  check('提案写入成功', data.saved === 201, String(data.saved));
  check('界面弹出外部提案提示', /外部 Agent/.test(data.toast || ''), data.toast);
  check(
    '润色页已载入新提案',
    (data.rowTexts || []).includes('おはようございます！'),
    JSON.stringify(data.rowTexts),
  );

  const shot = path.join(BASE, 'external-proposals.png');
  if (fs.existsSync(shot)) console.log(`\n截图：${shot}`);
  if (failures.length) {
    console.error(`\n${failures.length} 项失败`);
    process.exit(1);
  }
  console.log('\n全部通过');
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
