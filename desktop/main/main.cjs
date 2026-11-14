/**
 * KikuSub 主进程。
 *
 * 职责（对应改造规划 §2）：
 *  - 窗口：hiddenInset 标题栏 / vibrancy / 单实例 / 全屏
 *  - 菜单：⌘Z 必须真的接到渲染进程的撤回栈（不能用 role:'undo'，那是 DOM 撤销）
 *  - 文件关联：.mkv/.mp4/.srt/.vtt 双击打开、Dock 拖放、最近打开
 *  - sidecar 生命周期：启动即拉起、before-quit 必杀、崩溃自动重启（上限 3 次）
 *
 * 进程间约定：sidecar 以 `--port 0` 启动，stdout 首行是
 * `{"event":"ready","port":…,"token":…}`；主进程读到后注入渲染进程。
 */

// Electron 的 CJS 包在 ESM 下没有具名导出，只能默认导入再解构
const {
  app,
  BrowserWindow,
  clipboard,
  dialog,
  ipcMain,
  Menu,
  nativeTheme,
  shell,
} = require('electron');
const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const aikey = require('./aikey.cjs');
const launchguard = require('./launchguard.cjs');
const skill = require('./skill.cjs');
const {
  deleteCleanupCandidates,
  listCleanupCandidates,
  pruneLogs,
} = require('./files.cjs');

const DESKTOP_ROOT = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(DESKTOP_ROOT, '..');

const IS_DEV = !app.isPackaged;
// 截图路径优先取环境变量：打包后的 .app 直接带 `--screenshot=` 会被 Chromium
// 的命令行解析器拒掉（bad option），环境变量没有这个问题。
const SHOT_ARG = process.argv.find((a) => a.startsWith('--screenshot'));
const SHOT_PATH =
  process.env.KIKUSUB_SHOT || (SHOT_ARG ? SHOT_ARG.split('=')[1] || '/tmp/kikusub-app.png' : null);
// 截图前等多久：要盖住「sidecar 启动 + 首帧数据」的时间，默认 5.5s
const SHOT_DELAY_MS = Number(process.env.KIKUSUB_SHOT_DELAY || 5500);
// 开发截图用：KIKUSUB_WIN_SIZE=1440x900 覆盖默认窗口尺寸，方便按设计稿视口核对。
const WIN_SIZE = /^(\d{3,4})x(\d{3,4})$/.exec(process.env.KIKUSUB_WIN_SIZE || '');

// 开发模式下固定 userData：Electron 的单实例锁跟着 userData 走，如果每次
// 启动都带不同的 --user-data-dir，就会真的跑出第二个 Electron，Dock 里
// 出现两个图标。截图模式（SHOT_PATH）仍允许独立 profile 并行取证。
// 确实需要并行调试时显式设 KIKUSUB_ALLOW_MULTIPLE=1。
if (IS_DEV && !SHOT_PATH && process.env.KIKUSUB_ALLOW_MULTIPLE !== '1') {
  try {
    const devUserData = path.join(REPO_ROOT, '.dev-userdata');
    fs.mkdirSync(devUserData, { recursive: true });
    app.setPath('userData', devUserData);
  } catch {
    /* 路径不可写时退回默认 userData，不影响启动 */
  }
}
if (IS_DEV) {
  try {
    app.setName('KikuSub');
  } catch {
    /* 某些环境不允许改 name，忽略 */
  }
}

/** @type {BrowserWindow | null} */
let win = null;
/** @type {{port:number, token:string, pid:number} | null} */
let sidecar = null;
let sidecarRestarts = 0;
let quitting = false;
/** 改模型目录等主动重启：旧进程退出后要立刻拉起新进程。 */
let restartPending = false;
/** 首次启动向导完成后才拉起 sidecar（模型目录要作为环境变量传进去）。 */
let firstRunPending = false;
/** 本次是否已走到建窗（安全模式直接退出时为 false，不能把失败计数清零）。 */
let startedNormally = false;
/** 双击文件启动时，open-file 可能早于窗口/内核就绪；先存着，页面加载后再送。 */
let pendingFile = null;
/** 退出清理：用户确认前不能真正退出。 */
let allowQuit = false;
let quitFlow = null;
let quitConfirming = false;

// ---------------------------------------------------------------------------
// sidecar
// ---------------------------------------------------------------------------

/** 用户可写目录：~/Library/Application Support/KikuSub（KIKUSUB_DATA_DIR 可覆盖）。 */
function dataDir() {
  if (process.env.KIKUSUB_DATA_DIR) return process.env.KIKUSUB_DATA_DIR;
  return path.join(app.getPath('appData'), 'KikuSub');
}

/** 开发模式沿用仓库目录；打包后是 Application Support。 */
function baseDir() {
  return IS_DEV ? REPO_ROOT : dataDir();
}

function logsDir() {
  return path.join(baseDir(), 'outputs', 'logs');
}

/**
 * 应用级启动偏好（模型目录、主题、是否完成首次设置）。
 *
 * 为什么放在主进程：模型目录必须在 sidecar 启动前就定下来，它通过
 * `KIKUSUB_MODELS_DIR` 传给 Python；渲染进程/服务层都来不及参与。
 */
function preferencesPath() {
  const override = (process.env.KIKUSUB_PREFERENCES_PATH || '').trim();
  return override || path.join(dataDir(), 'preferences.json');
}

function expandPath(raw) {
  const text = String(raw || '').trim();
  if (!text) return '';
  if (text === '~') return app.getPath('home');
  if (text.startsWith('~/')) return path.join(app.getPath('home'), text.slice(2));
  return path.resolve(text);
}

function loadPreferences() {
  try {
    const payload = JSON.parse(fs.readFileSync(preferencesPath(), 'utf8'));
    return payload && typeof payload === 'object' ? payload : {};
  } catch {
    return {};
  }
}

// ---- Agent 技能（一键配置）-----------------------------------------------
//
// 把随包的 skill 目录装到用户的技能根目录，供外部 agent（如 DeepSeek Harness）读取。
// 目标根默认 `~/.agents/skills/`——DSH 会扫的用户级根之一；KIKUSUB_SKILL_ROOT 可覆盖。
// 注意 `~/.claude/skills/` 是 Claude Code 的根，DSH **不扫**，装那里在 `/` 菜单里看不到。
// 目标目录由主进程决定，**不接受渲染层传入**。
function skillSourceDir() {
  return path.join(app.getAppPath(), 'resources', 'skill', 'kikusub-subtitle');
}

function skillTargetDir() {
  const override = (process.env.KIKUSUB_SKILL_ROOT || '').trim();
  return override || skill.defaultTargetDir({ home: app.getPath('home') });
}

// ---- AI 密钥（本机加密）---------------------------------------------------
//
// 刻意**不依赖系统钥匙串**：keychain 条目的 ACL 认的是代码签名要求，本项目以 DMG
// 分发、ad-hoc 签名，每次发版 cdhash 都变，用户升级后就读不回旧条目——每个版本
// 都要重填一次 Key，且没有 Developer ID 就无从修复。改成 0600 主密钥文件后，
// 重装/升级/换 Electron 版本都不影响。实现见 desktop/main/aikey.cjs。
const AI_KEY_FIELD = 'aiKey';

function aiKeyFile() {
  return path.join(dataDir(), '.ai-key');
}

