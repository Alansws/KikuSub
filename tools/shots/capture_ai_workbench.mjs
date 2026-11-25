#!/usr/bin/env node
/**
 * AI 三页视觉基线矩阵（润色 / 断句重排 / 双引擎复核）。
 *
 * 为什么不直接用 capture_matrix.sh：那支脚本的 polish / reshape / dual 是**空态**，
 * 视觉基线里最有信息量的是「有字幕、有 B 版、有提案 / 有对照」的状态。这里用
 * KIKUSUB_DEV_SEED + 临时假提案 + B 版边车，把三页的代表状态拍成
 * `<state>-<theme>-<size>.png`，与 capture_matrix.sh 的命名约定一致。
 *
 * 用法：
 *   node tools/shots/capture_ai_workbench.mjs --out /tmp/ai-current
 *   node tools/shots/capture_ai_workbench.mjs --out /tmp/ai-current --compare docs/images/shots/baseline
 *   node tools/shots/capture_ai_workbench.mjs --out docs/images/shots/baseline
 *
 * 选项：
 *   --out DIR           输出目录，默认 docs/images/shots/current-ai
 *   --theme LIST        light,dark,mincho（默认全跑）
 *   --states LIST       polish-dual,reshape-draft,dual（默认全跑）
 *   --size WxH          默认 1360x838
 *   --compare DIR       只比对，不写基线；打印每张图的 PSNR
 *   --no-sandbox        追加 Electron --no-sandbox（沙箱 / CI 环境）
 *
 * 依赖：desktop/node_modules/electron、ffmpeg、python3（只用 core 的纯 stdlib 模块）。
 * 截图不抢焦点；每张图使用独立临时 profile。
 */

import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const BASE = path.join(os.tmpdir(), 'kikusub-ai-workbench-shots');
const FIXTURE_OUT = path.join(BASE, 'out');
const DEFAULT_OUT = path.join(ROOT, 'docs/images/shots/current-ai');
const ALL_THEMES = ['light', 'dark', 'mincho'];
const ALL_STATES = ['polish-dual', 'reshape-draft', 'dual'];

const RESHAPE_SRT = `1
00:00:00,000 --> 00:00:02,900
よう、久しぶり。お前は変わったな、本当に。

2
00:00:04,700 --> 00:00:07,800
雨の日だけ、君はここに来る。だから今日も来てみたんだ。

3
00:00:07,900 --> 00:00:09,400
話したいことがある。

4
00:00:09,500 --> 00:00:11,000
それは……とても大事な話。

5
00:00:11,100 --> 00:00:12,600
でも、うまく言えない。

6
00:00:12,700 --> 00:00:14,200
少しだけ、時間をくれないか。

7
00:00:14,300 --> 00:00:15,800
ああ、構わないよ。

8
00:00:15,900 --> 00:00:17,400
じゃあ、一緒に歩こう。

9
00:00:17,500 --> 00:00:19,000
……ありがとう。`;

