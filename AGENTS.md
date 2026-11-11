# AGENTS.md — 日语影片字幕转录工作台开发指南

本文件面向在此仓库中继续开发的智能体与开发者。开始改动前先阅读本文件和相关模块；它记录当前实际实现，而不仅是产品愿景。

## 1. 项目定位与运行方式

这是一个 **macOS 桌面应用**形态的日语影视字幕工作台：Electron 主进程 + Svelte 5 渲染层，Python 以内置 sidecar（FastAPI）提供内核。它面向动漫、电影、Galgame、广播剧等音频场景，支持：

- Anime Whisper：重视自然、连贯的日语对话转写；
- Qwen3-ASR + CTC：转写后利用自带的 CTC 对齐头取得逐字发声时间，并针对日语分句；
- Silero VAD 分段、可选动态响度归一化、时间范围转录、原片绝对时间轴、取消后保存已完成字幕；
- 视频 + 波形核对台、质检待核队列、SRT/VTT/TXT 导出、参数预设与完整任务报告；
- AI 提案（润色 / 翻译平行轨）与随包 Agent 技能。

**主入口是 `desktop/`。** `app.py` 与 `static/` 已从仓库移除；旧 Gradio 界面归档在 Git 标签 `v0.9-gradio` 与本地独立目录 `~/Downloads/kikusub_gardio`，不再随本仓库演进。

开发模式（安装 `requirements.txt`、`desktop/npm install` 与系统 `ffmpeg` 后）：

```bash
cd desktop && npm run build && npx electron .
```

sidecar 也可以单独启动：`source .venv/bin/activate && python -m server --port 0`，stdout 首行输出 `{"event":"ready","port":…,"token":…}`。

首次真正转录时才会加载（必要时下载）模型。不要在不需要模型推理的改动验证中触发下载或完整转录；界面、波形与提案链路的验证用 `KIKUSUB_DEV_SEED`（见 `desktop/README.md`）。

## 2. 仓库结构

