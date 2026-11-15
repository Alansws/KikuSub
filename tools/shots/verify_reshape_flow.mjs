#!/usr/bin/env node
/**
 * 断句重排「分段计划冻结」端到端回归。
 *
 * 复现 2026-11-15 的用户现场：501 条 A（Whisper）+ 516 条 B（千问），进断句重排页
 * 切成 4 段。然后跑两种场景：
 *
 *   flow  ：单源 ↔ 双源切换不动段轨；覆盖两段后段轨仍是 4 段、勾还在；⌘Z 撤掉
 *           自家那次覆盖时，段轨勾选同步回退（不留脏 delta）。
 *   stale ：覆盖一段后在核对台删一条字幕（同一部片，media.id 不变）→ 回断句重排
 *           必须出「计划失效」横幅、暂停复制/覆盖、且**不**提供会错位的「恢复」按钮；
 *           点「重新定计划」后回到可用状态。
 *
 * 两种场景都用主进程自带的 `--screenshot` 静默路径（showInactive + capturePage +
 * app.exit），不抢焦点、跑完自己退出。断言失败时退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_reshape_flow.mjs                 # 两个场景都跑
 *   node tools/shots/verify_reshape_flow.mjs --scenario flow
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox 在沙箱 / CI 里补启动参数
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-reshape-verify');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(os.tmpdir(), 'kikusub-ai-workbench-shots', 'media.mp4');

/** 页面内取值工具：只读 DOM，不改业务状态。 */
const HELPERS = String.raw`
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const rail = () =>
    [...document.querySelectorAll('.aiw-rail-item')].map((b) =>
      b.querySelector('.aiw-rail-count')?.textContent.trim());
  const doneFlags = () =>
    [...document.querySelectorAll('.aiw-rail-flag')].map((f) => f.classList.contains('done'));
  const chip = () => {
    const hit = [...document.querySelectorAll('.aiw-chip')]
      .map((e) => e.textContent.replace(/\s+/g, ' ').trim())
      .find((t) => t.includes('已覆盖'));
    return hit || '';
  };
  const banner = () =>
    document.querySelector('.note.warn')?.textContent.replace(/\s+/g, ' ').trim() || '';
  const btn = (label) =>
    [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === label);
  const byText = (part) =>
    [...document.querySelectorAll('button')].find((b) => b.textContent.includes(part));
  const snapshot = () => ({
    rail: rail(),
    chip: chip(),
    done: doneFlags(),
    banner: banner(),
    copyDisabled: byText('复制')?.disabled ?? null,
    replanVisible: Boolean(btn('重新定计划')),
    restoreVisible: Boolean(btn('恢复上一版分段')),
  });
  function makeSrt(count) {
    const tc = (v) => {
      const h = Math.floor(v / 3600);
      const m = Math.floor((v % 3600) / 60);
      const s = (v % 60).toFixed(3).replace('.', ',');
      return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0') + ':' + s;
    };
    let out = '';
    let t = 0;
    for (let i = 1; i <= count; i += 1) {
      out += i + '\n' + tc(t) + ' --> ' + tc(t + 1) + '\n重排后的第' + i + '句\n\n';
      t += 1.2;
    }
    return out;
  }
  /** 覆盖当前段：粘 100 条新稿 → 解析 → 覆盖。 */
  async function coverSegment(count) {
    const box = document.querySelector('.aiw-drop textarea');
    if (!box) return false;
    box.value = makeSrt(count);
    box.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(200);
    byText('解析并预检')?.click();
    await sleep(1400);
    const apply = [...document.querySelectorAll('button')]
      .find((b) => /覆盖第|确认覆盖|覆盖核对台/.test(b.textContent));
    if (!apply) return false;
    apply.click();
    await sleep(1800);
    return true;
  }
  const openReshape = async () => {
    document.querySelectorAll('.sb-item')[5]?.click();
    await sleep(1400);
  };
`;

const FLOW = `(async () => {
  ${HELPERS}
  await sleep(1200);
  await openReshape();
  const out = {};
  out.enter = snapshot();

  btn('单源')?.click();
  await sleep(500);
  out.single = snapshot();
  btn('双源 A+B')?.click();
  await sleep(900);
  out.dualAgain = snapshot();

  out.cover1 = await coverSegment(100);
  out.after1 = snapshot();
  out.cover2 = await coverSegment(100);
  out.after2 = snapshot();

  // 用户当时手贱的那一下：单源 → 双源
  btn('单源')?.click();
  await sleep(500);
  btn('双源 A+B')?.click();
  await sleep(1000);
  out.afterToggle = snapshot();

  // ⌘Z 撤掉第二次覆盖；再撤一次第一次
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', metaKey: true, bubbles: true }));
  await sleep(1600);
  out.undo1 = snapshot();
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', metaKey: true, bubbles: true }));
  await sleep(1600);
  out.undo2 = snapshot();
  return JSON.stringify(out);
})()`;

