#!/usr/bin/env node
/**
 * 检查器「朗读 ⚙」展开面板的窄栏几何回归（2026-11-26 真机报障）。
 *
 * 现场：检查器固定 348px（最小窗口 1080×680 也是这个宽度）。拥有 OmniVoice
 * 克隆音色时点开 `朗读 ⚙`，展开面板的内容超出检查器右边界被裁掉：
 *   - 第一行 `音量已…`（.tts-meta）被截断；
 *   - 第二行 `1.0× | 上传 | 截取 | 音色库 1 | 管理` 最右侧按钮被切掉一半。
 *
 * 这里不开窗地量三组数：
 *   1. 检查器与面板自身的 `scrollWidth <= clientWidth`（不许横向溢出）；
 *   2. 面板内**每一个**按钮 / 下拉框的 boundingBox 都落在检查器左右边界内；
 *   3. 关键文案（音色库的计数、管理的按钮）真的在可见范围内，而不是被裁掉。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现。断言失败退出码非 0。
 *
 * 用法：
 *   node tools/shots/verify_tts_panel_fit.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_tts_panel_fit.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-tts-fit');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'fit.mp4');
const SHOT = path.join(BASE, 'tts-panel-348.png');
const SIZE = process.env.KIKUSUB_TTS_FIT_SIZE || '1080x680';

const CUES = [
  { start: 0.5, end: 1.5, text: '深呼吸して' },
  { start: 2.0, end: 3.0, text: '吸って' },
  { start: 4.0, end: 5.0, text: 'もう一回' },
];

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const waitFor = async (fn, ms = 20000) => {
      const t0 = Date.now();
      while (Date.now() - t0 < ms) {
        const value = fn();
        if (value) return value;
        await sleep(60);
      }
      return null;
    };
    const box = (el) => {
      const r = el.getBoundingClientRect();
      return { left: r.left, right: r.right, width: r.width, top: r.top, height: r.height };
    };

    try {
      await waitFor(() => document.querySelector('.sb-item'));
      await waitFor(() => document.querySelector('.wave-wrap'), 30000);
      await sleep(900);

      // 点开「朗读 ⚙」
      const gear = await waitFor(() => document.querySelector('.tts-more'));
      if (!gear) return JSON.stringify({ error: '没有找到朗读设置按钮 .tts-more' });
      gear.click();
      const panel = await waitFor(() => document.querySelector('.tts-panel'), 4000);
      await sleep(360);

      const aside = document.querySelector('.inspector');
      const scroll = document.querySelector('.ins-scroll');
      const asideBox = box(aside);
      const panelBox = panel ? box(panel) : null;

      // 面板里所有交互控件 + 关键文案节点
      const controls = panel
        ? [...panel.querySelectorAll('button, select, .tts-panel-row > * > *')]
        : [];
      const outside = [];
      for (const el of controls) {
        const r = box(el);
        if (!r.width && !r.height) continue;
        if (r.left < asideBox.left - 0.5 || r.right > asideBox.right + 0.5) {
          outside.push({
            cls: (el.className || el.tagName || '').toString().slice(0, 60),
            text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 24),
            left: Math.round(r.left),
            right: Math.round(r.right),
          });
        }
      }

      const manage = panel
        ? [...panel.querySelectorAll('.tts-action')].find((b) =>
            (b.textContent || '').includes('管理'),
          )
        : null;
      const voiceBtn = panel
        ? [...panel.querySelectorAll('.tts-action')].find((b) =>
            (b.textContent || '').includes('音色库'),
          )
        : null;

      // 面板行内是否有被挤成 0 宽 / 完全落到右边界的元素
      const clipped = panel
        ? [...panel.querySelectorAll('.tts-action, .tts-select-wrap')]
            .filter((el) => {
              const r = box(el);
              return r.right > asideBox.right + 0.5 || r.width < 8;
            })
            .map((el) => (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 20))
        : [];

      const out = {
        viewport: { w: window.innerWidth, h: window.innerHeight },
        asideWidth: Math.round(asideBox.width),
        asideLeft: Math.round(asideBox.left),
        asideRight: Math.round(asideBox.right),
        aside: {
          clientWidth: aside.clientWidth,
          scrollWidth: aside.scrollWidth,
          clientHeight: aside.clientHeight,
          scrollHeight: aside.scrollHeight,
        },
        scroll: {
          clientWidth: scroll.clientWidth,
          scrollWidth: scroll.scrollWidth,
        },
        panel: panel
          ? {
              clientWidth: panel.clientWidth,
              scrollWidth: panel.scrollWidth,
              left: Math.round(panelBox.left),
              right: Math.round(panelBox.right),
            }
          : null,
        panelOpen: Boolean(panel),
        outside,
        clipped,
        controlCount: controls.length,
        meta: (panel?.querySelector('.tts-meta')?.textContent || '').replace(/\s+/g, ' ').trim(),
        metaFull: panel?.querySelector('.tts-meta')?.getAttribute('title') || '',
        manageLabel: (manage?.textContent || '').replace(/\s+/g, ' ').trim(),
        voiceLabel: (voiceBtn?.textContent || '').replace(/\s+/g, ' ').trim(),
        voiceCount: (voiceBtn?.querySelector('.tts-count')?.textContent || '').trim(),
        rows: panel
          ? [...panel.querySelectorAll('.tts-panel-row')].map((row) => ({
              h: Math.round(box(row).height),
              items: [...row.children].map((el) => Math.round(box(el).width)),
            }))
          : [],
      };
      return JSON.stringify(out);
    } catch (err) {
      return JSON.stringify({ error: String((err && err.message) || err), stack: String(err?.stack || '') });
    }
  })()
`;

function ensureMedia() {
  fs.mkdirSync(BASE, { recursive: true });
  fs.mkdirSync(OUT, { recursive: true });
  if (!fs.existsSync(MEDIA)) {
    execFileSync(
      'ffmpeg',
      [
        '-y', '-v', 'error',
        '-f', 'lavfi', '-i', 'color=c=0x223344:s=640x360:d=6',
        '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast',
        MEDIA,
      ],
      { stdio: 'ignore' },
    );
  }
  const seed = path.join(BASE, 'seed.json');
  // 一个克隆音色 + 两个系统音色：`音色库 1` 计数徽章与「管理」按钮都只在
  // 克隆音色被选中时出现——真机报障那一屏正是这个组合。
  const payload = {
    mediaPath: MEDIA,
    cues: CUES,
    tts: {
      system: ['Kyoko', 'Otoya'],
      custom: [{ name: '角色 1', duration: 4.7 }],
      voiceId: 'clone-0',
    },
  };
  fs.writeFileSync(seed, JSON.stringify(payload, null, 1), 'utf8');
  return seed;
}

function run(seed) {
  const profile = path.join(BASE, 'profile');
  fs.rmSync(profile, { recursive: true, force: true });
  const args = ['.', '--no-sandbox', `--user-data-dir=${profile}`, `--screenshot=${SHOT}`];
  const env = {
    ...process.env,
    KIKUSUB_WIN_SIZE: SIZE,
    KIKUSUB_DEV_SEED: seed,
    KIKUSUB_SHOT_DELAY: '5200',
    KIKUSUB_DEV_EVAL: EVAL,
    KIKUSUB_OUTPUT_DIR: path.join(BASE, 'outputs'),
    KIKUSUB_DATA_DIR: path.join(BASE, 'data'),
    KIKUSUB_ALLOW_MULTIPLE: '1',
  };
  const extra = process.env.KIKUSUB_SHOT_ELECTRON_ARGS;
  if (extra) args.push(...extra.split(' '));
  const stdout = execFileSync('npx', ['electron', ...args], {
    cwd: path.join(ROOT, 'desktop'),
    env,
    encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024,
  });
  const line = stdout
    .split('\n')
    .reverse()
    .find((l) => l.startsWith('[eval]'));
  if (!line) throw new Error('渲染进程没有回传结果');
  return JSON.parse(line.replace('[eval] ', ''));
}

let failed = 0;
function check(label, ok, detail) {
  if (ok) {
    console.log(`✅ ${label}`);
  } else {
    failed += 1;
    console.log(`❌ ${label}`);
    if (detail !== undefined) console.log('   ', JSON.stringify(detail));
  }
}

const seed = ensureMedia();
const r = run(seed);
if (r.error) {
  console.error('❌ 采集失败：', r.error);
  console.error(r.stack || '');
  process.exit(1);
}

console.log(`视口 ${r.viewport.w}×${r.viewport.h} · 检查器 ${r.asideWidth}px`);
check('「朗读 ⚙」面板已展开', r.panelOpen === true, r);
check('检查器宽 348px', r.asideWidth === 348, r.asideWidth);
check('选中克隆音色（音色库计数 1）', r.voiceCount === '1', r.voiceLabel);
check('「管理」按钮只在克隆音色时出现', r.manageLabel.includes('管理'), r.manageLabel);
check('面板没有横向溢出（panel）', r.panel && r.panel.scrollWidth <= r.panel.clientWidth, r.panel);
check('检查器没有横向溢出（aside）', r.aside.scrollWidth <= r.aside.clientWidth, r.aside);
check('检查器滚动区没有横向溢出', r.scroll.scrollWidth <= r.scroll.clientWidth, r.scroll);
check('面板内控件全部落在检查器框内', r.outside.length === 0, r.outside);
check('没有被压成 0 宽 / 越界的动作按钮', r.clipped.length === 0, r.clipped);
check('面板第一行仍能看到音色信息', r.meta.length > 0, r.meta);
// 面板右缘必须在检查器右缘之内（含 1px 亚像素容差）
check(
  '面板右缘不越过检查器右缘',
  Boolean(r.panel) && r.panel.right <= r.asideRight + 1 && r.panel.left >= r.asideLeft - 1,
  { panel: r.panel, asideLeft: r.asideLeft, asideRight: r.asideRight },
);

console.log(`截图：${SHOT}`);
if (failed) {
  console.error(`\n${failed} 项失败`);
  process.exit(1);
}
console.log('\n全部通过。');
