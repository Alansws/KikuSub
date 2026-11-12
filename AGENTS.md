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
| `core/tts/` | 本地 TTS 子系统：引擎抽象（`base.py`）、macOS `say` 兜底（`mac_say.py`）、OmniVoice 零样本克隆（`clone_engine.py`）、音色仓库（`voice_manager.py`）、懒加载/空闲卸载（`manager.py`）、权重下载（`model_store.py`）。**不 import fastapi / gradio**；torch / omnivoice 只在 `load()` 里延迟导入。 |
| `server/routes_tts.py` | 本地日语 TTS：音色列表、合成缓存、从视频切片建音色、上传/重命名/删除、模型下载、`/media/tts/*` 音频流。 |
| `core/ai_proposal.py` | 提案契约的**唯一实现**：源指纹 digest、结构校验、`apply_polish()`。前端不得自己算 digest 或另写校验。 |
| `core/ai_client.py` | OpenAI 兼容的纯 urllib 客户端（不引 SDK），只管传输与 JSON 解析。 |
| `core/ai_polish.py` / `core/ai_translate.py` | 分块、提示词、结构重问与结果组装；取消只能落在分块之间。 |
| `core/i18n.py` | 双语排版的唯一构造：`bilingual_cues()`（一条两行，烧录/叠加层）与 `bilingual_entries()`（每语种一条，字幕交付文件）。 |
| `core/transcribe.py` | 共用字幕数据结构/格式、时间解析、FFmpeg 音频抽取、Anime Whisper、Silero VAD 和启发式分句。 |
| `core/qwen_ctc.py` | Qwen3-ASR 模型推理、CTC 对齐头、日语断句动态规划（含 P1-1 词边界成本）、字幕劈词修复、编码特征复用。 |
| `core/audio_cache.py` | 16k wav 解码缓存（`cache_key` / `ensure_wav` / `peaks` / `prune`），转写与核对台波形共用一次解码；`KIKUSUB_AUDIO_CACHE=0` 关闭。partial 文件名带 pid + 随机后缀，支持取消。 |
| `core/jobs.py` | 进程内单槽任务注册表与 `CancelToken`：同一时间只允许一个重任务，取消只能由发起它的会话发出。AI 润色/翻译也走这里，与转写共用单槽。 |
| `core/procutil.py` | 可取消、带超时的子进程执行器（Popen + 读线程 + terminate/kill），ffmpeg/ffprobe 统一走这里。 |
| `core/logging_setup.py` | 日志落盘（`outputs/logs/kikusub.log`，5MB × 3 轮转）、14 天 / 64MB 保留清理与后台线程 excepthook。 |
| `tests/` | pytest 回归；重依赖用例在轻量 CI 中自动 skip。 |
| `tools/eval/` | 纯标准库 SRT 评测台（CER/块准确率/劈词计数）；改断句或 VAD 参数前后必须跑同一区间。 |
| `tools/pack/` | `build_sidecar.sh`（PyInstaller）+ `build_app.sh`（手工装配 .app）+ `rebuild.sh`（一条命令：按需重打 sidecar → 构建渲染层 → 装配 → 打开）。改 Python 后必须先重打 sidecar。 |
| `core/presets.py` | `presets.json` 的校验、向后兼容读取和原子写入。 |
| `core/engines.py` | **引擎注册表**（无 torch 依赖）：名称、语种、用途、HF 仓库、体积、必需文件、安装检测。设置页的引擎卡片与工具栏过滤都读这张表。新增引擎在这里加一条，再到 `core/pipeline.py` 注册推理对象并提供 `ensure_model(progress_cb)`。 |
| `core/settings.py` | 应用级设置（启用的引擎、自动压制代理、AI 的 base_url / model / 分块参数），原子写 `settings.json`（`KIKUSUB_SETTINGS_PATH` 可覆盖）。**AI Key 不在其中**。 |
| `server/routes_settings.py` | 设置/引擎/诊断接口：`/api/settings`、`/api/engines/*`、`/api/log`、`/api/diagnostics`、`/api/diagnostics/log/clear`。 |
| `core/prompts.py` | 可编辑提示词模板库：默认模板、`{{SRT}}` / `{{LANG}}` 渲染、`prompts.json` 原子读写。 |
| `server/routes_prompts.py` | 提示词模板接口：`/api/prompts`（读取/新建/改/选中/删除/恢复内置）。 |
| `core/video_export.py` | 成片导出：探测、分辨率/码率规划、Pillow 字幕精灵 + ffmpeg crop/overlay 硬字幕、软字幕/仅封装。 |
| `server/routes_export.py` | 成片导出接口：`/api/export/options`、`/api/export/plan`、`/api/export`。 |
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
- **核对表来源与报告解耦（2026-11 修复）**：`Session.review_source`（`transcription` /
  `import` / `draft`）随字幕快照一起返回，并参与历史回滚；导入字幕或恢复草稿后，
  右侧检查器不得再展示上一次转写的质检速览 / 生效参数 / 输出，`GET /api/qa` 返回
  `detached: true` 的空态且 `POST /api/qa/action` 返回 409——旧 item 与当前字幕已经
  对不上，继续操作会删错句、补错区间。整片/追加转写会重写来源；单句/选区重转保留来源，
  因为它不重写质检队列。
