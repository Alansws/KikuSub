#!/usr/bin/env node
/**
 * 「清理标点」复现回归：2026-11-17 原料文报障 + 2026-11-25 译文轨接入。
 *
 * 现场（截图为证）：
 *   34  `大きく深呼吸してみましょうか。 吸って…`   ← 句中句号 + 行尾省略号
 *   35  `吐いて、もう一回`                        ← 句中顿号
 *   译文 `啊，，别` / `呼…刚刚好舒服。`            ← 译文轨也要能清，但不能按日语规则清
 *
 * 这个脚本在**真实界面**里断言：
 *
 *   1. 原文默认口径：4 条会改、行尾 1 处、句中 4 处，预览 before→after 正确；
 *   2. 省略号「全部删」时句中的 `あの…そう` 也进统计；
 *   3. 译文轨：只清行尾与连续重复，句中 `…` 与 `！` 原样保留；
 *   4. 「清理哪一轨」可切 原文 / 两轨；两轨一起清只发一个请求；
 *   5. 应用后两轨同时落盘，按一次撤销两轨一起回去；
 *   6. 偏好落在 `kikusub.punctClean.v3`。
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

/** 译文轨：第 1 条折叠重复、第 2/3 条清行尾；第 4 条 `！` 与第 5 条原样保留。 */
const ZH = ['啊，，别', '呼…刚刚好舒服。', '谢谢你，再见。', '别碰我！', '（停顿）'];

const EXPECT = {
  /** 原文默认口径：4 条会改、行尾 1 处、句中 4 处。 */
  sourceCount: 4,
  endMarks: '行尾 1 处',
  midMarks: '句中 4 处',
  after: ['吐いてもう一回', '大きく深呼吸してみましょうか吸って', 'Thank you またね'],
  fullSpaceAfter: '吐いて　もう一回',
  /** 切「全部删」后 `あの…そう` 也进统计。 */
  allCount: 5,
  /** 译文默认：3 条会改（折叠 1 + 行尾 2），问号感叹号不动。 */
  targetCount: 3,
  targetSub: '行尾 2 处 · 重复 1 处',
  targetAfter: ['啊，别', '呼…刚刚好舒服'],
  totalBoth: 7,
  /** 译文「重复标点：不动」后只剩两条行尾要清。 */
  targetNoCollapse: 2,
  prefsKey: 'kikusub.punctClean.v3',
};

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
    const panel = () => document.querySelector('.punct-panel');
    const stats = () =>
      [...document.querySelectorAll('.pp-stat')].map((row) => text(row));
    const previews = () =>
      [...document.querySelectorAll('.pp-line')].map((line) => ({
        before: text(line.querySelector('.pp-old')),
        after: text(line.querySelector('.pp-new')),
        hit: [...line.querySelectorAll('.pp-old .del')].map((s) => s.textContent).join(''),
      }));
    const segBy = (label) =>
      [...document.querySelectorAll('.pp-seg')].find(
        (seg) => seg.getAttribute('aria-label') === label,
      );
    const pick = (label, index) =>
      segBy(label)?.querySelectorAll('button')[index]?.click();
    const rows = () => [...document.querySelectorAll('.row')];
    const srcLine = (i) => text(rows()[i]?.querySelector('.c-text > .line:not(.sub)'));
    const subLine = (i) => text(rows()[i]?.querySelector('.c-text > .line.sub'));
    const toast = () => text(document.querySelector('.toast'));

    if (!(await until(() => rows().length >= 5 && document.querySelector('.line.sub')))) {
      return JSON.stringify({ error: '种子没有落地', rows: rows().length });
    }
    await sleep(300);

    document.querySelector('[data-punct-trigger]').click();
    await sleep(250);

    const out = { opened: Boolean(panel()), stats: stats(), previews: previews() };

    // 旧口径（原文）：句中换全角空格
    pick('句中标记处理方式', 2);
    await sleep(200);
    out.fullSpace = { stats: stats(), previews: previews() };
    pick('句中标记处理方式', 0);
    await sleep(200);

    // 原文：省略号「全部删」→ 句中的省略号那条也进统计
    pick('省略号处理方式', 1);
    await sleep(200);
    out.allEllipsis = { stats: stats(), previews: previews() };
    pick('省略号处理方式', 0);
    await sleep(200);

    // 译文：重复标点「不动」→ 只剩两条行尾
    pick('译文重复标点处理方式', 1);
    await sleep(200);
    out.targetNoCollapse = { stats: stats() };
    pick('译文重复标点处理方式', 0);
    await sleep(200);

    // 「清理哪一轨」：只清原文 → 统计只剩一行；再切回两轨
    pick('清理哪一轨', 0);
    await sleep(200);
    out.sourceOnly = { stats: stats() };
    pick('清理哪一轨', 2);
    await sleep(250);
    out.back = { stats: stats(), previews: previews() };

    // 应用：两轨一次提交
    document.querySelector('.pp-foot button.primary').click();
    await until(() => (toast() ?? '').includes('已清理'));
    out.applyToast = toast();
    await sleep(700);
    out.afterApply = { src: [srcLine(0), srcLine(1)], sub: [subLine(0), subLine(1)] };

    // 撤销：一步退回两轨
    const undo = [...document.querySelectorAll('button')].find((b) =>
      (b.getAttribute('title') ?? '').startsWith('撤回：'),
    );
    undo?.click();
    await sleep(900);
    out.afterUndo = { src: [srcLine(0), srcLine(3)], sub: [subLine(0), subLine(1)] };

    // 停在面板展开态：截图本身就是「两轨口径 + 双份统计/预览」的取证
    document.querySelector('[data-punct-trigger]').click();
    await sleep(400);
    out.reopened = Boolean(panel());
    out.prefs = localStorage.getItem('kikusub.punctClean.v3');
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
  if (process.env.KIKUSUB_VERIFY_DEBUG) console.error(stdout.slice(-4000));
  const line = stdout.split('\n').filter((row) => row.startsWith('[eval]')).pop();
  if (!line) throw new Error('渲染进程没有回传结果');
  return JSON.parse(line.slice('[eval] '.length));
}

