# AGENTS.md — 日语影片字幕转录工作台开发指南

本文件面向在此仓库中继续开发的智能体与开发者。开始改动前先阅读本文件和相关模块；它记录当前实际实现，而不仅是产品愿景。

## 1. 项目定位与运行方式

这是一个以 **Gradio** 提供本地 Web 界面的日语影视字幕转录工具。它面向动漫、电影、Galgame、广播剧等音频场景，支持：

- Anime Whisper：重视自然、连贯的日语对话转写；
- Qwen3-ASR + CTC：转写后利用自带的 CTC 对齐头取得逐字发声时间，并针对日语分句；
- Silero VAD 分段、可选动态响度归一化、时间范围转录、原片绝对时间轴、取消后保存已完成字幕；
- SRT/VTT/TXT 导出、纯标点字幕清理、参数预设读写与完整任务报告。

主入口是 `app.py`。在安装 `requirements.txt` 及系统 `ffmpeg` 后运行：

```bash
python app.py
```

服务仅监听 `127.0.0.1:7860`，并在浏览器中打开。首次真正转录时才会加载（必要时下载）模型。不要在不需要模型推理的改动验证中触发下载或完整转录。

## 2. 仓库结构

| 路径 | 职责 |
| --- | --- |
| `app.py` | Gradio 页面、参数控件注册、预设交互、任务编排、文件写出和报告生成。 |
| `core/` | **算法内核包**（无任何 UI 依赖）。`paths.py` 是运行期路径中枢（`KIKUSUB_MODELS_DIR` / `KIKUSUB_OUTPUT_DIR` / `KIKUSUB_PRESETS_PATH` 可覆盖）；`python -m core.smoke` 自检内核与 UI 解耦，`tests/test_core_boundary.py` 看守这条边界。**禁止在 `core/` 内 import gradio / fastapi。** |
| `server/` | **新服务层（FastAPI）**。`python -m server` 启动，stdout 首行输出 `{"event":"ready","port":…,"token":…}` 供 Electron 主进程握手。`/api/*` 走 Bearer token，`/media/*` 走 `?token=`（`<video src>` 发不了自定义头）。`--legacy` 时把旧 Gradio 挂到 `/legacy`。**禁止在 server/ 内 import app.py**（除 `_mount_legacy` 的显式延迟导入）。 |
| `core/transcribe.py` | 共用字幕数据结构/格式、时间解析、FFmpeg 音频抽取、Anime Whisper、Silero VAD 和启发式分句。 |
| `core/qwen_ctc.py` | Qwen3-ASR 模型推理、CTC 对齐头、日语断句动态规划（含 P1-1 词边界成本）、字幕劈词修复、编码特征复用。 |
| `core/audio_cache.py` | 16k wav 解码缓存（`cache_key` / `ensure_wav` / `peaks` / `prune`），转写与核对台波形共用一次解码；`KIKUSUB_AUDIO_CACHE=0` 关闭。partial 文件名带 pid + 随机后缀，支持取消。 |
| `core/jobs.py` | 进程内单槽任务注册表与 `CancelToken`：同一时间只允许一个重任务，取消只能由发起它的 Gradio session 发出。 |
| `core/procutil.py` | 可取消、带超时的子进程执行器（Popen + 读线程 + terminate/kill），ffmpeg/ffprobe 统一走这里。 |
| `core/logging_setup.py` | 日志落盘（`outputs/logs/kikusub.log`，5MB × 3 轮转）与后台线程 excepthook。 |
| `tests/` | pytest 回归；重依赖用例在轻量 CI 中自动 skip。 |
| `tools/eval/` | 纯标准库 SRT 评测台（CER/块准确率/劈词计数）；改断句或 VAD 参数前后必须跑同一区间。 |
| `static/` | 主题 CSS、核对台 JS、质检队列 JS/HTML、空态 HTML；`app.py` 启动时读取。JS 改动必须过 `node --check static/reviewer.js` 与 `node --check static/qa_panel.js`。 |
| `core/presets.py` | `presets.json` 的校验、向后兼容读取和原子写入。 |
| `presets.json` | 用户持久化的命名调参预设；属于运行数据，修改其 schema 时要兼容旧内容。 |
| `models/` | 模型缓存。`anime-whisper/` 与 `qwen3-asr-ja-anime/` 均可能很大，不应作为普通源码改动。 |
| `outputs/` | 生成的字幕样例和运行产物。 |
| `README.md` | 面向用户的安装、功能和调参说明；改变用户可见行为时同步更新。 |