const STALE = `(async () => {
  ${HELPERS}
  window.confirm = () => false; // 「重新定计划」的二次确认：先拒绝，停在横幅上取证
  await sleep(1200);
  await openReshape();
  const out = {};
  out.enter = snapshot();
  out.cover1 = await coverSegment(100);
  out.afterApply = snapshot();

  // 同一部片、media.id 不变，但在核对台删掉一条字幕
  document.querySelectorAll('.sb-item')[2]?.click();
  await sleep(1300);
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete', bubbles: true }));
  await sleep(1300);
  await openReshape();
  out.afterExternalEdit = snapshot();

  // 手动重新分段（这次放行确认）
  window.confirm = () => true;
  btn('重新定计划')?.click();
  await sleep(1600);
  out.afterReplan = snapshot();
  return JSON.stringify(out);
})()`;

const SCENARIOS = { flow: FLOW, stale: STALE };

function ensureFixture() {
  fs.mkdirSync(OUT, { recursive: true });
  if (!fs.existsSync(MEDIA)) {
    // 与 capture_ai_workbench.mjs 共用同一份夹具媒体（20s 纯色片，不随仓库分发）。
    fs.mkdirSync(path.dirname(MEDIA), { recursive: true });
    execFileSync(
      'ffmpeg',
      [
        '-y',
        '-v',
        'error',
        '-f',
        'lavfi',
        '-i',
        'color=c=0x223344:s=640x360:d=20',
        '-pix_fmt',
        'yuv420p',
        '-c:v',
        'libx264',
        '-preset',
        'ultrafast',
        MEDIA,
      ],
      { stdio: 'pipe' },
    );
  }

  const cues = [];
  for (let i = 0; i < 501; i += 1) {
    const start = i * 3.2;
    cues.push({ start, end: start + 2.2, text: `Whisper 第${i + 1}句。` });
  }
  const altCues = [];
  for (let i = 0; i < 516; i += 1) {
    const start = i * 3.11;
    altCues.push({ start, end: start + 2.0, text: `Qwen 第${i + 1}句。` });
  }

  const seedPath = path.join(BASE, 'seed.json');
  fs.writeFileSync(seedPath, JSON.stringify({ mediaPath: MEDIA, cues }, null, 2));
  fs.writeFileSync(path.join(BASE, 'alt.json'), JSON.stringify(altCues));

  const prepare = String.raw`
import hashlib, json
from datetime import datetime
from pathlib import Path
base = Path(${JSON.stringify(BASE)})
out = Path(${JSON.stringify(OUT)})
media = Path(${JSON.stringify(MEDIA)})
alt_cues = json.loads((base / 'alt.json').read_text())
out.mkdir(parents=True, exist_ok=True)
stat = media.stat()
fingerprint = f"{media.resolve()}|{stat.st_size}|{int(stat.st_mtime_ns)}"
key = hashlib.sha1(fingerprint.encode()).hexdigest()[:16]
at = datetime(2026, 11, 15, 15, 0).timestamp()
alt = {
    'version': 1,
    'engine': 'qwen',
    'cues': alt_cues,
    'source': {'kind': 'transcription', 'engine': 'qwen', 'name': 'Qwen3-ASR 转写',
               'path': '', 'job_id': '', 'at': at, 'apply': 'alt_review'},
    'created_at': at,
    'params': {'vad_onset_pad_ms': 400},
    'media_path': str(media),
}
(out / f'{media.stem}.{key}.autosave_draft.alt.json').write_text(
    json.dumps(alt, ensure_ascii=False, indent=2), encoding='utf-8')
`;
  const preparePath = path.join(BASE, 'prepare.py');
  fs.writeFileSync(preparePath, prepare);
  execFileSync('python3', [preparePath], { encoding: 'utf8' });
  return seedPath;
}

function run(scenario) {
  const profile = path.join(BASE, `profile-${scenario}`);
  fs.rmSync(profile, { recursive: true, force: true });
  fs.mkdirSync(profile, { recursive: true });

  const extra = (process.env.KIKUSUB_SHOT_ELECTRON_ARGS || '')
    .split(/\s+/)
    .filter(Boolean);
  const env = {
    ...process.env,
    KIKUSUB_ALLOW_MULTIPLE: '1',
    KIKUSUB_WIN_SIZE: '1360x838',
    KIKUSUB_SHOT_DELAY: '2500',
    KIKUSUB_OUTPUT_DIR: OUT,
    KIKUSUB_DATA_DIR: path.join(BASE, 'data'),
    KIKUSUB_PREFERENCES_PATH: path.join(BASE, 'prefs.json'),
    KIKUSUB_DEV_SEED: ensureFixture(),
    KIKUSUB_DEV_EVAL: SCENARIOS[scenario],
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
        `--screenshot=${path.join(BASE, `${scenario}.png`)}`,
        ...extra,
      ],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 180_000 },
    ).toString();
  } catch (error) {
    stdout = `${error.stdout ?? ''}`;
    console.error(String(error.stderr ?? '').slice(-800));
  }
  const line = stdout
    .split('\n')
    .filter((row) => row.startsWith('[eval]'))
    .pop();
  if (!line) throw new Error(`${scenario}：渲染进程没有回传结果`);
  return JSON.parse(line.slice('[eval] '.length));
}