function writePreferences(payload) {
  const target = preferencesPath();
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const tmp = `${target}.tmp-${process.pid}`;
  fs.writeFileSync(tmp, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  fs.renameSync(tmp, target);
}

/** 读密钥；返回 `backend` 与 `broken`，调用方据此区分「没配」与「配了但读不出来」。 */
function getAiKeyState() {
  const blob = loadPreferences()[AI_KEY_FIELD];
  if (typeof blob !== 'string' || !blob) {
    return { key: '', backend: 'none', broken: false, legacy: false };
  }

  if (aikey.isLocalBlob(blob)) {
    const key = aikey.decrypt(blob, aikey.readKeyFile(aiKeyFile()));
    return { key: key || '', backend: key ? 'local' : 'none', broken: !key, legacy: false };
  }

  // 历史遗留：更早的版本用 safeStorage 存的（base64 里有 `v10` 头）。本方案读不了，
  // 标记 broken 让用户重填一次，而不是静默当作"没配过"。
  return { key: '', backend: 'none', broken: true, legacy: true };
}

function setAiKey(raw) {
  const text = String(raw || '').trim();
  if (!text) return clearAiKey();
  try {
    const blob = aikey.encrypt(text, aikey.ensureKeyFile(aiKeyFile()));
    savePreferences({ [AI_KEY_FIELD]: blob });
    return { ok: true, backend: 'local', persistent: true };
  } catch (err) {
    mainLog(`[ai-key] 加密保存失败：${err && err.message ? err.message : err}`);
    return { ok: false, reason: 'write-failed' };
  }
}

function getAiKey() {
  return getAiKeyState().key;
}

function clearAiKey() {
  const prefs = loadPreferences();
  if (AI_KEY_FIELD in prefs) {
    delete prefs[AI_KEY_FIELD];
    try {
      writePreferences(prefs);
    } catch (err) {
      mainLog(`[ai-key] 清除失败：${err && err.message ? err.message : err}`);
      return { ok: false };
    }
  }
  return { ok: true };
}

function savePreferences(patch) {
  const target = preferencesPath();
  const merged = { ...loadPreferences(), ...patch };
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const tmp = `${target}.tmp-${process.pid}`;
  fs.writeFileSync(tmp, `${JSON.stringify(merged, null, 2)}\n`, 'utf8');
  fs.renameSync(tmp, target);
  return merged;
}

// ---- 启动失败计数与安全模式 ----------------------------------------------
//
// 桌面端没有 autoUpdater：发出去的版本如果一开就崩，用户既收不到"修复版已发布"，
// 也没法判断该重装——只能删 App。这里兜一层：连续打不开就跳过界面与内核，
// 只给原生对话框（下载页 / 日志目录 / 仍然尝试一次）。判定逻辑是纯函数，
// 见 desktop/main/launchguard.cjs 与 desktop/test/launchguard.test.cjs。

/** 本次启动先记一笔，返回**之前**连续失败了几次。任何异常都不该挡启动。 */
function noteLaunchAttempt() {
  try {
    const prefs = loadPreferences();
    const failures = launchguard.readFailureCount(prefs);
    savePreferences(launchguard.attemptPatch(prefs));
    if (failures) mainLog(`[launch] previous consecutive failures=${failures}`);
    return failures;
  } catch (err) {
    mainLog(`[launch] 计数失败（忽略）：${err && err.message ? err.message : err}`);
    return 0;
  }
}

function clearLaunchFailures() {
  try {
    if (!launchguard.readFailureCount(loadPreferences())) return;
    savePreferences(launchguard.stablePatch());
    mainLog('[launch] 启动稳定，失败计数已清零');
  } catch (err) {
    mainLog(`[launch] 清零失败（忽略）：${err && err.message ? err.message : err}`);
  }
}

/** 安全模式：不建窗口、不启 sidecar。返回 true 表示用户选择"仍然正常启动一次"。 */
function resolveSafeMode(failures) {
  mainLog(`[safe-mode] 连续 ${failures} 次启动失败，进入安全模式`);
  // 自检开关：无头验证时不让原生对话框把进程挂住（等价于用户点了「退出」）
  if (process.env.KIKUSUB_SAFE_MODE_AUTO === 'quit') {
    mainLog('[safe-mode] auto:quit');
    return false;
  }
  let choice = 3;
  try {
    choice = dialog.showMessageBoxSync({
      type: 'warning',
      title: 'KikuSub 启动异常',
      message: `KikuSub 最近连续 ${failures} 次没能正常打开。`,
      detail:
        '为免再次崩溃，本次已跳过界面与转写内核。\n' +
        '建议先安装修复版；如果只是偶发问题，也可以尝试正常启动一次。\n\n' +
        `下载页：${launchguard.DOWNLOAD_URL}\n日志目录：${logsDir()}`,
      buttons: ['尝试正常启动', '打开下载页', '打开日志目录', '退出'],
      defaultId: 0,
      cancelId: 3,
      noLink: true,
    });
  } catch (err) {
    mainLog(`[safe-mode] 对话框失败：${err && err.message ? err.message : err}`);
    return false;
  }
  if (choice === 0) {
    clearLaunchFailures();
    return true;
  }
  if (choice === 1) {
    try {
      shell.openExternal(launchguard.DOWNLOAD_URL);
    } catch (err) {
      mainLog(`[safe-mode] 打开下载页失败：${err && err.message ? err.message : err}`);
    }
    return false;
  }
  if (choice === 2) {
    try {
      shell.openPath(logsDir());
    } catch (err) {
      mainLog(`[safe-mode] 打开日志目录失败：${err && err.message ? err.message : err}`);
    }
    return false;
  }
  return false;
}

/**
 * 主进程日志。
 *
 * sidecar 自己的日志在 `kikusub.log`；但「窗口起没起来、ffmpeg 找没找到、sidecar
 * 为什么退出」这些只在主进程里，用户看不到终端。单独写一份 `main.log`，
 * 让设置页的「打开日志目录」能拿到完整链路。
 */
function mainLog(message) {
  try {
    const dir = logsDir();
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, 'main.log');
    try {
      if (fs.statSync(file).size > 5 * 1024 * 1024) {
        // Windows 上 rename 到已存在的 .1 会失败；先删旧备份
        try {
          fs.unlinkSync(`${file}.1`);
        } catch {
          /* 还没有旧备份 */
        }
        fs.renameSync(file, `${file}.1`);
      }
    } catch {
      /* 文件还不存在 */
    }
    fs.appendFileSync(file, `${new Date().toISOString()} ${message}\n`, 'utf8');
  } catch {
    /* 日志失败不能影响主流程 */
  }
}

/**
 * 清空主进程自己的 `main.log` 与它的轮转备份。
 *
 * sidecar 的「清空全部日志」只能处理它自己持有的 handler；主进程的日志由这里
 * 负责。主进程每次写日志都是 appendFileSync（没有长期持有的 fd），所以直接截断
 * 活动文件是安全的；备份文件直接删除。
 */
function clearMainLogs() {
  let removed = 0;
  let freed = 0;
  try {
    const dir = logsDir();
    let entries = [];
    try {
      entries = fs.readdirSync(dir);
    } catch {
      return { removed, freed };
    }
    for (const name of entries) {
      if (name !== 'main.log' && !name.startsWith('main.log.')) continue;
      const full = path.join(dir, name);
      try {
        const stat = fs.statSync(full);
        if (name === 'main.log') {
          fs.writeFileSync(full, '');
        } else {
          fs.unlinkSync(full);
          removed += 1;
        }
        freed += stat.size;
      } catch {
        /* 单个文件失败不影响其他文件 */
      }
    }
  } catch {
    /* 日志清理失败不能拖垮应用 */
  }
  return { removed, freed };
}

/**
 * 原生外观跟随应用主题。
 *
 * 侧栏用 `vibrancy: 'sidebar'`，它的颜色由 macOS 的明暗外观决定，不受
 * `<html data-theme>` 影响。如果只切 CSS，深色主题下最左侧（红绿灯那一列）
 * 会透出系统浅色的毛玻璃，看起来像没切过去。设置 nativeTheme 后原生材质一起变。
 */
