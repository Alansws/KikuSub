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
  里的重复也要在该行标红。旧版 `view.ai=mod+4 / view.export=mod+5` 只在仍是旧默认值
  时迁移到 `⌘4..⌘7`（双引擎复核 / 润色 / 翻译 / 导出）；2026-11 加「断句重排」后再次顺延到
`⌘4..⌘8`（… / 润色 / 断句重排 / 翻译 / 导出）。两次迁移都只在「仍是旧默认值」时改，用户自定义过的键不覆盖。
- **按钮焦点与输入控件**：`allowOnControls` 只让传输键（←/→、↑/↓、⇧Space）在按钮 / 链接
  焦点上生效；`textarea` / `input`（含 `type=range` 滑杆）/ `select` / `contenteditable`
  永远让位。`onKey` 顶部先 `isComposing || keyCode===229` 早退，日语输入法组合中不抢键。
- **方向键不触发网页 history**：核对台的 ←/→、⌘←/⌘→ 显式 `preventDefault()`；主进程菜单
  没有 back/forward accelerator，但仍保留导航守卫。输入控件内的方向键保持原生行为。

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

#### sidecar 的 cwd 与「原地重打包」（2026-11 修复）

- **sidecar 的 cwd 绝不落在 `.app` 里面**：`tools/pack/build_app.sh` 是先 `rm -rf KikuSub.app`
  再重新装配，而 sidecar 是 detached 的（父进程退出它也不跟着死）。装配那一刻它的 cwd 变成
  一个已删除的 inode，之后每次 `os.getcwd()` 都抛 `ENOENT`——torch 在 import 期就会踩
  （`torch/_dynamo/config.py: default_debug_dir_root`），一次 Whisper/Qwen 转写 1 秒内失败，
  界面只剩一句 `[Errno 2] No such file or directory`，跟视频和模型都无关。打包态一律用数据目录
  当 cwd（`startSidecar()` 里的 `cwd = base`）。
- 两道兜底：`core/paths.ensure_usable_cwd()` 在 sidecar 启动、以及每次 `run_transcription()`
  之前各查一次，cwd 坏了就 `chdir` 到 `outputs/`（回归 `tests/test_paths_cwd.py`）；
  `build_app.sh` 在 `rm -rf "$APP"` 前先让同路径旧实例退出，退不掉就**报错退出**，
  不许带着旧进程覆盖包体。

#### 日志清理

- `setup_logging()` 启动时调用 `prune_logs()`：只删 `*.log.N` 轮转备份，
  **永不删正在写的 `kikusub.log` / `main.log`**；策略为 14 天或整个日志目录 64 MB。
- sidecar 每 6 小时后台清理一次；Electron 主进程启动时用 `main/files.cjs` 的
  `pruneLogs()` 执行同一策略。
- 设置页「清理旧日志」走 `POST /api/diagnostics/log/clean`，是同一份 `prune_logs()`；
  不要为了“清空”去 truncate 活动日志（会破坏 handler 的 inode/offset）。

### 3.7 窗口可见性：验证一律无窗口（2026-11-16 用户红线）

用户的原话是「每次改个功能都反复弹 Electron 窗口，干扰这台电脑上别的事，之后不许再弹」。
这条契约把「不弹窗」做成**默认行为**，而不是让智能体记得别弹——记忆会失效，默认值不会。

- **判定只有一处**：`desktop/main/windowmode.cjs` 的 `resolveWindowMode()`（纯函数，
  `desktop/test/window-mode.test.cjs` 覆盖）。主进程只按结果执行，不许在别处再写一份
  `show() / 不 show()` 的判断。

  | 启动方式 | 结果 |
  | --- | --- |
  | `--screenshot` / `KIKUSUB_SHOT` | 不显示，透明窗口取帧后退出 |
  | `KIKUSUB_NO_WINDOW=1`（CI / 自动化总开关） | 不显示，进程照常跑 |
  | 未打包且无 `KIKUSUB_ALLOW_WINDOW=1` | **拒绝启动**：打印无窗口验证路径，退出码 2（不建窗口、不起 sidecar、不计启动失败） |
  | `npm start` / `desktop/run.sh`（已带 `ALLOW_WINDOW=1`） | 显示 |
  | 打包后的 `.app` 双击 / Dock / Finder | 显示（用户意图明确） |

