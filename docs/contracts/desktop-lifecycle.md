# 桌面启动、日志、退出清理与运行开关

> 从 `AGENTS.md` 拆出（2026-11-13）。Electron 主进程生命周期、日志与诊断、模型目录、快捷键、退出清理、单实例与截图开关。总索引见 [AGENTS.md](../../AGENTS.md)。

---

### 3.5 日志与诊断（2026-11 新增）

- **服务层必须在 `server/__main__.py` 里调 `core.logging_setup.setup_logging()`**：漏掉这一步会导致 `outputs/logs/kikusub.log` 永远为空（曾经就是这样）。日志目录是 `config.output_dir/logs`。
- 日志分三层：sidecar 的 `kikusub.log`、Electron 主进程的 `main.log`、渲染端通过 `POST /api/log` 写入的 `kikusub.renderer`。排查用户问题优先看 `~/Library/Application Support/KikuSub/outputs/logs/`。
- **不要把 token、cookie、完整音视频内容写进日志**；文件路径与转写片段文本可以记。
- 请求中间件会对 `/api/*` 记录方法/路径/状态/耗时/`X-Request-Id`/会话 id；波峰与 `/media/*` 降为 DEBUG，避免刷屏。
- 渲染端 API 失败会自动带 `X-Request-Id` 记日志；新增「用户关键动作」时同时 `logEvent(...)`，否则用户报障时无法还原操作序列。
- 局部转写的 `write_audit` 语义：`replace_range`（核对台单句/选区修正）**不写**整片质检队列；转写页的整片/区间任务都要写，否则报告与质检面板数字不一致。

#### 3.5.1 应用图标（2026-11 修订）

- **唯一图标源是 `docs/app-icon.png`**（1024×1024、RGBA、圆角与投影已烘进图里）。
  `desktop/build/icon.icns` 必须由它重新渲染后打包：`tools/pack/make_icon.swift`
  按 macOS 全部尺寸生成 iconset，`build_app.sh` 的 0/7 步先执行它，缺图直接失败——
  绝不允许「沿用上一版 icon.icns」静默装出图标过时的 .app。
- 旧波形 logo（深色圆角 + 米白声波 + 朱红底线）只作历史资产留在
  `docs/archive/logo-waveform.*`，**不再参与打包，也不要再被 README 引用**。
  README / README_EN 头部与仓库社交预览都必须用新图标（蓝紫渐变 K + 播放键 + 胶片）。
- 装配后删除 Electron 自带的 `Contents/Resources/electron.icns`，避免图标缓存
  误用旧图；`build_app.sh` 末尾会 `touch` + `lsregister -f`。Finder 缓存仍顽固时
  运行 `bash tools/pack/refresh_finder_icon.sh --restart`。
- 对外展示面（README 头部、GitHub「Social preview」卡）与安装包图标是两条链路：
  前者是仓库文件 + Settings 手工上传，后者才走打包脚本。改图标时三处都要看，
  否则会出现「Dock 是新的、仓库页还是旧的」。

### 3.6 桌面启动、设置与退出清理（2026-11 新增）

#### 首次启动与模型目录

- 首次启动由主进程判定（`shouldFirstRun()`，`desktop/main/main.cjs`）：没有
  `preferences.json`、没有 `KIKUSUB_MODELS_DIR`、且默认/已有模型目录里没有权重时才弹
  选择模型目录的向导。旧用户目录里已有模型则**跳过**，保持原样。
- 向导完成前**不得启动 sidecar**：模型目录必须作为 `KIKUSUB_MODELS_DIR` 在 spawn 时传入，
  Python 的 `core.paths.MODELS_DIR` 是 import 期常量，运行中改不了。
- **首次启动第二步是「配置本地模型」**（`FirstRun.svelte` → `EngineSetup.svelte`）：
  `completeSetup` 写入目录并启动 sidecar 后，列出 `core.engines` 的两个 ASR 引擎与可选的
  OmniVoice，用户可勾选后「一键配置所选」或「稍后再说」。**默认只勾推荐 Anime Whisper；
  OmniVoice 默认不勾**，TTS 默认仍是 `say`，但用户可在设置「TTS 对照」里切换默认偏好（见 §3.4.2）。已安装项只展示、不重复下载；
  下载进度用 `/api/engines/{key}/download` + `/api/jobs/{id}` 与 `/api/tts/model/status` 轮询。
  设置页「引擎与模型 → 运行首次配置…」复用同一个组件，所以老用户也能补配置。
- 偏好写在 `dataDir()/preferences.json`（`KIKUSUB_PREFERENCES_PATH` 可覆盖）：
  `setupCompleted / modelsDir / theme`。开发模式 `dataDir()` 是仓库根，文件已 gitignore。
- 设置页「运行环境 → 模型目录 → 更改…」会保存新目录并重启 sidecar；重启走
  `restartPending`（不计崩溃次数），渲染进程必须能在 `sidecar:down → sidecar:ready`
  后重新 `boot()`，否则界面会停在“内核未连接”。
- 模型下载目标由 `core/engines.model_dir()` 从 `MODELS_DIR` 派生；改目录后下载/安装检测
  自然落在新目录。`KIKUSUB_MODELS_DIR` 优先级最高，设置页不允许在它存在时改目录。
- **双击素材启动不能丢文件**：首次启动时 `open-file` 可能早于窗口/sidecar。主进程用
  `pendingFile` 等 `did-finish-load` 再送；渲染层 `openMedia()` 在内核未连接时把路径存进
  `pendingMediaPath`，`boot()` 成功后自动补导入。菜单打开/拖放到 Dock 走同一条链路。