| 路径 | 职责 |
| --- | --- |
| `desktop/` | **桌面端（当前主入口）**。`main/` 是 Electron 主进程：窗口/菜单/单实例、sidecar 生命周期、首次启动向导、退出清理、AI 密钥加密（`aikey.cjs`）、技能安装（`skill.cjs`）；`files.cjs` 只依赖 fs，可被 `node --test` 覆盖。`renderer/src/` 是 Svelte 5 渲染层：`views/`（导入 / 转写 / 核对 / AI 优化台 / 详情与导出 / 设置）、`lib/store.svelte.ts` 状态与动作、`lib/api.ts` 服务层客户端。 |
| `desktop/resources/skill/` | 随包的 Agent 技能，构建时复制进 app，由设置页「一键配置」装到 `~/.agents/skills/`。 |
| `core/` | **算法内核包**（无任何 UI 依赖）。`paths.py` 是运行期路径中枢（`KIKUSUB_MODELS_DIR` / `KIKUSUB_OUTPUT_DIR` / `KIKUSUB_PRESETS_PATH` 可覆盖）；`python -m core.smoke` 自检内核与 UI 解耦，`tests/test_core_boundary.py` 看守这条边界。**禁止在 `core/` 内 import gradio / fastapi。** |
| `server/` | **服务层（FastAPI）**。`python -m server` 启动，stdout 首行输出 `{"event":"ready","port":…,"token":…}` 供 Electron 主进程握手。`/api/*` 走 Bearer token，`/media/*` 走 `?token=`（`<video src>` 发不了自定义头）。**禁止在 server/ 内 import UI 代码。** |
| `server/routes_ai.py` | 提案接口：`/api/ai/proposal`、`/api/ai/apply`、`/api/ai/prompt`、`/api/ai/from-srt`、`/api/ai/proposal/import`。 |
| `server/routes_translations.py` | 译文平行轨：`/api/translations`（整版应用、撤销、过期检测）。 |
| `core/ai_proposal.py` | 提案契约的**唯一实现**：源指纹 digest、结构校验、`apply_polish()`。前端不得自己算 digest 或另写校验。 |
| `core/ai_client.py` | OpenAI 兼容的纯 urllib 客户端（不引 SDK），只管传输与 JSON 解析。 |
| `core/ai_polish.py` / `core/ai_translate.py` | 分块、提示词、结构重问与结果组装；取消只能落在分块之间。 |
| `core/i18n.py` | 双语 cue 的唯一构造（`bilingual_cues()`），导出与显示都调它。 |
| `core/transcribe.py` | 共用字幕数据结构/格式、时间解析、FFmpeg 音频抽取、Anime Whisper、Silero VAD 和启发式分句。 |
| `core/qwen_ctc.py` | Qwen3-ASR 模型推理、CTC 对齐头、日语断句动态规划（含 P1-1 词边界成本）、字幕劈词修复、编码特征复用。 |
| `core/audio_cache.py` | 16k wav 解码缓存（`cache_key` / `ensure_wav` / `peaks` / `prune`），转写与核对台波形共用一次解码；`KIKUSUB_AUDIO_CACHE=0` 关闭。partial 文件名带 pid + 随机后缀，支持取消。 |
| `core/jobs.py` | 进程内单槽任务注册表与 `CancelToken`：同一时间只允许一个重任务，取消只能由发起它的会话发出。AI 润色/翻译也走这里，与转写共用单槽。 |
| `core/procutil.py` | 可取消、带超时的子进程执行器（Popen + 读线程 + terminate/kill），ffmpeg/ffprobe 统一走这里。 |
| `core/logging_setup.py` | 日志落盘（`outputs/logs/kikusub.log`，5MB × 3 轮转）、14 天 / 64MB 保留清理与后台线程 excepthook。 |
| `tests/` | pytest 回归；重依赖用例在轻量 CI 中自动 skip。 |
| `tools/eval/` | 纯标准库 SRT 评测台（CER/块准确率/劈词计数）；改断句或 VAD 参数前后必须跑同一区间。 |
| `tools/pack/` | `build_sidecar.sh`（PyInstaller）+ `build_app.sh`（手工装配 .app）；改 Python 后必须先重打 sidecar。 |
| `core/presets.py` | `presets.json` 的校验、向后兼容读取和原子写入。 |
| `core/engines.py` | **引擎注册表**（无 torch 依赖）：名称、语种、用途、HF 仓库、体积、必需文件、安装检测。设置页的引擎卡片与工具栏过滤都读这张表。新增引擎在这里加一条，再到 `core/pipeline.py` 注册推理对象并提供 `ensure_model(progress_cb)`。 |
| `core/settings.py` | 应用级设置（启用的引擎、自动压制代理、AI 的 base_url / model / 分块参数），原子写 `settings.json`（`KIKUSUB_SETTINGS_PATH` 可覆盖）。**AI Key 不在其中**。 |
| `server/routes_settings.py` | 设置/引擎/诊断接口：`/api/settings`、`/api/engines/*`、`/api/log`、`/api/diagnostics`。 |
| `presets.json` | 用户持久化的命名调参预设；属于运行数据，修改其 schema 时要兼容旧内容。 |
| `models/` | 模型缓存。`anime-whisper/` 与 `qwen3-asr-ja-anime/` 均可能很大，不应作为普通源码改动。 |
| `outputs/` | 生成的字幕样例和运行产物。 |
| `README.md` / `README_EN.md` / `CONTRIBUTING.md` | 面向用户与贡献者的说明；改变用户可见行为时同步更新。 |

## 3. 核对工作台与内核设计原则

> 旧 Gradio 界面（`app.py` / `static/`）已从仓库移除，源码归档在 Git 标签 `v0.9-gradio` 与本地独立目录 `~/Downloads/kikusub_gardio`。本章只保留当前桌面端 + 共用内核仍然有效的约束；桌面端核对台从 §3.4 开始。

- **断句改动必须有数字（2026-11）**：改 `qwen_ctc._break_costs` / `partition_cues` / VAD 参数前后，必须用 `python tools/eval/score_srt.py --reference ... --hypothesis ... --from ... --to ...` 跑同一区间，同时看 CER、`particle_start_cues`、`aux_start_cues`、最长条与 >4.3s 条数。禁止只凭个别样例“看起来更好”就改词边界；减少劈词与块均准确率之间存在已知取舍。
- **并发与取消（2026-11 加固）**：转写/局部转写必须通过 `jobs.JobRegistry` 单槽占用，**禁止**再引入模块级 `CANCEL_EVENT`。取消令牌必须归属于发起任务的会话；别的窗口点「打断」只能收到“本会话没有任务”的提示，绝不能误伤正在跑的任务。客户端断开只发取消信号，槽位由真正停止工作的 worker 在 `finally` 中释放，避免“界面已返回、模型还在跑”时被新任务覆盖。所有 `subprocess` 外部命令必须走 `procutil.run_command`（超时/取消/terminate），代理成片先写 `*.part.mp4` 再原子 rename。
- **覆盖审计（2026-11 新增）**：主 VAD 的漏检（VAD 没切到、Whisper 根本没收到）不会产生 `missed` 记录，所以 `core/coverage.py` 必须保持一条**只读旁路**：按字幕切空白间隙 → 20ms/40ms RMS 包络 → 每个间隙取最长候选 → 局部峰值归一化后跑一次 Silero 只取概率 → `last_coverage_spans` 交给 `build_audit_items(coverage_spans=...)`。它**不回写**字幕、不改主 VAD 参数、不改 `load_wav_mono` 的电平；`find_coverage_spans()` 失败必须吞掉，不能影响转写。质检对用户只暴露两个组：`coverage` → `miss`（漏检，默认置顶），`missed/dropped/suspect` → `low`（低置信，默认折叠）；`_audit_coverage()` 仍然只表达引擎能力，不要把 `coverage` 塞进去。默认参数（8s 空白 / 1.5s 候选 / 65 分位 / 局部 VAD 均值 0.20）是在 2026-11-10 的 14 分钟样本上调的；改阈值前先用同一段音频跑 `find_coverage_spans()` 看召回与条数。
- **补录区间必须夹在空白边界内（2026-11 修复）**：`QaPanel.fill()` / `ReviewView` 的 `padEnd:0.3` 会把覆盖项尾部的下一句开头也切进来；`transcribeRange()` 现在接受 `clampStart/clampEnd`，调用方必须传 `item.gap_start/gap_end`。`server/jobs.py` 的 `replace_range` 也不能再按「cue.start < 区间尾就删」处理：只删除重叠 ≥50% 或中点落入区间的 cue，边缘被切到 0.2s 的邻句必须保留。回归用例在 `tests/test_server_jobs_range.py`。

