#!/usr/bin/env node
/**
 * 设置四个子页的布局回归：不许挤出内容区、不许文字互相压住（2026-11-24，§3.4.16）。
 *
 * 触发：用户报「设置每个子页显示都异常」。上一版把断点全改成 `@container sheet`
 * 之后断点是对的，但 `.set-row-ctl { flex: 0 0 auto }` 让控件列永不收缩，
 * 一条「路径 + 徽标 + 三个按钮」把左侧说明压成 46–160px、9–11 行的竖条；
 * 音色克隆卡的三列网格则让步骤链溢出，压住「打开模型目录」。
 *
 * 这个脚本不比较像素（那样每次字体微调都会红），只断言三条布局不变量：
 *
 * 1. 内容区里没有任何元素的右边界越过 `.set-content` 的右边界；
 * 2. 没有两块可见文字（按钮 / 徽标 / 步骤 / 标题 / 说明 / 输入框）互相压住；
 * 3. 没有可见文字元素 `scrollWidth > clientWidth`（`.set-path` 的省略号是有意的，
 *    它带 title，单独放行）。
 *
 * 四页 × 四种视口条件（1440 / 1120 / 1000 / 1440 + 200% 缩放）全部要满足。
 * 折叠区（进阶 / 其余内部路径 / 日志原文）在每个视口里都展开再量，避免只量短状态。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），桌面上不出现。
 *
 * 用法：
 *   node tools/shots/verify_settings_layout.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_settings_layout.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-settings-layout');

/** 四页 × 四档视口；`zoom` 用 CSS zoom 模拟 200% 缩放。 */
const CASES = [
  { name: '1440x900', size: '1440x900', zoom: 1 },
  { name: '1120x800', size: '1120x800', zoom: 1 },
  { name: '1000x700', size: '1000x700', zoom: 1 },
  { name: '1440x900-zoom200', size: '1440x900', zoom: 2 },
];
const TABS = ['engines', 'appearance', 'ai', 'env'];

/**
 * 在渲染进程里扫四个页签。每一步滚动 260px 量一次，覆盖整页高度；
 * 只统计「真的画出来」的元素（宽高 > 0），关掉的 details 里没有盒子。
 */
const EVAL = String.raw`
  (async () => {
    const ZOOM = __ZOOM__;
    if (ZOOM !== 1) {
      document.documentElement.style.zoom = String(ZOOM);
      await new Promise((r) => setTimeout(r, 500));
    }
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const label = (el) => {
      const cls = typeof el.className === 'string' ? el.className.split(' ')[0] : '';
      return el.tagName.toLowerCase() + (cls ? '.' + cls : '');
    };

    // 设置入口是侧栏最后一项（「设置」不在 View 联合类型里，它开浮层）。
    const items = document.querySelectorAll('.sb-item');
    items[items.length - 1]?.click();
    await sleep(2600);
    const content = document.querySelector('.set-content');
    if (!content) return JSON.stringify({ error: '设置浮层没有打开' });

    const result = { contentW: Math.round(content.getBoundingClientRect().width), tabs: {} };

    for (const id of ${JSON.stringify(TABS)}) {
      document.querySelector('#set-tab-' + id)?.click();
      await sleep(1200);
      // 把折叠区全部展开，最长状态也要量。
      for (const d of content.querySelectorAll('details:not([open])')) {
        d.open = true;
        await sleep(100);
      }
      await sleep(350);

      const broke = [];
      const overlaps = [];
      const clipped = [];
      const maxY = Math.max(0, content.scrollHeight - content.clientHeight);

      for (let y = 0; y <= maxY; y += 260) {
        content.scrollTo(0, y);
        await sleep(150);
        const cr = content.getBoundingClientRect();
        for (const el of content.querySelectorAll('*')) {
          const r = el.getBoundingClientRect();
          if (r.width <= 0 || r.height <= 0) continue;
          // ① 越过内容区右边界
          if (r.right > cr.right + 1) broke.push({ y, el: label(el), over: Math.round(r.right - cr.right) });
          // ③ 可见文字溢出自己的盒子（路径的 ellipsis 放行：它带 title）
          if (el.children.length === 0 && (el.textContent || '').trim() && !el.classList.contains('set-path')) {
            const cs = getComputedStyle(el);
            const ellipsis = cs.textOverflow === 'ellipsis';
            if (!ellipsis && el.scrollWidth > el.clientWidth + 3 && el.clientWidth > 20) {
              clipped.push({ y, el: label(el), sw: el.scrollWidth, cw: el.clientWidth });
            }
          }
        }
      }

      // ② 两块可见文字互相压住（同一行里的兄弟 / 跨列的卡片内容）
      const nodes = [
        ...content.querySelectorAll(
          '.step, .status-chip, .feature-buttons, .btn, .set-row-title, .set-row-desc, .ai-input, .live, .detail-btn, .nav-item, .legend-item',
        ),
      ];
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          if (a.contains(b) || b.contains(a)) continue;
          const ra = a.getBoundingClientRect();
          const rb = b.getBoundingClientRect();
          if (ra.width < 4 || rb.width < 4) continue;
          const ox = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
          const oy = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
          if (ox > 3 && oy > 3) {
            overlaps.push({
              a: label(a) + ':' + a.textContent.trim().slice(0, 12),
              b: label(b) + ':' + b.textContent.trim().slice(0, 12),
              ox: Math.round(ox),
              oy: Math.round(oy),
            });
          }
        }
      }

      const uniq = (arr) => {
        const seen = new Set();
        return arr
          .filter((row) => {
            const key = JSON.stringify(row);
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
          })
          .slice(0, 6);
      };
      content.scrollTo(0, 0);
      await sleep(150);
      result.tabs[id] = {
        broke: uniq(broke),
        overlaps: uniq(overlaps),
        clipped: uniq(clipped),
      };
    }
    return JSON.stringify(result);
  })()
`;

