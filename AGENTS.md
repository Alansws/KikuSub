---
created: 2026-11-12 21:26
updated: 2026-11-13 02:53
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

## 1. 项目定位与运行方式

这是一个 **macOS 桌面应用**形态的日语影视字幕工作台：Electron 主进程 + Svelte 5 渲染层，Python 以内置 sidecar（FastAPI）提供内核。它面向动漫、电影、Galgame、广播剧等音频场景，支持：

- Anime Whisper：重视自然、连贯的日语对话转写；
- Qwen3-ASR + CTC：转写后利用自带的 CTC 对齐头取得逐字发声时间，并针对日语分句；
- SenseVoice-Small / FireRedASR2-AED：两个**可选装**的中文引擎（ONNX / CPU，权重按需下载、默认停用）；
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
| `core/engines.py` | **引擎注册表**（无 torch 依赖）：名称、语种、用途、HF 仓库、体积、必需文件、安装检测、`family`（whisper / qwen / sherpa）。设置页的引擎卡片与工具栏过滤都读这张表。新增引擎在这里加一条，再到 `core/pipeline.py` 注册推理对象并提供 `ensure_model(progress_cb)`。 |
| `core/sherpa_asr.py` | 两个中文引擎的推理外壳（SenseVoice-Small / FireRedASR2-AED，sherpa-onnx · ONNX · CPU）。**顶层不 import sherpa_onnx**，只在 `load()` 延迟导入；权重不随包，`ensure_model()` 只下 int8 与 tokens。 |
| `core/text_cues_zh.py` | 中文分句的唯一实现（纯函数，无 torch）：token→字符时间轴、标点/停顿/字数切条。改中文断句口径先改这里的测试。 |
| `core/params.py` | 可调参数规格表（`whisper.*` / `qwen.*` / `sensevoice.*` / `firered.*`）；`config_kwargs()` 把界面键映射成引擎 dataclass 字段。新增引擎参数只改这里，前端不用动。 |
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

## 3. 契约索引：改哪块先读哪份

| 你要改的东西 | 先读 | 关键契约 |
| --- | --- | --- |
| 核对台交互、字幕块聚合、选区、时间线缩放、主题令牌、历史、查找替换、TTS | [docs/contracts/review-console.md](docs/contracts/review-console.md) | 单击/框选阈值、50 步统一历史、`duration/69` 缩放、主题覆盖块、选区 clamp |
| 启动/退出清理、日志与诊断、模型目录、快捷键、单实例、截图开关 | [docs/contracts/desktop-lifecycle.md](docs/contracts/desktop-lifecycle.md) | 退出前清理顺序、日志留存、`--screenshot` 取证开关 |
| AI 提案、润色、翻译平行轨、随包技能 | [docs/contracts/ai-proposal.md](docs/contracts/ai-proposal.md) | 源指纹 digest、结构校验、`apply_polish()`、D-1～D-6 |
| 提示词模板、成片导出、手动代理、媒体 Range | [docs/contracts/export-and-prompt.md](docs/contracts/export-and-prompt.md) | 导出设置必须走 `setExport*`、代理写 `*.part.mp4` 再 rename |
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
10. **改前端必须真验证**：`cd desktop && npm run build`，然后实际过一遍单击跳转、抖动单击不建选区、
    缩放、保存；只看编译通过不算验证。
11. **两个 4000 行文件只许变短**：改 `lib/store.svelte.ts` / `views/ReviewView.svelte` 前，先把
    **这次功能要用到的**纯逻辑抽到 `lib/`（单独一个 commit，行为不变），再接线。守卫是
    `tests/test_big_file_budget.py`，抽完把预算下调。不是"为了拆而拆"，是为了不让功能开发
    变成"先读完 4000 行"。
12. **新增引擎只改两处**：元信息进 `core/engines.py`（含 `family`），推理对象与分派进 `core/pipeline.py`；
    `server/routes_jobs.py` 按 `family` 选配置，报告/质检按 `family` 选口径。**禁止**在别处再维护一份引擎 key 白名单
    （加中文引擎时踩过：`if payload.engine == "qwen": ... else: whisper` 会把未知引擎静默当 Whisper）。

## 5. 改动纪律（提交流程）

- **分支模型**：`main` 是主线（只接收已测试的改动、只在这打发版 tag）；日常开发在 `app/macos`，
  测试绿了才合入 `main`。**不要直接在 `main` 上改代码**——那会让下次合并变成冲突。
  完整四步与回滚口径见 [docs/release.md](docs/release.md)。
- 提交按层拆开：`core,server` / `desktop` / `docs` 各自成 commit，不要把渲染层和内核混成一个包。
- 改动前 `git status` 必须是干净的（或明确知道自己在改哪几个文件）；不要在混杂工作区上叠加新改动。
- 验证按**改动范围**跑，不必每次全量（见下面「验证时机」表）。全量 `pytest -q` 约 40s，
  但"改个文档也跑 423 例"会把注意力磨平；环境依赖的用例用 marker 排除
  （`-m "not needs_macos"` 等，见 `pytest.ini`）。基线命令：`python -m core.smoke`。
- **改 `.svelte` 后多跑一步** `npm run check:svelte`：存量 9 个真实类型错误已冻结成基线
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
| `desktop/main/`（主进程） | `npm run test:main` | 同上 + 真的启动一次 `npx electron .` |
| `desktop/renderer/`（`.svelte` / `.ts`） | `npm run check` + `npm run check:svelte` | `npm run build` + 按红线 10 手点（单击/抖动/缩放/保存） |
| 样式、布局、主题 | 上面两条 | `bash tools/shots/capture_matrix.sh --compare docs/images/shots/baseline` |
| 改了 Python（`core/` `server/`） | 上面 + `bash tools/pack/build_sidecar.sh` | `bash tools/pack/rebuild.sh --no-open` |
| 发版 | — | `bash tools/release/preflight.sh --with-tests` |

单屏取证也可以用 `KIKUSUB_DEV_SEED` + `--screenshot`，见 [tools/shots/README.md](tools/shots/README.md)。


## 6. 发版

**唯一依据是 [docs/release.md](docs/release.md)**（四步：合入审查 → 本地实测 → 打包分发 → 发布日志）。
顺序固定：`app/macos` 测试绿 → bump `desktop/package.json` 的 version → 合入 `main` → 在 `main` 上打 tag。

```bash
bash tools/release/preflight.sh --with-tests   # 程序化闸门：版本/tag/分支/sidecar/图标/测试
bash tools/pack/rebuild.sh --no-open           # 重打 sidecar + 构建渲染层 + 装配
bash tools/pack/build_dmg.sh                   # 出 DMG
```

CI 的 `release-tag` job 会拦两件事：tag 与 `package.json` 版本不一致、tag 的提交不在 `main` 上。
本地可选装钩子：`git config core.hooksPath tools/git-hooks`（推发版 tag 前自动跑 preflight）。