- **重启自动接上一次会话**：`openMedia` 成功后写 `localStorage['kikusub.lastMedia']`；
  手动导入字幕写 `['kikusub.lastSubtitle']`（带媒体路径，防止串片）；核对台每 2.5 秒写
  `['kikusub.lastPosition']`。冷启动 `App.svelte` 在 `boot()` 且没有 dev seed 时调
  `restoreLastSession()`：先 `openMedia(path, { restoreDraft: true })`，有工作草稿就恢复
  草稿，否则恢复上次手动导入的字幕，最后 `seekTo()` 回到上次播放头。**不要**把字幕快照
  另存一份到 localStorage；必须走现有 `restoreDraft` / `openSubtitle` 链路，来源标记、
  质检解耦与 ⌘Z 才不会和真实会话不一致。

- **顶部引擎切换（2026-11 改版）**：工具栏不再平铺分段，`components/EngineSwitch.svelte`
  用「当前引擎胶囊 + 可滚动列表」；列表项显示用途、就绪圆点与体积，3–4 个引擎也不会挤占
  工具栏。`ProgressBar.svelte` 是模型下载 / OmniVoice 校验的统一轨道：`percent=null` 走
  不确定进度，确定进度只改 `transform: scaleX()`，完成态转绿。改这两块时保留
  `bind:engine` 契约与 `prefers-reduced-motion` 降级。

#### 快捷键

- **⌘,（Ctrl+,）** 打开设置。菜单 `设置…` 已绑 accelerator，渲染层 `onKey` 还要再兜一层：
  输入框聚焦时菜单快捷键可能被吃掉，且设置快捷键要在 `typing` early-return **之前**处理。
- **⌘K** 打开「键盘快捷键」面板（`ShortcutsDialog.svelte`）；面板里的组合存
  `localStorage['kikusub.shortcuts.v1']`，菜单里也有「键盘快捷键…」入口。用户自定义优先，
  不要再把播放 / 删除 / 视图切换写死回菜单 accelerator。
- **冲突必须当场说清楚**：录制新组合时如果与另一个动作或固定快捷键重复，消息要显示在
  正在录制的那一行下面（不能只放在面板底部，用户看不到），并保留原键不保存；已保存映射
  里的重复也要在该行标红。旧版 `view.export=mod+4 / view.report=mod+5` 只在仍是旧默认值
  时迁移到新的 `⌘5`，用户自定义过的键不覆盖。

#### 退出前清理（⌘Q / 关窗）

- 主进程 `before-quit` 与 `win.on('close')` 都拦截：扫描 `outputs/` 顶层的时间区间碎字幕
  与 `outputs/web_proxies/*.mp4`，通过 `quit:prompt` 交给渲染进程逐个勾选。
- **默认全部不勾选，不勾选即删除**；勾选才保留。面板没有可询问的窗口时宁可保留文件，
  绝不无人确认就删。没有候选时不弹空面板，直接退出。
- 删除前必须 `stopSidecarAndWait()`，避免和正在写的 `.part.mp4` / SRT 抢文件；删除只允许
  操作主进程捕获的候选路径，渲染进程传别的路径不得生效。
- 确认/清理期间用 `quitConfirming` 阻断重复的 `before-quit`/`close`；取消退出时必须清掉
  `quitFlow` 并让窗口继续活着。`quit:confirm` 期间 `quitting=true`，sidecar 退出后不得自动重启。
- **退出必须先 `beginQuitTeardown()` 再动 sidecar**（2026-11 修复）：它 `sendToRenderer('app:quitting')`
  并立刻 `win.hide()`。渲染层收到后置 `app.quitting=true`，`markSidecarDown()` 在退出期间只把
  连接状态置灰——不弹「正在启动转写内核…」遮罩、不清会话、不弹“内核已断开”toast。
  漏掉这步，`stopSidecar()` 的 `sidecar:down` 会被当成崩溃重启，用户按 ⌘Q 看到的是重启遮罩。
- **`stopSidecarAndWait()` 的“已退出”判定必须同时看 `exitCode` 与 `signalCode`**：Node 里被信号
  杀掉的子进程 `exitCode` 恒为 `null`、只有 `signalCode`。只判 `exitCode` 会让每次 ⌘Q 都等满
  5 秒超时（sidecar 实际 0.3 秒就退了）。`restartSidecar()` 的存活判定同理；`child.on('exit')`
  里还要把 `childRef` 置空，否则崩溃后 `activate` / 改模型目录会把死引用当活内核。
- 清理逻辑在 `desktop/main/files.cjs`，用 `node --test desktop/test/files.test.cjs` 回归；
  区间文件名正则要与 `core/subtitles.format_time_tag` 保持一致（`00m40s-00m52s`、
  `01h02m03s`、`from_`/`to_`）。`isFragmentSubtitle()` 必须排除
  `*.autosave_draft.srt` / `*.reviewed.srt` / `*.clean.srt`：核对工作稿与成片不是临时碎片，
  不能因为媒体名里带区间标记就在退出时被默认删除。

#### 日志清理

- `setup_logging()` 启动时调用 `prune_logs()`：只删 `*.log.N` 轮转备份，
  **永不删正在写的 `kikusub.log` / `main.log`**；策略为 14 天或整个日志目录 64 MB。
- sidecar 每 6 小时后台清理一次；Electron 主进程启动时用 `main/files.cjs` 的
  `pruneLogs()` 执行同一策略。
- 设置页「清理旧日志」走 `POST /api/diagnostics/log/clean`，是同一份 `prune_logs()`；
  不要为了“清空”去 truncate 活动日志（会破坏 handler 的 inode/offset）。