- **截图不再 `showInactive()`**：旧实现会让窗口在桌面上亮 4.5–5.5 秒——这正是「反复弹窗」的
  主要来源。现在窗口 `setOpacity(0)` + `setHasShadow(false)` + `setIgnoreMouseEvents(true)`，
  并隐藏 Dock 图标；窗口仍参与合成，`capturePage()` 的帧与可见时一致，桌面上什么都看不到。
- **`tools/pack/rebuild.sh` 默认只构建装配，不打开**：`--open` 才是人的动作；`--no-open`
  仍接受（等价于默认）。
- **不许智能体代劳**：`npx electron .`、`npm start`、`desktop/run.sh`、
  `open *.app`、`rebuild.sh --open` 都属于「人要看界面」的操作。要确认界面就截图落盘，
  用 `read_image` 看 PNG。规则入口在 `AGENTS.md` §0.5 与红线 13。

### 3.7.1 200% 页面缩放：不在支持范围内（2026-11-24 用户决定，永久生效）

用户的原话是「我们的软件根本就不适合 200% 的时候还能使用，不用考虑这一点」。这条把
一个反复消耗时间的假问题**永久关闭**。

- **200% 不是产品状态**：应用**没有**缩放菜单（⌘+ / ⌘- / ⌘0 都不存在），所以 200% 只能
  通过系统辅助功能或外部注入到达，不是用户能走到的路径。1360×838 的窗口在 200% 下只剩
  **680×419** 的有效视口——这个尺寸下核对台的「侧栏 236 + 检查器 348」就已经占满 584px，
  监看舞台只剩 96px，布局塌是**必然结果而不是 bug**。
- **禁止为它写代码**：不加 200% 专用断点、不加第二套导航 / 汉堡菜单 / 折叠抽屉、
  不为了 200% 调字号或间距。`@media (max-width: 900px)` 存在是因为**窗口本来就可以缩到
  900px 以下**（用户会拉窗口），那与缩放无关，保留。
- **禁止为它写验收**：验收脚本里**不许**再出现 `zoom200` / `KIKUSUB_ZOOM=2` 用例。
  这类用例会稳定地红（布局本来就塌），逼下一个人去排查一个不需要修的问题——这正是
  2026-11-24 那次 `verify_settings_layout` 报 6 条失败、查下去发现是 200% 才会遇到的坑。
  `KIKUSUB_ZOOM` 取证开关**保留但不再被任何脚本使用**（真要手动看一眼时才用）。
- **验收视口只认这几个**：`1440×900`（设计基准）、`1360×838`（默认窗口）、
  `1120×800`、`1000×700`（窄窗下限）。再窄就是用户自己把窗口拉到不合理的尺寸。
- **守卫**：`tests/test_no_zoom200_policy.py` 检查
  ① `AGENTS.md` 仍有这条红线；
  ② `tools/shots/` 下没有任何脚本（`README.md` 除外）出现 `zoom200` / `KIKUSUB_ZOOM`；
  ③ 验收视口清单里没有 200% 条目。

### 3.8 外部工具 ffmpeg / ffprobe：随包静态二进制（2026-11-21 新增，Step 7）

macOS **不自带 ffmpeg**，而从访达启动的 `.app` 只拿到 `/usr/bin:/bin:/usr/sbin:/sbin`——
Homebrew 的 `/opt/homebrew/bin` 不在里面。所以在 Step 7 之前，「下载 .app → 双击 → 导入视频」
对没装过 Homebrew 的普通用户是**必然失败**，报的还是 Internal Server Error。这一节把
「工具从哪来」定成一个顺序，不再靠用户装 brew。

**解析只有一处实现**：`core/paths.py` 的 `ffmpeg_bin()` / `ffprobe_bin()`。
凡是拼 `subprocess` 命令的地方都必须用它们，**禁止再把裸 `"ffmpeg"` 写进命令列表**
（回归：`tests/test_ffmpeg_paths.py` 会用 AST 扫 `core/` 与 `server/`，命中即失败）。

