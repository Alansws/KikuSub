# KikuSub 桌面外壳（Electron + Svelte）

Electron 主进程 + Svelte 5 渲染层，Python sidecar 提供内核。用户文档见仓库根目录的
[README.md](../README.md)，实现约束见 [AGENTS.md](../AGENTS.md) 的 §3.4–§3.7。

## 跑起来

```bash
cd desktop
npm install                       # 首次
npm run build                     # 构建渲染进程
npm run test:main                 # 主进程单测（清理 / 密钥 / 技能）
npx electron .                    # 启动
```

**注意：本机 shell 里可能已有 `ELECTRON_RUN_AS_NODE=1`（某些 Electron 宿主会设），
它会让任何 Electron 二进制退化成纯 Node。启动前必须清掉：**

```bash
env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS npx electron .
```

被沙箱拦住时再加 `--no-sandbox`（仅调试用，正常双击启动不需要）。

开发模式下 userData 固定到仓库的 `.dev-userdata/`（已 gitignore）：Electron 的单实例锁跟着
userData 走，所以即使命令行里带了不同的 `--user-data-dir`，也只会有一个 Electron / Dock 图标。
确实要并行调试多个实例时显式加 `KIKUSUB_ALLOW_MULTIPLE=1`；`--screenshot` 取证模式会自动跳过这条限制。

应用图标源是 `../docs/app-icon.png`（1024 透明底），`tools/pack/make_icon.swift` 生成
`build/icon.icns`；开发模式的 Dock 图标直接用 `build/icon.png`。

## 结构

```
desktop/
├── main/
│   ├── main.cjs       主进程：窗口 / 菜单 / sidecar 生命周期 / 单实例 / 首次启动 / 退出清理 / 截图模式
│   ├── files.cjs      临时产物扫描、删除与日志保留策略（纯 Node，可单测）
│   ├── aikey.cjs      AI Key 的本机加密（AES-256-GCM + 0600 主密钥）
│   ├── skill.cjs      随包 Agent 技能的安装器（纯 Node，可单测）
│   └── preload.cjs    contextIsolation 下唯一的桥（端口、token、对话框、AI Key、主题）
├── resources/skill/   随包的 kikusub-subtitle 技能（打包时复制进 .app）
├── test/              files / aikey / skill / 模板导入的 node:test
└── renderer/
    └── src/
        ├── App.svelte        外壳：握手、菜单、拖放、快捷键、首次向导与退出面板
        ├── app.css           设计令牌（与静态高保真稿同一套值）
        ├── lib/api.ts        服务层客户端（Bearer + X-Kikusub-Session）
        ├── lib/store.svelte.ts   状态与动作（runes）
        ├── components/       Sidebar / Toolbar / Inspector / StatusBar / Icon /
        │                     ParamPanel / QaPanel / FirstRun / QuitPrompt
        └── views/            Import / Transcribe / Review / AiView / PromptView /
                              ExportView / Report / Settings
```

## 自截图（不打扰桌面）

```bash
env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS \
  KIKUSUB_DEV_SEED=/tmp/seed.json KIKUSUB_SHOT_DELAY=7000 \
  npx electron . --no-sandbox --screenshot=/tmp/app.png
```

`KIKUSUB_DEV_SEED` 指向 `{ "mediaPath": "...", "cues": [{ "start": 0, "end": 2, "text": "…" }] }`，
渲染进程会把它灌进当前会话后直接进核对屏——联调与截图不必每次真跑转写。打包后这个入口恒为 `null`。

还需要切视图时用 `KIKUSUB_DEV_EVAL`：里面的 JS 会在截图前于渲染进程执行一次，可以点
`.sb-item` 切侧栏、点工具栏「AI 优化」进提案台，再 `await` 一会儿等数据到位。截图前会
打印一行 `[probe]`，给出当前视图、行数与视频尺寸，便于确认截到的是哪一屏。

> README 里的截图就是这样生成的：一段 32 秒的真实素材 + 真实 SRT 做种子，AI 提案用
> `core.ai_proposal.build_proposal()` 造好后放到导出目录，界面自己回收它。

## 各屏能做什么

- **导入**：拖入视频 / 音频 / 字幕；最近打开（带视频首帧封面，纯黑片头会自动挑有画面的帧）、导出文件夹、导入字幕；
  MKV / HEVC 在后台压 480p 代理，不挡用户操作。
- **转写**：引擎、时间区间、输出格式、结果处理（自动 / 覆盖 / 追加）；右侧参数面板与预设。
- **核对**：视频 + 波形 + 字幕轨道 + 检查器；单击跳转、拖动框选、逐帧擦洗、字幕块整体/两端拖动、
  三态显示、暂存与导出、⌘Z 整块回退；顶部 20 步可回溯历史（点任意一步跳回）、⌘F 查找替换、
  右栏本机 TTS 对照（系统 say 兜底 + OmniVoice 克隆；可上传多段参考音频、从当前句截取、
  在音色库中试听/设为默认；右键任意一句也能「以此句音频新建音色…」）、音轨右键添加 0.8 秒空字幕、聚焦统一 69×。
- **AI 优化台**：双栏 diff，左原文只读、右建议双击可改；采纳/拒绝、只看改动、应用整批、
  另存 / 丢弃 / 导入提案；润色与翻译两种类型，翻译带目标语种。