function usage() {
  const text = fs.readFileSync(fileURLToPath(import.meta.url), 'utf8');
  const body = text.match(/\/\*\*([\s\S]*?)\*\//)?.[1] ?? '';
  console.log(body.replace(/^ \* ?/gm, '').trim());
}

function parseList(value, allowed, label) {
  const items = String(value)
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  if (!items.length) throw new Error(`--${label} 不能为空`);
  for (const item of items) {
    if (!allowed.includes(item)) throw new Error(`--${label} 不支持：${item}`);
  }
  return items;
}

function parseArgs(argv) {
  const args = {
    out: DEFAULT_OUT,
    themes: ALL_THEMES,
    states: ALL_STATES,
    size: '1360x838',
    compare: '',
    noSandbox: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    const next = () => {
      i += 1;
      if (i >= argv.length) throw new Error(`${flag} 缺少参数`);
      return argv[i];
    };
    switch (flag) {
      case '--out':
        args.out = path.resolve(next());
        break;
      case '--theme':
      case '--themes':
        args.themes = parseList(next(), ALL_THEMES, 'theme');
        break;
      case '--states':
        args.states = parseList(next(), ALL_STATES, 'states');
        break;
      case '--size':
        args.size = next();
        if (!/^\d{3,4}x\d{3,4}$/.test(args.size)) throw new Error(`--size 格式不对：${args.size}`);
        break;
      case '--compare':
        args.compare = path.resolve(next());
        break;
      case '--no-sandbox':
        args.noSandbox = true;
        break;
      case '-h':
      case '--help':
        usage();
        process.exit(0);
        break;
      default:
        throw new Error(`未知参数：${flag}`);
    }
  }
  return args;
}

function fail(code, message) {
  console.error(message);
  process.exit(code);
}

function hasCommand(command) {
  const result = spawnSync('which', [command], { stdio: 'ignore' });
  return result.status === 0;
}

function ensureFixture() {
  fs.mkdirSync(FIXTURE_OUT, { recursive: true });
  const media = path.join(BASE, 'media.mp4');
  if (!fs.existsSync(media)) {
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
        media,
      ],
      { stdio: 'pipe' },
    );
  }

  const seed = JSON.parse(fs.readFileSync(path.join(ROOT, 'tools/shots/seed.json'), 'utf8'));
  const seedPath = path.join(BASE, 'seed.json');
  fs.writeFileSync(seedPath, JSON.stringify({ ...seed, mediaPath: media }, null, 2));

  const prepare = String.raw`
import hashlib, json, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, ${JSON.stringify(ROOT)})
from core import ai_proposal as proposals
from core.subtitles import SubtitleCue, cues_to_srt

base = Path(${JSON.stringify(BASE)})
out = Path(${JSON.stringify(FIXTURE_OUT)})
media = Path(${JSON.stringify(media)})
cues = json.loads(Path(${JSON.stringify(seedPath)}).read_text())['cues']

# 固定 fixture 时间：双引擎页会显示「生成于 …」，不固定会让基线每次差一截。
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
    return ''

items = []
for idx, cue in enumerate(cue_objects, start=1):
    after = fake_edit(cue.text) or cue.text
    items.append({
        'i': idx,
        'before': cue.text,
        'after': after,
        'note': '示例改动（非真实建议）' if after != cue.text else '',
    })

# B：合并 1+2、3+4、5+6，条数与断句都与 A 不同。
b = [
    (0.0, 2.9, 'よう、久しぶり。お前は変わったな、本当に。'),
    (4.7, 7.8, '雨の日だけ、君はここに来る。だから今日も来てみたんだ。'),
    (7.9, 9.4, '話したいことがある。'),
    (9.5, 11.0, 'それは……とても大事な話。'),
    (11.1, 12.6, 'でも、うまく言えない。'),
    (12.7, 14.2, '少しだけ、時間をくれないか。'),
    (14.3, 15.8, 'ああ、構わないよ。'),
    (15.9, 17.4, 'じゃあ、一緒に歩こう。'),
    (17.5, 19.0, '……ありがとう。'),
]

proposal = proposals.build_proposal(
    kind='polish',
    src_lang='ja',
    texts=[cue.text for cue in cue_objects],
    items=items,
    texts_b=[text for _, _, text in b],
    model='fake-demo',
    entry='skill',
    source_path=str(srt_path),
    created_at=FIXED_AT,
)
proposal_path = proposals.proposal_path(out, media.stem, 'polish')
proposal_path.write_text(proposals.dump_proposal(proposal), encoding='utf-8')

stat = media.stat()
fingerprint = f"{media.resolve()}|{stat.st_size}|{int(stat.st_mtime_ns)}"
key = hashlib.sha1(fingerprint.encode()).hexdigest()[:16]
alt = {
    'version': 1,
    'engine': 'qwen',
    'cues': [{'start': start, 'end': end, 'text': text} for start, end, text in b],
    'source': {
        'kind': 'transcription',
        'engine': 'qwen',
        'name': 'Qwen3-ASR 转写',
        'path': '',
        'job_id': '',
        'at': FIXED_AT,
        'apply': 'alt_review',
    },
    'created_at': FIXED_AT,
    'params': {'vad_onset_pad_ms': 400},
    'media_path': str(media),
}
alt_path = out / f'{media.stem}.{key}.autosave_draft.alt.json'
alt_path.write_text(json.dumps(alt, ensure_ascii=False, indent=2), encoding='utf-8')
print(proposal_path)
print(alt_path)
`;
  const preparePath = path.join(BASE, 'prepare.py');
  fs.writeFileSync(preparePath, prepare);
  console.log(execFileSync('python3', [preparePath], { encoding: 'utf8' }).trim());

  return { media, seedPath };
}

const sleep = (ms) => `await new Promise((r) => setTimeout(r, ${ms}));`;