### 3.4 桌面版核对台（`desktop/renderer/src/views/ReviewView.svelte`）

- **单击 vs 框选**：`pointerdown` 先进入 `pending`，移动超过 `CLICK_SLOP=4px` 才升级为
  `select`。禁止恢复「按下即建选区」：全局视图下 1px 就是好几秒，用户报障过“单击跳转被
  识别成框选”。
- **擦洗区**：顶部 `RULER_H=17px` 和播放头两侧 `PLAYHEAD_GRAB=8px` 是专属 scrub；
  `beginScrub / setScrub / endScrub` 负责暂停、16ms 节流写 `video.currentTime`、松手
  恢复原播放状态。视频进度条复用同一套（禁止再写独立的 click-to-seek），三者共同保证
  拖动时能逐帧预览。
- **底部字幕轨道**：`LANE_H=17px`，`cueBlockAt()` 按 `(start, end)` 把同区间的双语/
  三语行聚合成一块。拖块体整体平移、拖两端单独改起止；提交走 `applyCueTimes()`
  （整表替换，服务端只压一次历史，⌘Z 一次能退回整块）。
- **同步**：`cueIndex` 变化时（点波形、拖播放头、播放中）表格 `revealRow()` 且
  `play.selected` 跟到该块；用户点的行若已在当前块内则保留其选择，不能被“块内第一条”
  规则抢回去。
- **核对期保存**：右侧检查器底部常驻 `save-dock`。`暂存进度` 调
  `POST /api/cues/draft`，只写运行数据目录的 `{stem}.autosave_draft.srt`（与旧 Gradio
  同名共用），不覆盖导出交付文件；编辑成功后由 `scheduleDraftSave()` 0.9s 防抖自动写一次。
  `导出` 调 `POST /api/cues/export` 写 `settings.json` 的 `export_dir`。两者语义不同：
  草稿是防丢备份，导出是交付文件；即使没有任务报告（重开应用后手动导入字幕）也必须能导出。
- **跟随**：状态持久化在 `localStorage['kikusub.follow']`；**只有按钮能改它**，缩放/平移、
  点击字幕、表格、画面、质检定位一律不得改——这曾经被报成「缩放时间线/点一下字幕
  跟随就被取消」。暂停时跳转依靠 `revealPlayhead()` 平移视窗让播放头保持可见，
  不应依赖“先敲空格开始播放”。
- 字幕轨道配色走 `app.css` 的 `--cue-lane / --cue-wash / --cue-block / --cue-block-hover /
  --cue-block-active / --cue-edge`，亮暗两套；禁止退回 `--separator` 那种 5% 灰。
- **侧栏（红绿灯列）必须跟着应用主题走**：窗口是 `hiddenInset + vibrancy:'sidebar'`，
  原生毛玻璃的明暗由系统外观决定，不受 `<html data-theme>` 控制。渲染层切主题时要
  通过 preload 的 `setTheme()` 通知主进程 `nativeTheme.themeSource`；同时深色
  `--bg-sidebar` 必须足够不透明（当前 `rgba(30,30,32,.92)`），否则浅色系统下会透成灰白。
  `main.ts` 在挂载前先应用 localStorage 里的主题，避免冷启动闪一下浅色。