function applyTheme(theme) {
  nativeTheme.themeSource = theme === 'dark' ? 'dark' : 'light';
}

function ensureDataDirs() {
  const base = dataDir();
  for (const sub of ['outputs', 'outputs/logs', 'outputs/web_proxies']) {
    fs.mkdirSync(path.join(base, sub), { recursive: true });
  }
  // 首次运行把仓库里的预设抄一份过去（之后就以 App Support 为准）
  const target = path.join(base, 'presets.json');
  if (!fs.existsSync(target)) {
    const source = IS_DEV
      ? path.join(REPO_ROOT, 'presets.json')
      : path.join(process.resourcesPath, 'python', 'presets.json');
    try {
      if (fs.existsSync(source)) fs.copyFileSync(source, target);
    } catch {
      /* 没有预设也能跑 */
    }
  }
  return base;
}

/** 默认模型目录：打包后必须落在可写的 Application Support，不能进只读的 .app。 */
function defaultModelsDir() {
  return path.join(dataDir(), 'models');
}

/**
 * 模型目录。优先级：
 *   1. KIKUSUB_MODELS_DIR 环境变量（高级用户/调试）
 *   2. 首次启动时用户选的目录（preferences.json）
 *   3. ~/Library/Application Support/KikuSub/models
 *   4. 开发期的仓库 models/（本机已下载的权重直接复用）
 *
 * 打包后 `.app` 内部是只读的，模型绝不能放进去——规划 §7 的结论。
 */
function modelsDir() {
  const fromEnv = (process.env.KIKUSUB_MODELS_DIR || '').trim();
  if (fromEnv) return expandPath(fromEnv);

  const saved = loadPreferences().modelsDir;
  if (saved) return expandPath(saved);

  const inAppSupport = defaultModelsDir();
  if (fs.existsSync(inAppSupport)) return inAppSupport;
  const inRepo = path.join(REPO_ROOT, 'models');
  if (IS_DEV && fs.existsSync(inRepo)) return inRepo;
  return IS_DEV ? inRepo : inAppSupport;
}

/** 目录里至少有任一引擎的**必需文件**，才算“老用户已经装过”，不再弹首次向导。 */
function modelsPresent(dir) {
  const whisper = path.join(dir, 'anime-whisper', 'model.safetensors');
  try {
    if (fs.existsSync(whisper)) return true;
  } catch {
    /* 权限问题按未安装处理 */
  }
  const qwenDir = path.join(dir, 'qwen3-asr-ja-anime');
  try {
    if (!fs.existsSync(path.join(qwenDir, 'config.json'))) return false;
    return fs.readdirSync(qwenDir).some((name) => name.endsWith('.safetensors'));
  } catch {
    return false;
  }
}

function shouldFirstRun() {
  if (process.env.KIKUSUB_FORCE_FIRST_RUN === '1') return true;
  if ((process.env.KIKUSUB_MODELS_DIR || '').trim()) return false;
  const prefs = loadPreferences();
  if (prefs.setupCompleted || prefs.modelsDir) return false;
  // 从旧版本升级：模型已经在默认目录里，不需要再问一遍
  return !modelsPresent(modelsDir());
}

/** 校验并创建模型目录；失败抛中文错误，首次向导/设置页直接展示。 */
function ensureWritableDir(raw) {
  const target = expandPath(raw);
  if (!target) throw new Error('请先选择模型目录');
  const resources = path.resolve(process.resourcesPath || '');
  const resolved = path.resolve(target);
  if (resources && (resolved === resources || resolved.startsWith(resources + path.sep))) {
    throw new Error('不能把模型目录放在应用包内部（只读），请选择其他位置');
  }
  try {
    fs.mkdirSync(resolved, { recursive: true });
    fs.accessSync(resolved, fs.constants.W_OK);
  } catch (err) {
    throw new Error(`目录不可写：${resolved}（${err && err.message ? err.message : err}）`);
  }
  return resolved;
}

/**
 * 补齐 PATH。
 *
 * **这是打包后最容易踩的坑**：从访达启动的 app 只拿到
 * `/usr/bin:/bin:/usr/sbin:/sbin`，而 Homebrew 装的 ffmpeg 在 /opt/homebrew/bin。
 * 结果就是「导入任何视频都失败」，报的还是 Internal Server Error。
 *
 * KIKUSUB_FFMPEG_DIR 可以显式指定（用户把 ffmpeg 装在别处时）。
 */
const PATH_CANDIDATES = [
  '/opt/homebrew/bin',
  '/opt/homebrew/sbin',
  '/usr/local/bin',
  '/usr/local/sbin',
];

function augmentedPath() {
  const parts = (process.env.PATH || '').split(':').filter(Boolean);
  const extra = process.env.KIKUSUB_FFMPEG_DIR
    ? [process.env.KIKUSUB_FFMPEG_DIR, ...PATH_CANDIDATES]
    : PATH_CANDIDATES;
  for (const dir of extra) {
    if (!parts.includes(dir)) parts.push(dir);
  }
  return parts.join(':');
}

/** 在 PATH 里找可执行文件，找不到返回 null（用于启动时把话说清楚）。 */
function findTool(name) {
  for (const dir of augmentedPath().split(':')) {
    const candidate = path.join(dir, name);
    try {
      if (fs.existsSync(candidate)) return candidate;
    } catch {
      /* 忽略无权限的目录 */
    }
  }
  return null;
}

function pythonPath() {
  if (!IS_DEV) {
    // 打包后：KikuSub.app/Contents/Resources/python/sidecar
    return path.join(process.resourcesPath, 'python', 'sidecar');
  }
  const venv = path.join(REPO_ROOT, '..', '.venv', 'bin', 'python');
  return fs.existsSync(venv) ? venv : 'python3';
}

