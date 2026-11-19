#!/usr/bin/env node
/**
 * 单句 AI 常驻区 + 多轮对话浮窗的无窗口回归。
 *
 * 覆盖用户报障的路径：B 引擎返回空 / 没跑 B，AI 区域仍可用；听音线索输入；
 * 切换句子不丢草稿；展开浮窗后能看到完整历史、每轮朗读/采用、可拖动缩放。
 *
 * 走 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），桌面上不出现。
 * 沙箱 / CI 里 Electron 起不来时：
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox node tools/shots/verify_arbitration_dialog.mjs
 */

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-arbitration-dialog');
const OUT = path.join(BASE, 'out');
const MEDIA = path.join(BASE, 'media.mp4');

const CUES = [
  { start: 0.4, end: 1.6, text: 'おはようございます' },
  { start: 1.8, end: 3.0, text: '今日はいい天気ですね' },
  { start: 3.2, end: 4.8, text: '' },
  { start: 5.0, end: 6.4, text: 'ちょっと待ってください' },
  { start: 6.6, end: 8.0, text: 'もう一回お願いします' },
];

const EVAL = String.raw`
  (async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const waitFor = async (fn, timeout = 8000) => {
      const start = Date.now();
      while (Date.now() - start < timeout) {
        const value = fn();
        if (value) return value;
        await sleep(80);
      }
      return null;
    };
    const text = (el) => (el ? el.textContent.trim() : null);
    const out = {};

    // 真实模型不能出现在无窗口回归里：只拦 /api/ai/config 与 /api/ai/arbitrate，
    // 其余请求照常走真实 sidecar。「重新判定」请求体是否真的清空历史，在这里取证。
    const realFetch = window.fetch.bind(window);
    const arbitrateCalls = [];
    window.fetch = async (input, init = {}) => {
      const url = String(typeof input === 'string' ? input : input?.url || '');
      if (url.includes('/api/ai/config')) {
        return new Response(
          JSON.stringify({
            enabled: true,
            base_url: 'https://stub.invalid/v1',
            model: 'stub-model',
            chunk_cues: 300,
            translate_chunk_cues: 300,
            context_cues: 3,
            arbitrate_base_url: '',
            arbitrate_model: '',
            local_context: 2048,
            auto_arbitrate: false,
            key_optional: true,
            arbitrate_key_optional: true,
            arbitrate_loopback: false,
            key_held_by: 'renderer',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (url.includes('/api/ai/arbitrate')) {
        const body = JSON.parse(init.body || '{}');
        arbitrateCalls.push(body);
        const n = arbitrateCalls.length;
        return new Response(
          JSON.stringify({
            text: n === 1 ? 'クリーン重判結果' : '追問結果',
            note: n === 1 ? '干净重判' : '带着上一轮结果追问',
            model: 'stub-model',
            elapsed_ms: 1,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return realFetch(input, init);
    };

    let stage = 'select-row';
    try {
    await waitFor(() => document.querySelector('.row[data-i="2"]'));
    document.querySelector('.row[data-i="2"]').click();
    await sleep(350);

    out.card = Boolean(document.querySelector('.arb'));
    out.head = text(document.querySelector('.arb-head b'));
    out.bEmptyTip = text(document.querySelector('.arb-tip.hint'));
    out.hasHintInput = Boolean(document.querySelector('.arb-hint textarea'));
    out.expandLabel = text(document.querySelector('.arb-expand'));
    out.runLabel = text(document.querySelector('.arb-run'));
    out.rejudgeLabelBefore = text(document.querySelector('.arb-run'));
    out.copyCounts = {
      a: document.querySelectorAll('.so-card.current .copy').length,
      b: document.querySelectorAll('.so-card.alt .copy').length,
      ai: document.querySelectorAll('.arb-card .copy').length,
    };
    out.cardDuplicateEntry = [...document.querySelectorAll('.arb-card .arb-actions button')].some(
      (button) => /查看对话|继续追问/.test(text(button)),
    );
    out.sendFollowUp = {
      label: text(document.querySelector('.arb-send-followup')),
      disabled: Boolean(document.querySelector('.arb-send-followup')?.disabled),
    };
    const bAdopt = [...document.querySelectorAll('.so-actions button')].find((b) =>
      (b.textContent || '').includes('采用 B 版'),
    );
    out.bAdoptDisabled = Boolean(bAdopt?.disabled);
    out.bBadges = [...document.querySelectorAll('.so-badge')].map(text);

    stage = 'draft-typing';
    // 输入草稿 -> 切到另一句 -> 切回来：线程缓存应保留草稿。
    const input = document.querySelector('.arb-hint textarea');
    if (input) {
      input.value = '听起来像 スゴイ';
      input.dispatchEvent(new Event('input', { bubbles: true }));
      await sleep(120);
    }
    document.querySelector('.row[data-i="3"]').click();
    await sleep(250);
    document.querySelector('.row[data-i="2"]').click();
    await sleep(300);
    out.draftAfterSwitch = document.querySelector('.arb-hint textarea')?.value ?? '';
    out.sendFollowUpWithDraft = {
      label: text(document.querySelector('.arb-send-followup')),
      disabled: Boolean(document.querySelector('.arb-send-followup')?.disabled),
    };
    out.rejudgeLabelWithHistory = text(document.querySelector('.arb-run'));

    stage = 'open-dialog';
    // 展开浮窗。
    document.querySelector('.arb-expand').click();
    await waitFor(() => document.querySelector('.arb-dialog'));
    await sleep(250);
    const dialog = document.querySelector('.arb-dialog');
    out.dialog = Boolean(dialog);
    out.dialogTitle = text(dialog?.querySelector('.dlg-title b'));
    out.hasContext = Boolean(dialog?.querySelector('.ctx'));
    out.aiMessages = dialog?.querySelectorAll('.msg.ai').length ?? 0;
    out.userMessages = dialog?.querySelectorAll('.msg.user').length ?? 0;
    out.ttsButtons = [...(dialog?.querySelectorAll('.msg.ai .msg-tts') || [])].map(text);
    out.adoptButtons = [...(dialog?.querySelectorAll('.msg.ai .msg-actions button') || [])].map(text);
    out.dialogDraft = dialog?.querySelector('.dlg-foot textarea')?.value ?? '';
    out.dialogCopyButtons = dialog?.querySelectorAll('.msg.ai .copy').length ?? 0;
    out.userUndoButtons = [...(dialog?.querySelectorAll('.msg.user .msg-undo') || [])].map(text);
    out.dialogRejudgeLabel = text(dialog?.querySelector('.dlg-links .link'));
    out.dialogSendLabel = text(dialog?.querySelector('.dlg-actions .btn.primary'));
    out.selectable = {
      ctx: getComputedStyle(dialog.querySelector('.ctx-text')).userSelect,
      ai: getComputedStyle(dialog.querySelector('.msg.ai .msg-text')).userSelect,
      note: getComputedStyle(dialog.querySelector('.msg.ai .msg-note')).userSelect,
      user: getComputedStyle(dialog.querySelector('.msg.user p')).userSelect,
    };

    stage = 'drag-dialog';
    // 拖动标题栏：位置应变化。
    const head = dialog.querySelector('.dlg-head');
    const before = { left: dialog.style.left, top: dialog.style.top };
    const hs = head.getBoundingClientRect();
    head.dispatchEvent(new PointerEvent('pointerdown', {
      bubbles: true, clientX: hs.left + 40, clientY: hs.top + 12, pointerId: 1,
    }));
    await sleep(80);
    window.dispatchEvent(new PointerEvent('pointermove', {
      bubbles: true, clientX: hs.left + 110, clientY: hs.top + 72, pointerId: 1,
    }));
    await sleep(80);
    window.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1 }));
    await sleep(120);
    out.dragged = dialog.style.left !== before.left || dialog.style.top !== before.top;

    stage = 'resize-dialog';
    // 右下角缩放：尺寸应变化。
    const resize = dialog.querySelector('.dlg-resize');
    const sizeBefore = { w: dialog.getBoundingClientRect().width, h: dialog.getBoundingClientRect().height };
    resize.dispatchEvent(new PointerEvent('pointerdown', {
      bubbles: true, clientX: 10, clientY: 10, pointerId: 2,
    }));
    await sleep(80);
    window.dispatchEvent(new PointerEvent('pointermove', {
      bubbles: true, clientX: 90, clientY: 70, pointerId: 2,
    }));
    await sleep(80);
    window.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 2 }));
    await sleep(120);
    const sizeAfter = dialog.getBoundingClientRect();
    out.resized = Math.abs(sizeAfter.width - sizeBefore.w) > 8 || Math.abs(sizeAfter.height - sizeBefore.h) > 8;

    stage = 'esc-close';
    // Esc 收起浮窗。
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await sleep(200);
    out.dialogClosedByEsc = !document.querySelector('.arb-dialog');

    stage = 'clean-rejudge';
    // ---- 重新判定：必须清空历史，只带干净材料 ----
    const sidebarInput = document.querySelector('.arb-hint textarea');
    sidebarInput.value = '';
    sidebarInput.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(100);
    out.sendFollowUpDisabledEmpty = Boolean(
      document.querySelector('.arb-send-followup')?.disabled,
    );
    out.rejudgeLabelBefore = text(document.querySelector('.arb-run'));
    document.querySelector('.arb-run').click();
    await waitFor(() => arbitrateCalls.length >= 1, 6000);
    await waitFor(
      () => (document.querySelector('.arb-card .arb-text')?.textContent || '').includes('クリーン重判結果'),
      5000,
    );
    await sleep(150);
    const clean = arbitrateCalls[0] || {};
    out.cleanHistoryLen = Array.isArray(clean.history) ? clean.history.length : -1;
    out.cleanHint = clean.hint ?? null;
    out.cleanRequestHasOldText = /旧追问|被带偏|听起来像 スゴイ/.test(JSON.stringify(clean));
    out.cleanResultText = text(document.querySelector('.arb-card .arb-text'));
    out.rejudgeLabelAfterClean = text(document.querySelector('.arb-run'));
    out.sendFollowUpDisabledAfterClean = Boolean(
      document.querySelector('.arb-send-followup')?.disabled,
    );

    stage = 'send-followup';
    // ---- 发送追问：只有输入框非空时才追加进 history ----
    const followInput = document.querySelector('.arb-hint textarea');
    followInput.value = '新しいヒント';
    followInput.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(100);
    out.sendFollowUpEnabledWithDraft = !document.querySelector('.arb-send-followup')?.disabled;
    document.querySelector('.arb-send-followup').click();
    await waitFor(() => arbitrateCalls.length >= 2, 6000);
    await waitFor(
      () => (document.querySelector('.arb-card .arb-text')?.textContent || '').includes('追問結果'),
      5000,
    );
    await sleep(150);
    const follow = arbitrateCalls[1] || {};
    out.followHistoryLen = Array.isArray(follow.history) ? follow.history.length : -1;
    out.followHistoryFirst = follow.history?.[0]?.text ?? '';
    out.followHint = follow.hint ?? '';
    out.followResultText = text(document.querySelector('.arb-card .arb-text'));

    stage = 'dialog-copy-undo';
    // ---- 浮窗：复制反馈 + 撤销上一轮追问并同步右侧结果卡 ----
    document.querySelector('.arb-expand').click();
    await waitFor(() => document.querySelector('.arb-dialog'));
    await sleep(250);
    const actionDialog = document.querySelector('.arb-dialog');
    out.afterFollow = {
      ai: actionDialog.querySelectorAll('.msg.ai').length,
      user: actionDialog.querySelectorAll('.msg.user').length,
      undoLabels: [...actionDialog.querySelectorAll('.msg.user .msg-undo')].map(text),
    };
    const copyButton = actionDialog.querySelector('.msg.ai .copy');
    out.copyLabelBefore = text(copyButton);
    copyButton?.click();
    await sleep(250);
    out.copyLabelAfter = text(actionDialog.querySelector('.msg.ai .copy'));
    actionDialog.querySelector('.msg.user .msg-undo')?.click();
    await sleep(300);
    out.afterUndo = {
      ai: actionDialog.querySelectorAll('.msg.ai').length,
      user: actionDialog.querySelectorAll('.msg.user').length,
      cardText: text(document.querySelector('.arb-card .arb-text')),
      rejudgeLabel: text(actionDialog.querySelector('.dlg-links .link')),
      footerUndoGone: ![...actionDialog.querySelectorAll('.dlg-links .link')].some((button) =>
        (text(button) || '').includes('撤回上一轮')),
      sendDisabledEmpty: Boolean(actionDialog.querySelector('.dlg-actions .btn.primary')?.disabled),
    };

    stage = 'final-followup';
    // 再追加一条追问，让最终截图同时出现用户气泡（撤销入口）与复制按钮。
    const dialogInput = actionDialog.querySelector('.dlg-foot textarea');
    dialogInput.value = '截图用追问';
    dialogInput.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(100);
    out.dialogSendEnabledWithDraft = !actionDialog.querySelector('.dlg-actions .btn.primary')
      ?.disabled;
    actionDialog.querySelector('.dlg-actions .btn.primary').click();
    await waitFor(() => arbitrateCalls.length >= 3, 6000);
    await waitFor(() => document.querySelectorAll('.arb-dialog .msg.user').length >= 1, 5000);
    await sleep(150);
    out.reopenedForShot = Boolean(document.querySelector('.arb-dialog'));
    out.finalUndoVisible = Boolean(document.querySelector('.msg.user .msg-undo'));

    return JSON.stringify(out);
    } catch (err) {
      return JSON.stringify({ ...out, stage, error: String(err), stack: err?.stack });
    }
  })()
`;

