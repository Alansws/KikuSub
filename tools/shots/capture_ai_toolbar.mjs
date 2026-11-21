#!/usr/bin/env node
/**
 * 「翻译 / 润色 / 断句重排」顶部工作条取证（2026-11-21 界面重构 Step 5）。
 *
 * 一次跑完三个页面的代表状态，并顺手断言这次改版的三条硬约束：
 *   1. 三页头部只有两行（`.aiw-title-row` + `.aiw-cmd-row`）；
 *   2. 翻译页模板只有一个入口（不再有「模板：X」静态文字与下拉框并排）；
 *   3. 源文本已变化（digest 不符）时底部应用主按钮必须禁用。
 *
 * 另外补两张空态证据（翻译无提案 / 断句重排只改几处），确认中间不是一片白。
 *
 * 用法：
 *   node tools/shots/capture_ai_toolbar.mjs                 # 截图 + 断言
 *   node tools/shots/capture_ai_toolbar.mjs --out /tmp/x    # 换输出目录
 *   node tools/shots/capture_ai_toolbar.mjs --state translate-empty
 *   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox 在沙箱 / CI 里补启动参数
 *
 * 走主进程 `--screenshot` 静默路径（透明窗口 + capturePage + app.exit），
 * 桌面上不出现窗口；断言失败退出码非 0。
 */

import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-ai-toolbar');
const MEDIA = path.join(BASE, 'media.mp4');
const DEFAULT_OUT = path.resolve(ROOT, '..');
const STAMP = 'ui-step5-2026-11-21';

const RESHAPE_SRT = `1
00:00:00,000 --> 00:00:02,900
よう、久しぶり。お前は変わったな、本当に。

2
00:00:04,700 --> 00:00:07,800
雨の日だけ、君はここに来る。だから今日も来てみたんだ。

3
00:00:07,900 --> 00:00:12,600
話したいことがある。それは……とても大事な話。でも、うまく言えない。

4
00:00:12,700 --> 00:00:15,800
少しだけ、時間をくれないか。ああ、構わないよ。

5
00:00:15,900 --> 00:00:19,000
じゃあ、一緒に歩こう。……ありがとう。`;

const ZH = [
  '哟，好久不见。你真的变了。',
  '只有在雨天，你才会来这里。所以今天我也来了。',
  '我有话想说。',
  '那是……非常重要的话。',
  '可是，说不出口。',
  '能给我一点时间吗？',
  '啊，没关系。',
  '那，一起走吧。',
  '……谢谢。',
  '嗯。',
  '走吧。',
  '回头见。',
];

const HELPER = String.raw`
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const byText = (root, part) =>
    [...(root?.querySelectorAll('button') ?? [])].find((b) => (b.textContent || '').includes(part));
  const clickSidebar = async (label) => {
    [...document.querySelectorAll('.sb-item')]
      .find((el) => (el.getAttribute('aria-label') || '').startsWith(label))?.click();
    await sleep(1500);
  };
`;

