#!/usr/bin/env node
/**
 * 双引擎复核「对照范围」回归（2026-11-26 真机报障）。
 *
 * 现场：第 1、2 章字幕已进核对台，第 3 章用「两版一起 + 替换选区」跑完，
 * 于是 A = 1–3 章 636 条（00:13–55:36）、B = 第 3 章 220 条（35:58–55:36）。
 *
 * 这个脚本在**真实界面**里造出同一份现场并断言：
 *
 *   1. 进页面默认聚焦「章节三」，页头两个数字是**本段**的 223 / 220，
 *      不是整片的 636 / 220；
 *   2. 页头横幅写明「当前聚焦：章节三 · 35:53–55:41（已隐去范围外 A 413 条）」；
 *   3. 统计片与侧栏徽标只算本段（不再出现 400 多条「仅 A」假差异）；
 *   4. 切到「全片」才出现那批假差异，切回章节三又消失；
 *   5. 写回按钮在当前范围下叫「用 B 替换当前范围」（不是「覆盖核对台」）；
 *   6. 点它之后前两章 413 条**一条不少**，章节三被换成 B 的 220 条，
 *      ⌘Z 一次退回原状。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），不弹窗；
 * 会弹原生对话框的动作一律用 `window.confirm` 打桩（脚本里替掉它，不点系统按钮）。
 *
 * 用法：
 *   node tools/shots/verify_dual_scope.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_dual_scope.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-dual-scope');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');
const SHOT = path.join(BASE, 'dual-scope.png');

/** 三章时间轴（秒）：用户现场的第三段就是 35:53.364–55:41.072。 */
const CH1 = [13.0, 1380.0];
const CH2 = [1380.0, 2153.0];
const CH3 = [2153.364, 3341.072];

const CHAPTERS = [
  { id: 'ch-1', title: '章节一', start: CH1[0], end: CH1[1] },
  { id: 'ch-2', title: '章节二', start: CH2[0], end: CH2[1] },
  { id: 'ch-3', title: '章节三', start: CH3[0], end: CH3[1] },
];

/** 在 [start, end) 里均匀铺 count 条字幕。 */
function fill(start, end, count, prefix) {
  const step = (end - start) / count;
  return Array.from({ length: count }, (_, i) => ({
    start: Number((start + i * step).toFixed(3)),
    end: Number((start + i * step + 1.5).toFixed(3)),
    text: `${prefix}${i}`,
  }));
}

/**
 * 现场：A 累积 1–3 章 636 条；B 是章节三 220 条（去掉首 2 末 1），
 * 与 A 同一句的时间轴差一丝、每 7 行一处听写分歧（真实双引擎的样子）。
 */
function scene() {
  const ch3 = fill(CH3[0], CH3[1], 223, 'a3-');
  const a = [...fill(CH1[0], CH1[1], 200, 'a1-'), ...fill(CH2[0], CH2[1], 213, 'a2-'), ...ch3];
  const b = ch3.slice(2, -1).map((cue, i) => ({
    start: Number((cue.start + 0.12).toFixed(3)),
    end: Number((cue.end + 0.03).toFixed(3)),
    text: i % 7 ? cue.text.replace('a3-', 'b3-') : `${cue.text.replace('a3-', 'b3-')}-聞き違い`,
  }));
  return { a, b };
}