- 修改后必须 `cd desktop && npm run build`，并至少实际验证：单击跳转、抖动单击不建选区、
  刻度/播放头/进度条拖动、字幕块整体与两端拖动、⌘Z 一次回退整块、播放头同步表格与检查器。

### 3.4.1 导出目录与转写自动保存（2026-11 新增）

- 字幕交付文件的唯一目标是 `settings.json` 的 `export_dir`；空值才回退到
  `OUTPUT_DIR`（打包后 `~/Library/Application Support/KikuSub/outputs`）。
  新增写字幕的路径必须走 `core.settings.resolve_export_dir()`，不要在
  `core/pipeline.py` 或路由里硬编码 `OUTPUT_DIR`（会绕过设置页）。
- 转写页的整片与区间任务都经 `server/jobs.py` 调 `core.pipeline.run_transcription`，
  完成即落盘；`TranscribeRequest.export_dir` 是服务层把设置传下去的唯一通道。
  漏句清单 / 质检 JSON / 代理缓存仍属于运行数据，留在 `output_dir`。
- 桌面端的导入页、转写页与核对台都有「导入字幕…」，原生对话框的 `defaultPath` 就是导出目录；
  新增入口时继续走 `window.kikusub.pickSubtitle()`，不要让用户自己逐层找路径。

## 3.5 日志与诊断（2026-11 新增）

- **服务层必须在 `server/__main__.py` 里调 `core.logging_setup.setup_logging()`**：漏掉这一步会导致 `outputs/logs/kikusub.log` 永远为空（曾经就是这样）。日志目录是 `config.output_dir/logs`。
- 日志分三层：sidecar 的 `kikusub.log`、Electron 主进程的 `main.log`、渲染端通过 `POST /api/log` 写入的 `kikusub.renderer`。排查用户问题优先看 `~/Library/Application Support/KikuSub/outputs/logs/`。
- **不要把 token、cookie、完整音视频内容写进日志**；文件路径与转写片段文本可以记。
- 请求中间件会对 `/api/*` 记录方法/路径/状态/耗时/`X-Request-Id`/会话 id；波峰与 `/media/*` 降为 DEBUG，避免刷屏。
- 渲染端 API 失败会自动带 `X-Request-Id` 记日志；新增「用户关键动作」时同时 `logEvent(...)`，否则用户报障时无法还原操作序列。
- 局部转写的 `write_audit` 语义：`replace_range`（核对台单句/选区修正）**不写**整片质检队列；转写页的整片/区间任务都要写，否则报告与质检面板数字不一致。

### 3.5.1 应用图标（2026-11 修复）

- `desktop/build/icon.icns` 必须由 `docs/logo.svg` 重新渲染后打包，不能用
  `docs/logo-1024.png` 直接转 icns——那张是白底 flattened PNG，四角不透明，
  在深色 Finder 下会露出白角（用户报过「访达里图标异常、Dock 正常」）。
  `tools/pack/make_icon.swift` 负责按 macOS 全部尺寸渲染透明圆角图标，
  `build_app.sh` 的 0/7 步会先执行它。
- 装配后删除 Electron 自带的 `Contents/Resources/electron.icns`，避免图标缓存
  误用旧图；`build_app.sh` 末尾会 `touch` + `lsregister -f`。Finder 缓存仍顽固时
  运行 `bash tools/pack/refresh_finder_icon.sh --restart`。

## 3.6 桌面启动、设置与退出清理（2026-11 新增）

### 首次启动与模型目录

- 首次启动由主进程判定（`shouldFirstRun()`，`desktop/main/main.cjs`）：没有
  `preferences.json`、没有 `KIKUSUB_MODELS_DIR`、且默认/已有模型目录里没有权重时才弹
  选择模型目录的向导。旧用户目录里已有模型则**跳过**，保持原样。
- 向导完成前**不得启动 sidecar**：模型目录必须作为 `KIKUSUB_MODELS_DIR` 在 spawn 时传入，
  Python 的 `core.paths.MODELS_DIR` 是 import 期常量，运行中改不了。
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

### 快捷键

- **⌘,（Ctrl+,）** 打开设置。菜单 `设置…` 已绑 accelerator，渲染层 `onKey` 还要再兜一层：
  输入框聚焦时菜单快捷键可能被吃掉，且设置快捷键要在 `typing` early-return **之前**处理。

### 退出前清理（⌘Q / 关窗）

- 主进程 `before-quit` 与 `win.on('close')` 都拦截：扫描 `outputs/` 顶层的时间区间碎字幕
  与 `outputs/web_proxies/*.mp4`，通过 `quit:prompt` 交给渲染进程逐个勾选。
