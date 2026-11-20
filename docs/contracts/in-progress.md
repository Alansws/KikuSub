# 进行中的专项（跨会话必须能接上）

> 从 `AGENTS.md` 拆出（2026-11-16，AGENTS.md 有 20KB 上限）。这里记「做到哪、下一步是什么」；
> 方向与红线仍在 [AGENTS.md](../../AGENTS.md)，待办清单在 [backlog.md](../backlog.md)。

## P0 时机修复 + 拟声质检（2026-11-20 已落地）

- `core/timing_repair.py`：音频感知的句首静音拉回（保留 end）；`whisper.enable_start_repair`
  默认开。闸门：`head_removed` / 纯拟声 / 「…」+单双假名 / 单双假名保底。
- `nonverbal` 质检 kind：Whisper 与 Qwen 的纯喘息/笑声/拟声不再静默删除，进队列（最多 20 条）；
  `whisper.nonverbal_qa` 默认开，`qwen.nonverbal_qa` 默认关（Qwen 对呼吸声敏感，
  长片容易一次多出二十条待核；参数面板可手动打开），只改队列不改字幕。
- 同区间 `score_srt.py` 结果：Test 1 Whisper CER 9.80% / 漏块 9 / 最长 4.71s；
  Test 2 Whisper 15.48% / 13 / 3.82s；Test 2 Qwen 11.47% / 10 / 3.89s——三项均与基线逐项一致。
- 质检条数：Test 1 Whisper 85→88（+3 纯发声）、Test 2 Whisper 75→76（+1；
  评测卡同一跑为 77，属单次转写波动）、Test 2 Qwen 5→25（+20，命中 20 条上限）。
  **2026-11-20 复核后 `qwen.nonverbal_qa` 默认改 false**：Qwen 基线只有 5 条待核，
  打开后变成 25 条纯喘息，长片里太吵；参数保留，需要时手动开。
- 旧 112 条 Test 2 样本（用户提到的 0.6–0.89s 句首静音）离线复算：
  16 条高静音里拉回 6 条（0.51–0.84s），2 条「…むぅ/…んっ」按长叹词跳过，
  8 条 CPS 正常跳过。
- 当前默认 104 条 Test 2 直连诊断：`start_repair` 检查 90 段、拉回 0
  （head_removed 2 / 句首省略短叹 3 / 无静音 35 / 静音不足 0.55s 50），
  说明当前 VAD 分段本身已经够紧；旧 112 条样本是不同分段/参数下的历史产物。

## 转录引擎标定（四引擎均已完成一轮）

- Anime Whisper：[转录标定-AnimeWhisper-2026-11.md](../转录标定-AnimeWhisper-2026-11.md)
  （分窗 VAD、默认参数、句首尾发声剔除）。
- Qwen3-ASR + CTC：[转录标定-Qwen-2026-11.md](../转录标定-Qwen-2026-11.md)
  （分窗 VAD 是最大收益；内存建议已修正）。
- 中文两个引擎：[转录标定-中文-2026-11.md](../转录标定-中文-2026-11.md)
  （四处修复；脚本在 `tune/zh`）。
- **四引擎标定完成**：默认参数固化为引擎绑定预设，旧预设已删除；见
  [预设契约](params-and-presets.md)。
- **通用对齐层已落地**（`core/align_layer.py`）：借 Qwen 的 acoustic-only CTC 头给任意
  日语文本打逐字时间，Anime Whisper 侧是 `whisper.use_ctc_alignment`（默认关）。
  精度 p90 约 320ms，没到 ±150ms 门槛，所以没设默认；细节见
  [Qwen 标定文档](../转录标定-Qwen-2026-11.md) §4，门槛在 [backlog](../backlog.md) P1-5。

## 日语引擎优化路线

依据：[日语引擎优化路线-2026-11.md](../日语引擎优化路线-2026-11.md)。

- **P0-2 评测台已入库**：`tools/eval/` 的 `run_clip.py` / `probe_window.py` /
  `baseline.json`，用法与素材口径见 [tools/eval/README.md](../../tools/eval/README.md)（素材不随仓库）。
- **P0-1 已完成**：`qwen.vad_onset_pad_ms` 默认 400（Test 二 CER 13.42%→11.47%、句首缺字
  5→1；Test 一 12.97%→12.22%；长片不劣化），whisper 同改法 CER +1.61pt，**不启用**。
  闸门 `onset_gate` 只在 A/B 里用、不进参数面板（实测按文档口径无效）。
- **P0-3a 完成**：置信度特征 AUC 全 <0.75（最好 0.703），按止损线**不进 audit**；
  诊断脚本 `tools/eval/qwen_confidence_diag.py`。
- **P1-1 完成**：`kind="compare"` 只回文本；单句复核保留，批量复核入口已按双引擎重构删除；
  `transcribe_window()` + 空闲 180s 卸载。下一步 P1-3 词表 / P1-2 对齐 spike。
- **双引擎复核与工作流重构已完成**（S1–S4）：见
  [需求文档](../双引擎复核与工作流-需求-2026-11.md)。