- **跟随**：状态持久化在 `localStorage['kikusub.follow']`；**只有按钮能改它**，缩放/平移、
  点击字幕、表格、画面、质检定位一律不得改——这曾经被报成「缩放时间线/点一下字幕
  跟随就被取消」。暂停时跳转依靠 `revealPlayhead()` 平移视窗让播放头保持可见，
  不应依赖“先敲空格开始播放”。
- 字幕轨道配色走 `app.css` 的 `--cue-lane / --cue-wash / --cue-block / --cue-block-hover /
  --cue-block-active / --cue-edge`，亮暗两套；禁止退回 `--separator` 那种 5% 灰。
- **主题是「令牌 + 注册表」，不是组件分支**：外观 id 只有 `light` / `dark`（青空，浅 + 深）
  与 `mincho`（明朝墨，单色），落在 `<html data-theme>` 上；名字、所属主题与 scheme 的映射在
  `renderer/src/lib/themes.ts`，切换入口是设置页「主题 / 明暗」。持久化走
  `localStorage['kikusub.theme']`，另用 `kikusub.mode` 记住青空上次的明暗（切回青空时恢复）。
  **加主题 = `app.css` 写一块 `html[data-theme='<id>']` 覆盖 + 注册表加一条**，组件里不要再写
  `data-theme` 判断。字幕字体是 `--font-cue`（只有主题换它：明朝墨用明朝，译文轨仍走
  `--font-sans`），主操作实心色是 `--btn-primary-bg`、开关/勾选/滑杆的「开」色是
  `--control-on`，两者当前都等于 accent（**主题色统一**：按钮、滑杆、开关都跟着主题走，
  不要再给某套主题单独换成墨色——产品上已经否过一次）。
- **侧栏（红绿灯列）必须跟着应用主题走**：窗口是 `hiddenInset + vibrancy:'sidebar'`，
  原生毛玻璃的明暗由系统外观决定，不受 `<html data-theme>` 控制。渲染层切主题时要
  通过 preload 的 `setTheme()` 通知主进程 `nativeTheme.themeSource`；主进程只认 scheme
  （`dark` → dark，其余 → light），同时把外观 id 写进 `preferences.json` 供冷启动首帧使用。
  侧栏 `--bg-sidebar` 必须足够不透明（深色当前 `rgba(10,12,16,.92)`），否则浅色系统下会透成灰白。
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
- **最近打开封面**走 `core/thumbnails.py` + `GET /api/media/thumb?path=…`：先取真正的首帧，
  用 Pillow 判断是否纯黑/接近黑场；是黑场才用 FFmpeg `thumbnail` 在前 60 秒里挑代表帧。
  结果按「路径 + mtime + 大小」缓存在 `{output_dir}/thumbnails/`，并限制 2 个并发 ffmpeg。
  不要为了封面解码整部片，也不要在前端用 canvas 抓首帧（MKV/HEVC 会黑屏）。