function srtOf(cues) {
  const clock = (s) => {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = (s % 60).toFixed(3).padStart(6, '0');
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${sec}`;
  };
  return cues
    .map((cue, i) => `${i + 1}\n${clock(cue.start)} --> ${clock(cue.end)}\n${cue.text}\n`)
    .join('\n');
}

/**
 * 片源必须**长过第三章**（3341s ≈ 55:41）。
 *
 * 章节归一化会把 `end` 夹到片长：种子用的是 8 秒的占位片时，`loadChapters` /
 * `saveChapters` 会把「章节三 35:53–55:41」直接夹成 0–8 秒并丢掉整章，
 * 于是复核页永远聚焦不到章节三。1 fps 的纯色片 5 分钟就生成完、不到 100KB。
 */
function ensureMedia() {
  if (fs.existsSync(MEDIA)) {
    const probe = execFileSync('ffprobe', [
      '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', MEDIA,
    ]).toString();
    if (Number(probe) >= 3400) return;
  }
  fs.mkdirSync(BASE, { recursive: true });
  execFileSync('ffmpeg', [
    '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x223344:s=160x90:r=1:d=3400',
    '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', '-g', '300', MEDIA,
  ]);
}

function ensureFixtures() {
  const { a, b } = scene();
  const seedPath = path.join(BASE, 'seed.json');
  fs.writeFileSync(
    seedPath,
    JSON.stringify({ mediaPath: MEDIA, cues: a, chapters: CHAPTERS }, null, 2),
    'utf8',
  );
  const bPath = path.join(BASE, 'chapter3.srt');
  fs.writeFileSync(bPath, srtOf(b), 'utf8');
  return { seedPath, bPath };
}

const evalScript = (bPath) => `
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const until = async (fn, ms = 20000) => {
      const end = Date.now() + ms;
      while (Date.now() < end) {
        const hit = await fn();
        if (hit) return hit;
        await sleep(120);
      }
      return null;
    };
    const text = (el) => (el ? el.textContent.replace(/\\s+/g, ' ').trim() : null);
    const q = (sel) => document.querySelector(sel);
    const sidecar = await window.kikusub.getSidecar();
    const sid = localStorage.getItem('kikusub.sid') || '';
    const H = {
      Authorization: 'Bearer ' + sidecar.token,
      'Content-Type': 'application/json',
      'X-Kikusub-Session': sid,
    };
    const api = (p, init) => fetch('http://127.0.0.1:' + sidecar.port + p, { headers: H, ...init });
    const json = (p, init) => api(p, init).then((r) => r.json());

    // 等 dev seed 把媒体与 636 条主稿灌进会话
    await until(async () => {
      const st = await json('/api/cues').catch(() => ({}));
      return Array.isArray(st.cues) && st.cues.length === 636;
    });

    // 导入 B（只有章节三的 220 条）——走产品自己的导入接口
    const imported = await api('/api/alt-review/import', {
      method: 'POST',
      body: JSON.stringify({ path: ${JSON.stringify(bPath)} }),
    });
    if (!imported.ok) {
      return JSON.stringify({ error: '导入 B 失败', status: imported.status, detail: (await imported.text()).slice(0, 300) });
    }

    // 进双引擎复核页（侧栏第 4 项）
    document.querySelectorAll('.sb-item')[3]?.click();
    const ready = await until(() => q('.list .row') || q('.scope-banner'));
    if (!ready) {
      return JSON.stringify({ error: '复核页没有落地', title: q('.tb-title')?.textContent, body: document.body.className });
    }
    await sleep(800);

    const readScope = () => {
      const tabs = [...document.querySelectorAll('.scope-tab')].map((el) => text(el));
      const active = document.querySelector('.scope-tab.on');
      const banner = text(q('.scope-banner'));
      const chips = [...document.querySelectorAll('.chip')].map((el) => text(el));
      const ver = [...document.querySelectorAll('.ver')].map((el) => text(el));
      const replace = document.querySelector('.btn.overwrite');
      const badge = text(document.querySelector('.sb-item.alt .sb-badge, .sb-item:nth-child(4) .sb-badge'));
      return {
        tabs,
        active: text(active),
        banner,
        chips,
        ver,
        replaceLabel: text(replace),
        replaceTitle: replace?.getAttribute('title') ?? '',
        rows: document.querySelectorAll('.list .row').length,
        scopeChip: text(q('.scope-chip')),
        badge,
      };
    };

    const out = { scoped: readScope() };

    // 切到全片：那 400 多条假差异才该出现
    const allTab = [...document.querySelectorAll('.scope-tab')].find((el) => (text(el) || '').startsWith('全片'));
    allTab?.click();
    await until(() => (text(q('.scope-tab.on')) || '').startsWith('全片'));
    await sleep(700);
    out.whole = readScope();

    // 切回章节三
    const chTab = [...document.querySelectorAll('.scope-tab')].find((el) => (text(el) || '').startsWith('章节三'));
    chTab?.click();
    await until(() => (text(q('.scope-tab.on')) || '').startsWith('章节三'));
    await sleep(700);
    out.back = readScope();

    // 写回：window.confirm 打桩（脚本里不点系统按钮），并记录弹窗文案
    const confirms = [];
    const realConfirm = window.confirm;
    window.confirm = (msg) => {
      confirms.push(String(msg));
      return true;
    };
    const before = await json('/api/cues');
    const replaceBtn = document.querySelector('.btn.overwrite');
    out.replaceLabelBeforeClick = text(replaceBtn);
    replaceBtn?.click();
    const wrote = await until(async () => {
      const now = await json('/api/cues');
      return Array.isArray(now.cues) && now.cues.length !== before.cues.length ? now : null;
    }, 15000);
    window.confirm = realConfirm;
    out.confirms = confirms;
    out.after = {
      count: wrote?.cues?.length ?? null,
      firstTwoChaptersIntact:
        !!wrote && wrote.cues.slice(0, 413).every((cue, i) => cue.text === before.cues[i].text),
      chapter3FromB: !!wrote && wrote.cues.filter((cue) => cue.text.startsWith('b3-')).length,
      chapter3FromA: !!wrote && wrote.cues.filter((cue) => cue.text.startsWith('a3-')).length,
    };

    // ⌘Z 一次退回
    await api('/api/cues/undo', { method: 'POST' });
    const undone = await json('/api/cues');
    out.undo = {
      count: undone?.cues?.length ?? null,
      restored: !!undone && undone.cues.every((cue, i) => cue.text === before.cues[i]?.text),
    };

    // 收尾回到复核页并停在「章节三」：截图要拍的是用户看到的那个画面
    // （写回后 setView('review') 会离开本页，不切回来就拍到核对台）。
    document.querySelectorAll('.sb-item')[3]?.click();
    await until(() => q('.scope-banner'), 10000);
    await sleep(1200);
    out.finalShot = readScope();

    return JSON.stringify(out);
  })()