const EVAL = {
  polish: `(async () => {
    ${HELPER}
    await clickSidebar('润色');
    const sd = [...document.querySelectorAll('.aiw-title-row button')].find((b) => b.textContent.trim() === '双源');
    sd?.click();
    await sleep(1500);
    const row1 = document.querySelector('.aiw-title-row');
    const row2 = document.querySelector('.aiw-cmd-row');
    const apply = document.querySelector('.aiw-applybar .btn.primary');
    return JSON.stringify({
      hasRow1: Boolean(row1),
      hasRow2: Boolean(row2),
      headChildren: document.querySelector('.aiw-head')?.children.length ?? 0,
      row1H: Math.round(row1?.getBoundingClientRect().height || 0),
      cmdH: Math.round(row2?.getBoundingClientRect().height || 0),
      laneTabs: [...document.querySelectorAll('.aiw-lane button')].map((b) => b.textContent.trim()),
      oldChannelBars: document.querySelectorAll('.aiw-channel').length,
      pasteReply: [...document.querySelectorAll('button')].filter((b) => (b.textContent || '').includes('粘贴回复')).length,
      bodyHasOldEntry: document.body.innerText.includes('外部粘贴'),
      applyLabel: apply?.textContent.trim() ?? '',
      applyDisabled: apply?.disabled ?? null,
    });
  })()`,

  'polish-stale': `(async () => {
    ${HELPER}
    await clickSidebar('润色');
    await sleep(1200);
    const apply = document.querySelector('.aiw-applybar .btn.primary');
    const note = document.querySelector('.note.err');
    return JSON.stringify({
      applyDisabled: apply?.disabled ?? null,
      applyLabel: apply?.textContent.trim() ?? '',
      note: (note?.textContent || '').replace(/\\s+/g, ' ').trim(),
      moreApplyDisabled: Boolean(document.querySelector('.aiw-applybar .btn.ghost')?.disabled),
    });
  })()`,

  translate: `(async () => {
    ${HELPER}
    await clickSidebar('翻译');
    const row1 = document.querySelector('.aiw-title-row');
    const selects = [...(row1?.querySelectorAll('select') ?? [])];
    return JSON.stringify({
      hasRow1: Boolean(row1),
      hasRow2: Boolean(document.querySelector('.aiw-cmd-row')),
      headChildren: document.querySelector('.aiw-head')?.children.length ?? 0,
      row1H: Math.round(row1?.getBoundingClientRect().height || 0),
      templates: row1?.querySelectorAll('.aiw-template').length ?? -1,
      templateSelects: row1?.querySelectorAll('.aiw-template select').length ?? -1,
      templateTextEcho: /模板[：:]/.test(row1?.textContent || ''),
      applyInBar: Boolean(document.querySelector('.aiw-applybar .btn.primary')),
      rows: document.querySelectorAll('.ai .list .row').length,
    });
  })()`,

  'translate-empty': `(async () => {
    ${HELPER}
    await clickSidebar('翻译');
    const card = document.querySelector('.aiw-blank-card');
    return JSON.stringify({
      card: Boolean(card),
      title: card?.querySelector('.aiw-blank-title')?.textContent.trim() ?? '',
      steps: card?.querySelectorAll('.aiw-blank-steps li').length ?? 0,
      actions: [...(card?.querySelectorAll('.aiw-blank-actions button') ?? [])].map((b) => b.textContent.trim()),
      cardWidth: Math.round(card?.getBoundingClientRect().width ?? 0),
      rowAction: Boolean(byText(document.querySelector('.aiw-cmd-row'), '复制提示词')),
    });
  })()`,

  'translate-empty-api': `(async () => {
    ${HELPER}
    await clickSidebar('翻译');
    [...document.querySelectorAll('.aiw-lane button')].find((b) => b.textContent.includes('自动 API'))?.click();
    await sleep(400);
    const card = document.querySelector('.aiw-blank-card');
    return JSON.stringify({
      card: Boolean(card),
      title: card?.querySelector('.aiw-blank-title')?.textContent.trim() ?? '',
      steps: card?.querySelectorAll('.aiw-blank-steps li').length ?? 0,
      note: (card?.querySelector('.aiw-blank-note')?.textContent || '').replace(/\s+/g, ' ').trim(),
      lane: [...document.querySelectorAll('.aiw-lane button')].map((b) => b.textContent.trim()),
      rowAction: Boolean(byText(document.querySelector('.aiw-cmd-row'), '生成译文建议')),
      actions: [...(card?.querySelectorAll('.aiw-blank-actions button, .aiw-blank-actions .aiw-link') ?? [])].map((b) => ({ label: b.textContent.trim(), disabled: b.disabled })),
    });
  })()`,

  'reshape-empty': `(async () => {
    ${HELPER}
    await clickSidebar('断句重排');
    return JSON.stringify({
      headChildren: document.querySelector('.aiw-head')?.children.length ?? 0,
      row1H: Math.round(document.querySelector('.aiw-title-row')?.getBoundingClientRect().height || 0),
      steps: document.querySelectorAll('.aiw-step').length,
      guides: document.querySelectorAll('.aiw-guide').length,
      step3: (document.querySelector('.aiw-step:nth-of-type(3) .aiw-guide-title')?.textContent || '').trim(),
      previewRows: document.querySelectorAll('.preview-row').length,
    });
  })()`,

  reshape: `(async () => {
    ${HELPER}
    await clickSidebar('断句重排');
    const box = document.querySelector('.aiw-drop textarea');
    box.value = ${JSON.stringify(RESHAPE_SRT)};
    box.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(300);
    byText(document.querySelector('.reshape'), '解析并预检')?.click();
    // 解析 toast 会停留 3.2s；等它消失再截，图里不夹临时浮层。
    await sleep(4200);
    const row1 = document.querySelector('.aiw-title-row');
    return JSON.stringify({
      headChildren: document.querySelector('.aiw-head')?.children.length ?? 0,
      row1H: Math.round(row1?.getBoundingClientRect().height || 0),
      laneTabs: [...document.querySelectorAll('.aiw-lane button')].map((b) => b.textContent.trim()),
      apiDisabled: [...document.querySelectorAll('.aiw-lane button')].find((b) => b.textContent.includes('自动 API'))?.disabled ?? null,
      draft: Boolean(document.querySelector('.preview-row')),
      applyLabel: [...document.querySelectorAll('.reshape button')].find((b) => /覆盖第|覆盖核对台|确认覆盖/.test(b.textContent))?.textContent.trim() ?? '',
      guide: document.querySelectorAll('.aiw-guide').length,
    });
  })()`,

  'reshape-ops': `(async () => {
    ${HELPER}
    await clickSidebar('断句重排');
    byText(document.querySelector('.reshape'), '只改几处')?.click();
    await sleep(1200);
    return JSON.stringify({
      guide: document.querySelectorAll('.aiw-guide').length,
      guideTitle: document.querySelector('.aiw-guide-title')?.textContent.trim() ?? '',
      opsEmpty: Boolean(document.querySelector('.aiw-guide')),
      headChildren: document.querySelector('.aiw-head')?.children.length ?? 0,
    });
  })()`,
};

