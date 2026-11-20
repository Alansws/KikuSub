---
created: 2026-11-12 21:26
updated: 2026-11-17 20:57
---
# AGENTS.md — 日语影片字幕转录工作台开发指南

本文件面向在此仓库中继续开发的智能体与开发者。**注意：它是索引，不是全文。**

2026-11-13 起，长期积累的领域契约从本页拆到了 `docs/contracts/`：这一页原先有 65KB（≈1.7 万
token），每次会话光读规范就要吃掉一大截上下文，而且里面还留着已经删掉的 Gradio 界面的规则
（错误的文档比没有文档更可怕）。现在本页只保留**定位、结构、红线、索引**，细节去哪读看第 3 节。

## 0. 读法（30 秒）

1. 先读本页「红线」与「改动纪律」；
2. 按要改的域打开 `docs/contracts/` 里对应的那一份，**别凭记忆改**；
3. 动手前先让基线变绿：`pytest -q` + `python -m core.smoke`。
   **用 `python`（3.12，依赖齐全），不要用 `python3`**——本机 `python3` 是 3.14，连 pytest 都没装。
4. 全程**不许在本机弹出窗口**（§0.5）。验证一律走无窗口路径，截图落盘后用 `read_image` 看。

## 0.5 无窗口铁律（2026-11-16 用户红线）

**改这个仓库的任何功能，都不许在用户桌面上弹出任何窗口。** 窗口 / Dock 图标 / 抢焦点都会打断
用户在这台电脑上正在做的别的事，而验证不需要看见界面。

- **禁止**（只许用户自己做）：`npx electron .`、`npm start`、`desktop/run.sh`、
  `open build/pack/KikuSub.app`、`rebuild.sh --open`；裸跑 `rebuild.sh` 只构建装配、不打开。
- **允许**（全程无窗口）：`pytest`、`npm run check` / `check:svelte` / `build` / `test:main`、
  `npx electron . --screenshot=…`、`tools/shots/` 下的静默脚本；截图落盘后用 `read_image` 看。
- **代码兜底**：未打包启动默认拒绝建窗口（退出码 2）；截图用透明窗口取帧。判定与细节见
  [desktop-lifecycle §3.7](docs/contracts/desktop-lifecycle.md)，守卫是 `tests/test_no_window_policy.py`。

## 1. 项目定位与运行方式

这是一个 **macOS 桌面应用**形态的日语影视字幕工作台：Electron 主进程 + Svelte 5 渲染层，Python 以内置 sidecar（FastAPI）提供内核。它面向动漫、电影、Galgame、广播剧等音频场景，支持：

- Anime Whisper：重视自然、连贯的日语对话转写；
- Qwen3-ASR + CTC：转写后利用自带的 CTC 对齐头取得逐字发声时间，并针对日语分句；
- SenseVoice-Small / FireRedASR2-AED：两个**可选装**的中文引擎（ONNX / CPU，权重按需下载、默认停用）；
- WhisperSeg / Silero VAD 分段、可选动态响度归一化、人声分离（整片 / 区间，默认仅 VAD）、时间范围转录、原片绝对时间轴、取消后保存已完成字幕；
- 视频 + 波形核对台、质检待核队列、批量清理标点、SRT/VTT/TXT 导出、参数预设与完整任务报告；
- AI 提案（润色 / 翻译平行轨）、结构建议、断句重排与随包 Agent 技能。

**主入口是 `desktop/`。** `app.py` 与 `static/` 已从仓库移除；旧 Gradio 界面归档在 Git 标签 `v0.9-gradio`，不再随本仓库演进。

开发模式（安装 `requirements.txt`、`desktop/npm install` 与系统 `ffmpeg` 后）：

```bash
cd desktop && npm run build && npm start   # 人类手动看界面；智能体一律别用（§0.5）
```

> 开发模式默认**不弹窗**：`npm start` / `desktop/run.sh` 是显式的人入口（内部设
> `KIKUSUB_ALLOW_WINDOW=1`）；直接 `npx electron .` 会被主进程拒绝。智能体验证用
> `--screenshot`（无窗口）。

sidecar 也可以单独启动：`source .venv/bin/activate && python -m server --port 0`，stdout 首行输出 `{"event":"ready","port":…,"token":…}`。

首次真正转录时才会加载（必要时下载）模型。不要在不需要模型推理的改动验证中触发下载或完整转录；界面、波形与提案链路的验证用 `KIKUSUB_DEV_SEED`（见 `desktop/README.md`）。

## 2. 仓库结构

