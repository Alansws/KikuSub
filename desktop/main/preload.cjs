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

  // 文件操作（只给「在访达中显示」，不给读写）
  revealInFinder: (target) => ipcRenderer.invoke('shell:reveal', target),
  openPath: (target) => ipcRenderer.invoke('shell:open', target),

  // 窗口状态
  setTitle: (title) => ipcRenderer.send('window:set-title', title),
  setDocumentEdited: (dirty) => ipcRenderer.send('window:set-dirty', dirty),

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

  // 开发用：截图/联调时由主进程注入「媒体 + 字幕」，打包后恒为 null
  getDevSeed: () => ipcRenderer.invoke('dev:seed'),

  // 拖进窗口的文件：Electron 32+ 去掉了 File.path，只能由主进程侧换算
  getPathForFile: (file) => {
    try {
      return webUtils.getPathForFile(file);
    } catch {
      return '';
    }
  },
});