| 顺序 | 来源 | 用途 |
| --- | --- | --- |
| 1 | `KIKUSUB_FFMPEG` / `KIKUSUB_FFPROBE`（完整文件路径） | 用户把 ffmpeg 装在奇怪位置时的最终手段 |
| 2 | `KIKUSUB_FFMPEG_DIR`（目录，含两个工具） | 老变量，主进程一直支持；错误文案里也写着它 |
| 3 | **包内 `Contents/Resources/bin/`** | 随 `.app` 分发的静态 ffmpeg/ffprobe（Step 7） |
| 4 | 系统 `PATH` | 开发机上的 Homebrew；装了 brew 的用户 |
| 5 | 裸名字兜底 | 让 `subprocess` 抛 `FileNotFoundError`，各模块据此给「请安装 ffmpeg」的提示 |

- **包内位置有两个来源，顺序固定**：① 主进程打包态显式传
  `KIKUSUB_BUNDLE_BIN=<resourcesPath>/bin`；② 没有它时 Python 按目录层数推
  （`_bundled_bin_candidates()`）。**不要只写 `APP_ROOT.parent / "bin"`**：PyInstaller
  onedir 会把 `core` 冻进可执行文件，`core/paths.py` 的 `__file__` 是
  `Resources/python/sidecar/core/paths.py`，`APP_ROOT` 是 **onedir 目录本身**，
  `APP_ROOT.parent` 是 `Resources/python`。Step 7 第一版就是这么写错的，日志里是
  `bundled_bin=…/Resources/python/bin`、`PATH+=(无)`，包内 ffmpeg 完全没被发现；
  验收脚本 `tools/pack/verify_bundled_ffmpeg.sh` 正是靠「干净 PATH 跑打包 sidecar」把它逼出来的。
- **主进程同步前置 PATH**：`desktop/main/main.cjs` 的 `augmentedPath()` 把
  `KIKUSUB_FFMPEG_DIR → Resources/bin → 原 PATH → Homebrew 常见目录` 拼成 sidecar 的环境；
  `core/paths.install_bundled_bin_path()` 在 sidecar 启动时再前置一次（幂等），给
  「按 PATH 找 ffmpeg」的第三方代码兜底。
- **开发环境不读包内二进制**：仓库根旁边的 `bin/` 不存在，解析自然落到 Homebrew——
  本机开发仍是无缝的，不需要为了跑测试下载 130 MB。
- **设置页诊断要能说清楚用的是哪份**：`/api/settings` 的 `ffmpeg` 块多一个
  `source` 字段（`bundled` / `explicit` / `system`），路径照旧。
- **来源与许可必须清晰**（GPLv3 的分发义务）：二进制不入库（约 130 MB），由
  `tools/pack/fetch_ffmpeg.sh` 按**钉死的版本 + sha256** 取回；`build_app.sh` 第 6 步把
  `ffmpeg` / `ffprobe` / `LICENSE-ffmpeg-GPLv3.txt` / `NOTICE-ffmpeg.txt` 放进
  `Contents/Resources/bin/`，**先单独 ad-hoc 签名这两个 Mach-O**，再签整个 `.app`
  （重新签名会替换 Mach-O 里的签名块，包内二进制的体积与 sha256 因此与下载时不同——
  实测 ffmpeg 小约 3.9 MB，是预期行为，`NOTICE-ffmpeg.txt` 里写明了）。
  当前来源是 Martin Riedl 的 FFmpeg Build Server（静态链接、arm64、Developer ID 签名 + 公证、
  `--enable-gpl --enable-version3`，含 x264/x265/libass），版本与校验值写在
  `tools/pack/fetch_ffmpeg.sh` 顶部与生成的 `NOTICE.txt` 里。
- **缺内置 ffmpeg 时**：`build_app.sh` 只告警（开发机可以只用 Homebrew）；
  `KIKUSUB_REQUIRE_BUNDLED_FFMPEG=1` 变成硬失败，`tools/release/preflight.sh` 第 8 项
  默认就按「发版必须随包」要求它。