- **默认全部不勾选，不勾选即删除**；勾选才保留。面板没有可询问的窗口时宁可保留文件，
  绝不无人确认就删。没有候选时不弹空面板，直接退出。
- 删除前必须 `stopSidecarAndWait()`，避免和正在写的 `.part.mp4` / SRT 抢文件；删除只允许
  操作主进程捕获的候选路径，渲染进程传别的路径不得生效。
- 确认/清理期间用 `quitConfirming` 阻断重复的 `before-quit`/`close`；取消退出时必须清掉
  `quitFlow` 并让窗口继续活着。`quit:confirm` 期间 `quitting=true`，sidecar 退出后不得自动重启。
- 清理逻辑在 `desktop/main/files.cjs`，用 `node --test desktop/test/files.test.cjs` 回归；
  区间文件名正则要与 `core/subtitles.format_time_tag` 保持一致（`00m40s-00m52s`、
  `01h02m03s`、`from_`/`to_`）。`isFragmentSubtitle()` 必须排除
  `*.autosave_draft.srt` / `*.reviewed.srt` / `*.clean.srt`：核对工作稿与成片不是临时碎片，
  不能因为媒体名里带区间标记就在退出时被默认删除。

### 日志清理

- `setup_logging()` 启动时调用 `prune_logs()`：只删 `*.log.N` 轮转备份，
  **永不删正在写的 `kikusub.log` / `main.log`**；策略为 14 天或整个日志目录 64 MB。
- sidecar 每 6 小时后台清理一次；Electron 主进程启动时用 `main/files.cjs` 的
  `pruneLogs()` 执行同一策略。
- 设置页「清理旧日志」走 `POST /api/diagnostics/log/clean`，是同一份 `prune_logs()`；
  不要为了“清空”去 truncate 活动日志（会破坏 handler 的 inode/offset）。

## 3.7 AI 提案与 AI 优化台（2026-11 M1，后续里程碑会扩展）

- **时间码由结构保证，不靠提示词**：提案里只有 `{i, text}`，**没有时间戳**。应用时
  `start/end` 一律取自当前 `review_cues`，提案里的任何时间字段都不参与。任何把时间码塞进
  模型载荷、或从提案读时间码的实现都算破坏契约（见 `docs/AI优化与翻译-开发文档-2026-11.md` D-1）。
- **唯一实现**：`core/ai_proposal.py` 负责 digest、结构校验与 `apply_polish()`。
  前端**不得**自己算 digest，也**不得**另写一份校验；`/api/ai/apply` 与将来的生成任务
  必须调同一个 `validate_proposal()`。
- **应用 = 整批一次历史**：走一次 `Session.replace_review()`，`⌘Z` 一次全退回。
  **禁止**逐条改（27 处改动压 27 次栈会让人没法用）。
- **失败不动字幕**：digest 不符 → 409，结构不符 → 422，`session.review_cues` 一个字节都不改。
- **文件位置**：`{output_dir}/{stem}.ai-polish.json`、`{stem}.{lang}.ai-translate.json`。
  外部 agent 带来的提案走 `POST /api/ai/proposal/import`（校验通过才落到标准位置），
  原生对话框是 `window.kikusub.pickProposal()` —— 不要复用 `pickSubtitle`（只认 srt/vtt）。
- **`AiView` 只认提案**，不关心是 in-app 还是外部 skill 生成的：这是"一个提案层、两个入口"的
  全部意义（D-2）。改界面时不要为某个来源开分支。
- 验收脚本：`python tools/make_fake_proposal.py <srt>` 造一份假提案；
  用例在 `tests/test_ai_proposal.py` / `tests/test_server_ai.py`。
- 译文**不写进** `review_cues.text`（D-3），它将来是平行轨；`/api/ai/apply` 只处理
  `kind=polish`，翻译提案会被 422 拒绝。

### 3.7.1 调用模型（2026-11 M2）

- 客户端在 `core/ai_client.py`：**纯 urllib，不引 openai SDK**（sidecar 是打包产物，
  少一个依赖少一份体积）。`chat_json()` 只管传输与 JSON 解析，分块在 `core/ai_polish.py`。
- **密钥只走请求头 `X-AI-Key`**：渲染进程从 `window.kikusub.aiKey.get()`（主进程解出
  明文）取出来，随请求发一次。服务层**不读不写不记**；`settings.json` 里没有也不要加
  `ai_api_key` 字段。日志只允许 host / model / 状态码 / 耗时。
