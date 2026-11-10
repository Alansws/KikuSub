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
const { app, BrowserWindow, dialog, ipcMain, Menu, shell } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const DESKTOP_ROOT = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(DESKTOP_ROOT, '..');

const IS_DEV = !app.isPackaged;
const SHOT_ARG = process.argv.find((a) => a.startsWith('--screenshot'));
const SHOT_PATH = SHOT_ARG
  ? (SHOT_ARG.split('=')[1] || '/tmp/kikusub-app.png')
  : null;
// 截图前等多久：要盖住「sidecar 启动 + 首帧数据」的时间，默认 5.5s
const SHOT_DELAY_MS = Number(process.env.KIKUSUB_SHOT_DELAY || 5500);

/** @type {BrowserWindow | null} */
let win = null;
/** @type {{port:number, token:string, pid:number} | null} */
let sidecar = null;
let sidecarRestarts = 0;
let quitting = false;

// ---------------------------------------------------------------------------
// sidecar
// ---------------------------------------------------------------------------

function pythonPath() {
  if (!IS_DEV) {
    // 打包后：KikuSub.app/Contents/Resources/python/kikusub-server
    return path.join(process.resourcesPath, 'python', 'kikusub-server');
  }
  const venv = path.join(REPO_ROOT, '..', '.venv', 'bin', 'python');
  return fs.existsSync(venv) ? venv : 'python3';
}

function startSidecar() {
  if (quitting) return;

  const exe = pythonPath();
  const args = IS_DEV ? ['-m', 'server', '--port', '0'] : ['--port', '0'];
  const cwd = IS_DEV ? REPO_ROOT : path.join(process.resourcesPath, 'python');

  console.log('[sidecar] 启动', exe, args.join(' '));
  const child = spawn(exe, args, {
    cwd,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
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
        win?.webContents.send('sidecar:ready', payload);
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
    sidecar = null;
    win?.webContents.send('sidecar:down', { code, signal });
    if (quitting) return;
    if (sidecarRestarts >= 3) {
      dialog.showErrorBox('内核启动失败', '转写内核连续 3 次异常退出，请查看日志后重启应用。');
      return;
    }
    sidecarRestarts += 1;
    setTimeout(startSidecar, 600 * sidecarRestarts);
  });

  child.on('error', (err) => {
    console.error('[sidecar] 无法启动', err);
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

function stopSidecar() {
  const child = childRef;
  if (!child || child.killed) return;
  try {
    child.kill('SIGTERM');
  } catch {
    /* 已退出 */
  }
  // 3 秒还没退就强杀，绝不留下孤儿进程占着模型
  setTimeout(() => {
    try {
      if (!child.killed) child.kill('SIGKILL');
    } catch {
      /* ignore */
    }
  }, 3000).unref?.();
}


/** 开发用种子：仅用于截图/联调，打包后不生效。 */
let devSeed = null;
if (!app.isPackaged && process.env.KIKUSUB_DEV_SEED) {
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
    width: 1360,
    height: 838,
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
    },
  });

  win.once('ready-to-show', () => {
    // 截图模式不弹窗：capturePage 对未显示的窗口同样能拿到已绘制的帧
    if (SHOT_PATH) captureAndQuit();
    else win.show();
  });

  // 渲染进程就绪后把已有握手补发一次（避免 sidecar 比页面先好的竞态）
  win.webContents.on('did-finish-load', () => {
    if (sidecar) win.webContents.send('sidecar:ready', sidecar);
  });

  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) {
    win.loadURL(devUrl);
  } else {
    win.loadFile(path.join(DESKTOP_ROOT, 'renderer', 'dist', 'index.html'));
  }

  // 开发期把渲染进程的 console 接到终端，省得为了看一行错误去开 DevTools
  if (!app.isPackaged) {
    win.webContents.on('console-message', (event) => {
      console.log(`[renderer:${event.level}] ${event.message}`);
    });
  }

  win.on('closed', () => {
    win = null;
  });
}