## 3. 补漏核对工作台设计原则

- **监看画面与转录源解耦**：`review_payload` 的 `src` 有四种来源——自动跟随导入的媒体、手动导入的任意本地片源（`📂 导入监看画面`）、`outputs/web_proxies` 里的历史 480p 代理（`📦` 下拉，零拷贝）、以及「已关闭」空态。手动片源路径记录在 `outputs/monitor_last.json`，供下次打开自动恢复；`prepare_review_workspace`（即 `media.change`）会清空该记忆，重新回到自动模式。`src` 为空时前端必须销毁 `window.__reviewerInstance` 与 keydown 监听，避免悬空引用。
- 底部核对区由 `review_cues_state` 管理，和当前转写结果 `cues_state` 分离。导入 SRT 或“将本次转写设为基线”才会覆盖核对基线；“添加本次局部转写”追加去重后的条目。
- 视频播放器拖动进度条、播放时，底部音频轨道必须有高亮时间播放线（时间游标）实时同步跟随。
- **字幕叠加层两条硬约束**（改 `REVIEWER_CLIENT_JS` 时必须保持）：
  1. **多行聚合**：画面字幕由 `rebuildCaptionIndex()` 按 `(start, end)` 归并成「字幕块」，同区间的多条字幕（中日双语 SRT 的日/中两行）合并为多行渲染，行序沿用导入顺序。禁止退回 `cues.find(...)` 单条查找，否则双语只显示一行。`_unique_sorted_cues()` 的排序也因此保留原始下标做末位 tiebreak。
  2. **与视窗解耦**：`updateCaption()` 必须在 `updatePlayhead()` 中位于「播放头是否在可视区」的 early-return **之前**，任何缩放比例、光标位置、进度条拖动状态下都要更新，否则放大波形后播放会出现「字幕卡住不跳句」。
- 放大波形后播放时，视窗按「整页平移」跟随播放头（`ensurePlayheadVisible()`，落点约在窗口左侧 15%），工具栏 `#rw-follow-toggle` 可开关；播放中用户主动拖动/缩放波形会自动关闭跟随，避免框选区被拽走。
- 触控板缩放（捏合）与双指横移操作需精准平滑支持，允许将局部波形横向大幅放大（如放大至数秒区间），方便精细框选。
- 框选范围后，提供一键将该时间段同步到上方“时间片段截取”输入框（`slice-start`, `slice-end`），且能够联动更新上方的状态或者直接触发局部转录。
- 重新导入 SRT 时，必须彻底更新 `review_cues_state` 以及前端表格和波形展示，杜绝旧基线残留。
- **全链路撤回/重做体系 (Undo/Redo)**：由 `undo_stack_state` 与 `redo_stack_state` 管理，支持任意删除、单行更新、插入、清空、导入或追加操作后的无损撤回。前端通过 `Cmd+Z` (Mac) 或 `Ctrl+Z` (Windows/Linux) 及界面按钮触发撤回，`Cmd+Shift+Z` / `Ctrl+Shift+Z` / `Ctrl+Y` 触发重做。
- **高健壮性与防崩溃规范**：核对区所有操作函数在面对用户误操作（如空白时间、非法格式、越界行号）时，一律采用 `gr.Warning()` 友好提示并返回 `fallback` 保护当前已有字幕状态，严禁抛出未经处理的 `gr.Error()` 导致界面状态丢失；所有 Gradio 事件处理函数返回值的数量必须与 `outputs` 声明的组件列表严格一一对应。
- **断句改动必须有数字（2026-11）**：改 `qwen_ctc._break_costs` / `partition_cues` / VAD 参数前后，必须用 `python tools/eval/score_srt.py --reference ... --hypothesis ... --from ... --to ...` 跑同一区间，同时看 CER、`particle_start_cues`、`aux_start_cues`、最长条与 >4.3s 条数。禁止只凭个别样例“看起来更好”就改词边界；减少劈词与块均准确率之间存在已知取舍。
- **并发与取消（2026-11 加固）**：转写/局部转写必须通过 `jobs.JobRegistry` 单槽占用，**禁止**再引入模块级 `CANCEL_EVENT`。取消令牌必须归属于发起它的 Gradio session（`gr.Request.session_hash`）；别的窗口点「打断」只能收到“本会话没有任务”的提示，绝不能误伤正在跑的任务。客户端断开（GeneratorExit）只发取消信号，槽位由真正停止工作的 worker 在 `finally` 中释放，避免“界面已返回、模型还在跑”时被新任务覆盖。所有 `subprocess` 外部命令必须走 `procutil.run_command`（超时/取消/terminate），代理成片先写 `*.part.mp4` 再原子 rename。
- **压制进度只允许一个数据源**：`manual_transcode_proxy_generator` 是流式生成器，**禁止**再给它加 `progress=gr.Progress()` 或调用 `progress()`，`.click()` 也必须保持 `show_progress="hidden"`。Gradio 原生追踪器会被渲染进 `proxy_status` 容器，其文案还受「每 10% 一档（milestone）+ 两次换文案至少间隔 5 秒 + 文案 1 秒后自动清空」三重限制（见 `gradio/templates/frontend/assets/statustracker-*.js`），与卡片按 0.3s 刷新的真实百分比完全错拍，界面就会在「原生浮层」和「卡片」两种形态之间反复横跳（曾表现为 19% ↔ 33% 交替）。卡片样式统一走 `.ppc-*` 类并使用 `<div>/<b>/<em>`，不要用 `<span>` 内联样式——`.proxy-status-box span { ... !important }` 会把配色和字号全部覆盖掉。进度值还必须取单调最大值（`max_out_s`），并在时长探测失败时走 `pct=None` 的不确定进度态，绝不凭空造百分比。
- **全片转写进度也只允许一个数据源**：`transcribe_media` 的 `.then()` **必须**保持 `show_progress="hidden"`，并且**禁止**再调用 `progress()`。`show_progress="full"` 会把原生追踪器画进每一个 output 组件，于是「📊 全片转录原始结果、表格与任务详报」区域及以下会同时出现多条进度条，与顶部卡片错拍闪烁。进度只由 `_render_transcribe_progress_card()` 渲染进「3 输出与执行」的 `transcribe_progress`，样式走 `.tpc-*` 类（`<div>/<b>`），百分比同样取单调最大值。