- **验收命令**：`bash tools/pack/verify_bundled_ffmpeg.sh`（可加
  `KIKUSUB_STEP7_MEDIA=/path/to/film.mkv`）。它把 PATH 清成
  `/usr/bin:/bin:/usr/sbin:/sbin`、直接起 `.app` 里的 sidecar，断言
  `/api/settings` 的 `ffmpeg.source == "bundled"`，并真跑一次 ffprobe（探时长）与
  ffmpeg（生成缩略图）。**pytest 只能证明解析顺序，证明不了冻结后的布局**，两者都要有。

### 3.9 外部 CLI（`kikusub`）与 runtime.json（2026-11-21 新增）

- **发现通道**：sidecar 启动、bind 端口后把 `<output_dir>/runtime.json`（**0600**、原子替换）
  写成 `{app, runtime_version, api_version, port, token, pid, started_at, output_dir, session_id}`。
  端口由 OS 分配、token 每次随机，CLI 没有别的可靠办法拿到它们；不要改成让 CLI 扫描端口或读进程环境。
- **session_id 的写入规则**：只有客户端**带着已有会话 id** 回来（渲染层的 `X-Kikusub-Session`）
  才会更新。CLI 自己会新建空会话；如果那个 id 也被记下，下一次 CLI 就会读到空工程而不是
  界面上正在编辑的字幕。没有 session_id 时 CLI 必须报「界面还没建立会话」，不许自己建。
- **崩溃残留**：优雅退出删文件；强杀/崩溃留下的旧文件由 CLI 用 `pid` 探活识别（`os.kill(pid, 0)`），
  pid 不存在就报「旧文件」并继续找下一个候选，不把旧 token 当可用实例。
- **CLI 产物**：`tools/kikusub/` 是纯 stdlib（urllib/json/pathlib）客户端，PyInstaller **onedir**
  产出 `kikusub` + `kikusub-internal/`（免解压的 CPython 运行时），两者一起装进
  `Contents/Resources/bin/`（**不能**放 `Contents/MacOS`：APFS 默认大小写不敏感，`MacOS/kikusub` 会解析到主可执行文件 `KikuSub`，装配时会把 Electron 主二进制覆盖成 CLI——`build_app.sh` 现在用「主可执行文件逐字节等于 Electron」硬断言拦住）；设置页「AI 与技能 → 命令行工具」把 `kikusub` 软链到
  `~/.local/bin/kikusub`（**不覆盖同名普通文件**）。macOS 默认 PATH 不含该目录，设置页同时给
  可复制的 `~/.zshrc` 命令；兜底是 app 内绝对路径。
  **绝不用 onefile**：onefile 每次启动都要把运行时解压到临时目录并重新做签名校验，实测
  `kikusub --help` 4.5–9.6 s；onedir 免解压后是毫秒级（`build_cli.sh` 构建完会打印实测值）。
- **runtime.json 路径一致性**：打包态 sidecar 写
  `~/Library/Application Support/KikuSub/outputs/runtime.json`（主进程把
  `KIKUSUB_OUTPUT_DIR` 设为 `<appData>/KikuSub/outputs`）。这是 CLI 默认候选列表的第一项，
  所以终端直接敲 `kikusub project` 即可，**不需要** `--runtime`；源码仓库里跑才落到
  `<repo>/outputs/runtime.json`。路径口径由
  `tests/test_kikusub_cli.py::test_default_runtime_path_matches_packaged_app` 看守。
- **CLI 只读 + 只提交提案**：`project / cues / cue / qa / listen` 不写会话；
  `propose` 只调 `POST /api/ai/proposal`、`/api/ai/structure/from-json`、`/api/ai/reshape/proposal`，
  应用接口一个都不碰。`listen` 走 `kind=compare`，`--separate` 时窗口先分离人声再送识别。
- **开发模式路径**：`build/pack/dist/kikusub`；runtime 文件在仓库 `outputs/runtime.json`。
  打包后是 `~/Library/Application Support/KikuSub/outputs/runtime.json`。
- **验证**：`tests/test_runtime_file.py`、`tests/test_server_evidence.py`、
  `tests/test_server_compare_separate.py`、`tests/test_kikusub_cli.py`；
  UI 侧 `tools/shots/verify_external_proposals.mjs`（无窗口截图，断言提示 + 自动载入）。