function startSidecar() {
  if (quitting || firstRunPending) return;

  const exe = pythonPath();
  const args = IS_DEV ? ['-m', 'server', '--port', '0'] : ['--port', '0'];
  const cwd = IS_DEV ? REPO_ROOT : path.join(process.resourcesPath, 'python');

  // 开发模式沿用仓库目录（与 sidecar、CLI 共用同一份 outputs/presets，
  // 三个入口看到的是同一套数据）；打包后才切到 Application Support。
  const base = IS_DEV ? REPO_ROOT : ensureDataDirs();
  let models = modelsDir();
  try {
    models = ensureWritableDir(models);
  } catch (err) {
    console.error('[sidecar] 模型目录不可用', err);
    mainLog(`[sidecar] models dir unusable ${models} | ${err && err.message ? err.message : err}`);
    dialog.showErrorBox(
      '模型目录不可用',
      `${models}\n\n请到「设置 → 引擎与模型」里改一个可写目录。\n${err && err.message ? err.message : err}`,
    );
  }
  const modelReady = modelsPresent(models);

  const env = { ...process.env, PYTHONUNBUFFERED: '1', PATH: augmentedPath() };
  const ffmpeg = findTool('ffmpeg');
  const ffprobe = findTool('ffprobe');
  if (!ffmpeg || !ffprobe) {
    console.warn('[sidecar] ⚠️ 找不到 ffmpeg/ffprobe，导入会失败。');
    console.warn('          装一个：brew install ffmpeg；或用 KIKUSUB_FFMPEG_DIR 指定目录。');
  } else {
    console.log('[sidecar] ffmpeg', ffmpeg);
  }
  // 模型目录在两种模式下都显式传：开发期默认还是仓库 models/，但设置页改成
  // 自定义目录后必须让 sidecar 立刻看到同一个路径。
  env.KIKUSUB_MODELS_DIR = models;
  if (!IS_DEV) {
    Object.assign(env, {
      KIKUSUB_OUTPUT_DIR: path.join(base, 'outputs'),
      KIKUSUB_PRESETS_PATH: path.join(base, 'presets.json'),
    });
  }

  console.log('[sidecar] 启动', exe, args.join(' '));
  console.log('[sidecar] 数据目录', base);
  console.log('[sidecar] 模型目录', models, modelReady ? '(已就绪)' : '(⚠️ 未找到模型，首次转写会下载)');
  mainLog(
    `[sidecar] start exe=${exe} args=${args.join(' ')} cwd=${cwd} data=${base} models=${models} ` +
      `modelReady=${modelReady} ffmpeg=${ffmpeg || '(none)'}`,
  );
  const child = spawn(exe, args, {
    cwd,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
    // 关键：让 sidecar 成为新进程组的组长。退出时用负 pid 一次带走它和它启动的
    // ffmpeg；否则只杀 Python 会把正在编码的 ffmpeg 留给 launchd 继续跑。
    // Windows 不支持负 pid，保持默认行为（stopSidecar 里用 taskkill /T）。
    detached: process.platform !== 'win32',
  });

  let handshakeBuf = '';
  let resolved = false;

  child.stdout.setEncoding('utf8');
  child.stdout.on('data', (chunk) => {
    if (resolved) {
      process.stdout.write(`[sidecar] ${chunk}`);
      return;
    }
    handshakeBuf += chunk;
    const nl = handshakeBuf.indexOf('\n');
    if (nl === -1) return;
    const line = handshakeBuf.slice(0, nl).trim();
    handshakeBuf = handshakeBuf.slice(nl + 1);
    try {
      const payload = JSON.parse(line);
      if (payload.event === 'ready') {
        resolved = true;
        sidecar = payload;
        sidecarRestarts = 0;
        console.log(`[sidecar] ready port=${payload.port} pid=${payload.pid}`);
        mainLog(`[sidecar] ready port=${payload.port} pid=${payload.pid}`);
        sendToRenderer('sidecar:ready', payload);
        resolvePending?.();
      }
    } catch {
      // 首行不是握手（比如某条日志），忽略并等下一行
      process.stdout.write(`[sidecar] ${line}\n`);
    }
  });

  child.stderr.setEncoding('utf8');
  child.stderr.on('data', (chunk) => process.stderr.write(`[sidecar:err] ${chunk}`));

  child.on('exit', (code, signal) => {
    console.warn(`[sidecar] 退出 code=${code} signal=${signal}`);
    mainLog(`[sidecar] exit code=${code} signal=${signal}`);
    sidecar = null;
    if (childRef === child) childRef = null;
    sendToRenderer('sidecar:down', { code, signal });
    if (quitting) return;
    if (restartPending) {
      // 主动重启（例如改了模型目录）：不走崩溃计数，也不弹错误框
      restartPending = false;
      sidecarRestarts = 0;
      setTimeout(startSidecar, 150);
      return;
    }
    if (sidecarRestarts >= 3) {
      dialog.showErrorBox('内核启动失败', '转写内核连续 3 次异常退出，请查看日志后重启应用。');
      return;
    }
    sidecarRestarts += 1;
    setTimeout(startSidecar, 600 * sidecarRestarts);
  });

  child.on('error', (err) => {
    console.error('[sidecar] 无法启动', err);
    mainLog(`[sidecar] spawn error ${err && err.stack ? err.stack : err}`);
    sidecar = null;
    sendToRenderer('sidecar:down', { code: null, signal: null });
    dialog.showErrorBox(
      '找不到 Python 内核',
      `无法执行：${exe}\n\n开发模式下请确认仓库根目录存在 .venv/。\n${err.message}`,
    );
  });

  childRef = child;
}

/** @type {import('node:child_process').ChildProcess | null} */
let childRef = null;
let resolvePending = null;

/** sidecar 以 detached 启动，是进程组组长；负 pid 能一次覆盖它和 ffmpeg 等子进程。 */
function killProcessGroup(child, signal) {
  if (!child || !child.pid || process.platform === 'win32') return false;
  try {
    process.kill(-child.pid, signal);
    return true;
  } catch {
    return false;
  }
}

function processGroupAlive(child) {
  if (!child || !child.pid || process.platform === 'win32') return false;
  try {
    process.kill(-child.pid, 0);
    return true;
  } catch {
    return false;
  }
}

/** 杀整棵 sidecar 进程树；组不存在时才退回只杀直接子进程。 */
function killSidecarTree(child, signal) {
  if (!child || !child.pid) return;
  if (process.platform === 'win32') {
    try {
      spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F']);
    } catch {
      /* ignore */
    }
    return;
  }
  if (killProcessGroup(child, signal)) {
    mainLog(`[sidecar] group ${signal} -> pid=${child.pid}`);
    return;
  }
  mainLog(`[sidecar] group ${signal} failed，退回单进程 -> pid=${child.pid}`);
  try {
    child.kill(signal);
  } catch {
    /* 已退出 */
  }
}

function stopSidecar() {
  const child = childRef;
  // 注意：`child.killed` 只表示「SIGTERM 发出去了」，不代表进程已退出。
  // 用它判断会让 3 秒后的 SIGKILL 永远不执行，留下占着模型的孤儿进程。
  if (!child) {
    mainLog('[sidecar] stop skipped: no child');
    return;
  }
  mainLog(`[sidecar] stop pid=${child.pid} exit=${child.exitCode} signal=${child.signalCode}`);
  killSidecarTree(child, 'SIGTERM');
  // 3 秒还没退就强杀，绝不留下孤儿进程占着模型/继续编码
  setTimeout(() => {
    if (child.exitCode === null && child.signalCode === null) {
      killSidecarTree(child, 'SIGKILL');
    } else if (processGroupAlive(child)) {
      // sidecar 自己退了，但它启动的 ffmpeg 还在组里
      killSidecarTree(child, 'SIGKILL');
    }
  }, 3000).unref?.();
}

/** 等 sidecar 与它的子进程都退出（最多 timeoutMs），退出清理删代理前必须等它停手。 */
function stopSidecarAndWait(timeoutMs = 5000) {
  return new Promise((resolve) => {
    const child = childRef;
    if (!child) {
      resolve();
      return;
    }
    let done = false;
    let timer = null;
    const finish = () => {
      if (done) return;
      done = true;
      if (timer) clearInterval(timer);
      resolve();
    };
    // 被信号杀掉时 exitCode 保持 null，只有 signalCode 有值。只判 exitCode 会让
    // 这里永远等满 timeoutMs——sidecar 明明 0.3 秒就退了，用户却要盯着「正在启动
    // 转写内核」的遮罩 5 秒才退出（⌘Q 卡顿的根因）。
    const exited = () => child.exitCode !== null || child.signalCode !== null;
    const check = () => {
      if (exited() && !processGroupAlive(child)) finish();
    };
    child.once('exit', check);
    timer = setInterval(check, 120);
    timer.unref?.();
    stopSidecar();
    setTimeout(finish, timeoutMs).unref?.();
  });
}

/** 改了模型目录后重启内核；渲染进程会收到 sidecar:down → sidecar:ready 并重新握手。 */
function restartSidecar() {
  if (quitting || firstRunPending) {
    startSidecar();
    return;
  }
  // 被信号杀掉时 exitCode 是 null、signalCode 才有值；只判 exitCode 会把
  // 已经死掉的 childRef 当成活进程，于是只写 restartPending 却不再拉起新内核。
  if (!childRef || childRef.exitCode !== null || childRef.signalCode !== null) {
    startSidecar();
    return;
  }
  restartPending = true;
  sidecarRestarts = 0;
  stopSidecar();
}