/** 自截图模式：不碰用户桌面，直接把窗口画面存成 PNG 后退出。 */
async function captureAndQuit() {
  try {
    // 隐藏窗口不会持续重绘，capturePage 会拿到首帧。先短暂显示（不抢焦点），
    // 让合成器把当前状态真正画出来。
    win.showInactive();
    await new Promise((r) => setTimeout(r, SHOT_DELAY_MS));
    if (!app.isPackaged) {
      const info = await win.webContents.executeJavaScript(
        `JSON.stringify({
          hasBridge: typeof window.kikusub,
          hasSeed: typeof window.kikusub?.getDevSeed,
          active: document.querySelector('.sb-item.active')?.textContent?.trim(),
          title: document.querySelector('.tb-title')?.textContent,
          rows: document.querySelectorAll('.row').length,
        })`,
      );
      console.log('[probe]', info);
    }
    const image = await win.webContents.capturePage();
    fs.writeFileSync(SHOT_PATH, image.toPNG());
    console.log('[shot] 已保存', SHOT_PATH);
  } catch (err) {
    console.error('[shot] 失败', err);
  } finally {
    quitting = true;
    stopSidecar();
    app.exit(0);
  }
}

// ---------------------------------------------------------------------------
// 菜单
// ---------------------------------------------------------------------------

function buildMenu() {
  const send = (channel, payload) => () => win?.webContents.send(channel, payload);

  const template = [
    {
      label: 'KikuSub',
      submenu: [
        { role: 'about', label: '关于 KikuSub' },
        { type: 'separator' },
        { label: '设置…', accelerator: 'CmdOrCtrl,', click: send('menu:settings') },
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
        { label: '打开…', accelerator: 'CmdOrCtrl+O', click: () => pickMedia() },
        { type: 'separator' },
        { label: '导出字幕…', accelerator: 'CmdOrCtrl+E', click: send('menu:export') },
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
      ],
    },
    {
      label: '显示',
      submenu: [
        { label: '导入', accelerator: 'CmdOrCtrl+1', click: send('menu:view', 'import') },
        { label: '转写', accelerator: 'CmdOrCtrl+2', click: send('menu:view', 'transcribe') },
        { label: '核对', accelerator: 'CmdOrCtrl+3', click: send('menu:view', 'review') },
        { label: '报告', accelerator: 'CmdOrCtrl+4', click: send('menu:view', 'report') },
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
        { label: '播放 / 暂停', accelerator: 'Space', click: send('menu:play') },
        { label: '上一句', accelerator: 'Up', click: send('menu:prev-cue') },
        { label: '下一句', accelerator: 'Down', click: send('menu:next-cue') },
      ],
    },
    { role: 'windowMenu', label: '窗口' },
    {
      role: 'help',
      label: '帮助',
      submenu: [
        { label: '打开日志目录', click: () => shell.openPath(path.join(REPO_ROOT, 'outputs', 'logs')) },
        { label: '项目主页', click: () => shell.openExternal('https://github.com/') },
      ],
    },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function pickMedia() {
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
  win.webContents.send('file:opened', file);
  return file;
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
}));

ipcMain.handle('dialog:pick-media', () => pickMedia());

ipcMain.handle('sidecar:get', () => sidecar);

ipcMain.handle('dev:seed', () => {
  console.log('[seed] 渲染进程来取种子:', devSeed ? 'ok' : 'null');
  return devSeed;
});

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
    buildMenu();
    startSidecar();
    createWindow();

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  // 双击文件 / 拖到 Dock 图标
  app.on('open-file', (event, filePath) => {
    event.preventDefault();
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
      win.webContents.send('file:opened', filePath);
    }
  });

  app.on('before-quit', () => {
    quitting = true;
    stopSidecar();
  });

  app.on('window-all-closed', () => {
    // macOS 惯例：关窗不退应用，但这里单窗口工具，关窗即退，避免 sidecar 空转
    app.quit();
  });
}
