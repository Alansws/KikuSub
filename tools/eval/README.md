# tools/eval — 客观评测台

把「转录结果好不好」变成可复核的数字。所有脚本都**不依赖 Gradio**，直接调用引擎，
因此不受「改了代码没重启 app.py」这类事故影响。

## 1. 先决条件（两份素材不入库）

`.gitignore` 把本地测试素材排除了（体积 / 版权原因），换机器时需自备：

| 素材 | 位置 | 生成方式 |
|---|---|---|
| 参考字幕 | `测试用_言叶之庭_中日双语.srt` | 自备（双条目同时间轴写法） |
| 16k 单声道音频 | `outputs/eval/full16k.wav` | `ffmpeg -i 测试用_言叶之庭.mkv -vn -ar 16000 -ac 1 outputs/eval/full16k.wav` |

基线产物 `tools/eval/baseline_474.srt` **在库里**，用于回归比对。

依赖：`soundfile` / `torch` / `silero-vad` / `rapidfuzz`（与主程序同一份 venv）。

## 2. 快速开始

```bash
PY=/Users/sws/.workbuddy-ai/binaries/python/envs/default/bin/python

# ① 评测台自检：参考口径 + 基线指标是否与文档一致（8 秒，不跑模型）
$PY tools/eval/scorecard.py --selftest

# ② 给任意一份产物打分（--vad 顺带统计 VAD 不达标块，需加载音频）
$PY tools/eval/scorecard.py tools/eval/baseline_474.srt --vad 0.45

# ③ E1 全局阈值扫描（单变量：只改 threshold，4 档 ≈ 15 分钟）
$PY tools/eval/sweep_threshold.py --thresholds 0.45,0.35,0.30,0.25

# ④ 全量断言（都不加载模型，全部秒级）
for t in test_impl test_a5 test_p4 test_d6 test_qwen_d6; do $PY tools/eval/$t.py; done
```

`scorecard.py` 的 stdout 末尾固定一行 TSV（表头见 `HEADER`），方便脚本汇总；
`--json` 可把同一份结果落盘。

## 3. 脚本清单

| 脚本 | 作用 | 是否跑模型 |
|---|---|---|
| `eval_lib.py` | 参考字幕解析、字符级对齐、CER / 块准确率 / 边界 / cps | 否 |
| `scorecard.py` | **一行指标**（全片 + 去歌 CER、块均、漏块、插入、VAD 不达标、超长条）＋ 自检 | 否 |
| `sweep_threshold.py` | E1 阈值扫描，产出 `outputs/eval/sweep/`（srt + results.json + summary.md） | 是（全片 ×N） |
| `analyze.py` | 全片归因：逐块分档（正确 / 识别错 / VAD 没覆盖 / 有覆盖没出字）、逐 5 分钟、A3 漏句核对 | 否（用已有产物 + VAD） |
| `attribution.py` | 同上但更早的版本，只做分档 | 否 |
| `vad_recall.py` | 多组 VAD 配置的召回率对照（覆盖率 / 零覆盖块） | 否 |
| `exp_full.py` | 全片复现基线（0.45 参数），与交付版逐条比对 | 是 |
| `exp_det.py` | 确定性检验：同参数再跑一遍，逐条比对 | 是 |
| `exp_whisper.py` | A1 切点吸附 / A3 空段重试 / A5 禁切点的对照实验 | 是 |
| `exp_more.py` | A1 等长位移对照、A5 干净口径、BGM 逐段诊断 | 是 |
| `exp_qwen.py` | Qwen 侧 A6 四桶 / P4 撞上限分类 | 是 |
| `exp_bgm_cause.py` | 42:00–44:20 只有 1 条的成因（响度档位 / 可复现性） | 是 |
| `perf.py` | P1 解码缓存 / P6 波形落盘 / P7 禁切点预计算的计时 | 否 |
| `test_impl.py` / `test_a5.py` / `test_p4.py` / `test_d6.py` / `test_qwen_d6.py` | 回归断言（报告渲染 / 原子写 / 缝合闸门 / P4 / A5 禁切 / D6 切分 / Qwen 字级时间接线 / E5 漏句降噪） | 否 |

所有脚本的 `ROOT` 由 `Path(__file__).resolve().parents[2]` 推导，仓库可整体搬走；
数据一律写 `outputs/eval/`（已 gitignore），脚本与基线 SRT 留在 `tools/eval/`。

## 4. 口径（与 `docs/优化效果实测报告-第一批与第二批.md` 一致）

- **参考**：482 块 / 5315 字，覆盖 00:38–45:36。双语 SRT 按 `(start, end)` 归并取含假名那条；
  制作组信息与无假名条目（画面文字 / 译注）剔除。
- **全片 CER** = (S + D + I) / 5315，字符级 Levenshtein（`rapidfuzz`）。
- **去歌 CER**：只统计 42:00（2514s）之前的参考块与产物。42:00 之后是主题歌《Rain》的歌词，
  任何 ASR 都不可能低 CER，必须与全片分开看。
- **块均准确率**：482 块逐块命中率均值（用全局对齐的 ops 反推，天然容忍 1→N 切分）。
- **漏块**：块准确率 < 35% 且 ≥3 字。
- **插入字数**：全局对齐的 `ins`，即幻觉量，**硬约束 ≤90**。
- **VAD 不达标块**：参考块时长内被 VAD 合并段覆盖 ≥0.3s **且** ≥块时长 25% 才算达标。

## 5. 基线（2026-10-26，Whisper 侧，MPS）

| 指标 | 值 |
|---|---|
| 全片 CER | 25.08%（S357 / D907 / I69） |
| 去歌 CER | 23.34% |
| 块均准确率 | 70.5% |
| 漏块 | 92 |
| 插入字数 | 69 |
| 字幕条数 | 474 |
| VAD 不达标块（0.45/120/150/200） | 82 / 763 字 |
| 最长条 / >4.3s | 6.10s / 10 条 |
| 转写耗时（46 分钟片） | 203–217s |

## 6. 纪律

1. **一次只改一个变量**。要动 VAD 就只动 VAD，要动合并参数就只动合并参数，
   两者混在一起跑出来的差异无法归因。
2. **每份记录都要报插入字数**。召回类改动的唯一失败模式就是音乐/雨声段幻觉，
   CER 降了但插入涨到 90 字以上，一律回退。
3. **确定性已验证**（同参数两次全片 474 条逐条一致），单次 A/B 可信；但**不要跨设备比较**。
4. 参考字幕含站内广播 / 电视新闻，VAD 天然难覆盖，**不追 100% 召回**。