| 路径 | 职责 |
| --- | --- |
| `desktop/` | **桌面端（主入口）**。`main/` 是 Electron 主进程：窗口/菜单/单实例、sidecar 生命周期、首启向导、退出清理、AI 密钥（`aikey.cjs`）、技能安装（`skill.cjs`）；`files.cjs` 可被 `node --test` 覆盖。`renderer/src/` 是 Svelte 5 渲染层：`views/` 八视图 + 设置，`lib/store.svelte.ts` 工作区、`lib/aiWorkspace.svelte.ts` 提案/双源、`lib/api.ts` 客户端。 |
| `desktop/resources/skill/` | 随包 Agent 技能，构建时复制进 app，设置页「一键配置」装到 `~/.agents/skills/`。 |
| `desktop/main/windowmode.cjs` | **窗口可见性判定（纯函数）**：截图 / `KIKUSUB_NO_WINDOW` / 开发模式默认拒绝 / 显式允许 / 打包版；单测在 `desktop/test/window-mode.test.cjs`。 |
| `core/` | **算法内核包**（无 UI 依赖）。`paths.py` 是运行期路径中枢；`python -m core.smoke` 与 `tests/test_core_boundary.py` 看守边界。**禁止在 `core/` 内 import gradio / fastapi。** |
| `server/` | **服务层（FastAPI）**。`/api/*` 走 Bearer token，`/media/*` 走 `?token=`。**禁止在 server/ 内 import UI 代码。** |
| `server/routes_ai.py` | 提案接口：proposal / apply / prompt / from-srt / import；单句判定 `/api/ai/arbitrate`、本地档位 `/api/ai/local-model/*`；结构建议在 `routes_structure.py`。 |
| `core/ai_arbitrate.py` / `core/ai_local_model.py` | 单句 AI 判定（第三版）：dual / same / single / blind 提示词、2048 预算、`{text, note}` 校验；本地 LM Studio 档位 2048 / 4096 / 8192 自动校准。 |
| `server/routes_alt_review.py` / `core/dual_review.py` | 第二版接口（GET / 导入 / DELETE / 整列覆盖）与实时对齐 diff。 |
| `server/routes_translations.py` | 译文平行轨：`/api/translations`（整版应用、撤销、过期检测）。 |
| `core/tts/` | 本地 TTS：`say` 兜底、OmniVoice 克隆、音色仓库、懒加载 / 空闲卸载、权重下载。**不 import fastapi / gradio**；torch 只在 `load()` 延迟导入。 |
| `server/routes_tts.py` | 本地日语 TTS：音色列表、合成缓存、切片建音色、增删改、模型下载、`/media/tts/*`。 |
| `core/ai_proposal.py` | 提案契约的**唯一实现**：源指纹 digest、结构校验、`apply_polish()`；结构建议在 `ai_structure.py`。 |
| `core/ai_client.py` | OpenAI 兼容 urllib 客户端；本地空 Key；判定/重载在 `ai_arbitrate.py` / `ai_local_model.py`。 |
| `core/ai_polish.py` / `core/ai_translate.py` | 分块、提示词、结构重问与结果组装；取消只能落在分块之间；支持 `from_index` / `to_index` 片段范围与手动批次。 |
| `core/i18n.py` | 双语排版唯一构造：`bilingual_cues()`（一条两行）与 `bilingual_entries()`（每语种一条）。 |
| `core/transcribe.py` | 字幕结构 / 格式、时间解析、FFmpeg 抽取、Anime Whisper、Silero VAD 与启发式分句。 |
| `core/qwen_ctc.py` | Qwen3-ASR 模型推理、CTC 对齐头、日语断句动态规划、字幕劈词修复、编码特征复用。 |
| `core/short_clip.py` | 核对台短选区「轻声兜底」：降阈值重试 → 整段送引擎（只服务人工框选 / 单句重转）。 |
| `core/audio_cache.py` | 16k wav 解码缓存（`cache_key` / `ensure_wav` / `peaks` / `prune`），转写与核对台共用一次解码；`KIKUSUB_AUDIO_CACHE=0` 关闭。 |
| `core/jobs.py` | 进程内单槽任务注册表与 `CancelToken`：同时只允许一个重任务，取消只能由发起会话发出。 |
| `core/procutil.py` | 可取消、带超时的子进程执行器（Popen + 读线程 + terminate/kill）；ffmpeg/ffprobe 统一走这里。 |
| `core/logging_setup.py` | 日志落盘（`outputs/logs/kikusub.log`，5MB × 3 轮转）、14 天 / 64MB 保留清理、后台 excepthook。 |
| `tests/` | pytest 回归；重依赖用例在轻量 CI 中自动 skip。 |
| `tools/eval/` | 评测台：`score_srt.py` 打分（CER / 块准确率 / 劈词数）、`run_clip.py` 跑片出 scorecard、`probe_window.py` 逐窗直探、`baseline.json` 基线。改断句 / VAD 前后必须跑同一区间；素材用 `--fixtures`。 |
| `tools/pack/` | `build_sidecar.sh`（PyInstaller）+ `build_app.sh`（手工装配 .app）+ `rebuild.sh`（按需重打 sidecar → 构建渲染层 → 装配；默认不打开，`--open` 才打开）。改 Python 后必须先重打 sidecar。 |
| `core/presets.py` | `presets.json` 的校验、兼容读取与原子写入。 |
| `core/engines.py` | **引擎注册表**（无 torch 依赖）：名称、语种、用途、HF 仓库、体积、安装检测、`family`、`reviewable`、`file_tag` / `legacy_tags`；设置页与命名都读这张表。新增引擎在这里加一条，再到 `core/pipeline.py` 注册推理对象。 |
| `core/sherpa_asr.py` | 两个中文引擎推理外壳（sherpa-onnx · ONNX · CPU）。**顶层不 import sherpa_onnx**，只在 `load()` 延迟导入；权重不随包，`ensure_model()` 只下 int8 与 tokens。 |
| `core/text_cues_zh.py` | 中文分句唯一实现（纯函数）：token→字符时间轴、标点 / 停顿 / 字数切条；改口径先改这里。 |
| `core/punctuation.py` | FireRedPunc 标点恢复（ONNX Runtime / CPU）：只在完全无句读时补，按字符偏移插回原文。权重随 FireRed 下到 `<引擎目录>/punc/`。 |
| `core/model_fetch.py` | 可选权重 HF 下载入口（直连失败才走镜像）；SenseVoice / FireRed / FireRedPunc 共用。 |
| `core/params.py` | 可调参数规格表（`whisper.*` / `qwen.*` / `sensevoice.*` / `firered.*`）；`config_kwargs()` 映射界面键到引擎字段。新增参数只改这里。 |
| `core/settings.py` | 应用级设置（引擎、AI base_url / model / 分块；判定覆盖 / 档位 / 自动判定），原子写 `settings.json`（`KIKUSUB_SETTINGS_PATH` 可覆盖）。**AI Key 不在其中**。 |
| `server/routes_settings.py` | 设置 / 引擎 / 诊断接口：`/api/settings`、`/api/engines/*`、`/api/log`、`/api/diagnostics*`。 |
| `core/prompts.py` | 提示词模板库：五分类、`{{SRT_A}}` 占位符、原子读写。 |
| `server/routes_prompts.py` | 提示词模板接口：`/api/prompts`（增删改 / 恢复内置）。 |
| `core/video_export.py` | 成片导出：探测、分辨率 / 码率规划、Pillow 精灵 + ffmpeg 硬字幕、软字幕 / 仅封装；片段导出按 `clip_range` 归零。 |
| `core/clip_range.py` | 片段范围纯函数（`clip_window` / `select_cues_in_range` / `shift_*` / `clip_tag`），润色 / 翻译 / 导出共用。 |
| `core/chapters.py` / `server/routes_chapters.py` | 章节 / 时刻点：衔接防重叠、按媒体指纹落盘、`ffmetadata_text`；`/api/chapters` 整表保存 = 一步历史。 |
| `server/routes_export.py` | 成片导出接口：`/api/export/options`、`/api/export/plan`、`/api/export`。 |
| `presets.json` | 命名调参预设；运行数据，改 schema 要兼容旧内容。 |
| `models/` | 模型缓存；`anime-whisper/` 与 `qwen3-asr-ja-anime/` 很大，不作普通源码改动。 |
| `outputs/` | 生成的字幕样例和运行产物。 |
| `README.md` / `README_EN.md` / `CONTRIBUTING.md` | 面向用户与贡献者的说明；改变用户可见行为时同步更新。 |