- **详情与导出**：任务报告、逐段明细、质检结果、导出 SRT / VTT / TXT；烧录样式与导出参数的调整都进撤销历史（⌘Z 按最近一次操作在字幕与导出设置之间切换）。
- **设置**：引擎与模型（下载/校验/启用）、运行环境（模型与导出目录、诊断）、日志、
  AI 优化（Base URL / 模型 / 分块 / Key）、Agent 技能一键配置、TTS 默认音色、外观。

## 首次启动

打包后的 `.app` 里没有模型，`~/Library/Application Support/KikuSub/models` 也可能不存在。
首次启动时主进程先不拉起 sidecar，而是显示两步向导：

1. 「选择模型目录」：默认建议 `~/Library/Application Support/KikuSub/models`，也可以选外置盘 / 自定义目录；
2. 主进程校验目录可写并写入 `preferences.json`（`modelsDir` / `setupCompleted`），随后用
   `KIKUSUB_MODELS_DIR=<该目录>` 启动 sidecar；
3. 「配置本地模型」：列出 Anime Whisper / Qwen3-ASR / OmniVoice（可选），可勾选后
   「一键配置所选」，也可以「稍后再说」；OmniVoice 默认不勾选，TTS 默认仍是系统语音
   （可在设置里切换）；
4. 设置页「引擎与模型 → 运行首次配置…」复用同一组件，随时可以重新选择；
5. 设置页「运行环境 → 模型目录 → 更改…」可以随时换目录，换完自动重启内核并重新握手。

从旧版本升级且默认目录里已有模型时跳过向导。`KIKUSUB_MODELS_DIR` 优先级最高；
`KIKUSUB_PREFERENCES_PATH` 可覆盖偏好文件位置（调试 / 截图用），
`KIKUSUB_FORCE_FIRST_RUN=1` 可强制重放向导。

## 退出前清理（⌘Q）

退出（⌘Q 或关闭窗口）时会扫描 `outputs/` 顶层的时间区间碎字幕与 `outputs/web_proxies/*.mp4`，
逐个勾选保留；**默认全部不勾选，不勾选即删除**。没有窗口可询问时宁可保留。删除前会先停
sidecar，避免和正在写的代理 / 字幕抢文件。规则在 `main/files.cjs`，用
`node --test test/files.test.cjs` 回归；译文交付物（`*.zh-Hans.srt`、`*.bilingual.srt`）
不会被当成碎片。

没有候选文件时 ⌘Q 应当**立即退出**：主进程先 `win.hide()` 并广播 `app:quitting`，渲染层
在 `app.quitting` 期间不再显示「正在启动转写内核…」遮罩，也不会把 `sidecar:down` 当成
内核崩溃去重置会话。`stopSidecarAndWait()` 的“已退出”判定同时看 `exitCode` 与
`signalCode`（被信号杀掉的子进程 `exitCode` 恒为 `null`），否则每次退出都会白等 5 秒。

## AI Key 存储

`main/aikey.cjs` 用 32 字节本机主密钥（`{dataDir}/.ai-key`，0600）做 AES-256-GCM；
`preferences.json` 里只存 `aik1:` 密文。**不用 `safeStorage`**：ad-hoc 签名每次发版
cdhash 都变，keychain 条目会全部失效。改这块时守住三条：0600 权限、旧 `v10` blob 要能
识别并报 `broken`、绝不把明文写进任何文件或日志。用例在 `test/aikey.test.cjs`。

## 日志

- `outputs/logs/kikusub.log`（sidecar，含每条 API 请求与渲染端事件）
- `outputs/logs/main.log`（Electron 主进程）
- 打包后在 `~/Library/Application Support/KikuSub/outputs/logs/`

日志按「14 天 / 整个日志目录 64 MB」删除轮转备份，正在写的日志永不删；sidecar 每 6 小时
清理一次，设置页「清理旧日志」走同一个 `prune_logs()`。

## 打包成 .app

```bash
bash tools/pack/rebuild.sh         # 日常：按需重打 sidecar → 构建渲染层 → 装配 → 打开
bash tools/pack/build_sidecar.sh   # 只重打 Python sidecar（PyInstaller，约 3–5 分钟）
bash tools/pack/build_app.sh       # 只装配 + 自签，产出 build/pack/KikuSub.app
```

`rebuild.sh` 会先让正在运行的旧实例走正常退出流程，否则单实例锁会让新构建打不开。

> 改了 `core/` 或 `server/` 的 Python 代码后**必须**先重跑 `build_sidecar.sh`，
> 否则 `.app` 里仍是旧接口，会出现「界面有按钮、点击报 Method Not Allowed / 404」。
> `build_app.sh` 会检查 sidecar 是否比源码旧，旧了就拒绝装配。

`build_app.sh` 是手工装配（复制框架 → 改名可执行文件 → 写 Info.plist → 放 main/renderer
→ 放 sidecar 与 skill → 自签）。不用 electron-builder 是因为它在本机会被宿主文件策略
打断在 packaging 阶段；`package.json` 里的 `build` 字段保留着，普通机器上仍可用。

### 运行期目录

| 用途 | 路径 |
| --- | --- |
| 数据 / 输出 / 代理 | `~/Library/Application Support/KikuSub/` |
| 模型 | 首次启动时选择；默认同上 `models/` |
| 启动偏好 | 同上 `preferences.json`（模型目录 / 主题 / 首次设置 / AI Key 密文） |
| 日志 | 同上 `outputs/logs/kikusub.log`，14 天 / 64 MB 保留策略 |

开发模式沿用仓库目录，与 sidecar 单独启动时共享 `outputs/`、`presets.json`。