### 3.4.2 历史、TTS、查找替换与手动补字幕（2026-11 新增）

- **20 步可回溯历史**：`Session.history` 是「起始状态 + 每一步操作后的完整快照」的时间线，
  `history_cursor` 指向当前状态。**不要再退回 undo_stack/redo_stack 双栈**：界面要列出
  「这一步做了什么」并允许点任意一步跳过去，双栈没有中间态可展示。
  - 所有编辑都必须带操作说明：`replace_review(cues, label=...)`、`update_cue(..., label=...)`；
    新增写字幕的路径时也要传 label，否则历史里会出现「编辑字幕」这种无信息条目。
  - 上限是 **20 步操作**（`HISTORY_LIMIT`，另加一条起始状态）；超出后从最旧的操作开始丢。
  - `POST /api/cues/history/jump` 只移动 cursor、不产生新历史；跳转后后面的步骤仍可重做。
  - 没有实际变化的 PATCH 不压历史（`routes_cues.patch_cue` 已做相等判断）。
  - 前端 `cueHistory` 下拉在工具栏撤销/重做右侧；点条目走 `jumpCueHistory()`。
- **全局撤销：字幕 + 导出设置（2026-11 扩展）**：只在核对台里撤销不够——导出页调
  字号/描边/预设/形式/分辨率这些动作以前按了没反应，用户明确报过。
  - `store.svelte.ts` 的 `uiHistory` 是**渲染层本地**时间线（起始状态 + 每步完整快照，
    同样 20 步）；导出面板的字号/字重/预设/形式/字幕轨/分辨率/码率/位置写进这里。
    **禁止**在 `ExportView.svelte` 里直接写 `exporter.size = ...` 之类：一律走
    `setExportMode / setExportTrack / setExportResolution / setExportQuality / setExportSrt /
    setExportOutDir / updateExportStyle / applyExportStylePreset / resetExportStyle`，
    否则动作不会进历史。滑杆 `input` 由 `editExportUi()` 按 1.2 秒窗口合并成一步。
  - 服务端快照带 `undo_at` / `redo_at`（`Session.undo_timestamp()` / `redo_timestamp()`）；
    `nextUndo()/nextRedo()` 取**时间更近**的一边，所以 ⌘Z 撤回的是最近一次操作，
    不会永远先撤字幕。
  - 工具栏的撤销/重做/历史按钮对所有视图可见；历史面板分「字幕编辑」「导出设置」两组，
    各自可点任意一步跳回。⌘Z 在滑杆/复选框聚焦时也要生效（`App.svelte` 的 `onKey`
    对滑杆放行、只给文本输入框保留原生逐字撤销）。
  - 换片（`openMedia`）时 `resetExportUiHistory()`：上一部的字号快照不该在新片上被 ⌘Z 抬回来。
- **聚焦倍率固定 69×**：`ReviewView` 的 `FOCUS_ZOOM=69`，工具栏「聚焦」、选区「聚焦」、
  右栏「聚焦」、质检定位全部走 `duration/69`。**禁止**再使用「当前 viewSpan / 6」这类
  会随已有缩放叠加的公式（用户报过 145× 再点一次变 415×）。
- **转写选区完成后必须定位到新句**：服务端 `first_cue_in_range()` 返回 `target_index`
  （合并后第一条与区间重叠的字幕），前端 `onJobDone` 用 `jumpToCue()` 选中并强制滚动。
  `play.selectNonce` 用于绕开 `lastRevealed` 去重；只改 `play.selected` 会遇到
  「新句下标没变 → 表格不滚」的旧 bug。**转写选区不得改视窗缩放**：不要再在这里调
  `focusRange()`（它会把波形放大，用户明确要求保持当前聚焦状态）。