/** 开发用种子：仅用于截图/联调，打包后不生效。 */
let devSeed = null;
if (process.env.KIKUSUB_DEV_SEED) {
  try {
    devSeed = JSON.parse(fs.readFileSync(process.env.KIKUSUB_DEV_SEED, 'utf8'));
    console.log('[seed] 已加载', devSeed.mediaPath, devSeed.cues?.length ?? 0, '条字幕');
  } catch (err) {
    console.error('[seed] 读取失败', err);
  }
}

// ---------------------------------------------------------------------------
// 窗口
// ---------------------------------------------------------------------------

function createWindow() {
  win = new BrowserWindow({
    width: IS_DEV && WIN_SIZE ? Number(WIN_SIZE[1]) : 1360,
    height: IS_DEV && WIN_SIZE ? Number(WIN_SIZE[2]) : 838,
    minWidth: 1080,
    minHeight: 680,
    show: false,
    // 半透明 + vibrancy：侧栏的 backdrop-filter 才有东西可透
    backgroundColor: '#00000000',
    vibrancy: 'sidebar',
    visualEffectState: 'followWindow',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 19, y: 18 },
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      spellcheck: false,
      // 窗口被遮挡时 Chromium 会节流渲染，capturePage 就会拿到旧帧。
      // 关掉节流后，后台窗口也能正确重绘（对截图验证很关键）。
      backgroundThrottling: false,
    },
  });

  win.once('ready-to-show', () => {
    // 截图模式不弹窗：capturePage 对未显示的窗口同样能拿到已绘制的帧
    if (SHOT_PATH) captureAndQuit();
    else win.show();
  });

  // 渲染进程就绪后把已有握手补发一次（避免 sidecar 比页面先好的竞态）
  win.webContents.on('did-finish-load', () => {
    // 开发用：KIKUSUB_ZOOM=2 把页面放大到 200%，用于缩放健壮性截图。
    // 这是取证开关，不是产品功能（应用没有缩放菜单）。
    if (IS_DEV && process.env.KIKUSUB_ZOOM) {
      const factor = Number(process.env.KIKUSUB_ZOOM);
      if (Number.isFinite(factor) && factor > 0) {
        try {
          win.webContents.setZoomFactor(Math.min(3, Math.max(0.5, factor)));
          console.log('[zoom] factor=', win.webContents.getZoomFactor());
        } catch {
          /* 缩放失败不影响启动 */
        }
      }
    }
    if (sidecar) sendToRenderer('sidecar:ready', sidecar);
    if (pendingFile) {
      sendToRenderer('file:opened', pendingFile);
      pendingFile = null;
    }
  });

  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) {
    win.loadURL(devUrl);
  } else {
    win.loadFile(path.join(DESKTOP_ROOT, 'renderer', 'dist', 'index.html'));
  }

  // 开发期把渲染进程的 console 接到终端，省得为了看一行错误去开 DevTools
  win.webContents.on('console-message', (event) => {
    const level = String(event.level ?? '');
    if (level.includes('error') || level.includes('warning')) {
      mainLog(`[renderer:${level}] ${event.message}`);
    }
    if (!app.isPackaged) console.log(`[renderer:${level}] ${event.message}`);
  });

  // 关窗口也走同一套清理：否则点红绿灯关闭会绕过 ⌘Q 的提示。
  win.on('close', (event) => {
    if (allowQuit || quitting) return;
    if (quitConfirming) {
      event.preventDefault();
      return;
    }
    if (quitFlow) {
      event.preventDefault();
      return;
    }
    const files = sessionCleanupCandidates();
    if (!files.length) return;
    event.preventDefault();
    requestQuitCleanup('close', files);
  });

  win.on('closed', () => {
    win = null;
  });
}

/** 向渲染进程发事件；窗口/页面已销毁时静默丢弃，别让退出路径反过来崩主进程。 */
function sendToRenderer(channel, payload) {
  if (!win || win.isDestroyed() || win.webContents.isDestroyed()) return;
  win.webContents.send(channel, payload);
}

/** 自截图模式：不碰用户桌面，直接把窗口画面存成 PNG 后退出。 */
async function captureAndQuit() {
  try {
    // 隐藏窗口不会持续重绘，capturePage 会拿到首帧。先短暂显示（不抢焦点），
    // 让合成器把当前状态真正画出来。
    win.showInactive();
    await new Promise((r) => setTimeout(r, SHOT_DELAY_MS));
    // 开发用：KIKUSUB_DEV_EVAL 里的 JS 会在渲染进程里执行并打印结果
    if (process.env.KIKUSUB_DEV_EVAL) {
      try {
        const out = await win.webContents.executeJavaScript(process.env.KIKUSUB_DEV_EVAL);
        console.log('[eval]', typeof out === 'string' ? out : JSON.stringify(out));
      } catch (err) {
        console.log('[eval:error]', err.message);
      }
    }
    if (!app.isPackaged || process.env.KIKUSUB_PROBE) {
      const info = await win.webContents.executeJavaScript(
        `JSON.stringify({
          hasBridge: typeof window.kikusub,
          hasSeed: typeof window.kikusub?.getDevSeed,
          active: document.querySelector('.sb-item.active')?.textContent?.trim(),
          title: document.querySelector('.tb-title')?.textContent,
          rows: document.querySelectorAll('.row').length,
          video: (() => {
            const v = document.querySelector('video');
            return v ? { w: v.videoWidth, h: v.videoHeight, err: v.error && v.error.code, src: v.currentSrc.slice(-28) } : null;
          })(),
          notice: document.querySelector('.notice')?.textContent?.trim() ?? null,
        })`,
      );
      console.log('[probe]', info);
    }
    // 截图前把指针挪到窗口左上角：真实鼠标可能正停在某个控件上，
    // 截图里就会带出一块随机 hover 底色，评审时容易被误读成选中态。
    try {
      win.webContents.sendInputEvent({ type: 'mouseMove', x: 2, y: 2 });
      await new Promise((r) => setTimeout(r, 120));
    } catch {
      /* 合成器不接受时忽略，截图照常 */
    }
    const image = await win.webContents.capturePage();
    fs.writeFileSync(SHOT_PATH, image.toPNG());
    console.log('[shot] 已保存', SHOT_PATH);
  } catch (err) {
    console.error('[shot] 失败', err);
  } finally {
    quitting = true;
    // 不能只发信号就 app.exit：退出期间 sidecar 可能还在 spawn ffmpeg。
    // 等整棵进程树真的退出（最多 4 秒，超时后 SIGKILL）再走。
    await stopSidecarAndWait(4000);
    app.exit(0);
  }
}

// ---------------------------------------------------------------------------
// 退出前清理（选区碎 SRT / 视频代理）
// ---------------------------------------------------------------------------

function sessionCleanupCandidates() {
  // 不按进程启动时间过滤：用户要求「每次 ⌘Q 都问」，包括上次崩溃/强退留下的
  // 碎片字幕与代理。sinceMs=0 表示列出当前输出目录里的全部候选。
  return listCleanupCandidates(path.join(baseDir(), 'outputs'), 0);
}

/**
 * 退出流程真正开始：先把「这是在退出」告诉渲染进程，再收起窗口。
 *
 * 没有这一步，`stopSidecar()` 触发的 `sidecar:down` 会让渲染层以为是内核崩溃，
 * 弹出「正在启动转写内核…」遮罩并清空会话，用户要对着它等 sidecar 收尾
 * （⌘Q 假死的表象）。退出时既要停掉这套重连 UI，也要立刻让窗口消失。
 */