## 3. 契约索引：改哪块先读哪份

| 你要改的东西 | 先读 | 关键契约 |
| --- | --- | --- |
| 核对台交互、字幕块聚合、选区、时间线缩放、主题令牌、历史、查找替换、TTS | [docs/contracts/review-console.md](docs/contracts/review-console.md) | 单击/框选阈值、50 步统一历史、`duration/69` 缩放、主题覆盖块、选区 clamp |
| 启动/退出清理、日志与诊断、模型目录、快捷键、单实例、截图开关、**无窗口模式** | [docs/contracts/desktop-lifecycle.md](docs/contracts/desktop-lifecycle.md) | 退出前清理顺序、日志留存、`--screenshot` 取证开关、窗口可见性判定（§3.7） |
| AI 提案 / 双源 / 结构建议 / 断句重排 / 翻译轨 / 技能 | [docs/contracts/ai-proposal.md](docs/contracts/ai-proposal.md) | 源指纹 digest / digest_b、结构校验、`apply_polish()`、D-1～D-6、A1–A10、结构建议 3.7.5 |
| 提示词模板、成片导出、手动代理、媒体 Range | [docs/contracts/export-and-prompt.md](docs/contracts/export-and-prompt.md) | 导出设置必须走 `setExport*`、代理写 `*.part.mp4` 再 rename |
| 参数规格、预设、引擎绑定 | [docs/contracts/params-and-presets.md](docs/contracts/params-and-presets.md) | 保存/载入都必须带引擎、跨引擎 409、种子预设 = 当前默认值 |
| 想理解「为什么这么定规矩」/接手这套流程 | [docs/contracts/engineering-practice.md](docs/contracts/engineering-practice.md) | 五类失控的对照、五道护栏落点、规则→测试的三级升级、多模型协作 |
| （历史参考）已移除的 Gradio 面板 | [docs/archive/gradio-legacy.md](docs/archive/gradio-legacy.md) | **禁止照它改代码** |