const failures = [];
function check(name, condition, detail) {
  if (condition) console.log(`  ✓ ${name}`);
  else {
    failures.push(`${name}${detail ? ` → ${typeof detail === 'string' ? detail : JSON.stringify(detail)}` : ''}`);
    console.error(`  ✗ ${name}${detail ? ` → ${typeof detail === 'string' ? detail : JSON.stringify(detail)}` : ''}`);
  }
}
const has = (value, part) => String(value ?? '').includes(part);

function main() {
  ensureMedia();
  const data = run();
  if (data.error) throw new Error(`${data.error}（${JSON.stringify(data)}）`);

  check('面板能打开', data.opened === true);
  check('撤销后还能重新打开面板', data.reopened === true);

  // ---- 原文轨（历史口径不许动）
  check(
    `原文默认口径：${EXPECT.sourceCount} 条会改`,
    has(data.stats?.[0], `${EXPECT.sourceCount} 条`),
    data.stats,
  );
  check('原文统计含「行尾 1 处」', has(data.stats?.[0], EXPECT.endMarks), data.stats?.[0]);
  check('原文统计含「句中 4 处」', has(data.stats?.[0], EXPECT.midMarks), data.stats?.[0]);

  const [first, second, third] = data.previews ?? [];
  check('预览 1 原文是句中顿号那句', first?.before === CUES[0].text, first);
  check('预览 1 结果：顿号直接删掉', first?.after === EXPECT.after[0], first);
  check('预览 1 顿号被标红', first?.hit === '、', first);
  check('预览 2 结果：句中句号删、行尾省略号清', second?.after === EXPECT.after[1], second);
  check('预览 2 行尾省略号被标红', (second?.hit || '').includes('…'), second);
  check('预览 3 结果：英文旁补一个空格', third?.after === EXPECT.after[2], third);

  const full = data.fullSpace?.previews?.[0];
  check('旧口径可选：全角空格', full?.after === EXPECT.fullSpaceAfter, full);
  check(
    `省略号「全部删」：${EXPECT.allCount} 条会改`,
    has(data.allEllipsis?.stats?.[0], `${EXPECT.allCount} 条`),
    data.allEllipsis?.stats,
  );

  // ---- 译文轨（2026-11-25 新增）
  check(
    `译文默认口径：${EXPECT.targetCount} 条会改`,
    has(data.stats?.[1], `${EXPECT.targetCount} 条译文`),
    data.stats,
  );
  check('译文统计含「行尾 2 处 · 重复 1 处」', has(data.stats?.[1], EXPECT.targetSub), data.stats?.[1]);
  const previewList = data.previews ?? [];
  const previewOf = (text) => previewList.find((item) => item.before === text);
  const fold = previewOf(ZH[0]);
  const trail = previewOf(ZH[1]);
  check(
    '译文预览：重复标点折叠、行尾句号清掉',
    fold?.after === EXPECT.targetAfter[0] &&
      fold?.hit === '，' &&
      trail?.after === EXPECT.targetAfter[1] &&
      trail?.hit === '。',
    { fold, trail },
  );
  check(
    '译文预览：句中省略号与 ！ 不动',
    (trail?.after || '').includes('…') &&
      previewList.every((item) => item.before !== ZH[3]),
    previewList,
  );
  check(
    `译文「重复标点：不动」后只剩 ${EXPECT.targetNoCollapse} 条`,
    has(data.targetNoCollapse?.stats?.[1], `${EXPECT.targetNoCollapse} 条译文`),
    data.targetNoCollapse?.stats,
  );

  // ---- 轨道选择
  check('只清原文时统计只剩一行', data.sourceOnly?.stats?.length === 1, data.sourceOnly?.stats);
  check(
    '回到两轨：合计 7 条',
    has(data.back?.stats?.[0], `${EXPECT.sourceCount} 条`) &&
      has(data.back?.stats?.[1], `${EXPECT.targetCount} 条`),
    data.back?.stats,
  );

  // ---- 一步提交 / 一步撤销
  check(
    '应用 toast 报出两轨条数',
    has(data.applyToast, `原文 ${EXPECT.sourceCount} 条`) &&
      has(data.applyToast, `译文 ${EXPECT.targetCount} 条`),
    data.applyToast,
  );
  check(
    '两轨都落盘',
    data.afterApply?.src?.[0] === EXPECT.after[0] &&
      data.afterApply?.sub?.[0] === EXPECT.targetAfter[0] &&
      data.afterApply?.sub?.[1] === EXPECT.targetAfter[1],
    data.afterApply,
  );
  check(
    '一次撤销两轨一起回去',
    data.afterUndo?.src?.[0] === CUES[0].text &&
      data.afterUndo?.sub?.[0] === ZH[0] &&
      data.afterUndo?.sub?.[1] === ZH[1],
    data.afterUndo,
  );

  const prefs = data.prefs ? JSON.parse(data.prefs) : null;
  check(
    '偏好落在 v3 键且口径正确',
    prefs?.mid === 'delete' &&
      prefs?.ellipsis === 'trailing' &&
      prefs?.tracks === 'both' &&
      prefs?.targetEllipsis === true &&
      prefs?.targetCollapse === true,
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
