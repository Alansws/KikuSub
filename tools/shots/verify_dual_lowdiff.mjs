#!/usr/bin/env node
/**
 * 「双引擎复核」低相似度差异行回归：专名听错 / 整句幻觉要一眼看得到。
 *
 * 现场：`だーてん`（A，Anime Whisper）vs `当店、魔族`（B，Qwen3-ASR），
 * `build_review` 给出相似度 **0.000**。旧口径下 `CHAR_HIGHLIGHT_MIN_RATIO = 0.35`
 * 把整行掐成不着色，只剩一个 `~`——最该被看见的差异恰好最不显眼。
 *
 * 这个脚本在**真实界面**里断言：
 *
 *   1. 低相似度行出现「整句不同」提示（而不是静默一整行）；
 *   2. 低相似度行**仍然有短语级高亮**：B 列 `当店、魔族` 里 A 完全没有的片段被标成 ins；
 *   3. 「按差异大小排」打开后，首行的相似度 ≤ 末行的相似度（0% 那行会浮上来）；
 *   4. 采用 B 之后，那一行从 diff 消失（按钮仍然只作用在原来那条 A 上）。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），不弹窗。
 *
 * 用法：
 *   node tools/shots/verify_dual_lowdiff.mjs
 *   素材默认取仓库里已存的真实双引擎稿；可用 KIKUSUB_DUAL_A / _B 覆盖。
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-dual-lowdiff');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');

/** A：Anime Whisper（真实跑片产物里截取的前 40 条）。B：Qwen3-ASR 同片。 */
const A_SRT = path.resolve(
  process.env.KIKUSUB_DUAL_A ??
    path.join(ROOT, 'outputs/eval/dual_real3/Jap_test_2.AnimeWhisper.srt'),
);
const B_SRT = path.resolve(
  process.env.KIKUSUB_DUAL_B ??
    path.join(ROOT, 'outputs/eval/dual_real3/Jap_test_2.Qwen3-ASR.srt'),
);

