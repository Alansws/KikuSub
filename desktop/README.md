# KikuSub 桌面外壳（Electron + Svelte）

改造规划 §2 的产物：Electron 主进程 + Svelte 5 渲染进程，Python sidecar 提供内核。

## 跑起来

```bash
cd desktop
npm install                       # 首次
npm run build                     # 构建渲染进程
npx electron .                    # 启动
```

**注意：本机 shell 里存在 `ELECTRON_RUN_AS_NODE=1`（WorkBuddy 的 Electron 宿主设的），
它会让任何 Electron 二进制退化成纯 Node。启动前必须清掉：**

```bash
env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS npx electron .
```

被 WorkBuddy 沙箱拦住时再加 `--no-sandbox`（仅调试用，正常双击启动不需要）。

## 结构

```
desktop/
├── main/
│   ├── main.cjs       主进程：窗口 / 菜单 / sidecar 生命周期 / 单实例
│   └── preload.cjs    contextIsolation 下唯一的桥（只给端口、token、对话框）
└── renderer/
    └── src/
        ├── App.svelte        外壳：握手、菜单、拖放、快捷键
        ├── app.css           设计令牌（与静态高保真稿同一套值）
        ├── lib/api.ts        服务层客户端（Bearer + X-Kikusub-Session）
        ├── lib/store.svelte.ts  状态与动作（runes）
        ├── components/       Sidebar / Toolbar / Inspector / StatusBar / Icon
        └── views/            Import / Transcribe / Review / Report
```

## 自截图（不打扰桌面）

```bash
env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS \
  KIKUSUB_DEV_SEED=/tmp/seed.json KIKUSUB_SHOT_DELAY=7000 \
  npx electron . --no-sandbox --screenshot=/tmp/app.png
```

`KIKUSUB_DEV_SEED` 指向 `{ "mediaPath": "...", "cues": [...] }`，
渲染进程会把它灌进当前会话后直接进核对屏——联调与截图不必每次真跑转写。
打包后这个入口恒为 `null`。

## 已知缺口

- 480p 代理压制完成后，播放器仍指向原片（需要服务端把代理 URL 暴露出来）
- 虚拟列表、`content-visibility` 等丝滑工程尚未做（阶段 4）
- 质检浮标只有入口，没有展开面板
