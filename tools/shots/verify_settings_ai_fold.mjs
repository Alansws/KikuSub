#!/usr/bin/env node
/**
 * 设置页「进阶：单句判定独立模型与本地部署」折叠 + 导出页收尾的无窗口回归
 * （2026-11-21，界面重构 Step 6）。
 *
 * 四件事在真实界面里断言：
 *
 * 1. **全新配置时默认收起**：设置 → AI 与技能顶层只留「启用 / 服务地址 / 模型 /
 *    API Key / 连接测试」，进阶折叠区（单句判定覆盖、自动判定、本地档位、分块参数）
 *    默认不可见；点开就能看到，再点收起。
 * 2. **已配置时默认展开**：预置判定地址 / 判定模型 + 自动判定，折叠区一进来就是展开的，
 *    既有高级配置不会因为折叠而「消失」；用户手动收起后以用户为准。
 * 3. **导出页底部去宣传文案**：没有「为什么在 KikuSub 里导出」段落，底部只剩操作按钮。
 * 4. **无译文轨时一次提示**：页头一句「还没有译文轨：先到「双语翻译」生成并应用一版」，
 *    两段的译文 / 双语按钮同处置灰（Step 4.3 把原来重复的两句收敛成一条）。
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），桌面上不出现。
 *
 * 用法：
 *   node tools/shots/verify_settings_ai_fold.mjs
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_settings_ai_fold.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-settings-ai-fold');
const MEDIA = path.join(BASE, 'clip.mp4');

const HINT = '还没有译文轨：先到「双语翻译」生成并应用一版，这里才能选译文 / 双语。';
const OLD_WHY = '为什么在 KikuSub 里导出';

/** 顶部公共小工具：切页、等元素、可读文本、是否真的可见（关掉的 details 里没有盒子）。 */
const PRELUDE = String.raw`
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const waitFor = async (fn, ms = 9000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) {
      const value = fn();
      if (value) return value;
      await sleep(80);
    }
    return null;
  };
  const text = (node) => node?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
  // 关掉的 <details> 里内容仍有 layout 盒子（content-visibility: hidden），
  // getClientRects() 判不出来；checkVisibility() 才是「真的画在屏幕上」。
  const visible = (node) =>
    Boolean(node && node.getClientRects().length && node.checkVisibility?.() !== false);
  const byLabel = (label) => document.querySelector('[aria-label="' + label + '"]');
`;

const EVAL_SETTINGS = String.raw`
  (async () => {
    ${PRELUDE}

    document.querySelectorAll('.sb-item')[9]?.click();
    await sleep(600);
    document.querySelector('#set-tab-ai')?.click();
    const fold = await waitFor(() => document.querySelector('details.ai-adv'));
    await sleep(500);
    if (!fold) return JSON.stringify({ error: 'AI 页没有出现进阶折叠区' });

    const state = () => {
      const arbUrl = byLabel('单句判定服务地址');
      const auto = byLabel('两版不一致时自动 AI 判定');
      const advParams = document.querySelector('details.advanced');
      return {
        open: Boolean(fold.open),
        title: text(fold.querySelector('.adv-title')),
        meta: text(fold.querySelector('.adv-meta')),
        visibleRowTitles: [...document.querySelectorAll('#set-pane-ai .set-row-title')]
          .filter(visible)
          .map(text),
        hasServiceRow: [...document.querySelectorAll('#set-pane-ai .set-row-title')]
          .some((node) => visible(node) && text(node) === '服务地址'),
        arbUrlVisible: visible(arbUrl),
        arbUrl: arbUrl?.value ?? null,
        arbModel: byLabel('单句判定模型名')?.value ?? null,
        autoArbChecked: auto?.getAttribute('aria-checked') ?? null,
        autoArbVisible: visible(auto),
        advancedParamsVisible: visible(advParams),
        advancedParamsMeta: text(advParams?.querySelector('.adv-summary')),
        chunkInputVisible: visible(document.querySelector('details.advanced .adv-input')),
      };
    };

    const first = state();
    const summary = fold.querySelector('summary');

    summary.click();
    await sleep(320);
    const opened = state();

    // 嵌套的「高级参数」也要能单独展开（两级 details 不打架）
    const advParams = document.querySelector('details.advanced');
    advParams?.querySelector('summary')?.click();
    await sleep(280);
    const nested = {
      open: Boolean(advParams?.open),
      inputVisible: visible(document.querySelector('details.advanced .adv-input')),
    };
    advParams?.querySelector('summary')?.click();
    await sleep(180);

    summary.click();
    await sleep(320);
    const closedAgain = state();

    // 截图把折叠区放到视口上部（核心配置在它上面，截图仍能看到折叠区的全部内容）
    const scroller = document.querySelector('.settings');
    if (fold.open) {
      // 展开态：把折叠区放到视口上部，既有判定配置一屏可见
      const foldTop = fold.getBoundingClientRect().top + scroller.scrollTop;
      scroller.scrollTop = Math.max(0, Math.round(foldTop - 170));
    } else {
      // 收起态：从页头开始截，顶层只剩核心配置
      scroller.scrollTop = 0;
    }
    await sleep(320);

    return JSON.stringify({ first, opened, nested, closedAgain });
  })()
`;