## 4. 转录任务详报面板（禁止退回 Textbox）

- 「📊 全片转录原始结果、表格与任务详报」下的「转录任务报告」**必须**保持为 `gr.HTML` + `render_report_panel()`（`app.py` 中 `build_transcription_report` 之后），**不要改回 `gr.Textbox`**：Gradio 6 的 Textbox 会按内容自动增高并在 `overflow:hidden` / `overflow:scroll` 之间切换，长报告反复更新后会把文本框卡在裁切状态、无法上下滑动。
- 滚动能力由面板自带的 `.report-body { max-height: min(58vh, 520px); overflow-y: auto }` 提供，任何改版都不得移除该容器或改成依赖组件自身高度的方案。
- 详报的**纯文本原稿**藏在面板内 `<pre id="report-raw-text" class="report-raw-src">` 里，「📋 一键复制」按钮的 JS 直接读它的 `textContent`（事件 `inputs=None`），因此复制内容与旧版完全一致；改渲染逻辑时必须同步保留该 `<pre>`。
- 指标胶囊复用顶部设备胶囊的 `.device-chip`（`chip-label` 灰字 + `chip-value` 等宽粗体），面板底色 `#f8fafc` + 3px `#a5b4fc` 左边框，与 `.progress-status-box` 同源；`status` Markdown 也挂 `progress-status-box`，保证「界面顶部 / 报告区」两处视觉一致。
- 该折叠面板默认 `open=True`（用户要求首屏即可看到转写结果与详报）。
- 【幻觉门控】/【幻觉复核】的逐段明细必须留在报告里（用户明确要求"不要在终端刷屏、要能复制"）：数据源是 `AnimeWhisperEngine.last_segment_stats["hallucination_spans"]`（字段 `start/end/dur/text/rule/verdict/peak`，`verdict` 取 `dropped|suspect`），由 `app._hallucination_rows()` 渲染，明细最多列 `HALLUCINATION_SPAN_LIMIT` 条。`transcribe.py` 里这两类段的日志只允许 `log.debug`，不要再升回 `log.info`。

## 5. 质检待核队列（2026-11）

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