function ensureMedia() {
  if (fs.existsSync(MEDIA)) return;
  fs.mkdirSync(BASE, { recursive: true });
  execFileSync('ffmpeg', [
    '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x334455:s=640x360:d=10',
    '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', MEDIA,
  ]);
}

function ensureSettings() {
  const settingsPath = path.join(BASE, 'settings.json');
  fs.writeFileSync(
    settingsPath,
    JSON.stringify(
      {
        enabled_engines: ['whisper', 'qwen', 'sensevoice', 'firered'],
        ai_enabled: true,
        ai_base_url: 'http://127.0.0.1:9/v1',
        ai_model: 'stub-model',
        ai_local_context: 2048,
        ai_auto_arbitrate: false,
      },
      null,
      2,
    ),
    'utf8',
  );
  return settingsPath;
}

function ensureSeed() {
  const seedPath = path.join(BASE, 'seed.json');
  fs.writeFileSync(
    seedPath,
    JSON.stringify(
      {
        mediaPath: MEDIA,
        cues: CUES,
        // B 引擎跑过但没识别出内容：AI 区仍要可用，并明确提示。
        secondOpinion: { engine: 'qwen', index: 2, text: '' },
        arbitration: {
          index: 2,
          text: 'こくろこくろ…あつ、あつ',
          note: '第三轮保留用户修正后的拟声词',
          model: 'deepseek-chat',
          hint: '听起来像 スゴイ',
          history: [
            {
              role: 'assistant',
              text: 'ぐちゅぐちゅ…あっ、あっ',
              note: '第一轮不采用',
              model: 'deepseek-chat',
            },
            { role: 'user', text: 'a kokoqu a a' },
            {
              role: 'assistant',
              text: 'こくろこくろ…あつ、あつ',
              note: '第二轮',
              model: 'deepseek-chat',
            },
            { role: 'user', text: '再听一遍，还是 kokoro' },
            {
              role: 'assistant',
              text: 'こくろこくろ…あつ、あつ',
              note: '第三轮',
              model: 'deepseek-chat',
            },
          ],
        },
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
    KIKUSUB_SHOT_DELAY: '2600',
    KIKUSUB_OUTPUT_DIR: OUT,
    KIKUSUB_DATA_DIR: path.join(BASE, 'data'),
    KIKUSUB_PREFERENCES_PATH: path.join(BASE, 'prefs.json'),
    // AI 配置走真实 sidecar 读盘：没有这份设置，卡片会停在「还没配置 AI 服务」，
    // 「重新判定」按钮根本不会渲染，也就测不到用户报障的那条路径。
    KIKUSUB_SETTINGS_PATH: ensureSettings(),
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
        `--screenshot=${path.join(BASE, 'dialog.png')}`,
        ...extra,
      ],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 180_000 },
    ).toString();
  } catch (error) {
    stdout = `${error.stdout ?? ''}`;
    console.error(String(error.stderr ?? '').slice(-800));
  }
  const line = stdout.split('\n').filter((row) => row.startsWith('[eval]')).pop();
  if (!line) {
    console.error(stdout.split('\n').filter((row) => row.startsWith('[eval:')).join('\n'));
    throw new Error('渲染进程没有回传结果');
  }
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
  if (data.error) {
    console.error(`EVAL ERROR @ ${data.stage}: ${data.error}`);
    console.error(data.stack || '');
    process.exit(1);
  }
  check('没跑 B 也出现 AI 区', data.card === true);
  check('标题是 AI 判定', data.head === 'AI 判定', data.head);
  check('B 未识别提示可见', (data.bEmptyTip || '').includes('未识别'), data.bEmptyTip);
  check('有听音线索输入框', data.hasHintInput === true);
  check('有展开对话按钮', (data.expandLabel || '').includes('展开对话'), data.expandLabel);
  check('B 为空时「采用 B 版」禁用', data.bAdoptDisabled === true);
  check('两版都空时徽章不说「一致」', (data.bBadges || []).includes('两版均无内容'), JSON.stringify(data.bBadges));
  check('切换句子后草稿还在', data.draftAfterSwitch === '听起来像 スゴイ', data.draftAfterSwitch);
  check('浮窗打开', data.dialog === true);
  check('浮窗标题', (data.dialogTitle || '').includes('AI 多轮对话'), data.dialogTitle);
  check('浮窗有可折叠上下文', data.hasContext === true);
  check('历史里有 AI 消息', data.aiMessages >= 2, String(data.aiMessages));
  check('历史里有用户消息', data.userMessages >= 2, String(data.userMessages));
  check(
    '每条 AI 消息都有朗读',
    data.ttsButtons.length === data.aiMessages && data.ttsButtons.every((label) => label === '朗读'),
    JSON.stringify(data.ttsButtons),
  );
  check(
    '每条 AI 消息都有采用',
    data.adoptButtons.length === data.aiMessages &&
      data.adoptButtons.every((label) => (label || '').includes('采用')),
    JSON.stringify(data.adoptButtons),
  );
  check('浮窗草稿同步', data.dialogDraft === '听起来像 スゴイ', data.dialogDraft);
  check('右侧只保留一个展开入口', data.cardDuplicateEntry === false);
  check(
    'A / B / AI 三张卡都有复制按钮',
    data.copyCounts.a === 1 && data.copyCounts.b === 1 && data.copyCounts.ai === 1,
    JSON.stringify(data.copyCounts),
  );
  check('输入框旁有明确的发送追问按钮', data.sendFollowUp.label === '发送追问', data.sendFollowUp.label);
  check(
    '已有追问时重判文案提示清空历史',
    (data.rejudgeLabelBefore || '').includes('清空追问并重判'),
    data.rejudgeLabelBefore,
  );
  check('草稿非空时发送追问可用', data.sendFollowUpWithDraft.disabled === false);
  check(
    '浮窗每条 AI 回复都有复制按钮',
    data.dialogCopyButtons === data.aiMessages,
    `${data.dialogCopyButtons} / ${data.aiMessages}`,
  );
  check(
    '浮窗每条用户追问都有撤销入口',
    data.userUndoButtons.length === data.userMessages &&
      data.userUndoButtons.every((label) => (label || '').includes('撤销这轮及之后')),
    JSON.stringify(data.userUndoButtons),
  );
  check(
    '浮窗重判也明确清空历史',
    data.dialogRejudgeLabel === '清空追问并重判',
    data.dialogRejudgeLabel,
  );
  check('浮窗发送按钮叫发送追问', data.dialogSendLabel === '发送追问', data.dialogSendLabel);
  check(
    '上下文 / AI 文本 / 理由 / 用户追问均可选中',
    Object.values(data.selectable || {}).every((value) => value === 'text'),
    JSON.stringify(data.selectable),
  );
  check('清空重判不带任何 history', data.cleanHistoryLen === 0, String(data.cleanHistoryLen));
  check('清空重判在输入框为空时 hint 为空', data.cleanHint === '', JSON.stringify(data.cleanHint));
  check('清空重判请求不带旧追问文本', data.cleanRequestHasOldText === false);
  check(
    '清空重判后只显示干净结果',
    (data.cleanResultText || '').includes('クリーン重判結果'),
    data.cleanResultText,
  );
  check('清空重判后按钮回到重新判定', data.rejudgeLabelAfterClean === '重新判定', data.rejudgeLabelAfterClean);
  check('清空重判后输入框为空时发送追问禁用', data.sendFollowUpDisabledAfterClean === true);
  check(
    '追问携带上一轮干净结果',
    data.followHistoryLen === 1 && data.followHistoryFirst === 'クリーン重判結果',
    JSON.stringify({ len: data.followHistoryLen, first: data.followHistoryFirst }),
  );
  check('追问 hint 只带本次输入', data.followHint === '新しいヒント', data.followHint);
  check(
    '追问成功追加一轮',
    data.afterFollow.ai === 2 && data.afterFollow.user === 1,
    JSON.stringify(data.afterFollow),
  );
  check(
    'AI 回复旁复制按钮有反馈',
    data.copyLabelBefore === '复制' && ['已复制', '复制失败'].includes(data.copyLabelAfter),
    `${data.copyLabelBefore} -> ${data.copyLabelAfter}`,
  );
  check(
    '撤销这一轮及之后只截断前端历史',
    data.afterUndo.ai === 1 && data.afterUndo.user === 0,
    JSON.stringify(data.afterUndo),
  );
  check(
    '撤销后右侧结果卡回到上一轮',
    data.afterUndo.cardText === data.cleanResultText,
    `${data.afterUndo.cardText} != ${data.cleanResultText}`,
  );
  check('撤销后重判文案回到重新判定', data.afterUndo.rejudgeLabel === '重新判定', data.afterUndo.rejudgeLabel);
  check('撤销后底部撤回入口消失', data.afterUndo.footerUndoGone === true);
  check('撤销后输入框为空时发送追问禁用', data.afterUndo.sendDisabledEmpty === true);
  check('输入框非空时发送追问可用', data.dialogSendEnabledWithDraft === true);
  check('截图前仍有撤销入口', data.finalUndoVisible === true);
  check('标题栏可拖动', data.dragged === true);
  check('右下角可缩放', data.resized === true);
  check('Esc 收起浮窗', data.dialogClosedByEsc === true);
  check('截图前重新打开浮窗', data.reopenedForShot === true);

  const shot = path.join(BASE, 'dialog.png');
  if (fs.existsSync(shot)) console.log(`\n截图：${shot}`);
  else console.error('\n截图缺失（--screenshot 没跑通？）');

  if (failures.length) {
    console.error(`\n${failures.length} 项失败`);
    process.exit(1);
  }
  console.log('\n全部通过');
}

main();