- **⌘F 查找与替换（只处理原文）**：`findState` 在 store 里；`ReviewView` 负责匹配计数、
  高亮与跳转，`replaceAllInCues()` 走一次 `replaceCues`（整表提交，历史里只有一步）。
  替换文本必须用函数替换（`() => replacement`），不能把 `$&` / `$1` 当正则替换模式。
  菜单 `查找与替换…` 与渲染层快捷键都要能打开；输入框聚焦时也要生效。
- **右键手动补字幕**：音轨 `contextmenu` → 「添加字幕」→ `insertCueAt(t)` 在光标处居中插入
  **0.8 秒空字幕**（贴片尾时自动前移），随后 `play.editNonce` 让右侧检查器文本框拿到焦点。
  这是给气声 / 模型识别为空 / 只想手打「啊」的场景用的，不要试图自动跑识别。
  **右键菜单与新建音色浮层必须用 `portal` 挂到 `body`**：`.view-enter.animated` 的切页动画
  `fill-mode: both` 会让计算后的 transform 变成 identity matrix，从而成为 `position: fixed`
  的包含块；留在里面会把菜单整体推偏「侧栏 + 工具栏」的距离（用户报过「离鼠标太远」）。
- **切割 / 合并 / 多选删除（2026-11 新增）**：
  - 有字幕区域右键新增「切割字幕」：`POST /api/cues/{index}/split` 在光标时间把一句切成两段，
    **两段都保留完整原文**（用户明确要求：自动判断断点内容不可靠，先保留原句再分别删减）。
    切割点距两端至少 0.05 秒；译文轨在同一位置复制一条，双语不会错位。
  - 框选两条以上字幕后右键「合并这 N 句字幕」：`POST /api/cues/merge` 取首尾时间、文本按顺序
    直接相连（西文单词间补空格），译文轨同样拼接。只允许下标连续的多条。
  - 底部字幕轨道支持 ⌘ 单击多选（再点取消），`POST /api/cues/delete` 批量删除只压一次历史；
    ⌘ 多选块在画布上用 accent 描边。删除必须同步删掉译文轨同下标条目。
  - 服务端的插入 / 删除 / 切割 / 合并都要经 `Session` 的结构性方法调整 `translations`，
    **禁止**只改 `review_cues` 让译文轨自己错位。`HistoryState` 现在连译文轨一起快照，
    ⌘Z 才能把字幕与译文成对恢复。
- **可自定义快捷键（2026-11 新增）**：`desktop/renderer/src/lib/shortcuts.svelte.ts` 是唯一映射，
  ⌘K 打开面板录制新组合（该快捷键本身也可改）。默认值：Enter 删除当前字幕（底部多选时一起删）、
  Space 播放 / 暂停、↑↓ 上下句、⌘F 查找、⌘↩ 添加空字幕、⌘1/⌘2 在 AI 优化台切润色 / 翻译。
  **菜单里不再给播放 / 上下句 / 视图 / 查找绑固定 accelerator**：否则用户改键后旧键仍然生效，
  且 AI 优化台的 ⌘1/⌘2 会被「显示 → 导入 / 转写」抢先。视图切换仍在菜单里可点，但按键走渲染层。
  输入框内只有 allowInTyping 的动作（视图切换 / AI 标签 / 查找 / 打开面板）生效。
