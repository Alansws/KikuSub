#!/usr/bin/env node
/**
 * 核对台检查器取证 + 回归：朱红质检徽标、朗读 ⚙ 展开面板、收整后的右栏底部。
 *
 * 2026-11-26 真机反馈三件事，这里一次全钉住：
 *   1. 页签「质检待核 4」里的 4 只是极淡灰数字 → 改成朱红微胶囊，且对比度达标；
 *   2. 展开朗读 ⚙ 时面板溢出 348px 检查器右缘 → 见 `verify_tts_panel_fit.mjs`，
 *      本脚本负责**在同一屏**拍下徽标 + 面板 + 底部收尾区；
 *   3. 右栏底部「AI 未启用 / 漏检提示 / 任务报告」下方一大块空白 → 收尾区（.meta-foot）
 *      被 `margin-top: auto` 钉在检查器底缘，一条发丝线与内容分开。
 *
 * 种子里有：12 条字幕、一个 OmniVoice 克隆音色、一份带 4 条待核的质检队列、
 * 一份任务报告——正是用户报障那一刻的检查器状态。
 *
 * 用法：
 *   node tools/shots/capture_review_inspector.mjs --out /tmp/review-inspector
 *   node tools/shots/capture_review_inspector.mjs --theme dark --size 1360x838
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node ...
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-review-inspector');
const MEDIA = path.join(BASE, 'inspector.mp4');

function arg(name, fallback) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : fallback;
}
const OUT = path.resolve(arg('--out', path.join(BASE, 'out')));
const SIZE = arg('--size', '1440x960');
const THEME = arg('--theme', 'light');

const CUES = [
  { start: 0.4, end: 1.6, text: 'よう、久しぶり。' },
  { start: 1.8, end: 3.0, text: 'お前は変わったな、本当に。' },
  { start: 3.2, end: 4.4, text: 'ここで待っていたんだよ、ずっと。' },
  { start: 4.6, end: 5.8, text: '雨の日だけ、君はここに来る。' },
  { start: 6.0, end: 7.2, text: 'だから今日も来てみたんだ。' },
  { start: 7.4, end: 8.6, text: '話したいことがある。' },
  { start: 8.8, end: 10.0, text: 'それは……とても大事な話。' },
  { start: 10.2, end: 11.4, text: 'でも、うまく言えない。' },
];

const QA_ITEMS = [
  { id: 'q1', kind: 'coverage', group: 'miss', start: 2.2, end: 2.6, text: '' },
  { id: 'q2', kind: 'coverage', group: 'miss', start: 5.0, end: 5.4, text: '' },
  { id: 'q3', kind: 'suspect', group: 'low', start: 6.2, end: 6.6, text: '今日は' },
  { id: 'q4', kind: 'suspect', group: 'low', start: 9.0, end: 9.4, text: 'えっと' },
];
const QA_PAYLOAD = {
  media: 'inspector.mp4',
  phase: 'done',
  engine: 'whisper',
  items: QA_ITEMS,
  statuses: {},
  scanned: { windows: 12, seconds: 12.0 },
  counts: {
    total: 4,
    pending: 4,
    done: 0,
    skipped: 0,
    by_group: { miss: 2, low: 2 },
  },
  revision: 1,
  latest_cue_count: CUES.length,
  hidden_missed: 1,
};

const REPORT = {
  job_id: '',
  media_id: '',
  out_filename: 'inspector.srt',
  out_path: '/tmp/inspector.srt',
  overview: [
    { label: '引擎', value: 'Anime Whisper' },
    { label: '耗时', value: '3m12s' },
    { label: '条数', value: String(CUES.length) },
  ],
  params: [{ label: 'VAD', value: 'silero · 0.25' }],
  quality: {
    headline: '漏检 2 处 · 低置信 2 句',
    coverage: 2,
    low_confidence: 2,
    missed: 2,
    hidden_missed: 1,
    dropped: 1,
    suspect: 2,
    nonverbal: 0,
    degraded: 0,
    has_findings: true,
    qwen_limited: false,
    engine_family: 'whisper',
  },
  sections: [],
  raw_text: '',
};

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const waitFor = async (fn, ms = 20000) => {
      const t0 = Date.now();
      while (Date.now() - t0 < ms) {
        const value = fn();
        if (value) return value;
        await sleep(70);
      }
      return null;
    };
    const text = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim();
    const box = (el) => {
      const r = el.getBoundingClientRect();
      return { left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), bottom: Math.round(r.bottom), w: Math.round(r.width) };
    };
    if (__THEME__ !== 'light') {
      document.documentElement.dataset.theme = __THEME__;
      localStorage.setItem('kikusub.appearance', __THEME__);
    }

    try {
      await waitFor(() => document.querySelector('.sb-item'));
      await waitFor(() => document.querySelector('.wave-wrap'), 30000);
      await sleep(900);

      const badge = document.querySelector('.insp-tab .tab-badge');
      const badgeCss = badge ? getComputedStyle(badge) : null;
      const tabCss = badge ? getComputedStyle(document.querySelector('.insp-tab')) : null;

      // 展开朗读 ⚙
      document.querySelector('.tts-more')?.click();
      const panel = await waitFor(() => document.querySelector('.tts-panel'), 4000);
      await sleep(360);

      const aside = document.querySelector('.inspector');
      const foot = document.querySelector('.meta-foot');
      const insScroll = document.querySelector('.ins-scroll');
      const asideBox = box(aside);
      const footBox = foot ? box(foot) : null;
      const panelBox = panel ? box(panel) : null;
      const outsidePanel = panel
        ? [...panel.querySelectorAll('button, select')].filter((el) => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && (r.left < asideBox.left - 0.5 || r.right > asideBox.right + 0.5);
          }).map((el) => text(el).slice(0, 12))
        : [];

      return JSON.stringify({
        badge: badge ? text(badge) : null,
        badgeColor: badgeCss?.color ?? '',
        badgeBg: badgeCss?.backgroundColor ?? '',
        badgeRadius: badgeCss?.borderRadius ?? '',
        badgeHeight: badge ? Math.round(badge.getBoundingClientRect().height) : null,
        tabInk3: tabCss ? getComputedStyle(document.documentElement).getPropertyValue('--ink-3').trim() : '',
        panelOpen: Boolean(panel),
        panel: panelBox,
        panelOutside: outsidePanel,
        footFound: Boolean(foot),
        foot: footBox,
        footText: text(foot),
        reportLink: text(document.querySelector('.meta-foot .meta-link')),
        aside: asideBox,
        asideOverflow: { clientWidth: aside.clientWidth, scrollWidth: aside.scrollWidth },
        scrollOverflow: { clientWidth: insScroll.clientWidth, scrollWidth: insScroll.scrollWidth },
        scrollBox: box(insScroll),
        chips: [...document.querySelectorAll('.meta-foot .chip')].map((el) => text(el)),
        aiRow: text(document.querySelector('.arb-setup') ?? document.querySelector('.arb')),
        aiRowBox: box(document.querySelector('.arb-setup') ?? document.querySelector('.arb')),
        viewport: { w: window.innerWidth, h: window.innerHeight },
      });
    } catch (err) {
      return JSON.stringify({ error: String((err && err.message) || err) });
    }
  })()
`;

function ensureMedia() {
  fs.mkdirSync(BASE, { recursive: true });
  if (!fs.existsSync(MEDIA)) {
    execFileSync('ffmpeg', [
      '-y', '-v', 'error',
      '-f', 'lavfi', '-i', 'color=c=0x223344:s=640x360:d=12',
      '-f', 'lavfi', '-i', 'sine=frequency=300:duration=12',
      '-shortest', '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast',
      '-c:a', 'aac', '-b:a', '96k', MEDIA,
    ], { stdio: 'ignore' });
  }
}

let failed = 0;
function check(label, ok, detail) {
  if (ok) console.log(`✅ ${label}`);
  else {
    failed += 1;
    console.log(`❌ ${label}`);
    if (detail !== undefined) console.log('   ', JSON.stringify(detail));
  }
}

ensureMedia();
fs.mkdirSync(OUT, { recursive: true });

const profile = path.join(BASE, `profile-${THEME}`);
fs.rmSync(profile, { recursive: true, force: true });
const seedPath = path.join(BASE, 'seed.json');
fs.writeFileSync(
  seedPath,
  JSON.stringify(
    {
      mediaPath: MEDIA,
      cues: CUES,
      qa: QA_PAYLOAD,
      qaOpen: false, // 停在「当前条目」页签，徽标与面板才能同框
      report: REPORT,
      tts: {
        system: ['Kyoko', 'Otoya'],
        custom: [{ name: '角色 1', duration: 4.7 }],
        voiceId: 'clone-0',
      },
    },
    null,
    1,
  ),
  'utf8',
);

const shot = path.join(OUT, `review-inspector-${SIZE}${THEME === 'light' ? '' : `-${THEME}`}.png`);
const args = ['.', '--no-sandbox', `--user-data-dir=${profile}`, `--screenshot=${shot}`];
const extra = process.env.KIKUSUB_SHOT_ELECTRON_ARGS;
if (extra) args.push(...extra.split(' '));
const stdout = execFileSync('npx', ['electron', ...args], {
  cwd: path.join(ROOT, 'desktop'),
  env: {
    ...process.env,
    KIKUSUB_WIN_SIZE: SIZE,
    KIKUSUB_DEV_SEED: seedPath,
    KIKUSUB_SHOT_DELAY: '5600',
    KIKUSUB_DEV_EVAL: EVAL.replace(/__THEME__/g, JSON.stringify(THEME)),
    KIKUSUB_OUTPUT_DIR: path.join(BASE, 'outputs'),
    KIKUSUB_DATA_DIR: path.join(BASE, `data-${THEME}`),
    KIKUSUB_ALLOW_MULTIPLE: '1',
  },
  encoding: 'utf8',
  maxBuffer: 32 * 1024 * 1024,
});
const line = stdout.split('\n').reverse().find((l) => l.startsWith('[eval]'));
if (!line) {
  console.error('❌ 渲染进程没有回传结果');
  process.exit(1);
}
const r = JSON.parse(line.replace('[eval] ', ''));
if (r.error) {
  console.error('❌ 采集失败：', r.error);
  process.exit(1);
}

console.log(`\n[${THEME} ${SIZE}] ${shot}`);
check('质检待核徽标显示 4', r.badge === '4', r.badge);
check('徽标是朱红（不是 --ink-3 灰）', Boolean(r.badgeColor) && r.badgeColor !== 'rgb(86, 97, 104)', r.badgeColor);
check('徽标有底色', r.badgeBg !== 'rgba(0, 0, 0, 0)', r.badgeBg);
check('徽标是胶囊（圆角 ≥ 7px）', parseFloat(r.badgeRadius) >= 7, r.badgeRadius);
check('朗读 ⚙ 面板已展开', r.panelOpen === true, r);
check('面板内按钮全部在检查器框内', r.panelOutside.length === 0, r.panelOutside);
check('检查器无横向溢出', r.asideOverflow.scrollWidth <= r.asideOverflow.clientWidth, r.asideOverflow);
check('底部收尾区存在', r.footFound === true, r);
check('漏检 / 低置信 chips 在收尾区里', r.chips.length === 2, r.chips);
check('任务报告入口在收尾区右侧', r.reportLink === '任务报告', r.reportLink);

if (r.foot && r.scrollBox) {
  // 收尾区贴住控制区底缘（内部 16px 下内边距）：空白落在内容与收尾区之间，
  // 而不是留在「最后一行」下面。
  const gap = r.scrollBox.bottom - r.foot.bottom;
  check('收尾区钉在检查器底缘（空白不再吊在下面）', gap >= 0 && gap <= 18, {
    gap,
    foot: r.foot,
    scroll: r.scrollBox,
  });
}

if (failed) {
  console.error(`\n${failed} 项失败`);
  process.exit(1);
}
console.log('\n全部通过。');