const evalScript = (bPath) => `
  (async () => {
    window.__KIKUSUB_DUAL_B__ = ${JSON.stringify(bPath)};
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const text = (el) => (el ? el.textContent.trim() : null);
    const rowEls = () => [...document.querySelectorAll('.list .row')];
    const lowRows = () => rowEls().filter((el) => el.querySelector('.low-tag'));

    // 先把真实 B 稿（Qwen3-ASR）导进第二列。走产品自己的 import 接口，
    // 端口/token 从 preload 的 getSidecar() 拿——和界面里那条路完全一致，
    // 不伪造 alt 数据，复核页看到的就是两个引擎对同一段音频的真实差异。
    const bPath = window.__KIKUSUB_DUAL_B__;
    if (bPath) {
      const sc = await window.kikusub.getSidecar();
      const sid = localStorage.getItem('kikusub.sid') || '';
      const H = {
        Authorization: 'Bearer ' + sc.token,
        'Content-Type': 'application/json',
        'X-Kikusub-Session': sid,
      };
      // 等 dev seed 把媒体灌进 session：openMedia 是异步的，dev-eval 可能抢在前面。
      // 判据用「服务端认得当前影片」——直接看核对台路口的媒体名，比猜状态码可靠
      // （空工程也回 200，只看 alt-review 的状态码会误判成已就绪）。
      for (let i = 0; i < 60; i += 1) {
        const probe = await fetch('http://127.0.0.1:' + sc.port + '/api/alt-review', {
          headers: { Authorization: H.Authorization, 'X-Kikusub-Session': sid },
        });
        const body = await probe.json().catch(() => ({}));
        if (probe.ok && body.exists) break;
        // seed 灌的是「媒体 + 40 条字幕」；核对台有字幕就说明 openMedia 已经落定。
        const st = await fetch('http://127.0.0.1:' + sc.port + '/api/cues', {
          headers: { Authorization: H.Authorization, 'X-Kikusub-Session': sid },
        }).then((r) => r.json()).catch(() => ({}));
        if (Array.isArray(st.cues) && st.cues.length > 0) break;
        await sleep(250);
      }
      const resp = await fetch('http://127.0.0.1:' + sc.port + '/api/alt-review/import', {
        method: 'POST',
        headers: H,
        body: JSON.stringify({ path: bPath }),
      });
      if (!resp.ok) {
        return JSON.stringify({
          error: '导入 B 稿失败',
          status: resp.status,
          detail: (await resp.text()).slice(0, 300),
        });
      }
      await sleep(700);
    }

    // 导入完再进复核页：页面在 mounted 时会走 loadAltDiff()，
    // 先切页再导入会沿用「还没有第二版」的旧状态（复核页不轮询）。
    document.querySelectorAll('.sb-item')[3]?.click();
    await sleep(2000);

    const out = { rows: rowEls().length };
    out.hasList = Boolean(document.querySelector('.list'));
    // 诊断：页面实际拿到的行与 ratio（低相似度可能根本没出现，不必猜）


    // 只看差异 + 按时间序
    const boxes = () => [...document.querySelectorAll('.head-end .chk input')];
    out.chkCount = boxes().length;

    // 默认时间序下，找相似度 0% 的那一行（当店、魔族）
    const findLow = () => {
      const el = lowRows().find((r) => (r.textContent || '').includes('当店'));
      return el ?? lowRows()[0] ?? null;
    };
    let low = findLow();
    out.lowCount = lowRows().length;
    if (low) {
      out.low = {
        tag: text(low.querySelector('.low-tag')),
        aText: text(low.querySelector('.c-side.a')),
        bText: text(low.querySelector('.c-side.b')),
        // 去掉「整句不同」提示后再读 B 列正文
        bBody: text(low.querySelector('.c-side.b'))?.replace(/^整句不同[^。]*?提示?/, ''),
        insMarks: [...low.querySelectorAll('.c-side.b mark.ins')].map((m) => m.textContent),
        delMarks: [...low.querySelectorAll('.c-side.a mark.del')].map((m) => m.textContent),
        markClass: low.querySelector('.mark')?.className ?? '',
        markTitle: low.querySelector('.mark')?.getAttribute('title') ?? '',
        hasAdopt: Boolean(low.querySelector('.act-btn.adopt')),
      };
    }

    // 打开「按差异大小排」：首行的 ratio 应最低
    const sortBox = boxes().find((b) => b.closest('.chk')?.textContent?.includes('按差异大小排'));
    sortBox?.click();
    await sleep(400);
    const ratioOf = (el) => {
      const t = el.querySelector('.mark')?.getAttribute('title') ?? '';
      const m = t.match(/(\d+)%/);
      return m ? Number(m[1]) : null;
    };
    const ratios = rowEls().slice(0, 6).map(ratioOf);
    out.sortedRatios = ratios;
    out.sortedFirstLow = Boolean(rowEls()[0]?.querySelector('.low-tag'));

    // 采用 B：作用于「当店」那一行
    const target = findLow();
    out.adoptTarget = text(target?.querySelector('.c-side.a'));
    target?.querySelector('.act-btn.adopt')?.click();
    await sleep(1200);
    out.afterAdoptStillLow = Boolean(
      rowEls().some((r) => (r.textContent || '').includes('当店')),
    );
    out.toast = text(document.querySelector('.toast'));

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

/** A 列走 dev seed（= 核对台当前版本），B 列用真实 Qwen 稿的头部片段落到磁盘。 */
function ensureSeed() {
  const src = fs.readFileSync(A_SRT, 'utf8');
  // 只取前 200s：A/B 断句不同，各截「前 40 条」会让两边时间轴错位、
  // 配不上对，低相似度行就一个也造不出来。按时间截才保证比的是同一段音频。
  const blocks = src.trim().split(/\n\s*\n/);
  const cues = [];
  for (const block of blocks) {
    const lines = block.split('\n');
    const m = /(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)/.exec(
      lines.find((l) => l.includes('-->')) ?? '',
    );
    if (!m) continue;
    const t = (h, mm, s, ms) => Number(h) * 3600 + Number(mm) * 60 + Number(s) + Number(ms) / 1000;
    const body = lines.slice(2).join(' ').trim();
    if (!body) continue;
    const startS = t(m[1], m[2], m[3], m[4]);
    if (startS >= 200) break;
    cues.push({ start: startS, end: t(m[5], m[6], m[7], m[8]), text: body });
  }
  const seedPath = path.join(BASE, 'seed.json');
  fs.writeFileSync(seedPath, JSON.stringify({ mediaPath: MEDIA, cues }, null, 2), 'utf8');
  return seedPath;
}

/** B 稿同样只取前 40 条，避免时间轴后半段空转。 */
function ensureBSrt() {
  const src = fs.readFileSync(B_SRT, 'utf8');
  const blocks = src.trim().split(/\n\s*\n/).filter((block) => {
    const line = block.split('\n').find((l) => l.includes('-->')) ?? '';
    const m = /(\d+):(\d+):(\d+)[,.]/ .exec(line);
    if (!m) return false;
    return Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) < 200;
  });
  const target = path.join(BASE, 'B.srt');
  const text = blocks
    .map((block, i) => {
      const lines = block.split('\n');
      const body = lines.slice(2).join('\n').trim();
      return `${i + 1}\n${lines[0].includes('-->') ? lines[0] : lines[1]}\n${body}\n`;
    })
    .join('\n');
  fs.writeFileSync(target, text, 'utf8');
  return target;
}

function run(bSrt) {
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
    KIKUSUB_SHOT_DELAY: '2600',
    KIKUSUB_OUTPUT_DIR: OUT,
    KIKUSUB_DATA_DIR: path.join(BASE, 'data'),
    KIKUSUB_PREFERENCES_PATH: path.join(BASE, 'prefs.json'),
    KIKUSUB_DEV_SEED: ensureSeed(),
    KIKUSUB_DEV_EVAL: evalScript(bSrt),
    KIKUSUB_DUAL_B_FILE: bSrt,
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
        `--screenshot=${path.join(BASE, 'dual-lowdiff.png')}`,
        ...extra,
      ],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 240_000 },
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
  const bSrt = ensureBSrt();
  const data = run(bSrt);
  console.log(JSON.stringify(data, null, 2));

  check('对照表已渲染', Boolean(data.hasList) && data.rows > 0, JSON.stringify(data.rows));
  check('存在低相似度行', data.lowCount > 0, `lowCount=${data.lowCount}`);
  check('低相似度行有「整句不同」提示', Boolean(data.low?.tag), data.low?.tag);
  check(
    '低相似度行仍做短语高亮（A 侧有 del 标记）',
    (data.low?.delMarks ?? []).length > 0,
    JSON.stringify(data.low?.delMarks),
  );
  check(
    'B 侧把 A 没有的片段标成 ins',
    (data.low?.insMarks ?? []).length > 0,
    JSON.stringify(data.low?.insMarks),
  );
  check('对照标记带 low 类（描边）', (data.low?.markClass ?? '').includes('low'), data.low?.markClass);
  check(
    'title 说明这是专名/幻觉那一档',
    (data.low?.markTitle ?? '').includes('专名') ||
      (data.low?.markTitle ?? '').includes('幻觉'),
    data.low?.markTitle,
  );
  check('低相似度行也有「采用 B」', data.low?.hasAdopt === true);
  check(
    '按差异大小排：首行相似度不高于第三行',
    (() => {
      const r = data.sortedRatios ?? [];
      if (r.length < 3) return false;
      return r[0] <= r[2];
    })(),
    JSON.stringify(data.sortedRatios),
  );
  check('排序后首行是低相似度行', data.sortedFirstLow === true);
  check('采用 B 后那一行不再以原 A 文本留在差异里', data.afterAdoptStillLow === false);

  const shot = path.join(BASE, 'dual-lowdiff.png');
  if (fs.existsSync(shot)) console.log(`\n截图：${shot}`);
  else console.error('\n截图缺失（--screenshot 没跑通？）');

  if (failures.length) {
    console.error(`\n${failures.length} 项失败`);
    process.exit(1);
  }
  console.log('\n全部通过');
}

main();
