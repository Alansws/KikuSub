# 进行中的专项（跨会话必须能接上）

> 从 `AGENTS.md` 拆出（2026-11-16，AGENTS.md 有 20KB 上限）。这里记「做到哪、下一步是什么」；
> 方向与红线仍在 [AGENTS.md](../../AGENTS.md)，待办清单在 [backlog.md](../backlog.md)。

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
