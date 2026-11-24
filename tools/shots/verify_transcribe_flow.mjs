#!/usr/bin/env node
/**
 * 转写页「任务编排」无窗口回归（2026-11-25）。
 *
 * 用户报障的两条路径：
 *   1. 先 Whisper 转一章进核对台，回转写页换 Qwen 想再转一遍进双引擎复核，
 *      却找不到入口（区间把「去向」藏掉了）；
 *   2. 往返一次核对台，时间区间就没了。
 *
 * 覆盖：
 *   - 产出三档：主稿 / 第二版 / 两版一起；底栏文案与主按钮随产出改；
 *   - 区间：填起止后底栏复述同一段；「第二版」的说明是「只换该区间的 B」；
 *   - 跨切页保留范围：去核对台再回来，起止与产出都还在；
 *   - 「整片」清空范围（输入框消失、底栏回到整片）；
 *   - 章节「加入转写选区」：带来源「章节一」进来，不再只是两个裸时间；
 *   - 双引擎复核空态 →「去转写页生成第二版」：回来产出已经是「第二版」。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现。断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_transcribe_flow.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_transcribe_flow.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-transcribe-flow');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'flow.mp4');
const SHOT = path.join(BASE, 'transcribe-flow.png');
const DURATION = 60;

const CUES = [
  { start: 5.0, end: 8.0, text: '最初の場面です' },
  { start: 20.0, end: 24.0, text: '真ん中の台詞' },
  { start: 40.0, end: 44.0, text: '後半の台詞' },
];
const CHAPTERS = [{ id: 'ch-1', start: 5, end: 8, title: '章节一' }];

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const waitFor = async (fn, ms = 20000) => {
      const t0 = Date.now();
      while (Date.now() - t0 < ms) {
        const value = fn();
        if (value) return value;
        await sleep(80);
      }
      return null;
    };
    const text = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim();
    const sidebar = (label) =>
      [...document.querySelectorAll('.sb-item')].find((el) =>
        (el.getAttribute('aria-label') || '').startsWith(label),
      );
    const buttonByText = (label, root = document) =>
      [...root.querySelectorAll('button')].find((el) => text(el) === label);
    const dock = () => document.querySelector('.dock');
    const dockPlan = () => text(dock()?.querySelector('.plan'));
    const dockDetail = () => text(dock()?.querySelector('.detail'));
    const dockButton = () => text(dock()?.querySelector('button.btn.primary'));
    const startInput = () => document.querySelector('input[aria-label="起始时间"]');
    const endInput = () => document.querySelector('input[aria-label="结束时间"]');
    const typeInto = async (input, value) => {
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      await sleep(220);
    };
    const openTranscribe = async () => {
      sidebar('转写')?.click();
      await waitFor(() => document.querySelector('.dock'));
      await sleep(500);
    };
    const goReview = async () => {
      sidebar('核对台')?.click();
      await waitFor(() => document.querySelector('.wave-wrap'));
      await sleep(500);
    };

    try {
      // 种子是异步注入的（openMedia → 字幕 → 章节 → setView('review')），
      // 必须等它落到核对台再点侧栏，否则会被最后那次 setView 踢走。
      await waitFor(() => document.querySelector('.sb-item'));
      await waitFor(() => document.querySelector('.wave-wrap'), 30000);
      await sleep(800);

      // 1) 转写页首屏：右栏有主稿，底栏是「整片 → 主稿」
      await openTranscribe();
      const subtitle = text(document.querySelector('.page-sub'));
      const rail = text(document.querySelector('.state[aria-label="现在的稿"]'));
      const initial = {
        subtitle,
        rail,
        railHasPrimary: rail.includes('主稿 · 核对台') && rail.includes('3 条'),
        railHasNoAlt: rail.includes('第二版 · 对照') && rail.includes('还没有'),
        plan: dockPlan(),
        button: dockButton(),
      };

      // 2) 填一段区间：底栏复述同一段；来源写「手动填写」
      buttonByText('区间')?.click();
      await sleep(300);
      const rangeInputs = Boolean(startInput() && endInput());
      await typeInto(startInput(), '00:10.000');
      await typeInto(endInput(), '00:20.000');
      const manual = {
        rangeInputs,
        plan: dockPlan(),
        source: text(document.querySelector('.hint')),
        button: dockButton(),
      };

      // 3) 产出切到第二版：按钮与说明都改口，核对台不动
      buttonByText('第二版')?.click();
      await sleep(300);
      const alt = {
        plan: dockPlan(),
        detail: dockDetail(),
        button: dockButton(),
        applied: text(document.querySelector('.seg button.on')),
      };

      // 4) 去核对台再回来：范围与产出都要还在（用户报障的核心）
      await goReview();
      await openTranscribe();
      const persisted = {
        start: startInput()?.value ?? '',
        end: endInput()?.value ?? '',
        plan: dockPlan(),
        button: dockButton(),
      };

      // 5) 整片：清空输入，底栏回到整片
      await goReview();
      await openTranscribe();
      buttonByText('整片')?.click();
      await sleep(300);
      const whole = {
        inputsGone: !startInput(),
        plan: dockPlan(),
        button: dockButton(),
      };

      // 6) 章节「加入转写选区」：带来源与章节名进来
      await goReview();
      [...document.querySelectorAll('.insp-tab')]
        .find((el) => (el.textContent || '').trim().startsWith('章节'))
        ?.click();
      await waitFor(() => document.querySelector('.chapters-panel'));
      await sleep(400);
      const chapterItem = [...document.querySelectorAll('.chapters-panel .item')].find((el) =>
        el.textContent.includes('章节一'),
      );
      const useChapter = chapterItem?.querySelector('button[aria-label="加入转写选区"]');
      useChapter?.click();
      await waitFor(() => document.querySelector('.dock'));
      await sleep(600);
      const chapter = {
        found: Boolean(useChapter),
        start: startInput()?.value ?? '',
        end: endInput()?.value ?? '',
        source: text(document.querySelector('.hint')),
        plan: dockPlan(),
      };

      // 7) 双引擎复核空态 → 去转写页生成第二版：产出已选好
      sidebar('双引擎复核')?.click();
      await waitFor(() => document.querySelector('.dual'));
      await sleep(500);
      const dualItem = sidebar('双引擎复核');
      dualItem?.click();
      await sleep(1600);
      const dualActive = document.querySelector('.sb-item.active')?.getAttribute('aria-label') ?? '';
      const dualBody = text(document.querySelector('.content')).slice(0, 200);
      const dualCta = buttonByText('去转写页生成第二版');
      const dualEmpty = { cta: Boolean(dualCta), page: dualBody, active: dualActive, label: dualItem?.getAttribute('aria-label') ?? '' };
      dualCta?.click();
      await waitFor(() => document.querySelector('.dock'));
      await sleep(500);
      const fromDual = {
        ctaFound: dualEmpty.cta,
        active: dualEmpty.active,
        label: dualEmpty.label,
        pageText: dualEmpty.page,
        plan: dockPlan(),
        button: dockButton(),
      };

      // 8) 右栏推荐：主稿来自 Whisper → 一键切 Qwen3 + 第二版（用户报障的那个动作）
      buttonByText('主稿')?.click();
      await sleep(400);
      const suggestButton = buttonByText('用 Qwen3-ASR + CTC 生成第二版');
      const railBeforeSuggest = text(document.querySelector('.state[aria-label="现在的稿"]'));
      suggestButton?.click();
      await sleep(600);
      const suggested = {
        found: Boolean(suggestButton),
        railHadPrimary: railBeforeSuggest.includes('最近一版来自 Anime Whisper'),
        plan: dockPlan(),
        button: dockButton(),
      };

      return JSON.stringify({
        initial,
        suggested,
        manual,
        alt,
        persisted,
        whole,
        chapter,
        fromDual,
      });
    } catch (err) {
      return JSON.stringify({ error: String((err && err.message) || err), stack: String(err?.stack || '') });
    }
  })()
`;

function ensureMedia() {
  fs.mkdirSync(BASE, { recursive: true });
  if (fs.existsSync(MEDIA)) fs.rmSync(MEDIA);
  execFileSync('ffmpeg', [
    '-y',
    '-v',
    'error',
    '-f',
    'lavfi',
    '-i',
    `color=c=0x223344:s=640x360:d=${DURATION}:r=24`,
    '-f',
    'lavfi',
    '-i',
    `sine=frequency=440:duration=${DURATION}`,
    '-pix_fmt',
    'yuv420p',
    '-c:v',
    'libx264',
    '-preset',
    'ultrafast',
    '-c:a',
    'aac',
    '-shortest',
    MEDIA,
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
        chapters: CHAPTERS,
        // 真实流程里主稿是 Whisper 转的；右栏据此推荐「用 Qwen3 生成第二版」。
        reviewSource: { kind: 'transcription', engine: 'whisper' },
      },
      null,
      2,
    ),
    'utf8',
  );
  return seedPath;
}

function run() {
  ensureMedia();
  ensureSeed();
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  fs.rmSync(SHOT, { force: true });
  const profile = path.join(BASE, 'profile');
  fs.rmSync(profile, { recursive: true, force: true });
  fs.mkdirSync(profile, { recursive: true });

  const extra = (process.env.KIKUSUB_SHOT_ELECTRON_ARGS || '').split(/\s+/).filter(Boolean);
  const env = {
    ...process.env,
    KIKUSUB_ALLOW_MULTIPLE: '1',
    KIKUSUB_WIN_SIZE: '1360x838',
    KIKUSUB_SHOT_DELAY: '4200',
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
      ['electron', '.', `--user-data-dir=${profile}`, `--screenshot=${SHOT}`, ...extra],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 240_000 },
    ).toString();
  } catch (error) {
    stdout = `${error.stdout ?? ''}`;
    console.error(String(error.stderr ?? '').slice(-1600));
  }
  const evalError = stdout.split('\n').filter((row) => row.startsWith('[eval:error]')).pop();
  if (evalError) throw new Error(evalError);
  const line = stdout.split('\n').filter((row) => row.startsWith('[eval]')).pop();
  if (!line) throw new Error('渲染进程没有回传结果');
  return JSON.parse(line.slice('[eval] '.length));
}

const failures = [];
function check(name, condition, detail) {
  if (condition) {
    console.log(`✅ ${name}`);
    return;
  }
  failures.push(name);
  console.log(`❌ ${name}${detail === undefined ? '' : `\n   ${JSON.stringify(detail)}`}`);
}

const r = run();
if (r.error) {
  console.log(`❌ 渲染进程抛错：${r.error}`);
  process.exit(1);
}

console.log(JSON.stringify(r, null, 2));
check('首屏：主稿 3 条 / 第二版还没有', r.initial.railHasPrimary && r.initial.railHasNoAlt, r.initial);
check('首屏：底栏「整片 → 主稿」', r.initial.plan.includes('整片 → 主稿（核对台）'), r.initial.plan);
check('首屏：按钮是「开始转写」', r.initial.button === '开始转写', r.initial.button);
check('区间：点「区间」出现两个时间框', r.manual.rangeInputs === true, r.manual);
check('区间：底栏复述起止', r.manual.plan.includes('00:10.000 – 00:20.000'), r.manual.plan);
check('区间：来源写手动填写', r.manual.source.includes('来源：手动填写'), r.manual.source);
check('第二版：底栏改成第二版', r.alt.plan.includes('第二版（对照）'), r.alt.plan);
check('第二版：按钮改口「生成第二版」', r.alt.button === '生成第二版', r.alt.button);
check(
  '第二版：说明只换该区间的 B',
  r.alt.detail.includes('只把 00:10.000 – 00:20.000 的第二版换成这次结果'),
  r.alt.detail,
);
check('跨切页：起止还在', r.persisted.start === '00:10.000' && r.persisted.end === '00:20.000', r.persisted);
check('跨切页：产出还是第二版', r.persisted.plan.includes('第二版（对照）'), r.persisted.plan);
check('整片：输入框消失', r.whole.inputsGone === true, r.whole);
check('整片：底栏回到整片', r.whole.plan.includes('整片 → 第二版（对照）'), r.whole.plan);
check('章节：带进来的起止正确', r.chapter.start === '00:05.000' && r.chapter.end === '00:08.000', r.chapter);
check('章节：来源写「章节一」', r.chapter.source.includes('来源：章节「章节一」'), r.chapter.source);
check('章节：底栏复述章节名', r.chapter.plan.includes('章节一 00:05.000 – 00:08.000'), r.chapter.plan);
check('双引擎空态：有生成第二版的入口', r.fromDual.ctaFound === true, r.fromDual);
check('双引擎空态：回来产出就是第二版', r.fromDual.plan.includes('第二版（对照）'), r.fromDual.plan);
check('右栏：主稿引擎已知时推荐另一个引擎', r.suggested.found && r.suggested.railHadPrimary, r.suggested);
check('右栏推荐：一键切到 Qwen3 + 第二版', r.suggested.plan.includes('Qwen3-ASR + CTC') && r.suggested.plan.includes('第二版（对照）'), r.suggested.plan);
check('右栏推荐：按钮跟着变成「生成第二版」', r.suggested.button === '生成第二版', r.suggested.button);

if (failures.length) {
  console.log(`\n${failures.length} 项失败：\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`\n截图：${SHOT}`);
console.log('全部通过。');