- **本机 TTS（2026-11 升级：系统 say → 本地零样本克隆）**：
  - 引擎分两层，都在 `core/tts/`：`mac_say.py`（零显存兜底，`say -v ?` 的日语列表）与
    `clone_engine.py`（OmniVoice，Apache-2.0，0.6B，官方建议 3–10 秒参考音频）。
    **不要**把 VoiceStudio 的 AGPL 代码搬进来；只借鉴「参考音频克隆 + 音色管理」的产品逻辑。
  - `voice_id` 是唯一命名空间：`system:Kyoko` / `clone:<8位id>`；空串由服务端选默认
    （服务端默认仍是系统语音；**用户可在设置「TTS 对照」里把默认偏好切到克隆音色**，
    存 `kikusub.ttsDefaultKind` / `kikusub.ttsDefaultVoiceId`，没有可用克隆音色时回退系统语音）。
    只有非 macOS 拿不到 `say` 时才回退到已有克隆音色。旧接口 `POST /api/tts`
    （`voice` + `rate`）保留兼容，内部换算成 `voice_id` + `speed`。
  - 音色落在 `{output_dir}/voices/<id>/`：`ref.wav`（24k/单声道/PCM16，已去首尾静音、≤10s）、
    `meta.json`（名称/参考文本/时长/来源）、`prompt.pt`（OmniVoice 声线 embedding 缓存，
    损坏或模型升级后自动重建）。**目录名用 id，不用音色名**：用户会重命名、用中文/空格。
  - 接口：`GET /api/tts/voices`（system + custom + engine/download 状态）、
    `POST /api/tts/synthesize`、`POST /api/tts /voices/extract-from-media`（用 ffmpeg 从
    当前视频精准切片 → 建音色）、`/api/tts/voices/upload`、`PATCH|DELETE /api/tts/voices/{id}`、
    `PUT .../ref-text`、`POST /api/tts/model/download`、`GET /api/tts/model/verify`
    （只读校验权重，0 字节文件也算缺失；设置页「校验 / 补齐」先走它，完整时不再弹下载确认）。
  - 缓存键 =「引擎 + voice_id + 参考音频指纹(mtime/size) + ref_text + 文本 + 速度」，
    命中直接返回文件名；`{output_dir}/tts_cache` 只留最近 240 个。音频流仍是
    `/media/tts/{file}?token=`（`<audio>` 发不了 Authorization 头）。
  - 资源：克隆模型**首次真正合成才加载**；空闲 `KIKUSUB_TTS_IDLE_SECONDS`（默认 300s）
    自动卸载；`JobManager` 的 `on_heavy_job` 在 transcribe / proxy / export 开跑前调
    `TTSManager.release()`。`KIKUSUB_TTS_DEVICE=cpu|mps` 可强制设备，
    `KIKUSUB_TTS_MODEL_DIR` 可改权重目录（默认 `models/omnivoice`）。
  - 下载走 `core/tts/model_store.py` 的独立后台线程（不占 `JobManager` 单槽），
    进度由 `/api/tts/voices` 的 `engine.download` 带出；模型约 3.3GB，**不随包分发**。
  - 前端：`store.tts` 的 `voiceId`/`speed` 落 `localStorage['kikusub.ttsVoiceId']` /
    `['kikusub.ttsSpeed']`（旧 `ttsVoice`/`ttsRate` 自动迁移）。右侧检查器负责音色下拉
    （克隆/系统分组）、**上传参考音频（原生对话框默认落在上次上传目录 / 当前视频目录，
    可一次选多段，每段各建一个音色）**、**从当前句截取**、**音色库（保存/试听/设为默认/
    重命名/删除/在访达中打开）**、模型下载；字幕表与波形右键「以此句音频新建音色…」
    仍走 `extractTtsVoiceFromCue()`。参考音频提示只保留一行「3–10 秒、单人、干声、无音乐」。
    换句/换片仍必须 `stopTts()`；不做云端 TTS，不读 AI Key。
  - **降级是硬要求**：没装 `omnivoice`、没下模型、MPS 失败（回退 CPU）都必须只让克隆
    引擎不可用，系统语音与界面不能卡死；合成失败返回可读的 502/503，前端弹 toast。


## 3.5 日志与诊断（2026-11 新增）