const failures = [];
function check(name, condition, detail) {
  if (condition) {
    console.log(`  ✓ ${name}`);
  } else {
    failures.push(`${name}${detail ? ` → ${detail}` : ''}`);
    console.error(`  ✗ ${name}${detail ? ` → ${detail}` : ''}`);
  }
}

function assertFlow(data) {
  const segs = data.enter.rail.length;
  check('进页切成 4 段', segs === 4, JSON.stringify(data.enter.rail));
  check('切单源不动段轨', JSON.stringify(data.single.rail) === JSON.stringify(data.enter.rail));
  check('切回双源不动段轨', JSON.stringify(data.dualAgain.rail) === JSON.stringify(data.enter.rail));
  check('覆盖第 1 段后仍是 4 段', data.after1.rail.length === 4, JSON.stringify(data.after1.rail));
  check('覆盖第 1 段后已覆盖 1/4', data.after1.chip === '已覆盖 1/4 段', data.after1.chip);
  check('覆盖第 2 段后已覆盖 2/4', data.after2.chip === '已覆盖 2/4 段', data.after2.chip);
  // 旧代码在这里掉成 3 段、勾全掉
  check(
    '覆盖两段后切单源→双源：段轨一个数字都不变',
    JSON.stringify(data.afterToggle.rail) === JSON.stringify(data.after2.rail),
    `${JSON.stringify(data.after2.rail)} vs ${JSON.stringify(data.afterToggle.rail)}`,
  );
  check('覆盖两段后切源：勾还在', JSON.stringify(data.afterToggle.done) === JSON.stringify(data.after2.done));
  check('⌘Z 一次：勾退到 1/4', data.undo1.chip === '已覆盖 1/4 段', data.undo1.chip);
  check(
    '⌘Z 一次：第 2 段条数回到覆盖前',
    data.undo1.rail[1] === data.enter.rail[1],
    `${data.enter.rail[1]} vs ${data.undo1.rail[1]}`,
  );
  check('⌘Z 两次：回到 0/4', data.undo2.chip === '已覆盖 0/4 段', data.undo2.chip);
  check(
    '⌘Z 两次：段轨回到进页时的样子',
    JSON.stringify(data.undo2.rail) === JSON.stringify(data.enter.rail),
    JSON.stringify(data.undo2.rail),
  );
  check('全程没有误报失效横幅', !data.afterToggle.banner && !data.undo1.banner);
}

function assertStale(data) {
  check('覆盖 1 段后已覆盖 1/4', data.afterApply.chip === '已覆盖 1/4 段', data.afterApply.chip);
  check('覆盖 1 段后没有失效横幅', !data.afterApply.banner);
  check('外部改动后出失效横幅', data.afterExternalEdit.banner.includes('分段计划已失效'));
  check(
    '失效时不静默重切（段轨仍是 4 段）',
    data.afterExternalEdit.rail.length === 4,
    JSON.stringify(data.afterExternalEdit.rail),
  );
  check('失效时覆盖率不变（1/4）', data.afterExternalEdit.chip === '已覆盖 1/4 段');
  check('失效时复制提示词被暂停', data.afterExternalEdit.copyDisabled === true);
  check('失效时不提供会错位的「恢复上一版分段」', data.afterExternalEdit.restoreVisible === false);
  check('失效时给「重新定计划」出口', data.afterExternalEdit.replanVisible === true);
  check('重新定计划后横幅消失', !data.afterReplan.banner);
  check('重新定计划后回到 0 覆盖', data.afterReplan.chip === '已覆盖 0/3 段', data.afterReplan.chip);
}

const wanted = (() => {
  const argv = process.argv.slice(2);
  const index = argv.indexOf('--scenario');
  if (index < 0) return Object.keys(SCENARIOS);
  const name = argv[index + 1];
  if (!SCENARIOS[name]) throw new Error(`未知场景：${name}`);
  return [name];
})();

for (const scenario of wanted) {
  console.log(`\n[${scenario}]`);
  const data = run(scenario);
  if (scenario === 'flow') assertFlow(data);
  else assertStale(data);
}

console.log('');
if (failures.length) {
  console.error(`${failures.length} 项断言失败`);
  process.exit(1);
}
console.log('全部通过');