function beginQuitTeardown() {
  quitting = true;
  sendToRenderer('app:quitting');
  if (win && !win.isDestroyed() && win.isVisible()) win.hide();
}

function finishQuit() {
  allowQuit = true;
  quitConfirming = false;
  beginQuitTeardown();
  quitFlow = null;
  stopSidecar();
  app.quit();
}

/**
 * 拦截退出，把清单交给渲染进程。
 *
 * 用原生 dialog 也能做，但 macOS 的 message box 只有一个 checkbox，无法满足
 * “逐个勾选要保留的文件”。这里用窗口内的模态面板，用户确认后再由主进程删。
 */
function requestQuitCleanup(kind, files) {
  if (quitFlow) return;
  if (!win || win.isDestroyed() || win.webContents.isDestroyed()) {
    // 没有窗口可问：宁可保留文件，也不在无人确认时删除
    mainLog(`[quit] no window, keep ${files.length} temp files`);
    finishQuit();
    return;
  }
  quitFlow = { kind, files };
  mainLog(`[quit] prompt kind=${kind} files=${files.length}`);
  sendToRenderer('quit:prompt', { files });
  // 用户一直不选：取消退出（不删任何文件），而不是替他做决定
  quitFlow.timer = setTimeout(() => {
    if (!quitFlow) return;
    mainLog('[quit] prompt timeout, cancel quit');
    quitFlow = null;
    sendToRenderer('quit:cancelled');
  }, 5 * 60 * 1000);
  quitFlow.timer.unref?.();
}

// ---------------------------------------------------------------------------
// 菜单
// ---------------------------------------------------------------------------