- **服务层必须在 `server/__main__.py` 里调 `core.logging_setup.setup_logging()`**：漏掉这一步会导致 `outputs/logs/kikusub.log` 永远为空（曾经就是这样）。日志目录是 `config.output_dir/logs`。
- 日志分三层：sidecar 的 `kikusub.log`、Electron 主进程的 `main.log`、渲染端通过 `POST /api/log` 写入的 `kikusub.renderer`。排查用户问题优先看 `~/Library/Application Support/KikuSub/outputs/logs/`。
- **不要把 token、cookie、完整音视频内容写进日志**；文件路径与转写片段文本可以记。
- 请求中间件会对 `/api/*` 记录方法/路径/状态/耗时/`X-Request-Id`/会话 id；波峰与 `/media/*` 降为 DEBUG，避免刷屏。
- 渲染端 API 失败会自动带 `X-Request-Id` 记日志；新增「用户关键动作」时同时 `logEvent(...)`，否则用户报障时无法还原操作序列。
- 局部转写的 `write_audit` 语义：`replace_range`（核对台单句/选区修正）**不写**整片质检队列；转写页的整片/区间任务都要写，否则报告与质检面板数字不一致。

### 3.5.1 应用图标（2026-11 修订）

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

## 3.6 桌面启动、设置与退出清理（2026-11 新增）

### 首次启动与模型目录

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

### 快捷键

- **⌘,（Ctrl+,）** 打开设置。菜单 `设置…` 已绑 accelerator，渲染层 `onKey` 还要再兜一层：
  输入框聚焦时菜单快捷键可能被吃掉，且设置快捷键要在 `typing` early-return **之前**处理。
- **⌘K** 打开「键盘快捷键」面板（`ShortcutsDialog.svelte`）；面板里的组合存
  `localStorage['kikusub.shortcuts.v1']`，菜单里也有「键盘快捷键…」入口。用户自定义优先，
  不要再把播放 / 删除 / 视图切换写死回菜单 accelerator。

### 退出前清理（⌘Q / 关窗）

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
- 双语分两种排版，**不能混用**（D-4，2026-11 修订）：
  - `core/i18n.bilingual_cues()` = **一条 cue 两行**，只给画面叠加层与烧录硬字幕用
    （ffmpeg 字幕精灵按 cue 取块，一条两行才能一起排版）。
  - `core/i18n.bilingual_entries()` = **每语种一条独立 cue**、共享同一时间轴，给
    `.bilingual.srt/.vtt` 交付文件用。官方双语 SRT（如诸神字幕组）就是这个写法；
    重新导入核对台时每条都是单行，不会被 `white-space:nowrap` 挤成「日文 中文」一行。
  - 字幕文件导出（`/api/cues/export`、成片附带 SRT）走 `bilingual_entries()`；
    烧录/叠加层走 `bilingual_cues()`。两处各写一遍同样禁止。
- 旧版双语文件（同一条 cue 两行）导入时按 `.bilingual.srt/.vtt` 文件名拆开：
  `core/subtitles.split_multiline_cues()`；普通 SRT 的多行 cue 不拆（只影响显示，
  表格用「 / 」连接、画面叠加层按 `\n` 分行）。
- 三态导出：`POST /api/cues/export` 的 `track`（`source|target|both`）+ `lang`；
  文件名后缀 `.lang` / `.bilingual`。**新增后缀必须同步 `desktop/main/files.cjs`
  的 `TRANSLATION_SUFFIX`**，否则退出清理会把交付物当碎片默认删除。
- 核对台三态与双语行高：`ReviewView` 的行高是 `$derived(app.track === 'both' ? ROW_H*2 : ROW_H)`，
  **固定双行高**；禁止改用自动测量（会和虚拟滚动的绝对定位打架）。
- 暂存必须连译文一起写（`{stem}.autosave_draft.i18n.json`）；恢复时条数不符的轨直接丢弃。
- **结构性编辑与译文对齐（2026-11 修复）**：删一句原文必须同时删掉 `translations[lang].texts/base`
  同下标条目；插入补空占位；切割复制一条；合并拼接。`Session.delete_cue/delete_cues/insert_cue/
  split_cue/merge_cues` 是唯一入口，路由不要自己改两张表。