function evalFor(state, theme) {
  const common = `
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    // mincho 是字幕字体偏好，不是第三套配色（2026-11-25 起）
    if (${JSON.stringify(theme)} === 'mincho') {
      document.documentElement.dataset.cueFont = 'mincho';
      localStorage.setItem('kikusub.cueFont', 'mincho');
      document.documentElement.dataset.theme = 'light';
      localStorage.setItem('kikusub.appearance', 'light');
    } else {
      document.documentElement.dataset.theme = ${JSON.stringify(theme)};
      localStorage.setItem('kikusub.appearance', ${JSON.stringify(theme)});
    }
    ${sleep(2400)}
  `;

  if (state === 'dual') {
    return `(async () => {${common}
      document.querySelectorAll('.sb-item')[3]?.click();
      ${sleep(1600)}
      ${sleep(500)}
      return 'ok';
    })()`;
  }

  if (state === 'polish-dual') {
    return `(async () => {${common}
      document.querySelectorAll('.sb-item')[4]?.click();
      ${sleep(1400)}
      [...document.querySelectorAll('button')]
        .find((b) => b.textContent.trim() === '双源')?.click();
      ${sleep(1400)}
      document.querySelector('.aiw-check input')?.click();
      ${sleep(300)}
      return 'ok';
    })()`;
  }

  return `(async () => {${common}
    document.querySelectorAll('.sb-item')[5]?.click();
    ${sleep(800)}
    const box = document.querySelector('.aiw-drop textarea');
    if (box) {
      box.value = ${JSON.stringify(RESHAPE_SRT)};
      box.dispatchEvent(new Event('input', { bubbles: true }));
      await sleep(250);
      [...document.querySelectorAll('button')]
        .find((b) => b.textContent.includes('解析并预检'))?.click();
      // 解析 toast 会停留 3.2s；等它消失再截，基线里不夹临时浮层。
      ${sleep(3800)}
    }
    ${sleep(500)}
    return 'ok';
  })()`;
}

function compare(name, outPath, baselineDir) {
  const baseline = path.join(baselineDir, name);
  if (!fs.existsSync(baseline)) {
    console.log(`  ? ${name}: 基线缺少 ${path.relative(process.cwd(), baseline)}`);
    return;
  }
  const result = spawnSync(
    'ffmpeg',
    ['-hide_banner', '-v', 'info', '-i', outPath, '-i', baseline, '-lavfi', '[0:v][1:v]psnr', '-f', 'null', '-'],
    { encoding: 'utf8' },
  );
  const text = `${result.stderr ?? ''}\n${result.stdout ?? ''}`;
  const average = /average:([^\s]+)/.exec(text)?.[1] ?? 'unknown';
  console.log(`  ~ ${name}: PSNR average:${average}`);
}

function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(error.message);
    usage();
    process.exit(2);
  }

  if (!fs.existsSync(path.join(ROOT, 'desktop/node_modules/electron'))) {
    fail(3, '缺少 desktop/node_modules/electron');
  }
  if (!hasCommand('ffmpeg')) fail(3, '缺少 ffmpeg');
  if (!hasCommand('python3')) fail(3, '缺少 python3');

  fs.mkdirSync(args.out, { recursive: true });
  const { seedPath } = ensureFixture();

  const electronArgs = [];
  if (process.env.KIKUSUB_SHOT_ELECTRON_ARGS) {
    electronArgs.push(...process.env.KIKUSUB_SHOT_ELECTRON_ARGS.split(/\s+/).filter(Boolean));
  }
  if (args.noSandbox) electronArgs.push('--no-sandbox');

  let failures = 0;
  for (const theme of args.themes) {
    for (const state of args.states) {
      const name = `${state}-${theme}-${args.size}.png`;
      const outPath = path.join(args.out, name);
      const profile = path.join(BASE, `profile-${state}-${theme}`);
      fs.rmSync(profile, { recursive: true, force: true });
      fs.mkdirSync(profile, { recursive: true });

      const env = {
        ...process.env,
        KIKUSUB_ALLOW_MULTIPLE: '1',
        KIKUSUB_WIN_SIZE: args.size,
        KIKUSUB_SHOT_DELAY: '7000',
        KIKUSUB_OUTPUT_DIR: FIXTURE_OUT,
        KIKUSUB_DATA_DIR: path.join(BASE, 'data'),
        KIKUSUB_PREFERENCES_PATH: path.join(BASE, 'prefs.json'),
        KIKUSUB_DEV_SEED: seedPath,
        KIKUSUB_DEV_EVAL: evalFor(state, theme),
      };
      delete env.ELECTRON_RUN_AS_NODE;
      delete env.NODE_OPTIONS;

      try {
        execFileSync(
          'npx',
          ['electron', '.', `--user-data-dir=${profile}`, ...electronArgs, `--screenshot=${outPath}`],
          {
            cwd: path.join(ROOT, 'desktop'),
            env,
            stdio: 'pipe',
            timeout: 180_000,
          },
        );
        console.log(`  ✓ ${name}`);
        if (args.compare) compare(name, outPath, args.compare);
      } catch (error) {
        failures += 1;
        const stderr = (error.stderr ?? '').toString().trim().slice(-600);
        console.error(`  ✗ ${name}${stderr ? `\n${stderr}` : ''}`);
      }
    }
  }

  console.log('');
  console.log(`输出目录：${path.relative(process.cwd(), args.out)}`);
  if (failures) {
    console.error(`${failures} 张截图失败`);
    process.exit(1);
  }
}

main();