`;

function run(bPath, theme, appearance) {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  const profile = path.join(BASE, `profile-${theme}-${appearance}`);
  fs.rmSync(profile, { recursive: true, force: true });
  fs.mkdirSync(profile, { recursive: true });

  const extra = (process.env.KIKUSUB_SHOT_ELECTRON_ARGS || '').split(/\s+/).filter(Boolean);
  const themeEval =
    `document.documentElement.dataset.palette='${theme}'` +
    `;localStorage.setItem('kikusub.palette','${theme}')` +
    `;document.documentElement.dataset.theme='${appearance}'` +
    `;localStorage.setItem('kikusub.appearance','${appearance}');`;
  const env = {
    ...process.env,
    KIKUSUB_ALLOW_MULTIPLE: '1',
    KIKUSUB_WIN_SIZE: '1360x838',
    KIKUSUB_SHOT_DELAY: '3200',
    KIKUSUB_OUTPUT_DIR: path.join(BASE, `data-${theme}-${appearance}`, 'out'),
    KIKUSUB_DATA_DIR: path.join(BASE, `data-${theme}-${appearance}`),
    KIKUSUB_PREFERENCES_PATH: path.join(BASE, 'prefs.json'),
    KIKUSUB_DEV_SEED: path.join(BASE, 'seed.json'),
    KIKUSUB_DEV_EVAL: themeEval + evalScript(bPath),
  };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.NODE_OPTIONS;

  const shot = SHOT.replace('.png', `-${theme}-${appearance}.png`);
  let stdout = '';
  try {
    stdout = execFileSync(
      'npx',
      ['electron', '.', `--user-data-dir=${profile}`, `--screenshot=${shot}`, ...extra],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 300_000 },
    ).toString();
  } catch (error) {
    stdout = `${error.stdout ?? ''}`;
    console.error(String(error.stderr ?? '').slice(-900));
  }
  const line = stdout.split('\n').filter((row) => row.startsWith('[eval]')).pop();
  if (!line) throw new Error(`渲染进程没有回传结果（${theme}/${appearance}）`);
  return { data: JSON.parse(line.slice('[eval] '.length)), shot };
}

const failures = [];
function check(name, condition, detail) {
  if (condition) console.log(`  ✓ ${name}`);
  else {
    failures.push(`${name}${detail === undefined ? '' : ` → ${JSON.stringify(detail)}`}`);
    console.error(`  ✗ ${name} → ${JSON.stringify(detail)}`);
  }
}

function main() {
  ensureMedia();
  const { bPath } = ensureFixtures();
  // 主口径跑两套色板；额外的深浅组合只在需要时用环境变量加跑（时间 × 次数）
  const combos = (process.env.KIKUSUB_SCOPE_COMBOS || 'cobalt/light,catppuccin/light')
    .split(',')
    .map((pair) => pair.split('/'));

  for (const [theme, appearance] of combos) {
    console.log(`\n[${theme} / ${appearance}]`);
    const { data, shot } = run(bPath, theme, appearance);
    if (data.error) {
      failures.push(`${theme}/${appearance} 运行失败：${data.error}`);
      console.error(JSON.stringify(data, null, 2));
      continue;
    }
    const scoped = data.scoped;
    check('默认聚焦章节三', (scoped.active || '').startsWith('章节三'), scoped.active);
    check(
      '页头两个数字是本段的（223 / 220），不是整片的',
      scoped.ver.some((v) => v.includes('223')) && scoped.ver.some((v) => v.includes('220')),
      scoped.ver,
    );
    check('横幅写明聚焦与隐去条数', /当前聚焦：章节三/.test(scoped.banner || '') && /已隐去范围外 A 413 条/.test(scoped.banner || ''), scoped.banner);
    check('统计片只算本段（「仅 A」不多）', (() => {
      const onlyA = scoped.chips.find((c) => c.includes('仅 A')) || '';
      const n = Number((onlyA.match(/(\d+)/) || [])[1] ?? 999);
      return n <= 3;
    })(), scoped.chips);
    check('列表按本段渲染（≥220 行）', scoped.rows >= 220, scoped.rows);
    check('写回按钮叫「用 B 替换当前范围」', scoped.replaceLabel === '用 B 替换当前范围', scoped.replaceLabel);
    check('写回按钮的 title 提到「其它章节一条不动」', /其它章节一条不动/.test(scoped.replaceTitle || ''), scoped.replaceTitle);

    check('切到全片后出现那批「仅 A」假差异', (() => {
      const onlyA = data.whole.chips.find((c) => c.includes('仅 A')) || '';
      const n = Number((onlyA.match(/(\d+)/) || [])[1] ?? 0);
      return n === 416;
    })(), data.whole.chips);
    check('全片口径下按钮仍是范围替换（不给整列覆盖）', data.whole.replaceLabel === '用 B 替换当前范围', data.whole.replaceLabel);
    check('切回章节三后假差异消失', (() => {
      const onlyA = data.back.chips.find((c) => c.includes('仅 A')) || '';
      const n = Number((onlyA.match(/(\d+)/) || [])[1] ?? 999);
      return n <= 3;
    })(), data.back.chips);

    check(
      '二次确认讲清范围与窗口外条数',
      /只换窗口内的 220 条/.test(data.confirms[0] || '') &&
        /窗口外的 413 条（其它章节）一条不动/.test(data.confirms[0] || ''),
      data.confirms,
    );
    check('写回后总条数 = 413 + 220', data.after.count === 633, data.after.count);
    check('前两章 413 条原样保留', data.after.firstTwoChaptersIntact === true);
    check('章节三换成 B 的 220 条', data.after.chapter3FromB === 220, data.after.chapter3FromB);
    check('章节三的旧 A 一条不剩', data.after.chapter3FromA === 0, data.after.chapter3FromA);
    check('⌘Z 一次退回原状', data.undo.count === 636 && data.undo.restored === true, data.undo);

    if (fs.existsSync(shot)) console.log(`\n截图：${shot}`);
    else console.error(`\n截图缺失：${shot}`);
  }

  if (failures.length) {
    console.error(`\n双引擎对照范围回归：${failures.length} 项失败`);
    process.exit(1);
  }
  console.log('\n双引擎对照范围回归：全部通过');
}

main();