function parseArgs(argv) {
  const args = {
    out: DEFAULT_OUT,
    states: [
      'polish',
      'translate',
      'reshape',
      'polish-stale',
      'translate-empty',
      'translate-empty-api',
      'reshape-empty',
      'reshape-ops',
    ],
  };
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    const next = () => {
      i += 1;
      if (i >= argv.length) throw new Error(`${flag} 缺少参数`);
      return argv[i];
    };
    if (flag === '--out') args.out = path.resolve(next());
    else if (flag === '--state') args.states = [next()];
    else if (flag === '--states') args.states = next().split(',').map((v) => v.trim()).filter(Boolean);
    else throw new Error(`未知参数：${flag}`);
  }
  for (const state of args.states) {
    if (!EVAL[state]) throw new Error(`未知状态：${state}`);
  }
  return args;
}

function hasCommand(command) {
  return spawnSync('which', [command], { stdio: 'ignore' }).status === 0;
}

/** 每个状态用一份独立的输出目录：提案文件决定页面拿到的建议。 */
function outputDirFor(state) {
  const dir = path.join(BASE, `out-${state}`);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function ensureMedia() {
  fs.mkdirSync(BASE, { recursive: true });
  if (fs.existsSync(MEDIA)) return;
  execFileSync(
    'ffmpeg',
    [
      '-y',
      '-v',
      'error',
      '-f',
      'lavfi',
      '-i',
      'color=c=0x223344:s=640x360:d=20',
      '-pix_fmt',
      'yuv420p',
      '-c:v',
      'libx264',
      '-preset',
      'ultrafast',
      MEDIA,
    ],
    { stdio: 'pipe' },
  );
}

function seedPath() {
  const seed = JSON.parse(fs.readFileSync(path.join(ROOT, 'tools/shots/seed.json'), 'utf8'));
  const out = path.join(BASE, 'seed.json');
  fs.writeFileSync(out, JSON.stringify({ ...seed, mediaPath: MEDIA }, null, 2));
  return out;
}

/**
 * 造夹具：A 的润色提案（双源）、译文提案、B 版边车；`polish-stale` 额外写一份
 * digest 对不上的旧稿提案（模拟「生成后原文被改」）。
 */
function prepareFixtures(state) {
  const out = outputDirFor(state);
  seedPath();
  const prepare = String.raw`
import hashlib, json, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, ${JSON.stringify(ROOT)})
from core import ai_proposal as proposals
from core.subtitles import SubtitleCue, cues_to_srt

base = Path(${JSON.stringify(BASE)})
out = Path(${JSON.stringify(out)})
media = Path(${JSON.stringify(MEDIA)})
state = ${JSON.stringify(state)}
seed = json.loads((base / 'seed.json').read_text())
cues = seed['cues']
FIXED_AT = datetime(2026, 11, 15, 15, 0).timestamp()
cue_objects = [SubtitleCue(start=float(c['start']), end=float(c['end']), text=c['text']) for c in cues]
srt_path = base / 'media.srt'
srt_path.write_text(cues_to_srt(cue_objects), encoding='utf-8')

def fake_edit(text):
    if 'は' in text:
        return text.replace('は', 'わ', 1)
    if '。' in text:
        return text.replace('。', '．', 1)
    if len(text) >= 2:
        return text[:-1] + '…'
    return text

items = []
for idx, cue in enumerate(cue_objects, start=1):
    after = fake_edit(cue.text) or cue.text
    items.append({'i': idx, 'before': cue.text, 'after': after,
                  'note': '示例改动（非真实建议）' if after != cue.text else ''})

b = [(0.0, 2.9, 'よう、久しぶり。お前は変わったな、本当に。'),
     (4.7, 7.8, '雨の日だけ、君はここに来る。だから今日も来てみたんだ。'),
     (7.9, 9.4, '話したいことがある。'),
     (9.5, 11.0, 'それは……とても大事な話。'),
     (11.1, 12.6, 'でも、うまく言えない。'),
     (12.7, 14.2, '少しだけ、時間をくれないか。'),
     (14.3, 15.8, 'ああ、構わないよ。'),
     (15.9, 17.4, 'じゃあ、一緒に歩こう。'),
     (17.5, 19.0, '……ありがとう。')]
texts_b = [text for _, _, text in b]

if state in ('polish', 'reshape', 'reshape-empty', 'reshape-ops'):
    proposal = proposals.build_proposal(
        kind='polish', src_lang='ja',
        texts=[cue.text for cue in cue_objects], items=items,
        texts_b=texts_b, model='fake-demo', entry='skill',
        source_path=str(srt_path), created_at=FIXED_AT)
    proposals.proposal_path(out, media.stem, 'polish').write_text(
        proposals.dump_proposal(proposal), encoding='utf-8')

if state == 'polish-stale':
    # 绑定的是「旧版原文」：当前稿一字之差，digest 必然不符
    old_texts = [cue.text + '。' for cue in cue_objects]
    stale_items = [{'i': i + 1, 'before': old, 'after': old[:-1] + '．', 'note': ''}
                   for i, old in enumerate(old_texts)]
    proposal = proposals.build_proposal(
        kind='polish', src_lang='ja', texts=old_texts, items=stale_items,
        model='fake-demo', entry='skill', source_path=str(srt_path), created_at=FIXED_AT)
    proposals.proposal_path(out, media.stem, 'polish').write_text(
        proposals.dump_proposal(proposal), encoding='utf-8')

if state == 'translate':
    zh = ${JSON.stringify(ZH)}
    texts = [cue.text for cue in cue_objects]
    t_items = [{'i': i + 1, 'before': text, 'after': zh[i % len(zh)], 'note': ''}
               for i, text in enumerate(texts)]
    proposal = proposals.build_proposal(
        kind='translate', src_lang='ja', texts=texts, items=t_items,
        dst_lang='zh-Hans', model='fake-translate', entry='in-app',
        source_path=str(srt_path), created_at=FIXED_AT)
    proposals.proposal_path(out, media.stem, 'translate', 'zh-Hans').write_text(
        proposals.dump_proposal(proposal), encoding='utf-8')

if state in ('polish', 'polish-stale', 'reshape', 'reshape-empty', 'reshape-ops'):
    stat = media.stat()
    fingerprint = f"{media.resolve()}|{stat.st_size}|{int(stat.st_mtime_ns)}"
    key = hashlib.sha1(fingerprint.encode()).hexdigest()[:16]
    alt = {
        'version': 1, 'engine': 'qwen',
        'cues': [{'start': s, 'end': e, 'text': t} for s, e, t in b],
        'source': {'kind': 'transcription', 'engine': 'qwen', 'name': 'Qwen3-ASR 转写',
                   'path': '', 'job_id': '', 'at': FIXED_AT, 'apply': 'alt_review'},
        'created_at': FIXED_AT, 'params': {'vad_onset_pad_ms': 400},
        'media_path': str(media),
    }
    (out / f'{media.stem}.{key}.autosave_draft.alt.json').write_text(
        json.dumps(alt, ensure_ascii=False, indent=2), encoding='utf-8')
`;
  const file = path.join(BASE, `prepare-${state}.py`);
  fs.writeFileSync(file, prepare);
  execFileSync('python3', [file], { encoding: 'utf8' });
  return out;
}

function run(state) {
  const outDir = prepareFixtures(state);
  const profile = path.join(BASE, `profile-${state}`);
  fs.rmSync(profile, { recursive: true, force: true });
  fs.mkdirSync(profile, { recursive: true });

  const extra = (process.env.KIKUSUB_SHOT_ELECTRON_ARGS || '').split(/\s+/).filter(Boolean);
  const env = {
    ...process.env,
    KIKUSUB_ALLOW_MULTIPLE: '1',
    KIKUSUB_WIN_SIZE: '1360x838',
    KIKUSUB_SHOT_DELAY: '6500',
    KIKUSUB_OUTPUT_DIR: outDir,
    KIKUSUB_DATA_DIR: path.join(BASE, 'data'),
    KIKUSUB_PREFERENCES_PATH: path.join(BASE, 'prefs.json'),
    KIKUSUB_DEV_SEED: seedPath(),
    KIKUSUB_DEV_EVAL: EVAL[state],
  };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.NODE_OPTIONS;

  let stdout = '';
  try {
    stdout = execFileSync(
      'npx',
      ['electron', '.', `--user-data-dir=${profile}`, `--screenshot=${path.join(outDir, 'shot.png')}`, ...extra],
      { cwd: path.join(ROOT, 'desktop'), env, stdio: 'pipe', timeout: 180_000 },
    ).toString();
  } catch (error) {
    stdout = `${error.stdout ?? ''}`;
    console.error(String(error.stderr ?? '').slice(-800));
  }
  const line = stdout.split('\n').filter((row) => row.startsWith('[eval]')).pop();
  if (!line) throw new Error(`${state}：渲染进程没有回传结果`);
  return { data: JSON.parse(line.slice('[eval] '.length)), shot: path.join(outDir, 'shot.png') };
}

const failures = [];
function check(name, condition, detail) {
  if (condition) console.log(`  ✓ ${name}`);
  else {
    failures.push(name);
    console.error(`  ✗ ${name}${detail === undefined ? '' : ` → ${JSON.stringify(detail)}`}`);
  }
}

function assertState(state, data) {
  if (state === 'polish') {
    check('头部只有两行（title-row + cmd-row）', data.hasRow1 && data.hasRow2 && data.headChildren === 2, data);
    check('第 1 行没有被挤成两行', data.row1H > 0 && data.row1H < 50, data.row1H);
    check('通道是二选一分段开关', data.laneTabs.length === 2 && data.laneTabs[0].includes('自动 API') && data.laneTabs[1].includes('外部手动'), data.laneTabs);
    check('不再有并排的 A/B 通道条', data.oldChannelBars === 0, data.oldChannelBars);
    check('「粘贴回复」只出现一次', data.pasteReply === 1, data.pasteReply);
    check('来源徽标不再叫「外部粘贴」', data.bodyHasOldEntry === false, data.bodyHasOldEntry);
  }
  if (state === 'polish-stale') {
    check('源文本已变化时主按钮禁用', data.applyDisabled === true, data);
    check('告警明确要求重新生成', /请重新生成|重新粘贴/.test(data.note), data.note);
    check('「更多应用」也禁用', data.moreApplyDisabled === true, data.moreApplyDisabled);
  }
  if (state === 'translate') {
    check('头部只有两行', data.hasRow1 && data.hasRow2 && data.headChildren === 2, data);
    check('第 1 行没有被挤成两行', data.row1H > 0 && data.row1H < 50, data.row1H);
    check('模板下拉框只有一个', data.templates === 1 && data.templateSelects === 1, data);
    check('没有「模板：X」静态重复文字', data.templateTextEcho === false, data);
    check('底部有应用主按钮', data.applyInBar === true, data);
    check('译文表格已渲染', data.rows > 0, data.rows);
  }
  if (state === 'translate-empty') {
    check('无提案时给中心引导卡', data.card === true, data);
    check('引导卡是 1–2 步', data.steps >= 1 && data.steps <= 2, data.steps);
    check('引导卡有主按钮', data.actions.length >= 1, data.actions);
    check('卡片宽度合理（不是整屏白板）', data.cardWidth > 300 && data.cardWidth <= 640, data.cardWidth);
    check('空态时第 2 行不再重复一套按钮', data.rowAction === false, data.rowAction);
  }
  if (state === 'translate-empty-api') {
    check('自动 API 空态也是中心引导卡', data.card === true && data.steps === 2, data);
    check('未配置 Key 时提示去设置并说明原因', /去设置|配好|Key/.test(data.note), data.note);
    check('通道开关仍提供外部手动出口', data.lane.includes('外部手动'), data.lane);
    check('空态时第 2 行不再重复一套按钮', data.rowAction === false, data.rowAction);
    check('未配置时生成按钮禁用', data.actions.some((a) => a.label.includes('生成') && a.disabled), data.actions);
  }
  if (state === 'reshape-empty') {
    check('空态头部两行、第 1 行不折行', data.headChildren === 2 && data.row1H > 0 && data.row1H < 50, data);
    check('左栏三步都在', data.steps === 3, data.steps);
    check('第 3 步有空态引导（不是一行小字）', data.guides === 1 && /第 3 步/.test(data.step3), data);
    check('右栏默认识稿而不是白板', data.previewRows > 0, data.previewRows);
  }
  if (state === 'reshape') {
    check('头部只有两行（无多段时不额外占行）', data.headChildren === 2, data.headChildren);
    check('第 1 行没有被挤成两行', data.row1H > 0 && data.row1H < 50, data.row1H);
    check('通道开关存在且自动 API 明确置灰', data.laneTabs.length === 2 && data.apiDisabled === true, data);
    check('粘稿后右栏出现对照表', data.draft === true, data);
    check('覆盖按钮按范围命名', /覆盖第|覆盖核对台|确认覆盖/.test(data.applyLabel), data.applyLabel);
  }
  if (state === 'reshape-ops') {
    check('只改几处有空态引导卡（不是一行小字）', data.guide === 1, data);
    check('引导卡标题是第 3 步', /第 3 步/.test(data.guideTitle), data.guideTitle);
    check('头部仍是两行', data.headChildren === 2, data.headChildren);
  }
}

function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(error.message);
    process.exit(2);
  }
  if (!fs.existsSync(path.join(ROOT, 'desktop/node_modules/electron'))) {
    console.error('缺少 desktop/node_modules/electron');
    process.exit(3);
  }
  if (!hasCommand('ffmpeg') || !hasCommand('python3')) {
    console.error('缺少 ffmpeg / python3');
    process.exit(3);
  }

  fs.mkdirSync(args.out, { recursive: true });
  ensureMedia();

  for (const state of args.states) {
    console.log(`\n[${state}]`);
    const { data, shot } = run(state);
    const target = path.join(args.out, `${STAMP}-${state}.png`);
    fs.copyFileSync(shot, target);
    console.log(`  → ${target}`);
    console.log(`  data ${JSON.stringify(data)}`);
    assertState(state, data);
  }

  console.log('');
  if (failures.length) {
    console.error(`${failures.length} 项断言失败`);
    process.exit(1);
  }
  console.log('全部通过');
}

main();
