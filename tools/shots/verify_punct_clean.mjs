#!/usr/bin/env node
/**
 * 「清理标点」复现回归：2026-11-17 用户报障的两类行。
 *
 * 现场（截图为证）：
 *   34  `大きく深呼吸してみましょうか。 吸って…`   ← 句中句号 + 行尾省略号
 *   35  `吐いて、もう一回`                        ← 句中顿号
 * 旧口径下第一行「点了没反应」（省略号默认保留），第二行只是把顿号换成一个空格
 * （全角空格模式下看着跟没清一样）。这个脚本在**真实界面**里断言：
 *
 *   1. 两行都进了「会改」统计，预览里 before→after 就是期望的样子；
 *   2. 省略号默认只清行尾——`あの…そう` 不动，切到「全部删」才动；
 *   3. 句中口径切到「全角空格」（旧口径）时，预览里是 `吐いて　もう一回`；
 *   4. 偏好落在 `kikusub.punctClean.v2`，不再读 v1。
 *
 * 走主进程自带的 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现，跑完自己退出。断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_punct_clean.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_punct_clean.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-punct-verify');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');

/** 用户截图里的那几句 + 两个反例（句中省略号、英文粘连）。 */
const CUES = [
  { start: 0.0, end: 1.4, text: '吐いて、もう一回' },
  { start: 1.5, end: 3.0, text: '大きく深呼吸してみましょうか。 吸って…' },
  { start: 3.1, end: 4.4, text: 'Thank you、またね' },
  { start: 4.5, end: 5.6, text: 'あの…そう' },
  { start: 5.7, end: 6.9, text: '先生、お願いします' },
];

const EXPECT = {
  /** 默认口径：4 条会改、行尾 1 处、句中 4 处。 */
  count: 4,
  endMarks: '行尾 1 处',
  midMarks: '句中 4 处',
  after: ['吐いてもう一回', '大きく深呼吸してみましょうか吸って', 'Thank you またね'],
  fullSpaceAfter: '吐いて　もう一回',
  /** 切「全部删」后 `あの…そう` 也进统计。 */
  allCount: 5,
  prefsKey: 'kikusub.punctClean.v2',
};

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const text = (el) => (el ? el.textContent.trim() : null);
    const panel = () => document.querySelector('.punct-panel');
    const stat = () => text(document.querySelector('.pp-stat'));
    const previews = () =>
      [...document.querySelectorAll('.pp-line')].map((line) => ({
        before: text(line.querySelector('.pp-old')),
        after: text(line.querySelector('.pp-new')),
        hit: [...line.querySelectorAll('.pp-old .del')].map((s) => s.textContent).join(''),
      }));
    const seg = (row) => [...document.querySelectorAll('.pp-seg')][row];
    const pick = (row, index) => seg(row).querySelectorAll('button')[index].click();

    document.querySelector('[data-punct-trigger]').click();
    await sleep(250);

    const out = { opened: Boolean(panel()), stat: stat(), previews: previews() };

    // 旧口径：句中换全角空格
    pick(0, 2);
    await sleep(200);
    out.fullSpace = { stat: stat(), previews: previews() };

    // 回到默认口径
    pick(0, 0);
    await sleep(200);

    // 省略号：全部删 → 句中省略号那条也进统计
    pick(1, 1);
    await sleep(200);
    out.allEllipsis = { stat: stat(), previews: previews() };

    // 回到默认（行尾删），停在默认状态截图
    pick(1, 0);
    await sleep(250);
    out.back = { stat: stat(), previews: previews() };
    out.prefs = localStorage.getItem('kikusub.punctClean.v2');
    out.legacyPrefs = localStorage.getItem('kikusub.punctClean');
    return JSON.stringify(out);
  })()
`;

function ensureMedia() {
  if (fs.existsSync(MEDIA)) return;
  fs.mkdirSync(BASE, { recursive: true });
  execFileSync('ffmpeg', [
    '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x223344:s=640x360:d=8',
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
        `--screenshot=${path.join(BASE, 'punct-clean.png')}`,
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

  check('面板能打开', data.opened === true);
  check(
    `默认口径：${EXPECT.count} 条会改`,
    (data.stat || '').includes(`${EXPECT.count} 条`),
    data.stat,
  );
  check('统计含「行尾 1 处」', (data.stat || '').includes(EXPECT.endMarks), data.stat);
  check('统计含「句中 4 处」', (data.stat || '').includes(EXPECT.midMarks), data.stat);

  const [first, second, third] = data.previews ?? [];
  check('预览 1 原文是句中顿号那句', first?.before === '吐いて、もう一回', JSON.stringify(first));
  check('预览 1 结果：顿号直接删掉', first?.after === EXPECT.after[0], JSON.stringify(first));
  check('预览 1 顿号被标红', first?.hit === '、', JSON.stringify(first));
  check(
    '预览 2 结果：句中句号删、行尾省略号清',
    second?.after === EXPECT.after[1],
    JSON.stringify(second),
  );
  check('预览 2 行尾省略号被标红', (second?.hit || '').includes('…'), JSON.stringify(second));
  check('预览 3 结果：英文旁补一个空格', third?.after === EXPECT.after[2], JSON.stringify(third));

  const full = data.fullSpace?.previews?.[0];
  check('旧口径可选：全角空格', full?.after === EXPECT.fullSpaceAfter, JSON.stringify(full));

  check(
    `省略号「全部删」：${EXPECT.allCount} 条会改`,
    (data.allEllipsis?.stat || '').includes(`${EXPECT.allCount} 条`),
    data.allEllipsis?.stat,
  );
  check(
    '回到默认口径后统计复原',
    (data.back?.stat || '').includes(`${EXPECT.count} 条`),
    data.back?.stat,
  );

  const prefs = data.prefs ? JSON.parse(data.prefs) : null;
  check(
    '偏好落在 v2 键且是 {mid:delete, ellipsis:trailing}',
    prefs?.mid === 'delete' && prefs?.ellipsis === 'trailing',
    data.prefs,
  );
  check('不再写 v1 键', data.legacyPrefs === null, data.legacyPrefs);

  const shot = path.join(BASE, 'punct-clean.png');
  if (fs.existsSync(shot)) console.log(`\n截图：${shot}`);
  else console.error('\n截图缺失（--screenshot 没跑通？）');

  if (failures.length) {
    console.error(`\n${failures.length} 项失败`);
    process.exit(1);
  }
  console.log('\n全部通过');
}

main();