const failures = [];
function check(name, condition, detail) {
  if (condition) {
    console.log(`✅ ${name}`);
    return;
  }
  failures.push(name);
  console.error(`❌ ${name}${detail === undefined ? '' : `\n   ${JSON.stringify(detail)}`}`);
}

function run(name, { size, zoom, shot }) {
  const dir = path.join(BASE, 'run', name);
  fs.rmSync(dir, { recursive: true, force: true });
  for (const sub of ['data', 'profile', 'out']) fs.mkdirSync(path.join(dir, sub), { recursive: true });
  fs.mkdirSync(path.dirname(shot), { recursive: true });

  const extra = (process.env.KIKUSUB_SHOT_ELECTRON_ARGS || '').split(/\s+/).filter(Boolean);
  const env = {
    ...process.env,
    KIKUSUB_ALLOW_MULTIPLE: '1',
    KIKUSUB_WIN_SIZE: size,
    KIKUSUB_SHOT_DELAY: '3500',
    KIKUSUB_OUTPUT_DIR: path.join(dir, 'out'),
    KIKUSUB_DATA_DIR: path.join(dir, 'data'),
    KIKUSUB_PREFERENCES_PATH: path.join(dir, 'prefs.json'),
    KIKUSUB_SETTINGS_PATH: path.join(dir, 'settings', 'settings.json'),
    KIKUSUB_DEV_EVAL: EVAL.replace('__ZOOM__', String(zoom)),
  };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.NODE_OPTIONS;

  let stdout = '';
  try {
    stdout = execFileSync(
      'npx',
      ['electron', '.', `--user-data-dir=${path.join(dir, 'profile')}`, `--screenshot=${shot}`, ...extra],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 240_000 },
    ).toString();
  } catch (error) {
    stdout = `${error.stdout ?? ''}`;
    console.error(String(error.stderr ?? '').slice(-1200));
  }
  const evalError = stdout.split('\n').filter((row) => row.startsWith('[eval:error]')).pop();
  if (evalError) throw new Error(`${name}: ${evalError}`);
  const line = stdout.split('\n').filter((row) => row.startsWith('[eval]')).pop();
  if (!line) throw new Error(`${name}: 渲染进程没有回传结果`);
  if (!fs.existsSync(shot)) throw new Error(`${name}: 没有生成截图 ${shot}`);
  return JSON.parse(line.slice('[eval] '.length));
}

console.log('设置四页布局回归（不越界 / 不重叠 / 不挤成竖条）\n');
for (const testCase of CASES) {
  const shot = path.join(BASE, `settings-layout-${testCase.name}.png`);
  const result = run(`layout-${testCase.name}`, { ...testCase, shot });
  if (result.error) throw new Error(`${testCase.name}: ${result.error}`);

  for (const tab of TABS) {
    const rows = result.tabs[tab];
    if (!rows) {
      check(`${testCase.name} · ${tab} 页有内容`, false);
      continue;
    }
    check(`${testCase.name} · ${tab}：没有元素越过内容区右边界`, rows.broke.length === 0, rows.broke);
    check(`${testCase.name} · ${tab}：没有文字互相压住`, rows.overlaps.length === 0, rows.overlaps);
    check(`${testCase.name} · ${tab}：没有文字被自己的盒子截断`, rows.clipped.length === 0, rows.clipped);
  }
  console.log(`   截图：${shot}\n`);
}

if (failures.length) {
  console.error(`\n${failures.length} 条失败：`);
  for (const name of failures) console.error(` - ${name}`);
  process.exit(1);
}
console.log('全部通过。');