const EVAL_EXPORT = (toBottom) => String.raw`
  (async () => {
    ${PRELUDE}

    document.querySelectorAll('.sb-item')[7]?.click();
    await waitFor(() => document.querySelector('.export-view'));
    await waitFor(() => document.querySelector('.sub-row .seg'));
    await sleep(1000);

    const hint = document.querySelector('.track-note span'); // 句子本身；右侧「去双语翻译」是动作
    const subButtons = [...document.querySelectorAll('.sub-row .seg button')].map((button) => ({
      label: text(button),
      disabled: Boolean(button.disabled),
    }));
    const videoButtons = [...document.querySelectorAll('.export-card .seg')]
      .map((seg) => [...seg.querySelectorAll('button')].map((button) => ({
        label: text(button),
        disabled: Boolean(button.disabled),
      })));
    const actions = document.querySelector('.actions');
    const scroller = document.querySelector('.export-view');
    const result = {
      hint: text(hint),
      hintCount: document.querySelectorAll('.track-note').length,
      subButtons,
      videoButtons,
      whyTextInPage: document.body.innerText.includes(${JSON.stringify(OLD_WHY)}),
      whyBlock: Boolean(document.querySelector('.why')),
      actions: {
        exists: Boolean(actions),
        text: text(actions),
        buttons: [...(actions?.querySelectorAll('button') ?? [])].map(text),
      },
      cueCount: text(document.querySelector('.cue-count')),
    };

    if (${Boolean(toBottom)}) {
      scroller.scrollTop = scroller.scrollHeight;
      await sleep(500);
      result.scrolledToBottom = true;
    }
    return JSON.stringify(result);
  })()
`;

function ensureMedia() {
  fs.mkdirSync(BASE, { recursive: true });
  if (!fs.existsSync(MEDIA)) {
    execFileSync('ffmpeg', [
      '-y', '-v', 'error',
      '-f', 'lavfi', '-i', 'color=c=0x223344:s=640x360:d=20',
      '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', MEDIA,
    ]);
  }
}

function seedPath() {
  const src = JSON.parse(fs.readFileSync(path.join(ROOT, 'tools', 'shots', 'seed.json'), 'utf8'));
  src.mediaPath = MEDIA;
  const out = path.join(BASE, 'seed.json');
  fs.writeFileSync(out, JSON.stringify(src, null, 2), 'utf8');
  return out;
}