- **密钥存储不要用 `safeStorage`**（2026-11-11 定稿，见开发文档 §11.4）：keychain 条目的
  ACL 认的是代码签名要求，而本项目以 DMG 分发、ad-hoc 签名，**每次发版 cdhash 都变，
  用户升级后 Key 全部失效**，且没有 Developer ID 无从修复。现在用
  `desktop/main/aikey.cjs`：32 字节主密钥存 `{dataDir}/.ai-key`（0600），
  `preferences.json` 里只放 `aik1:` 密文。
  改这块时守住三条：**0600 权限**、**旧 `v10` blob 要能识别并报 `broken`**、
  **绝不把明文写进任何文件或日志**。用例：`node --test desktop/test/aikey.test.cjs`。
- 只有将来改用 **Developer ID 签名 + 公证** 发布时，才值得切回 `safeStorage`；
  切之前先读开发文档 §11.4 的三方案对比。
- 生成走 `JobManager.start_ai_polish()`（与转写共用单槽），进度复用 `/ws/jobs/{id}`。
  `ai_client` 里带 key 的 `AiConfig` **只能作为线程参数**，绝不能塞进 `JobRecord`。
- 结构不合规（缺条 / 非 JSON）只**重问一次**（附 `STRICT_HINT`）；仍失败就整份放弃，
  绝不产出"半份提案"。改动率超 40% 会出现在 `warnings` 里，界面据此提示。
- 取消只能落在**分块之间**（urllib 阻塞不可中断），这是已知限制，不要假装能秒停。

### 3.7.2 译文平行轨（2026-11 M3）

- 译文**永远不写进** `review_cues.text`（D-3）。它存在 `Session.translations[lang]`，
  与 `review_cues` **逐条对齐**，并带一份 `base`（生成时的原文快照）用来算过期。
- 写轨只有两条路：`POST /api/translations`（应用一整版）与草稿恢复。两者都**只动轨**，
  不进 `review_cues` 的撤销栈；译文有自己的 `translation_undo[lang]`（上限 20 版）。
- 条数必须相等、`i` 必须连续、digest 必须匹配；**不通过就整批拒绝**，
  绝不落一份对不齐的轨（`test_server_translations.py`）。
- 双语 = **一条 cue 两行**（D-4），构造只有一份实现：`core/i18n.bilingual_cues()`。
  导出与显示都调它，禁止各写一遍。
- 三态导出：`POST /api/cues/export` 的 `track`（`source|target|both`）+ `lang`；
  文件名后缀 `.lang` / `.bilingual`。**新增后缀必须同步 `desktop/main/files.cjs`
  的 `TRANSLATION_SUFFIX`**，否则退出清理会把交付物当碎片默认删除。
- 核对台三态与双语行高：`ReviewView` 的行高是 `$derived(app.track === 'both' ? ROW_H*2 : ROW_H)`，
  **固定双行高**；禁止改用自动测量（会和虚拟滚动的绝对定位打架）。
- 暂存必须连译文一起写（`{stem}.autosave_draft.i18n.json`）；恢复时条数不符的轨直接丢弃。
### 3.7.3 Agent 技能（2026-11 M4）

- 技能包在 `desktop/resources/skill/kikusub-subtitle/`，装到 `~/.agents/skills/`（DSH 会扫描的
  用户级技能根）。`KIKUSUB_SKILL_ROOT` 可覆盖根目录，测试用它。
- **不要把目标根改回 `~/.claude/skills/`**：那是 Claude Code 的根，DSH 的 `skill-filesystem`
  只扫 `.dsh/skills` / `.agents/skills`（项目级）与 `~/.dsh/skills` / `~/.agents/skills`（用户级）。
  装错根的表现是目录都在、`SKILL.md` 也合法，但 `/` 菜单里没有这个技能。根目录的唯一实现是
  `desktop/main/skill.cjs` 的 `defaultTargetDir()`，`main.cjs` 只负责传 home。
- `SKILL.md` 里读 `references/paths.json` 优先用宿主给的技能目录，兜底只列 `.agents` / `.dsh`
  两处；不要再往文档和代码里加 `~/.claude`（本项目不面向 Claude Code）。
- **技能不碰字幕文件**：只读 SRT、写 `{output_dir}/{stem}.ai-polish.json` 或
  `{stem}.{lang}.ai-translate.json`。任何让 agent 直接改 SRT 的做法都是回退。
- `references/digest.md` 里有一个固定自测向量，`desktop/test/skill.test.cjs` 会校验它——
  改算法就同时改文档和用例，否则测试红。
- 安装器 `desktop/main/skill.cjs` 只用 fs（不引 electron），因此能被 `node --test` 覆盖；
  安装是"先删再拷"，`references/paths.json` 由渲染层传入的真实目录覆盖写入。
- 目标目录由**主进程**决定，不接受渲染层传进来的路径。