## 4. 红线（改之前先确认没踩）

1. **内核边界**：`core/` 不得 import gradio / fastapi / uvicorn / starlette；`server/` 不得 import UI。
   守卫是 `python -m core.smoke` 与 `tests/test_core_boundary.py`，不是靠自觉。
2. **提案只有一个实现**：源指纹 digest、结构校验、`apply_polish()` 都在 `core/ai_proposal.py`；
   前端不得自己算 digest 或另写校验。
3. **并发与取消**：转写必须通过 `jobs.JobRegistry` 单槽占用，取消令牌归属发起会话；
   **禁止**再引入模块级 `CANCEL_EVENT`。所有外部命令走 `procutil.run_command`（超时/取消/terminate）。
4. **断句改动必须有数字**：改 `_break_costs` / `partition_cues` / VAD 参数前后，用
   `tools/eval/score_srt.py` 对同一区间跑 CER、劈词数、最长条；禁止凭个别样例"看起来更好"。
5. **历史只有一条线**：`Session.history` 是 ≤50 步的 `WorkspaceState` 时间线，所有编辑必须带 `label`；
   禁止按域拆历史、禁止双栈。
6. **用户报障过的交互不许改回**：单击跳转 vs 框选阈值、进度条复用 click-to-seek、
   缩放步进 `duration/69`——改回去等于复活旧 bug。
7. **主题只走令牌**：加主题 = `app.css` 一块 `html[data-theme='<id>']` 覆盖 + 注册表一条；
   组件内不写主题专属色，分隔线不许退回 5% 灰。
8. **导出设置必须进历史**：一律走 `setExportMode / setExportTrack / setExportResolution /
   setExportQuality / setExportSrt / setExportOutDir / updateExportStyle / applyExportStylePreset /
   resetExportStyle`，禁止直接写 `exporter.*`。
9. **改 Python 就先重打 sidecar**：`bash tools/pack/build_sidecar.sh`（或 `tools/pack/rebuild.sh`）；
   `build_app.sh` 会因为 sidecar 比源码旧直接退出，这是有意的。
10. **改前端必须真验证，但不许开窗**：`cd desktop && npm run build && npm run check:svelte`，
    再用 `--screenshot` + `KIKUSUB_DEV_EVAL` 静默断言实际页面（单击跳转、抖动单击不建选区、缩放、保存），
    或跑 `node tools/shots/verify_reshape_flow.mjs` / `verify_review_transport.mjs`；
    只看编译通过不算验证。**「手点一遍」不许成为打开窗口的理由**（§0.5）。
11. **两个大文件只许变短**（`lib/store.svelte.ts` 3258 行 / `views/ReviewView.svelte` 3787 行）：
    改它们前，先把
    **这次功能要用到的**纯逻辑抽到 `lib/`（单独一个 commit，行为不变），再接线。守卫是
    `tests/test_big_file_budget.py`，抽完把预算下调。不是"为了拆而拆"，是为了不让功能开发
    变成"先读完 4000 行"。