function buildMenu() {
  const send = (channel, payload) => () => sendToRenderer(channel, payload);

  const template = [
    {
      label: 'KikuSub',
      submenu: [
        { role: 'about', label: '关于 KikuSub' },
        { type: 'separator' },
        { label: '设置…', accelerator: 'CmdOrCtrl,', click: send('menu:settings') },
        { label: '键盘快捷键…', click: send('menu:shortcuts') },
        { type: 'separator' },
        { role: 'hide', label: '隐藏 KikuSub' },
        { role: 'hideOthers', label: '隐藏其他' },
        { role: 'unhide', label: '显示全部' },
        { type: 'separator' },
        { role: 'quit', label: '退出 KikuSub' },
      ],
    },
    {
      label: '文件',
      submenu: [
        { label: '打开…', accelerator: 'CmdOrCtrl+O', click: () => pickMedia(true) },
        { type: 'separator' },
        { label: '导出…', accelerator: 'CmdOrCtrl+E', click: send('menu:export') },
        { type: 'separator' },
        { role: 'close', label: '关闭窗口' },
      ],
    },
    {
      label: '编辑',
      submenu: [
        // 刻意不用 role:'undo'/'redo'：那是 DOM 级撤销，接不到字幕撤回栈
        { label: '撤回', accelerator: 'CmdOrCtrl+Z', click: send('menu:undo') },
        { label: '重做', accelerator: 'Shift+CmdOrCtrl+Z', click: send('menu:redo') },
        { type: 'separator' },
        { role: 'cut', label: '剪切' },
        { role: 'copy', label: '拷贝' },
        { role: 'paste', label: '粘贴' },
        { role: 'selectAll', label: '全选' },
        { type: 'separator' },
        // 快捷键由渲染层的可自定义表处理（默认 ⌘F），这里只保留菜单动作，
        // 否则用户把「查找」改成别的键后，旧 accelerator 仍然会抢先触发。
        { label: '查找与替换…', click: send('menu:find') },
      ],
    },
    {
      label: '显示',
      submenu: [
        // ⌘1–⌘7 由渲染层处理（导入 / 转写 / 核对台 / 双引擎复核 / 润色 / 翻译 / 导出）。
        // 菜单不绑 accelerator：用户改键后旧键不能仍然生效。
        { label: '导入', click: send('menu:view', 'import') },
        { label: '转写', click: send('menu:view', 'transcribe') },
        { label: '核对台', click: send('menu:view', 'review') },
        { label: '双引擎复核', click: send('menu:view', 'dual') },
        { label: '润色', click: send('menu:view', 'polish') },
        { label: '翻译', click: send('menu:view', 'translate') },
        { label: '导出', click: send('menu:view', 'export') },
        { label: '任务详报', click: send('menu:view', 'report') },
        { type: 'separator' },
        { label: '切换检查器', accelerator: 'CmdOrCtrl+Alt+I', click: send('menu:inspector') },
        { label: '切换外观', accelerator: 'CmdOrCtrl+Shift+A', click: send('menu:theme') },
        { type: 'separator' },
        { role: 'togglefullscreen', label: '进入全屏幕' },
        { role: 'toggleDevTools', label: '开发者工具' },
      ],
    },
    {
      label: '播放',
      submenu: [
        // 播放 / 上下句的按键可通过 ⌘K 面板重绑，菜单不再固定 accelerator。
        { label: '播放 / 暂停', click: send('menu:play') },
        { label: '上一句', click: send('menu:prev-cue') },
        { label: '下一句', click: send('menu:next-cue') },
      ],
    },
    { role: 'windowMenu', label: '窗口' },
    {
      role: 'help',
      label: '帮助',
      submenu: [
        { label: '打开日志目录', click: () => shell.openPath(logsDir()) },
        { label: '打开数据目录', click: () => shell.openPath(baseDir()) },
        { label: '项目主页', click: () => shell.openExternal('https://github.com/') },
      ],
    },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function pickMedia(notify = false) {
  if (!win) return null;
  const result = await dialog.showOpenDialog(win, {
    title: '选择音视频或字幕',
    properties: ['openFile'],
    filters: [
      { name: '音视频', extensions: ['mkv', 'mp4', 'mov', 'm4v', 'webm', 'avi', 'ts', 'flv', 'wmv', 'mpg', 'mpeg', 'ogv'] },
      { name: '字幕', extensions: ['srt', 'vtt'] },
      { name: '全部文件', extensions: ['*'] },
    ],
  });
  if (result.canceled || !result.filePaths.length) return null;
  const file = result.filePaths[0];
  // 只有菜单「打开…」需要走事件广播；渲染进程自己调 IPC 时已经有返回值，
  // 再发一次事件会让同一个文件被导入两遍（会话被绑定两次）。
  if (notify) sendToRenderer('file:opened', file);
  return file;
}

/** 打开导出目录里的字幕文件：默认定位到用户设置的导出文件夹，省去逐层翻目录。 */
async function pickProposal(defaultDir) {
  if (!win) return null;
  let defaultPath = typeof defaultDir === 'string' && defaultDir.trim() ? defaultDir.trim() : '';
  try {
    if (defaultPath && !fs.existsSync(defaultPath)) defaultPath = path.dirname(defaultPath);
  } catch {
    defaultPath = '';
  }
  if (!defaultPath) defaultPath = baseDir();
  const result = await dialog.showOpenDialog(win, {
    title: '选择 AI 提案文件',
    message: '选择一份 proposal.json（AI 优化台会先校验再导入）',
    defaultPath,
    properties: ['openFile'],
    filters: [
      { name: 'AI 提案', extensions: ['json'] },
      { name: '全部文件', extensions: ['*'] },
    ],
  });
  if (result.canceled || !result.filePaths.length) return null;
  return result.filePaths[0];
}

async function pickSubtitle(defaultDir) {
  if (!win) return null;
  let defaultPath = typeof defaultDir === 'string' && defaultDir.trim() ? defaultDir.trim() : '';
  try {
    if (defaultPath && !fs.existsSync(defaultPath)) defaultPath = path.dirname(defaultPath);
  } catch {
    defaultPath = '';
  }
  if (!defaultPath) defaultPath = baseDir();
  const result = await dialog.showOpenDialog(win, {
    title: '选择要导入核对台的字幕',
    message: '从导出文件夹里选择上次转写的 .srt / .vtt',
    defaultPath,
    properties: ['openFile'],
    filters: [
      { name: '字幕', extensions: ['srt', 'vtt'] },
      { name: '全部文件', extensions: ['*'] },
    ],
  });
  if (result.canceled || !result.filePaths.length) return null;
  return result.filePaths[0];
}

/**
 * 选择参考音频：上传克隆音色时用，只认音频扩展名。
 *
 * 渲染层会传来「上次上传的目录」或当前视频所在目录；这比每次落在音乐文件夹
 * 有用得多——用户的参考音频通常就和素材放在一起。支持一次选多段，每段会
 * 各自建立一个克隆音色（OmniVoice 一次只接受一段参考音频）。
 */
async function pickAudio(defaultDir) {
  if (!win) return [];
  let initial = typeof defaultDir === 'string' && defaultDir.trim() ? defaultDir.trim() : '';
  try {
    if (initial && fs.existsSync(initial) && !fs.statSync(initial).isDirectory()) {
      initial = path.dirname(initial);
    }
  } catch {
    initial = '';
  }
  if (!initial) {
    try {
      initial = app.getPath('music');
    } catch {
      initial = app.getPath('home');
    }
  }
  const result = await dialog.showOpenDialog(win, {
    title: '选择参考音频（3–10 秒干净人声效果最好）',
    message: '支持 wav / mp3 / m4a / flac 等常见格式；可一次选多段，每段建立一个音色',
    defaultPath: initial,
    properties: ['openFile', 'multiSelections'],
    filters: [
      { name: '音频', extensions: ['wav', 'mp3', 'm4a', 'aac', 'flac', 'ogg', 'opus', 'aiff', 'aif', 'wma'] },
      { name: '全部文件', extensions: ['*'] },
    ],
  });
  if (result.canceled || !result.filePaths.length) return [];
  return result.filePaths;
}

/** 通用目录选择：设置页切换导出文件夹。 */
async function pickDirectory(title, defaultPath) {
  if (!win) return null;
  let initial = typeof defaultPath === 'string' && defaultPath.trim() ? defaultPath.trim() : '';
  try {
    if (initial && !fs.existsSync(initial)) initial = path.dirname(initial);
  } catch {
    initial = '';
  }
  const result = await dialog.showOpenDialog(win, {
    title: title || '选择文件夹',
    defaultPath: initial || app.getPath('home'),
    buttonLabel: '使用此文件夹',
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || !result.filePaths.length) return null;
  return result.filePaths[0];
}

async function pickModelsDir() {
  if (!win) return null;
  let defaultPath = modelsDir();
  try {
    if (!fs.existsSync(defaultPath)) defaultPath = path.dirname(defaultPath);
  } catch {
    defaultPath = app.getPath('home');
  }
  const result = await dialog.showOpenDialog(win, {
    title: '选择模型保存目录',
    defaultPath,
    buttonLabel: '使用此目录',
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || !result.filePaths.length) return null;
  return result.filePaths[0];
}

// ---------------------------------------------------------------------------
// IPC
// ---------------------------------------------------------------------------

ipcMain.handle('app:info', () => ({
  version: app.getVersion(),
  platform: process.platform,
  arch: process.arch,
  dev: IS_DEV,
  repoRoot: REPO_ROOT,
  dataDir: dataDir(),
  modelsDir: modelsDir(),
  preferencesPath: preferencesPath(),
}));

ipcMain.handle('dialog:pick-media', () => pickMedia());
ipcMain.handle('dialog:pick-subtitle', (_e, defaultDir) => pickSubtitle(defaultDir));
ipcMain.handle('dialog:pick-audio', (_e, defaultDir) => pickAudio(defaultDir));
ipcMain.handle('dialog:pick-proposal', (_e, defaultDir) => pickProposal(defaultDir));

// ---- AI 密钥 ----
ipcMain.handle('ai-key:set', (_e, text) => setAiKey(text));
ipcMain.handle('ai-key:get', () => getAiKey());
ipcMain.handle('ai-key:clear', () => clearAiKey());
ipcMain.handle('skill:status', () => {
  try {
    return { ok: true, ...skill.status({ sourceDir: skillSourceDir(), targetDir: skillTargetDir() }) };
  } catch (err) {
    return { ok: false, error: err && err.message ? err.message : String(err) };
  }
});

ipcMain.handle('skill:install', (_event, paths) => {
  try {
    return {
      ok: true,
      ...skill.install({
        sourceDir: skillSourceDir(),
        targetDir: skillTargetDir(),
        paths: paths && typeof paths === 'object' ? paths : {},
      }),
    };
  } catch (err) {
    mainLog(`[skill] 安装失败：${err && err.message ? err.message : err}`);
    return { ok: false, error: err && err.message ? err.message : String(err) };
  }
});

ipcMain.handle('ai-key:status', () => {
  const state = getAiKeyState();
  return {
    ok: true,
    // 本机加密与签名身份无关，永远可用
    available: true,
    has: Boolean(state.key),
    backend: state.backend,
    persistent: state.backend === 'local',
    legacy: state.legacy,
    broken: state.broken,
  };
});
ipcMain.handle('dialog:pick-directory', (_e, payload) =>
  pickDirectory(payload && payload.title, payload && payload.defaultPath),
);

ipcMain.handle('sidecar:get', () => sidecar);

// ---- 首次启动 / 模型目录 ----
ipcMain.handle('setup:get', () => ({
  firstRun: firstRunPending,
  modelsDir: modelsDir(),
  defaultModelsDir: defaultModelsDir(),
  dataDir: dataDir(),
  preferencesPath: preferencesPath(),
  ffmpeg: findTool('ffmpeg') || '',
  appVersion: app.getVersion(),
}));

ipcMain.handle('setup:pick-models-dir', () => pickModelsDir());

ipcMain.handle('setup:complete', (_event, chosen) => {
  const target = ensureWritableDir(chosen || defaultModelsDir());
  savePreferences({
    version: 1,
    setupCompleted: true,
    modelsDir: target,
    setupCompletedAt: new Date().toISOString(),
  });
  firstRunPending = false;
  mainLog(`[setup] first run complete models=${target}`);
  if (!childRef) startSidecar();
  return { ok: true, modelsDir: target };
});

ipcMain.handle('setup:set-models-dir', (_event, chosen) => {
  if ((process.env.KIKUSUB_MODELS_DIR || '').trim()) {
    throw new Error(
      '当前模型目录由 KIKUSUB_MODELS_DIR 环境变量指定；请先取消该环境变量再在应用内更改。',
    );
  }
  const target = ensureWritableDir(chosen);
  const previous = modelsDir();
  savePreferences({ version: 1, setupCompleted: true, modelsDir: target });
  mainLog(`[setup] models dir ${previous} -> ${target}`);
  if (path.resolve(previous) !== path.resolve(target)) restartSidecar();
  return { ok: true, modelsDir: target };
});

// ---- 退出清理 ----
ipcMain.handle('quit:get', () => (quitFlow ? { files: quitFlow.files } : null));

ipcMain.handle('quit:confirm', async (_event, keepPaths) => {
  const flow = quitFlow;
  if (!flow) return { ok: false, removed: 0, failed: 0 };
  clearTimeout(flow.timer);
  quitFlow = null;
  quitConfirming = true;
  // 先让 sidecar 停手（可能正在写代理/字幕），再删文件。
  // 窗口在这里就收起：删除 + 等进程树退出期间不该再让用户看见任何界面状态。
  beginQuitTeardown();
  let result = { removed: 0, failed: 0, freed: 0, errors: [] };
  try {
    await stopSidecarAndWait(5000);
    result = deleteCleanupCandidates(flow.files, Array.isArray(keepPaths) ? keepPaths : []);
    mainLog(
      `[quit] kind=${flow.kind} removed=${result.removed} failed=${result.failed} ` +
        `freed=${result.freed} keep=${(keepPaths || []).length}`,
    );
    if (result.errors.length) mainLog(`[quit] delete errors ${result.errors.join(' | ')}`);
  } catch (err) {
    mainLog(`[quit] cleanup failed ${err && err.stack ? err.stack : err}`);
  } finally {
    // 无论删除是否成功都要退出；文件留在盘上比卡死在“清理中”好
    finishQuit();
  }
  return { ok: true, removed: result.removed, failed: result.failed };
});

ipcMain.handle('quit:cancel', () => {
  if (!quitFlow) return;
  clearTimeout(quitFlow.timer);
  quitFlow = null;
  mainLog('[quit] cancelled by user');
  sendToRenderer('quit:cancelled');
});

ipcMain.handle('dev:seed', () => {
  console.log('[seed] 渲染进程来取种子:', devSeed ? 'ok' : 'null');
  return devSeed;
});

ipcMain.handle('clipboard:write', (_e, text) => {
  try {
    clipboard.writeText(String(text ?? ''));
    return true;
  } catch {
    return false;
  }
});

ipcMain.handle('logs:clear-main', () => clearMainLogs());

ipcMain.handle('shell:reveal', (_e, target) => {
  if (typeof target === 'string' && target) shell.showItemInFolder(target);
});

ipcMain.handle('shell:open', (_e, target) => {
  if (typeof target === 'string' && target) return shell.openPath(target);
  return null;
});

ipcMain.on('window:set-title', (_e, title) => {
  if (win && typeof title === 'string') win.setTitle(title || 'KikuSub');
});

ipcMain.on('window:set-dirty', (_e, dirty) => {
  if (win) win.setDocumentEdited(Boolean(dirty));
});

ipcMain.on('window:set-theme', (_e, theme) => {
  // 外观 id 原样存（'light' / 'dark' / 'mincho'）：主进程只关心原生明暗，
  // 但冷启动的窗口要在首帧就用对 vibrancy，所以把 id 也记下来。
  const raw = theme === 'cool' ? 'mincho' : theme; // 'cool' 是旧版「明朝墨」的 id
  const id = raw === 'dark' || raw === 'mincho' ? raw : 'light';
  applyTheme(id === 'dark' ? 'dark' : 'light');
  try {
    if (loadPreferences().theme !== id) savePreferences({ theme: id });
  } catch {
    /* 主题写盘失败不影响本次切换 */
  }
});

// ---------------------------------------------------------------------------
// 生命周期
// ---------------------------------------------------------------------------

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  app.whenReady().then(() => {
    // 安全模式闸门必须排在建窗、起 sidecar、读日志之前：崩在这几步正是要兜底的情况。
    // 截图/取证模式（--screenshot）不参与：它 5.5s 就 app.exit()，绕过 before-quit，
    // 连跑几次取证会被误判成"连续打不开"。
    if (!SHOT_PATH) {
      const previousFailures = noteLaunchAttempt();
      if (previousFailures >= launchguard.CRASH_LIMIT && !resolveSafeMode(previousFailures)) {
        app.quit();
        return;
      }
    }
    // 日志保留策略：过期备份 / 超出总量上限的旧轮转在这里清掉
    try {
      const pruned = pruneLogs(logsDir());
      if (pruned.removed) {
        mainLog(`[logs] pruned ${pruned.removed} old file(s), freed=${pruned.freed}`);
      }
    } catch {
      /* 日志清理失败不能挡启动 */
    }
    firstRunPending = shouldFirstRun();
    applyTheme(loadPreferences().theme === 'dark' ? 'dark' : 'light');
    mainLog(
      `[main] KikuSub start version=${app.getVersion()} electron=${process.versions.electron} ` +
        `platform=${process.platform}/${process.arch} packaged=${app.isPackaged} ` +
        `data=${baseDir()} logs=${logsDir()} models=${modelsDir()} prefs=${preferencesPath()} ` +
        `firstRun=${firstRunPending} ffmpeg=${findTool('ffmpeg') || '(none)'}`,
    );
    process.on('uncaughtException', (err) => {
      mainLog(`[main] uncaughtException ${err && err.stack ? err.stack : err}`);
    });
    process.on('unhandledRejection', (reason) => {
      mainLog(`[main] unhandledRejection ${reason && reason.stack ? reason.stack : reason}`);
    });
    buildMenu();
    // 开发模式 Dock 默认是 Electron 图标；带上应用图标，避免和真正的
    // Electron 进程混淆。打包后 Info.plist 会直接使用 icon.icns。
    if (IS_DEV && process.platform === 'darwin' && app.dock) {
      const iconPath = path.join(DESKTOP_ROOT, 'build', 'icon.png');
      try {
        if (fs.existsSync(iconPath)) app.dock.setIcon(iconPath);
      } catch {
        /* 图标问题不能挡启动 */
      }
    }
    // sidecar 启动失败不能连累窗口：先建窗口，出问题也要能看见界面和日志
    createWindow();
    startedNormally = true;
    if (!firstRunPending) {
      try {
        startSidecar();
      } catch (err) {
        console.error('[sidecar] 启动异常', err);
        dialog.showErrorBox('内核启动失败', String(err && err.message ? err.message : err));
      }
    } else {
      mainLog('[setup] waiting for first-run model directory');
    }

    // 跑够 STABLE_AFTER_MS 才算"起得来"：崩溃基本都发生在这段窗口里（截图模式除外）
    if (!SHOT_PATH) {
      const stableTimer = setTimeout(() => clearLaunchFailures(), launchguard.STABLE_AFTER_MS);
      if (typeof stableTimer.unref === 'function') stableTimer.unref();
    }

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
      if (!firstRunPending && !childRef && !quitting) startSidecar();
    });
  });

  // 双击文件 / 拖到 Dock 图标
  app.on('open-file', (event, filePath) => {
    event.preventDefault();
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
      if (win.webContents.isLoading()) {
        pendingFile = filePath;
      } else {
        sendToRenderer('file:opened', filePath);
      }
    } else {
      // 首次启动 / 窗口尚未创建：等 did-finish-load 再送，别把用户双击的文件丢掉
      pendingFile = filePath;
    }
  });

  app.on('before-quit', (event) => {
    if (allowQuit) {
      quitting = true;
      // 安全模式里退出不能清零：下次启动还得提醒用户装修复版
      if (startedNormally) clearLaunchFailures();
      stopSidecar();
      return;
    }
    // 正在清理 / 已经弹过面板：别重复弹，等这一次走完
    if (quitConfirming || quitFlow) {
      event.preventDefault();
      return;
    }
    const files = sessionCleanupCandidates();
    if (!files.length) {
      // 没有临时文件要问，但 sidecar/ffmpeg 可能还在跑：先等进程树退出再退出。
      // 先收起窗口并通知渲染层，别让 sidecar 的 down 事件弹成“正在启动转写内核”。
      event.preventDefault();
      quitConfirming = true;
      beginQuitTeardown();
      stopSidecarAndWait(5000).finally(() => {
        allowQuit = true;
        app.quit();
      });
      return;
    }
    event.preventDefault();
    requestQuitCleanup('quit', files);
  });

  app.on('window-all-closed', () => {
    // macOS 惯例：关窗不退应用，但这里单窗口工具，关窗即退，避免 sidecar 空转
    app.quit();
  });
}