- **人工改译文 = 已同步**：`Session.patch_translation` 把 `base[index]` 更新成当前原文，
  「这一条的原文改过了，译文可能需要同步」才会随这次保存消失。双语下同时改原文和译文时，
  前端必须**先提交原文、再提交译文**，否则 base 会落在旧原文上，提示永远清不掉。
- **换片清空**：`POST /api/session/bind` 检测到 media id 变化时调用 `reset_for_media()`，清空
  字幕、译文、历史与来源；前端 `openMedia` 随后 `loadTranslations()`。这是「导入新视频后
  上一部片的译文永远占着、软件不可用」的修复。核对台右栏也提供「删除译文」。
- **切回三态要定位**：`ReviewView` 监听 `app.track/trackLang`，变化时把 `play.selected` 落到
  当前时间的字幕并 `revealRow()`；双语是双行高，必须等 DOM 更新后再滚。
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

## 3.8 提示词模板、成片导出与手动代理（2026-11 新增）

### 3.8.1 提示词模板库

- 模板是普通 JSON，默认与 `settings.json` 同级（`prompts.json`，
  `KIKUSUB_PROMPTS_PATH` 可覆盖）。内置两条：`legacy`（原有模板）与
  `localization`（成熟汉化组）；用户对内置模板的修改会持久化，删掉文件恢复出厂。
- 正文占位符只有 `{{SRT}}` 与 `{{LANG}}`（兼容旧版 `__SRT__` / `__LANG__`）。
  **没有 `{{SRT}}` 时自动把当前字幕追加到末尾**，所以纯指令模板也能直接用。
- 手动通道 `GET /api/ai/prompt` 现在接受 `template_id`，缺省用当前选中模板；
  解析回来的 SRT 仍然**只按顺序取文本**，序号/时间戳全部丢弃（D-1 不破）。
- 界面：侧栏「提示词库」；单击选中、双击就地编辑；保存后 AI 优化台的
  「复制提示词」立刻用新内容。禁止把模板内容写进 `settings.json` 或日志。
- **润色也能走手动通道（2026-11）**：`GET /api/ai/prompt?kind=polish` 返回内置润色提示词
  （`core.ai_polish.build_manual_prompt`，带 SRT），`POST /api/ai/from-srt` 的 `kind=polish`
  只按顺序取文本、时间轴仍用当前 cue。润色不要求 API Key，也不绑定「AI 优化」开关。

### 3.8.2 成片导出

- **不要依赖 ffmpeg 的 `subtitles` / `ass` 滤镜**：Homebrew 的 ffmpeg 默认没有
  libass/freetype（本机 9.0.2 实测没有）。硬字幕走 Pillow 透明精灵 + ffmpeg
  `crop` 时间表达式 + 单个 `overlay`；每批最多 60 句（240 句时 FFmpeg 会报
  `Failed to configure input pad`），块高固定，第 0 块是空白。
- 输出文件名用**实际高度**（源 360p 选 1080p 不会放大，名字写 `360p`），不要
  用用户选的档位骗人。
- 三种模式：`burn`（重编码 + 烧录）、`soft`（重编码 + `mov_text` 软字幕）、
  `copy`（`-c copy` + 软字幕，MP4 不兼容时退回 MKV）。`copy` 模式忽略分辨率/
  码率，规划里要明确告诉用户。
- 编码先试 `h264_videotoolbox`，失败回退 `libx264`；音频 AAC（≥720p 192k，
  否则 128k）；写 `.part` 再原子 rename；`JobManager` 单槽，kind=`export`。
- **进度与取消（2026-11 修复）**：ffmpeg 命令必须带 `-nostats -progress pipe:1`，
  `core/video_export._progress_reader` 用读线程 + 队列轮询，每 150ms 检查取消令牌。
  旧实现没有 `-progress`，stdout 永远没有数据：进度停在 0%，取消也要等 ffmpeg 自己跑完。
  精灵渲染阶段同样要报进度（0–10%）并在每批前检查取消/关机状态。