- **手动粘贴通道（2026-11 补充）**：`GET /api/ai/prompt` 组提示词（里面**带** SRT 与时间戳，
  为的是让模型逐条对齐），`POST /api/ai/from-srt` 解析回复时**只按顺序取文本，
  序号与时间戳全部丢弃**，时间轴仍用我们自己的 cue。条数不符整批拒绝（422）。
  改这块时不要把解析结果里的时间戳写回字幕——那会直接破坏 D-1。

## 4. 转录任务详报面板（Gradio 版，已归档）

> 本节描述的是已移出仓库的 `app.py` 界面；桌面端对应实现见 `desktop/renderer/src/views/` 与 `server/routes_report.py`。以下内容仅作历史参考。

- 「📊 全片转录原始结果、表格与任务详报」下的「转录任务报告」**必须**保持为 `gr.HTML` + `render_report_panel()`（`app.py` 中 `build_transcription_report` 之后），**不要改回 `gr.Textbox`**：Gradio 6 的 Textbox 会按内容自动增高并在 `overflow:hidden` / `overflow:scroll` 之间切换，长报告反复更新后会把文本框卡在裁切状态、无法上下滑动。
- 滚动能力由面板自带的 `.report-body { max-height: min(58vh, 520px); overflow-y: auto }` 提供，任何改版都不得移除该容器或改成依赖组件自身高度的方案。
- 详报的**纯文本原稿**藏在面板内 `<pre id="report-raw-text" class="report-raw-src">` 里，「📋 一键复制」按钮的 JS 直接读它的 `textContent`（事件 `inputs=None`），因此复制内容与旧版完全一致；改渲染逻辑时必须同步保留该 `<pre>`。
- 指标胶囊复用顶部设备胶囊的 `.device-chip`（`chip-label` 灰字 + `chip-value` 等宽粗体），面板底色 `#f8fafc` + 3px `#a5b4fc` 左边框，与 `.progress-status-box` 同源；`status` Markdown 也挂 `progress-status-box`，保证「界面顶部 / 报告区」两处视觉一致。
- 该折叠面板默认 `open=True`（用户要求首屏即可看到转写结果与详报）。
- 【幻觉门控】/【幻觉复核】的逐段明细必须留在报告里（用户明确要求"不要在终端刷屏、要能复制"）：数据源是 `AnimeWhisperEngine.last_segment_stats["hallucination_spans"]`（字段 `start/end/dur/text/rule/verdict/peak`，`verdict` 取 `dropped|suspect`），由 `app._hallucination_rows()` 渲染，明细最多列 `HALLUCINATION_SPAN_LIMIT` 条。`transcribe.py` 里这两类段的日志只允许 `log.debug`，不要再升回 `log.info`。

## 5. 质检待核队列（Gradio 版，已归档）

> 本节描述的 `static/qa_panel.*` 已随旧界面移出仓库；桌面端对应实现见 `desktop/renderer/src/components/QaPanel.svelte`。以下内容仅作历史参考（其中覆盖审计与补录边界的通用约束已上移到 §3）。

报告里的三类清单只是归档；用户实际逐条核对用的是 `static/qa_panel.html` + `static/qa_panel.js` 的浮动队列。改这块时必须保持以下契约：

