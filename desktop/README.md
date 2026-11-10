# KikuSub 桌面外壳（Electron + Svelte）

改造规划 §2 的产物：Electron 主进程 + Svelte 5 渲染进程，Python sidecar 提供内核。

## 跑起来

```bash
cd desktop
npm install                       # 首次
npm run build                     # 构建渲染进程
npm run test:main                 # 退出清理 / 日志保留的 node:test
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
│   ├── main.cjs       主进程：窗口 / 菜单 / sidecar 生命周期 / 单实例 / 首次启动 / 退出清理
│   ├── files.cjs      临时产物扫描、删除与日志保留策略（纯 Node，可单测）
│   └── preload.cjs    contextIsolation 下唯一的桥（只给端口、token、对话框）
├── test/
│   └── files.test.cjs main/files.cjs 的 node:test 回归
└── renderer/
    └── src/
        ├── App.svelte        外壳：握手、菜单、拖放、快捷键、首次向导与退出面板
        ├── app.css           设计令牌（与静态高保真稿同一套值）
        ├── lib/api.ts        服务层客户端（Bearer + X-Kikusub-Session）
        ├── lib/store.svelte.ts  状态与动作（runes）
        ├── components/       Sidebar / Toolbar / Inspector / StatusBar / Icon /
        │                     FirstRun / QuitPrompt
        └── views/            Import / Transcribe / Review / Report / Settings
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

## 导入、导出与最近打开（2026-11-10）

- 转写页点「开始转写」成功后，字幕会**自动写入导出文件夹**（整片、转写页区间都算；
  核对台的局部修正仍是核对数据，按需再导出）。转写完成的卡片上直接显示落盘路径，
  并提供「在访达中显示 / 导出文件夹」。
- 核对台右侧检查器底部常驻「暂存进度 / 导出」。暂存写运行数据目录的
  `{stem}.autosave_draft.srt`（编辑后 0.9s 防抖自动写一次，不覆盖交付文件，
  可从「恢复上次暂存」取回）；导出写设置里的导出文件夹。这样即使重开应用后
  手动导入字幕、没有任务报告，也仍然能直接导出。
- 「设置 → 运行环境 → 导出文件夹」可查看、打开、更改默认目录，也能恢复默认。
  该目录只收字幕交付文件；日志、质检队列与 480p 代理仍在运行数据目录。
- 导入页的「导出文件夹」卡片可以在访达里打开目录，或点「导入字幕…」直接从该目录
  挑一个上次的 `.srt/.vtt` 载入核对台；转写页与核对台工具栏也有同一条入口。
- 「最近打开」每一行右侧有独立垃圾桶按钮，只删除这一条历史记录，不动磁盘文件。
- 侧栏底部「引擎」跟随顶部工具栏当前选中的引擎，不再固定显示第一个。

## 核对台能做什么（2026-11-10 补齐）

- 波形按可视窗口取包络（`?from=&to=`），滚轮 / 捏合 / 滑块缩放，双指横移或 ⌥ 拖动平移；
- **单击跳转、拖动才框选**：按下后移动超过 4px 才升级为框选，全局视图下手抖不会
  变成「框选了好几秒」；
- **逐帧擦洗**：顶部刻度条、播放头两侧 8px、以及上方视频进度条都可以按住拖动，
  拖动时暂停并连续 seek 预览画面（`video.currentTime` 每 16ms 至多写一次），
  松手回到原播放状态；MKV 未压好代理时播放头照样走；
- **底部字幕轨道**：蓝色块表示「这一段有字幕」，颜色与底槽明确区分；拖块体整体平移、
  拖左右两端单独改起止。双语同区间的多行是一块，一起移动、一次撤回；
- **播放头 ↔ 字幕同步**：播放头进入某句时，底部表格自动滚到该句并选中，右侧检查器
  同步显示；双语块内多行会整块高亮，点其中任意一行时保留你的选择不被抢回；
- 拖出选区后可试听、**转写选区**、填入转写页；每行可**单独重转**（只替换该区间）；
- 「聚焦」一键放大播放头附近；「跟随」是持久化偏好，**只有点按钮才会改变**，
  缩放/平移波形、点字幕/表格/画面都不会把它关掉（专业剪辑软件也不会因为缩放
  时间线就取消跟随播放头）。暂停时点字幕、点波形或拖完播放头，`revealPlayhead()`
  会把播放头平移回视窗内，不需要先播放一下；
- 质检面板逐项勾选、定位、补录、保留 / 恢复 / 删除，处理完自动推进下一条；
- 报告页逐条明细可展开，点时间码跳回核对台，支持导出 SRT / VTT / TXT；
- 双击 `.srt/.vtt`（或 ⌘O）导入字幕基线。

## 首次启动（真实用户的第一屏）

打包后的 `.app` 里没有模型，`~/Library/Application Support/KikuSub/models` 也可能不存在。
首次启动时主进程先不拉起 sidecar，而是让渲染进程显示「选择模型目录」向导：

1. 默认建议 `~/Library/Application Support/KikuSub/models`，也可以选外置盘/自定义目录；
2. 主进程校验目录可写并写入 `preferences.json`（`modelsDir` / `setupCompleted`）；
3. 之后才用 `KIKUSUB_MODELS_DIR=<该目录>` 启动 sidecar，下载与安装检测都落在这里；
4. 设置页「运行环境 → 模型目录 → 更改…」可以随时换目录，换完自动重启内核并重新握手。

如果用户是从旧版本升级、默认目录里已经有模型，则跳过向导，保持原样。
`KIKUSUB_MODELS_DIR` 环境变量仍然优先级最高；由它指定时应用内不允许再改。

`KIKUSUB_PREFERENCES_PATH` 可覆盖偏好文件位置（调试/截图用）；开发模式下默认写在
仓库根目录的 `preferences.json`（已 gitignore）。`KIKUSUB_FORCE_FIRST_RUN=1` 可强制
重放首次启动向导（调试用，会跳过“已有模型则不再询问”的判断）。

## 退出前清理（⌘Q）

退出（⌘Q 或关闭窗口）时主进程会扫描 `outputs/`：

- `*_00m40s-00m52s*` 这类「转写选区」碎字幕（含 `.qwen` / `.part_cancelled`）；
- `outputs/web_proxies/*.mp4` 视频代理。

面板默认**全部不勾选**；勾选的项目保留，未勾选的直接删除。没有窗口可询问时
（例如异常退出）宁可保留文件，不会在无人确认时删。删除前会先停掉 sidecar，
避免和正在写的代理/字幕抢文件。没有候选文件时直接退出，不弹空面板。

## 设置 / 引擎 / 日志

- 左下「设置」或 **⌘,**（菜单里也绑了同一条）：引擎与模型、运行环境、日志与诊断、工作流偏好；
- 引擎卡片由 `core/engines.py` 注册表驱动：语种、用途、预计/实际占用、安装状态、
  启用开关、一键下载与进度。顶部工具栏只显示已启用的引擎；
- **新增引擎**：在 `core/engines.py` 加一条 `EngineSpec`，在 `core/pipeline.py`
  注册推理对象并提供 `ensure_model(progress_cb)`。设置页与工具栏不用改。
- 日志：`outputs/logs/kikusub.log`（sidecar，含每条 API 请求与渲染端事件）、
  `outputs/logs/main.log`（Electron 主进程）。打包后在
  `~/Library/Application Support/KikuSub/outputs/logs/`；
- **日志也会清理**：sidecar 的 `RotatingFileHandler` 是 5 MB × 3；此外启动时和每 6 小时
  按「14 天 / 整个日志目录 64 MB」删轮转备份，主进程启动时也执行同一策略。
  设置页提供「清理旧日志」按钮（只删 `.log.N` 备份，正在写的日志保留）；
- 设置页可直接「复制诊断信息」（版本、目录、引擎状态、最近日志）用于报障。

## 已知缺口

- 「监看画面与转录源解耦」还没移植：原 Gradio 工作台可以单独导入监看画面、
  切换历史 480p 代理、关闭画面；桌面端目前只有自动跟随 + 代理自动切换。
- 虚拟列表、`content-visibility` 等剩余丝滑工程（阶段 4 的另一半）。
- 监看画面解耦仍未移植（见上）。

## 打包成 .app

```bash
bash tools/pack/build_sidecar.sh   # PyInstaller onedir，约 3–5 分钟，产出 737 MB
bash tools/pack/build_app.sh       # 装配 + 自签，产出 build/pack/KikuSub.app（约 931 MB）
```

产物：`repo/build/pack/KikuSub.app`，双击即可运行。

> 改了 `core/` 或 `server/` 的 Python 代码后，**必须**先重跑 `build_sidecar.sh`，否则
> `.app` 里仍是旧接口，会出现「界面有按钮、点击报 Method Not Allowed / 404」。
> `build_app.sh` 现在会检查 sidecar 是否比源码旧，旧了就拒绝装配并提示。

**为什么不用 electron-builder**：它在当前机器上会被宿主文件策略打断在
packaging 阶段（复制 Electron 框架时对 `default_app.asar` 报
`Operation not permitted`，随后进程被 SIGTERM）。`build_app.sh` 是手工装配：
复制框架 → 改名可执行文件 → 写 Info.plist → 放 main/renderer → 放 sidecar → 自签。
每一步都可见，出问题好定位。

`desktop/package.json` 里的 `build` 字段保留着，在普通机器上
`npx electron-builder --mac dir` 应该也能用。

### 运行期目录

| 用途 | 路径 |
| --- | --- |
| 数据 / 输出 / 代理 | `~/Library/Application Support/KikuSub/` |
| 模型 | 首次启动时选择；默认同上 `models/`（构建脚本在本机会软链到仓库里已下载的 6.6 GB） |
| 启动偏好 | 同上 `preferences.json`（模型目录 / 主题 / 首次设置完成） |
| 日志 | 同上 `outputs/logs/kikusub.log`，14 天 / 64 MB 保留策略 |

模型目录的优先级：`KIKUSUB_MODELS_DIR` 环境变量 → `preferences.json` 里用户选的目录 →
App Support `models/` → 开发期仓库 `models/`。

### 打包后的实测

- sidecar 从 `Contents/Resources/python/sidecar` 启动，握手 **0.31 s**（热启）
- 首次运行约 17 s（macOS 校验 3000+ 个未签名文件），之后都是 0.3 s
- 完整跑通：导入 MKV → 后台压制代理 → WS 通知 → 换源播放 → 4 条字幕 → 检查器
