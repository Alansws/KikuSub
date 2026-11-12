# Gradio 旧界面（已归档，2026-11 移除）

> 从 `AGENTS.md` 拆出（2026-11-13）。`app.py` 与 `static/` 已从仓库移除，Gradio 界面归档在 Git 标签 `v0.9-gradio`。**以下是历史参考，禁止照它改代码**；现行实现见 `desktop/renderer/src/` 与 `server/routes_*.py`。

> 保留这份的理由：里面几条约束（幻觉门控明细、质检队列单一数据源）在桌面端换成了别的实现，但结论仍然有效；等桌面端对应逻辑也稳定后可以整份删掉。

---

### 4. 转录任务详报面板（Gradio 版，已归档）

> 本节描述的是已移出仓库的 `app.py` 界面；桌面端对应实现见 `desktop/renderer/src/views/` 与 `server/routes_report.py`。以下内容仅作历史参考。

- 「📊 全片转录原始结果、表格与任务详报」下的「转录任务报告」**必须**保持为 `gr.HTML` + `render_report_panel()`（`app.py` 中 `build_transcription_report` 之后），**不要改回 `gr.Textbox`**：Gradio 6 的 Textbox 会按内容自动增高并在 `overflow:hidden` / `overflow:scroll` 之间切换，长报告反复更新后会把文本框卡在裁切状态、无法上下滑动。
- 滚动能力由面板自带的 `.report-body { max-height: min(58vh, 520px); overflow-y: auto }` 提供，任何改版都不得移除该容器或改成依赖组件自身高度的方案。
- 详报的**纯文本原稿**藏在面板内 `<pre id="report-raw-text" class="report-raw-src">` 里，「📋 一键复制」按钮的 JS 直接读它的 `textContent`（事件 `inputs=None`），因此复制内容与旧版完全一致；改渲染逻辑时必须同步保留该 `<pre>`。
- 指标胶囊复用顶部设备胶囊的 `.device-chip`（`chip-label` 灰字 + `chip-value` 等宽粗体），面板底色 `#f8fafc` + 3px `#a5b4fc` 左边框，与 `.progress-status-box` 同源；`status` Markdown 也挂 `progress-status-box`，保证「界面顶部 / 报告区」两处视觉一致。
- 该折叠面板默认 `open=True`（用户要求首屏即可看到转写结果与详报）。
- 【幻觉门控】/【幻觉复核】的逐段明细必须留在报告里（用户明确要求"不要在终端刷屏、要能复制"）：数据源是 `AnimeWhisperEngine.last_segment_stats["hallucination_spans"]`（字段 `start/end/dur/text/rule/verdict/peak`，`verdict` 取 `dropped|suspect`），由 `app._hallucination_rows()` 渲染，明细最多列 `HALLUCINATION_SPAN_LIMIT` 条。`transcribe.py` 里这两类段的日志只允许 `log.debug`，不要再升回 `log.info`。

### 5. 质检待核队列（Gradio 版，已归档）

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