- **单一数据源**：队列 JSON 只走隐藏 Textbox `#qa-payload`（字段 `items/statuses/counts/latest_cue_count/hidden_missed/revision/last_action`，以及运行态元数据 `phase/engine/coverage/scanned/transcribed_at`）。前端所有动作写入 `#qa-cmd` 后点击 `#btn-hidden-qa`，由 `qa_apply_action()` 统一处理；不要为每个按钮注册 Gradio 事件。元数据在处理动作里必须原样带回（`qa_apply_action()` 已透传），否则入口会退回 idle。
- **入口与内容解耦（2026-11 修订）**：`data-mode="hidden"` 只允许出现在「没有媒体且 `phase=idle`」时。`phase` 取 `idle|running|done`：媒体载入后 `idle` 就要显示「质检 · 待转写」浮标；`done` 即使 `items` 为空也必须保留「✅ 质检完成 · 0 处待核」，禁止再用 `items.length ? ... : 'hidden'` 把功能整体隐藏。0 条是「检查完成」的正结果，不是「功能不存在」。
- **空态必须自解释**：`items` 为 0 时面板不能空白。`renderEmpty()` 要同时给出「本次检查了多少切片/字幕」（`scanned`）、三类检查各自的「已检查 / 本引擎不启用」状态（`coverage`）和入口常驻说明；`#qa-fab-text` 在 `phase=done` 且 0 条时固定为「质检完成 · 0 处待核」。空态面板只在**用户第一次遇到**（`localStorage` 的 `kikusub.qa.emptyHintShown.v1`）且 `transcribed_at` 晚于本次页面加载时自动展开一次；刷新页面恢复旧 payload、之后的干净运行都只更新绿色浮标，不得反复弹窗。
- **引擎能力必须如实声明**：`coverage.dropped/suspect` 只在 Anime Whisper 下为 true；Qwen 只覆盖 `missed`。禁止为了“看起来功能齐全”给 Qwen 伪造 dropped/suspect 条目，也禁止把「不启用」写成「未发现」——`_audit_coverage()` 是唯一真源，报告与空态都读它。
- **事件闭包必须是动态的**：`qa_payload.change` 可能在页面加载时先发一次空 payload。所有点击回调只能从 `window.__qaRuntime.items/data` 取最新数据，禁止在首次绑定时把 `items` 闭包进回调（否则真实队列到达后，按钮仍认为“没有待核项”，面板会被空事件隐藏）。
- **三类语义不可混淆**：`missed`（有声音但识别为空）只能“补录/不是台词”；`dropped`（识别出过文字但复核为空被删）只能“恢复原句/重新识别/确认删除”；`suspect`（保留但短/低密度）只能“定位编辑/保留/删除”。新增动作要同时更新 `qa_apply_action()` 的 `last_action.message` 与前端 `resolutions` 文案。
- **进度只在同一次运行内恢复**：`write_audit_payload()` 在每次动作后原子写 `outputs/{stem}.qa.json`；`AUDIT_SESSION_ID` 在进程启动时生成并写入 payload，`load_audit_payload()` 遇到旧进程的 session 一律返回空队列。因此刷新页面/重开媒体可继续，**重启应用后默认清空**；新一轮转写重置状态也是预期行为。
- **不遮住关键操作**：面板默认“钉住”在右下角（`position: fixed`），但必须提供「收起为浮标」「取消钉住（内嵌）」；固定面板的 z-index 要低于 Gradio 弹窗。`focusRange()` 负责跳转+框选+播到段尾自动停，队列 JS 不直接改 reviewer 内部状态。
- **补录链路**：前端把区间写进 `#hidden-sync-start/end`，点 `#btn-hidden-bridge-transcribe`；成功后在转写事件的 `.then(js=...)` 调用 `window.__qaPanel.afterTranscribe(status)`，由它把该条标成 `done/filled`。失败或空结果不得标记完成。
- **「保留」不是纯状态**：`qa_apply_action()` 对 `suspect + kept` 必须调用 `_audit_ensure_item_cues()` 幂等补齐核对台缺失的 cue（按重叠/同文本去重，避免用户改过文字后重复插），并且**显式返回 `review_cues_table` 与 `review_payload`**（不能用 `gr.update()`），否则会出现“导出 SRT 里有这句、核对台表格里没有”的显示不同步。前端在 `keep` 前也必须 `requireBaseline()`，防止只往空核对台里补一条。

- **覆盖审计（2026-11 新增）**：主 VAD 的漏检（VAD 没切到、Whisper 根本没收到）不会产生 `missed` 记录，所以 `core/coverage.py` 必须保持一条**只读旁路**：按字幕切空白间隙 → 20ms/40ms RMS 包络 → 每个间隙取最长候选 → 局部峰值归一化后跑一次 Silero 只取概率 → `last_coverage_spans` 交给 `build_audit_items(coverage_spans=...)`。它**不回写**字幕、不改主 VAD 参数、不改 `load_wav_mono` 的电平；`find_coverage_spans()` 失败必须吞掉，不能影响转写。质检对用户只暴露两个组：`coverage` → `miss`（漏检，默认置顶），`missed/dropped/suspect` → `low`（低置信，默认折叠）；`_audit_coverage()` 仍然只表达引擎能力，不要把 `coverage` 塞进去。默认参数（8s 空白 / 1.5s 候选 / 65 分位 / 局部 VAD 均值 0.20）是在 2026-11-10 的 14 分钟样本上调的；改阈值前先用同一段音频跑 `find_coverage_spans()` 看召回与条数。

- **补录区间必须夹在空白边界内（2026-11 修复）**：`QaPanel.fill()` 的 `padEnd:0.3` 会把覆盖项尾部的下一句开头也切进来；`transcribeRange()` 现在接受 `clampStart/clampEnd`，调用方必须传 `item.gap_start/gap_end`。`server/jobs.py` 的 `replace_range` 也不能再按「cue.start < 区间尾就删」处理：只删除重叠 ≥50% 或中点落入区间的 cue，边缘被切到 0.2s 的邻句必须保留。回归用例在 `tests/test_server_jobs_range.py`。
