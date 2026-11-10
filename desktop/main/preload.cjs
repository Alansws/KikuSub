/**
 * preload：contextIsolation 下唯一的桥。
 *
 * 只暴露「渲染进程必须知道但拿不到」的东西：sidecar 的端口与 token、
 * 原生文件对话框、在访达中显示、窗口标题。**不暴露任何文件系统能力**——
 * 渲染进程要读文件一律走 HTTP。
 */

const { contextBridge, ipcRenderer, webUtils } = require('electron');

const listeners = new Map();

function on(channel, handler) {
  const wrapped = (_event, payload) => handler(payload);
  ipcRenderer.on(channel, wrapped);
  listeners.set(handler, { channel, wrapped });
  return () => {
    const item = listeners.get(handler);
    if (item) {
      ipcRenderer.removeListener(item.channel, item.wrapped);
      listeners.delete(handler);
    }
  };
}

contextBridge.exposeInMainWorld('kikusub', {
  // 主进程信息
  info: () => ipcRenderer.invoke('app:info'),

  // sidecar 握手：{ port, token, pid }
  // 页面可能在握手之后才挂载，所以先问一次当前值，再订阅后续变化
  getSidecar: () => ipcRenderer.invoke('sidecar:get'),
  onSidecarReady: (cb) => on('sidecar:ready', cb),
  onSidecarDown: (cb) => on('sidecar:down', cb),

  // 原生对话框
  pickMedia: () => ipcRenderer.invoke('dialog:pick-media'),
  // 默认打开导出文件夹，只让用户挑字幕；设置页用 pickDirectory 选导出目录
  pickSubtitle: (defaultDir) => ipcRenderer.invoke('dialog:pick-subtitle', defaultDir),
  pickProposal: (defaultDir) => ipcRenderer.invoke('dialog:pick-proposal', defaultDir),

  // Agent 技能：把随包 skill 装到 ~/.agents/skills/（DSH 扫描的用户级根）
  skill: {
    status: () => ipcRenderer.invoke('skill:status'),
    install: (paths) => ipcRenderer.invoke('skill:install', paths),
  },

  // AI 密钥：加解密都在主进程，渲染进程只在发起请求那一刻取用
  aiKey: {
    set: (text) => ipcRenderer.invoke('ai-key:set', text),
    get: () => ipcRenderer.invoke('ai-key:get'),
    clear: () => ipcRenderer.invoke('ai-key:clear'),
    status: () => ipcRenderer.invoke('ai-key:status'),
  },
  pickDirectory: (payload) => ipcRenderer.invoke('dialog:pick-directory', payload),

  // 剪贴板：file:// 页面里 navigator.clipboard 不一定可用，走主进程更稳
  writeClipboard: (text) => ipcRenderer.invoke('clipboard:write', text),

  // 文件操作（只给「在访达中显示」，不给读写）
  revealInFinder: (target) => ipcRenderer.invoke('shell:reveal', target),
  openPath: (target) => ipcRenderer.invoke('shell:open', target),

  // 窗口状态
  setTitle: (title) => ipcRenderer.send('window:set-title', title),
  setDocumentEdited: (dirty) => ipcRenderer.send('window:set-dirty', dirty),
  // 应用主题 → 原生 vibrancy / 红绿灯区域跟着深色走
  setTheme: (theme) => ipcRenderer.send('window:set-theme', theme),

  // 首次启动向导 / 模型目录
  getSetupState: () => ipcRenderer.invoke('setup:get'),
  completeSetup: (modelsDir) => ipcRenderer.invoke('setup:complete', modelsDir),
  pickModelsDir: () => ipcRenderer.invoke('setup:pick-models-dir'),
  setModelsDir: (modelsDir) => ipcRenderer.invoke('setup:set-models-dir', modelsDir),

  // 退出前清理：主进程发清单，渲染进程回传要保留的路径
  onQuitPrompt: (cb) => on('quit:prompt', cb),
  onQuitCancelled: (cb) => on('quit:cancelled', cb),
  // 页面可能比 before-quit 晚挂载：启动时补问一次当前待确认的清理清单
  getQuitPrompt: () => ipcRenderer.invoke('quit:get'),
  confirmQuit: (keepPaths) => ipcRenderer.invoke('quit:confirm', keepPaths),
  cancelQuit: () => ipcRenderer.invoke('quit:cancel'),

  // 菜单事件
  onMenu: (cb) => {
    const offs = [
      on('menu:undo', () => cb({ type: 'undo' })),
      on('menu:redo', () => cb({ type: 'redo' })),
      on('menu:settings', () => cb({ type: 'settings' })),
      on('menu:export', () => cb({ type: 'export' })),
      on('menu:inspector', () => cb({ type: 'inspector' })),
      on('menu:theme', () => cb({ type: 'theme' })),
      on('menu:play', () => cb({ type: 'play' })),
      on('menu:prev-cue', () => cb({ type: 'prev-cue' })),
      on('menu:next-cue', () => cb({ type: 'next-cue' })),
      on('menu:view', (view) => cb({ type: 'view', view })),
    ];
    return () => offs.forEach((off) => off());
  },

  // 双击文件 / 拖到 Dock
  onFileOpened: (cb) => on('file:opened', cb),

  // 拖进窗口的文件：Electron 32+ 去掉了 File.path，只能由主进程侧换算
  getPathForFile: (file) => {
    try {
      return webUtils.getPathForFile(file);
    } catch {
      return '';
    }
  },

  // 开发用：截图/联调时由主进程注入「媒体 + 字幕」，打包后恒为 null
  getDevSeed: () => ipcRenderer.invoke('dev:seed'),

});