12. **新增引擎只改两处**：元信息进 `core/engines.py`（含 `family` / `file_tag` / `reviewable`），推理对象与分派进 `core/pipeline.py`；
    `server/routes_jobs.py` 按 `family` 选配置，报告/质检按 `family` 选口径。**禁止**在别处再维护一份引擎 key 白名单
    （加中文引擎时踩过：`if payload.engine == "qwen": ... else: whisper` 会把未知引擎静默当 Whisper）。
13. **不许弹窗**：任何验证都走无窗口路径（§0.5）。`npx electron .`、`npm start`、`open *.app`、
    `rebuild.sh --open` 只允许用户自己做，不许代劳；截完图用 `read_image` 看，不要摆到桌面上。

## 5. 改动纪律（提交流程）

- **分支模型**：`main` 是主线（只接收已测试的改动、只在这打发版 tag）；日常开发在 `app/macos`，
  测试绿了才合入 `main`。**不要直接在 `main` 上改代码**——那会让下次合并变成冲突。
  完整四步与回滚口径见 [docs/release.md](docs/release.md)。
- 提交按层拆开：`core,server` / `desktop` / `docs` 各自成 commit，不要把渲染层和内核混成一个包。
- 改动前 `git status` 必须是干净的（或明确知道自己在改哪几个文件）；不要在混杂工作区上叠加新改动。
- 验证按**改动范围**跑，不必每次全量（见下面「验证时机」表）。全量 `pytest -q` 约 40s，
  但"改个文档也跑 423 例"会把注意力磨平；环境依赖的用例用 marker 排除
  （`-m "not needs_macos"` 等，见 `pytest.ini`）。基线命令：`python -m core.smoke`。
- **改 `.svelte` 后多跑一步** `npm run check:svelte`：存量 6 个真实类型错误已冻结成基线
  （`desktop/test/svelte-check-baseline.json`），只许降不许升。`tsc` 看不到 `.svelte`，
  这一步是目前唯一的类型防线。
- 合入 `main` 前过一遍 [docs/review.md](docs/review.md) 的自审清单。
- 规则沉淀：Review 里同一个位置反复出错，就把结论压缩成 1–2 句写进本页「红线」，或写进对应契约；
  能变成测试的（导错、漏 import、样式漂移）优先变成测试——`desktop/test/svelte-imports.test.cjs` 就是范例。

### 验证时机（改什么 → 必跑什么）

| 改动范围 | 每次改完 | 收尾 / 合入 `main` 前 |
| --- | --- | --- |
| 纯文档（`docs/`、`AGENTS.md`） | `pytest -q tests/test_docs_health.py` | 同左 |
| `core/` 算法 | `pytest -q -m "not integration"` | `pytest -q`；改断句/VAD 必须用 `tools/eval/score_srt.py` 跑同一区间 |
| `server/` 路由 | `pytest -q -m "not needs_ffmpeg"` | `pytest -q` |
| `desktop/main/`（主进程） | `npm run test:main` | 同上 + 无窗口冒烟：`npx electron . --screenshot=/tmp/kikusub-main.png`（不要裸跑） |
| `desktop/renderer/`（`.svelte` / `.ts`） | `npm run check` + `npm run check:svelte` | `npm run build` + 静默断言（红线 10：`--screenshot` / `verify_reshape_flow.mjs`，**不开窗**） |
| 样式、布局、主题 | 上面两条 | `bash tools/shots/capture_matrix.sh --compare docs/images/shots/baseline` |
| 改了 Python（`core/` `server/`） | 上面 + `bash tools/pack/build_sidecar.sh` | `bash tools/pack/rebuild.sh --no-open` |
| 发版 | — | `bash tools/release/preflight.sh --with-tests` |

单屏取证也可以用 `KIKUSUB_DEV_SEED` + `--screenshot`，见 [tools/shots/README.md](tools/shots/README.md)。


## 6. 发版

**唯一依据是 [docs/release.md](docs/release.md)**：`app/macos` 测试绿 → bump `desktop/package.json`
版本 → 合入 `main` → 在 `main` 打 tag。闸门：`bash tools/release/preflight.sh --with-tests`；
CI 的 `release-tag` job 拦「tag ≠ 版本」与「tag 不在 main」。本地可选钩子：
`git config core.hooksPath tools/git-hooks`。

## 7. 进行中的专项（跨会话必须能接上）

引擎标定、日语优化路线 P0–P3 等长期专项的「做到哪、下一步」已拆到
[in-progress.md](docs/contracts/in-progress.md)；接手时先读那一页，别在这里重复。
