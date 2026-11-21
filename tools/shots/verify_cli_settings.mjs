#!/usr/bin/env node
/** 设置页「命令行工具」面板：无窗口截图 + 断言状态来自主进程。 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-cli-panel');
const OUT = path.join(BASE, 'out');

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    await sleep(600);
    const out = {};
    out.status = await window.kikusub.cli.status();
    const nav = [...document.querySelectorAll('.sb-item')].find((el) => el.textContent.includes('设置'));
    if (nav) nav.click();
    await sleep(300);
    const tab = document.getElementById('set-tab-ai');
    if (tab) tab.click();
    await sleep(500);
    const panel = document.querySelector('.cli-state');
    if (panel) panel.scrollIntoView({ block: 'center' });
    await sleep(200);
    out.panelText = document.querySelector('.cli-state')?.textContent?.trim() || '';
    out.body = document.body.textContent.includes('命令行工具');
    out.link = document.body.textContent.includes('.local/bin');
    out.hintVisible = Boolean(document.querySelector('.cli-cmd'));
    return out;
  })()
`;

function run() {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
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
    KIKUSUB_SHOT_DELAY: '3500',
    KIKUSUB_OUTPUT_DIR: path.join(BASE, 'outputs'),
    KIKUSUB_SETTINGS_PATH: path.join(BASE, 'settings.json'),
    KIKUSUB_PREFERENCES_PATH: path.join(BASE, 'preferences.json'),
    KIKUSUB_DEV_EVAL: EVAL,
  };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.NODE_OPTIONS;
  const stdout = execFileSync(
    'npx',
    [
      'electron',
      '.',
      `--user-data-dir=${profile}`,
      `--screenshot=${path.join(BASE, 'cli-panel.png')}`,
      ...extra,
    ],
    { cwd: path.join(ROOT, 'desktop'), env, timeout: 120_000 },
  ).toString();
  const line = stdout.split('\n').filter((row) => row.startsWith('[eval]')).pop();
  if (!line) throw new Error('渲染进程没有回传结果');
  return JSON.parse(line.slice('[eval] '.length));
}

const failures = [];
function check(name, ok, detail) {
  if (ok) console.log(`  ✓ ${name}`);
  else {
    failures.push(name);
    console.error(`  ✗ ${name}${detail ? ` → ${detail}` : ''}`);
  }
}

const data = run();
console.log(JSON.stringify(data));
check('主进程返回 CLI 状态', data.status?.ok === true, JSON.stringify(data.status));
check('状态里有目标与软链路径', Boolean(data.status?.target && data.status?.linkPath));
check('设置页有「命令行工具」', data.body === true);
check('展示 .local/bin 路径', data.link === true);
check('状态徽标有文案', /已安装|未安装|需重装|占用/.test(data.panelText || ''), data.panelText);

const shot = path.join(BASE, 'cli-panel.png');
if (fs.existsSync(shot)) console.log(`\n截图：${shot}`);
if (failures.length) {
  console.error(`\n${failures.length} 项失败`);
  process.exit(1);
}
console.log('\n全部通过');