/** 预置「已配过单句判定」的 settings.json（判定地址 / 模型 + 自动判定）。 */
function configuredSettings(dir) {
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'settings.json');
  fs.writeFileSync(
    file,
    `${JSON.stringify(
      {
        ai_enabled: true,
        ai_base_url: 'https://api.deepseek.com',
        ai_model: 'deepseek-flash',
        ai_arbitrate_base_url: 'http://127.0.0.1:1234/v1',
        ai_arbitrate_model: 'qwen3.8-27b-heretic-uncensored',
        ai_auto_arbitrate: true,
        ai_local_context: 2048,
      },
      null,
      2,
    )}\n`,
    'utf8',
  );
  return file;
}

function run(name, { evalJs, seed = null, settings = null, shot }) {
  const dir = path.join(BASE, 'run', name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, 'data'), { recursive: true });
  fs.mkdirSync(path.join(dir, 'profile'), { recursive: true });
  fs.mkdirSync(path.join(dir, 'out'), { recursive: true });
  fs.mkdirSync(path.dirname(shot), { recursive: true });
  fs.rmSync(shot, { force: true });

  const extra = (process.env.KIKUSUB_SHOT_ELECTRON_ARGS || '').split(/\s+/).filter(Boolean);
  const env = {
    ...process.env,
    KIKUSUB_ALLOW_MULTIPLE: '1',
    KIKUSUB_WIN_SIZE: '1360x838',
    KIKUSUB_SHOT_DELAY: '3500',
    KIKUSUB_OUTPUT_DIR: path.join(dir, 'out'),
    KIKUSUB_DATA_DIR: path.join(dir, 'data'),
    KIKUSUB_PREFERENCES_PATH: path.join(dir, 'prefs.json'),
    KIKUSUB_SETTINGS_PATH:
      settings === 'configured'
        ? configuredSettings(path.join(dir, 'settings'))
        : path.join(dir, 'settings', 'settings.json'),
    KIKUSUB_DEV_EVAL: evalJs,
  };
  if (seed) env.KIKUSUB_DEV_SEED = seed;
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

const failures = [];
function check(name, condition, detail) {
  if (condition) {
    console.log(`✅ ${name}`);
    return;
  }
  failures.push(name);
  console.error(`❌ ${name}${detail === undefined ? '' : `\n   ${JSON.stringify(detail)}`}`);
}

ensureMedia();
const seed = seedPath();
const shots = {
  collapsed: path.join(BASE, 'settings-ai-fold-collapsed.png'),
  configured: path.join(BASE, 'settings-ai-fold-configured.png'),
  exportTrack: path.join(BASE, 'export-track-hint.png'),
  exportBottom: path.join(BASE, 'export-bottom.png'),
};

// ---- 1) 全新配置：进阶折叠区默认收起，核心配置在明面 ----
const fresh = run('settings-fresh', { evalJs: EVAL_SETTINGS, shot: shots.collapsed });
const freshFirst = fresh.first;

check(
  '折叠区标题是「进阶：单句判定独立模型与本地部署」',
  freshFirst.title.includes('进阶：单句判定独立模型与本地部署'),
  freshFirst.title,
);
check('全新配置时默认收起', freshFirst.open === false, freshFirst.open);
check(
  '收起时摘要写明「跟随全局 · 自动判定关」',
  freshFirst.meta.includes('跟随全局') && freshFirst.meta.includes('自动判定关'),
  freshFirst.meta,
);
check(
  '顶层保留核心配置（启用 / 服务地址 / 模型 / API Key / 连接测试）',
  ['启用 AI 优化', '服务地址', '模型', 'API Key', '连接测试'].every((label) =>
    freshFirst.visibleRowTitles.includes(label),
  ) &&
    freshFirst.hasServiceRow === true,
  freshFirst.visibleRowTitles,
);
check('收起时看不到「判定服务地址」', freshFirst.arbUrlVisible === false);
check('收起时看不到自动判定开关', freshFirst.autoArbVisible === false);
check('收起时看不到分块参数', freshFirst.advancedParamsVisible === false);

