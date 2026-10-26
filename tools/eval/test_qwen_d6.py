"""Qwen 侧 D6 接线断言（不加载模型）。

覆盖三件事：
1. `_char_times_in_span` 把 CTC 逐字时间映射成与 cue 文本等长的序列（零宽字沿用前字）；
2. `_cues_from_alignment` 对超过 `max_cue_dur` 的条**用字级时间戳**再切一刀（D6 第一优先级）；
3. 对齐降级 / 关闭对齐时，`_cues_fallback` 走能量谷分支（第二优先级），不退回按时间对半。

另含：Qwen 与 Whisper 的默认 VAD 阈值一致性、`chunk_level_stats`（E5 的 peak/rms）。

运行：python tools/eval/test_qwen_d6.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)

import qwen_ctc as Q  # noqa: E402
import transcribe as T  # noqa: E402
from qwen_ctc import AlignedChar, AlignmentResult, FoldedText, QwenCtcConfig, QwenCtcEngine  # noqa: E402

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(f"{'✅' if ok else '❌'} {msg}")
    if not ok:
        fails.append(msg)


# ---------------- 1. 字级时间映射 ----------------
chars = [
    AlignedChar(pos=0, char="今", start=0.0, end=0.5),
    AlignedChar(pos=1, char="日", start=0.5, end=1.0),
    AlignedChar(pos=2, char="は", start=1.0, end=1.4),
    AlignedChar(pos=4, char="い", start=1.4, end=1.9),   # pos=3 是不发声的字（零宽）
]
times = Q._char_times_in_span(chars, 0, 5, offset=10.0, cue_start=9.9)
check(len(times) == 5, f"映射长度与 cue 文本等长（{len(times)} == 5）")
check(times[3] == (times[2][1], times[2][1]), "零宽字沿用前一个字的结束时间")
check(abs(times[0][0] - 0.1) < 1e-9, f"时间相对 cue 起点（{times[0][0]:.2f}s）")
check(abs(times[4][1] - 2.0) < 1e-9, f"末字结束时间对齐 CTC（{times[4][1]:.2f}s = 10.0+1.9-9.9）")

# ---------------- 2. 对齐路径的超长条：用 char_times 切 ----------------
cfg = QwenCtcConfig()
text = "今日はいい天気ですね"
folded = FoldedText(text)
n = len(folded)
aligned = [
    AlignedChar(pos=i, char=folded.folded[i], start=i * 0.5, end=i * 0.5 + 0.5)
    for i in range(n)
]
result = AlignmentResult(chars=aligned, pauses=[], ok=True)

orig_partition = Q.partition_cues
Q.partition_cues = lambda char_spans, *a, **k: [list(range(len(char_spans)))]  # 强制单组
try:
    eng = QwenCtcEngine.__new__(QwenCtcEngine)   # 不走 __init__，不加载模型
    cues = eng._cues_from_alignment(result, offset=0.0, folded=folded, cfg=cfg)
finally:
    Q.partition_cues = orig_partition

check(len(cues) == 2, f"超长条被切开（{len(cues)} 条）")
check("".join(c.text for c in cues) == text, "文本守恒")
expect_cut = aligned[2].end        # nearest_text_cut → 切在「は」后（text[:3]），即第 3 个字结束处
check(abs(cues[0].end - expect_cut) < 1e-6,
      f"切点取自 CTC 逐字时间（{cues[0].end:.2f}s == {expect_cut:.2f}s）")
check(all(c.end - c.start <= cfg.max_cue_dur for c in cues), "全部 ≤ max_cue_dur")
check(cues[0].end == cues[1].start, "两条首尾相接")

# 同样的文本若不给 char_times，会走比例分支、切点不同 —— 证明第一优先级真的生效
no_ct = T._split_overlong_single(text, 0.0, 5.12, cfg.max_cue_dur)
check(no_ct[0][1] != expect_cut, f"无时间戳时切点不同（{no_ct[0][1]:.2f}s vs {expect_cut:.2f}s）")

# ---------------- 3. 降级/关闭对齐：能量谷分支 ----------------
sr = 16000
dur = 5.0
audio = np.random.RandomState(0).normal(0, 0.05, int(sr * dur)).astype(np.float32)
audio[int(2.9 * sr):int(3.1 * sr)] *= 0.01
eng2 = QwenCtcEngine.__new__(QwenCtcEngine)
fb = eng2._cues_fallback("あいうえおかきく", 0.0, dur, cfg, audio=audio)
check(len(fb) == 2, f"降级路径也切开（{len(fb)} 条）")
check("".join(c.text for c in fb) == "あいうえおかきく", "文本守恒（降级路径）")
check(abs(fb[0].end - 3.0) < 0.25, f"切点吸附到能量谷（{fb[0].end:.2f}s）")

# ---------------- 4. 双引擎默认阈值一致 ----------------
check(QwenCtcConfig().vad_threshold == T.VAD_THRESHOLD,
      f"Qwen 与 Whisper 默认阈值一致（{QwenCtcConfig().vad_threshold} == {T.VAD_THRESHOLD}）")

# ---------------- 5. E5 电平统计 ----------------
silent = T.chunk_level_stats(np.zeros(1600, dtype=np.float32))
tone = T.chunk_level_stats((0.5 * np.sin(np.linspace(0, 200, 1600))).astype(np.float32))
check(silent["peak"] == 0.0 and silent["rms"] == 0.0, "静音段 peak/rms 为 0")
check(0.45 < tone["peak"] <= 0.5 and 0.3 < tone["rms"] < 0.4, f"有声段电平正确（{tone}）")
check(T.chunk_level_stats(None) == {"peak": 0.0, "rms": 0.0}, "空数组不抛异常")

print()
print("全部通过" if not fails else f"{len(fails)} 项失败")
raise SystemExit(1 if fails else 0)
