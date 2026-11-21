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

## P1 VAD 后端 A/B（2026-11-20 已收口）

- `core/vad.py` 只保留两个经过验证的后端：`silero`（20s 窗，无额外权重）与
  `whisperseg`（推荐）。TEN 的适配移到 `tools/eval/ten_backend.py`，不再进内核。
- Test 二全片：WhisperSeg + 合并上限修复后 CER **10.67%**（Silero20 15.48%）、
  插入 64（90）、耗时 60.0s（127.5s）、质检 10（76）、参考条覆盖 100%、
  负样本 0 误报、>4.3s **0**（原 6）。
- 13 条「漏块」已逐条还原：13/13 的参考文本都在最终字幕里，0 条被门控删除；
  是 `score_srt.py` 的块准确率把跨边界整条字幕算进来造成的切分点误报，不是
  ASR 漏识别，也不是 VAD 没切到（详见 P1 文档 §7.1）。
- 超长条的真因是 `merge_fragmented_cues` 的 `+0.6s` 容差，不是 VAD 段过长：
  只把容差收回 `max_cue_dur`，CER/插入/漏块不变，>4.3s 6→0；压短送模段
  （4.0–4.3s）反而 CER +0.2–1.0pt、耗时 +30–60%。
- 默认切分器已改为 **WhisperSeg**；Silero 20s 保留为兼容选项。Qwen 固定 Silero
  （同一后端在 Qwen 上 CER +1.14pt），参数只对 Whisper 开放。
- 权重走 `core/model_fetch.py`（hf-mirror 回退）落到 `models/whisperseg/`；
  设置页「引擎与模型 → 切分器权重」可看就绪状态并预下载，首次转写也带进度下载。
- 详见 [P1-VAD后端AB实验方案-2026-11-20.md](../P1-VAD后端AB实验方案-2026-11-20.md) §7。
- **P2 已收官（2026-11-20 晚）**：单槽双引擎顺序协同——主引擎写主稿，副引擎只读
  进第二列；两侧用不同 VAD（Qwen 配 Silero、Whisper 配 WhisperSeg），中间强制
  `release()` + `mps.empty_cache()` 并过可用内存闸门；副稿经去重/置信度筛选后
  以 `ensemble` 进质检。设计见 [P2-双引擎顺序协同设计-2026-11-20.md](../P2-双引擎顺序协同设计-2026-11-20.md)。
  真机组合全部跑通（`tools/eval/dual_regression.py`，产物 `outputs/eval/p2_full/`）：
  - 整片：主 Qwen + 副 Whisper 120.6s / 主 Whisper + 副 Qwen 见 §P2 收官复验；
  - 区间 `replace_range`：预置跨区间旧第二列，范围外逐字不变、范围内被副稿替换；
  - 区间 + 人声分离 `vad_only`：两个 pass 的 `vad_audio_path` 都指向同一份分离人声，
    `separate_to_wav` 调用 0 次（缓存复用），Pass A 后释放 Whisper 再启动 Qwen。

## P3 人声分离「仅用于 VAD」（2026-11-20 收官）

- 默认档 `vad_only`：Demucs 只喂 VAD，ASR 仍读原声；高级档 `to_asr` 保留
  「分离人声送识别」。设计、实现与对照数字见
  [P3-人声分离仅VAD-2026-11-20.md](../P3-人声分离仅VAD-2026-11-20.md)。
- 关键验收（`tools/eval/sep_ab.py`）：
  - 言叶之庭 40:10–41:10 歌曲段：plain 24.26% → **vad_only 21.32%**（漏块 9→8、
    插入 9→7）；to_asr 16.18%（高级档在纯歌声段仍更强）。
  - Test 二 1:40–2:40 对白段：plain 与 **vad_only 同为 7.76%**；
    to_asr 退化到 11.21%——分离削清辅音的风险被实测证实。
  - 两组 plain / vad_only 的 ASR 16k wav sha256 相同（逐字节一致），
    收益只来自 VAD 边界。
- 参数面板：VAD 阈值旁显示当前切分器的标定推荐（WhisperSeg 0.35 / Silero 0.25），
  一击「用 0.35」；「句首提前」标记为仅 Silero 生效并置灰（代码里也按实际使用的
  后端门控，不会出现 UI 与行为不一致）。

### P3 后续：人声绝对能量门控（2026-11-21）

- 现象：`vad_only` 下 Demucs 的 vocals 在纯音乐/环境段并不是绝对零，WhisperSeg 会把
  -76～-85 dBFS 的串音判成语音；`dynaudnorm` 再把底噪抬起来，ASR 于是产出
  「ちゅぅ…」这类幻觉字幕（dpmx-014 片头 27.6s / 40.1s / 64.2s）。
- 为什么没有让 VAD 直接听 raw：实测把 VAD 参考换成 `enable_loudnorm=False` 后，
  言叶之庭 40:10–41:10 歌曲段 `vad_only` CER **21.32% → 25.74%**（插入 7→10），
  违反红线 4。最终**保留 dynaudnorm 做检测**，另解一份未归一化的 vocals 电平，
  只给门控用——检测边界与 CER 都不动。
- 实现：`core/vad.py` 的 `VOCAL_GATE_DBFS = -65.0` 与 `gate_stamps_by_energy()`；
  Whisper / Qwen / Sherpa 三条引擎在 VAD 之后、clamp/merge 之前门控；
  `load_wav_mono(peak_gain_out=…)` 用于还原峰值归一化增益（否则 -85 dBFS 的段会被
  放大 85 倍后看起来是 -50，门控失效）。
- 标定（dpmx-014，2h48m）：幻觉段 -76～-85 dBFS，真实对白中位 -33.8 dBFS；
  -65 丢 57/1101 段（128.5s），-60 会误删 -60.3 dBFS 的轻声句。
- A/B：两个评测区间 `vad_only` 的 CER / 漏块 / 插入与基线逐项一致
  （21.32% / 7.76%），ASR 16k wav sha256 相同，门控丢弃 0 段。
- 全片：VAD 1079→1022 段；对现有 1282 条主稿逐条门控只删 **6 条（0.47%）**。
  **能量门控只治近静音幻觉**，不解决占多数、确实有人声能量的喘息/拟声条目。
- 0–90s 真重跑：3 条幻觉（-85.2 / -76.5 / -80.8 dBFS）→ 0 条。

## 转写页布局与协同联动（2026-11-20 收官）

- 左栏拆成「基础设置与范围 / 结果与协同模式 / 已有字幕」三张轻卡片，提示独占一行，
  修掉「本次整片结果替换当前核对台」被挤成单字换行的问题。
- 「双引擎协同」选「顺序跑副引擎」时：结果去向固定为主稿→核对台、副稿→第二列 +
  补漏质检，隐藏互斥的「结果去向」档位；卡片内直接显示主/副配对与「交换主副」
  （交换会同步上方「识别引擎」），并且不再提供服务端会拒绝的「追加」。
- 右栏「VAD 切分器」下拉加宽到 200px，并在右栏被挤窄时按容器宽度退回单列，
  任何窗口宽度下都完整显示「WhisperSeg（推荐）」/「Silero 20s（兼容）」。
- 取证：`--screenshot` 无窗口截图（1440×960 light/dark、1180×900 窄屏）逐张
  `read_image` 自查；断言「用 0.35」与交换主副在真实页面里生效。

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