check('点开后可见「判定服务地址」', fresh.opened.open === true && fresh.opened.arbUrlVisible === true, fresh.opened);
check('点开后可见自动判定开关', fresh.opened.autoArbVisible === true);
check(
  '点开后可见高级分块参数（摘要 = 每块 200 · 翻译 120 · 上下文 5）',
  fresh.opened.advancedParamsVisible === true &&
    fresh.opened.advancedParamsMeta === '每块 200 · 翻译 120 · 上下文 5',
  fresh.opened.advancedParamsMeta,
);
check(
  '嵌套的「高级参数」能单独展开并看到三个输入框',
  fresh.nested.open === true && fresh.nested.inputVisible === true,
  fresh.nested,
);
check(
  '再点一次能收起（回到不可见）',
  fresh.closedAgain.open === false && fresh.closedAgain.arbUrlVisible === false,
  fresh.closedAgain,
);

// ---- 2) 已配过单句判定：默认保持展开，既有配置可见 ----
const configured = run('settings-configured', {
  evalJs: EVAL_SETTINGS,
  settings: 'configured',
  shot: shots.configured,
});
const confFirst = configured.first;

check('已配置判定地址 / 模型时默认展开', confFirst.open === true, confFirst);
check(
  '展开态能看到既有的判定服务地址',
  confFirst.arbUrlVisible === true && confFirst.arbUrl === 'http://127.0.0.1:1234/v1',
  confFirst.arbUrl,
);
check('展开态能看到既有的判定模型', confFirst.arbModel === 'qwen3.8-27b-heretic-uncensored', confFirst.arbModel);
check('展开态能看到自动判定已开', confFirst.autoArbChecked === 'true', confFirst.autoArbChecked);
check(
  '摘要写明「本机 LM Studio · 自动判定开」',
  confFirst.meta.includes('本机 LM Studio') && confFirst.meta.includes('自动判定开'),
  confFirst.meta,
);
check('用户手动收起后以用户为准（不再自动弹回展开）', configured.opened.open === false, configured.opened);
check('再点一次仍能展开', configured.closedAgain.open === true);
check(
  '展开态里也有分块参数摘要',
  configured.closedAgain.advancedParamsMeta === '每块 200 · 翻译 120 · 上下文 5',
  configured.closedAgain.advancedParamsMeta,
);

// ---- 3) 导出页：无译文轨时的轻量引导 ----
const exportTrack = run('export-track', {
  evalJs: EVAL_EXPORT(false),
  seed,
  shot: shots.exportTrack,
});
check('无译文轨时「译文 / 双语」是置灰的', exportTrack.subButtons.every((b) => b.label === '原文' || b.disabled), exportTrack.subButtons);
check('置灰按钮旁有一句引导文案', exportTrack.hint === HINT, exportTrack.hint);
check(
  '「暂无译文轨」只在页头出现一次（不再在两段里各写一遍）',
  exportTrack.hintCount === 1,
  exportTrack.hintCount,
);
check('成片「字幕轨」也给出同一句引导', exportTrack.videoButtons.some((row) => row.length >= 3), exportTrack.videoButtons);

// ---- 4) 导出页底部：宣传段落移除、操作栏干净 ----
const exportBottom = run('export-bottom', {
  evalJs: EVAL_EXPORT(true),
  seed,
  shot: shots.exportBottom,
});
check('页面里不再有「为什么在 KikuSub 里导出」', exportBottom.whyTextInPage === false);
check('也没有残留的说明块', exportBottom.whyBlock === false);
check(
  '底部操作栏只剩导出按钮',
  exportBottom.actions.exists === true &&
    exportBottom.actions.buttons.length === 1 &&
    exportBottom.actions.buttons[0].includes('导出'),
  exportBottom.actions,
);
check('有字幕可导（种子 12 条）', exportBottom.cueCount.startsWith('12'), exportBottom.cueCount);

console.log(`\n截图：\n  ${shots.collapsed}\n  ${shots.configured}\n  ${shots.exportTrack}\n  ${shots.exportBottom}`);
if (failures.length) {
  console.error(`\n${failures.length} 项失败：${failures.join(' / ')}`);
  process.exit(1);
}
console.log('\n全部通过。');