- **不能留下孤儿 ffmpeg（2026-11 修复）**：Electron 以 `detached:true` 启动 sidecar
  （新进程组），退出时 `kill(-pid)` 覆盖整棵树；主进程退出路径必须
  `await stopSidecarAndWait()` 后再 `app.exit`，不能只发信号就走。
  sidecar 侧：`_KikuSubServer` 在 SIGTERM/SIGINT 时先 `jobs.cancel_all()`，
  再 `begin_shutdown()` + `terminate_all_processes()`；`core/procutil` 的
  `SPAWN_LOCK` 保证关机开始后不会再出生新的 ffmpeg；`server/__main__.py` 还有
  父进程看门狗（Electron 崩溃/被强杀时 sidecar 在 2s 内自杀）。
  **禁止**把这些改回裸 `subprocess.run` 或只 `child.kill()`。
- **字幕样式（2026-11 新增）**：`SubtitleStyle`（字体/字重/字号/描边/阴影/位置/颜色）
  只影响 `burn`；字体以「文件名 + TTC 内 family/style 名」解析（macOS 的 PingFang、
  兰亭黑等位于 AssetsV2 的 hash 目录，禁止写死路径）。内置预设见 `STYLE_PRESETS`；
  `/api/export/styles` 必须返回本机可用性，`/api/export/style-preview` 用与导出
  完全相同的 `_text_layer()` 渲染 PNG（可带真实视频帧与 `zoom` 特写）。
  改样式字段时同步 `desktop/renderer/src/lib/api.ts` 的 `SubtitleStylePayload`。
- 目录：设置里的 `video_export_dir`，空值跟随 `export_dir`；所有路径统一在
  设置页「运行环境」的 `.path-row` 列表中展示/更改。
- 依赖：`Pillow>=10` 必须进 `requirements.txt`；`plan_export` 在缺 Pillow 时
  直接给「改用软字幕」的可读错误。`tests/test_export.py` 覆盖 burn/soft/copy。

### 3.8.3 手动代理

- `MediaInfo` 现在带 `video_width/height/bitrate` 与 `proxy_reason`
  （`container` / `codec` / `bitrate`）。`needs_proxy` 在码率 ≥25 Mbps 时也为真。
- 自动压制仍由 `auto_proxy` 控制；核对台工具栏与画面提示都提供手动
  「压制代理」，不依赖自动判定。代理任务仍走 `/api/jobs` 的 `kind=proxy`。
- 高码率 H.264 的提示文案要说明「能播但拖动卡」，不要写成「无法解码」。

### 3.8.3.1 媒体 Range（2026-11 修复）

- 当前 Starlette 0.38 的 `FileResponse` **没有 Range 支持**（0.39 才加），直接返回
  `FileResponse` 会让 `<video>` 拖动进度条时重新下载整段。`server/routes_media.py`
  的 `_media_response()` 自己处理单段 Range：206 + `Content-Range`，只读请求区间；
  无效 Range 返回 416；无 Range 才退回 `FileResponse`。**不要**再把 `stream_media`
  改回裸 `FileResponse`。`tests/test_server_api.py` 与 `tests/test_proxy.py` 的
  Range 用例是这条的回归保护。

### 3.8.4 日志清理与复制

- `/api/diagnostics/log/clean` 保持「按保留策略清备份」的语义；新增
  `/api/diagnostics/log/clear` 才**一定释放空间**：通过 handler 的
  `doRollover()` 轮转活动日志，再按 0 天/0 字节删备份，绝不直接 truncate
  正在写的流。主进程的 `main.log` 由 `logs:clear-main` IPC 截断/删备份。
- 设置页文案必须区分两者；`clean` 返回 0 时提示「没有过期备份，可点清空全部」。
- 「复制最近日志」限制 80 行、每行 500 字符；「复制精简诊断」只带最近 8 条问题
  + 20 行日志 + 路径/引擎摘要，并硬截断 24k 字符。**禁止**再把完整 300 行
  日志或 8000 字符 detail 直接塞进剪贴板。

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
