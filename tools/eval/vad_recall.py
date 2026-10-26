"""VAD 召回率分析：转录漏句到底是"模型没听出来"还是"VAD 没送去听"。

对每个 VAD 配置，计算：
- VAD 语音总时长 / 覆盖率
- 参考字幕（台词）时间轴的**覆盖率**：参考台词时长中被 VAD 判为语音的比例
- 完全没被任何 VAD 段覆盖的参考块数量（= 模型根本没机会看到）
"""
import json
import sys
from pathlib import Path

import soundfile as sf
import torch

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from silero_vad import get_speech_timestamps, load_silero_vad  # noqa: E402
from transcribe import merge_vad_segments, vad_neg_threshold  # noqa: E402
from eval_lib import fmt_t, load_reference  # noqa: E402

WAV = f"{ROOT}/outputs/eval/full16k.wav"
SR = 16000

audio, sr = sf.read(WAV, dtype="float32")
assert sr == SR, sr
ref = load_reference(f"{ROOT}/测试用_言叶之庭_中日双语.srt")
total = len(audio) / SR
ref_total = sum(b["end"] - b["start"] for b in ref)
print(f"音频 {total:.2f}s，参考台词块 {len(ref)} 个 / 总时长 {ref_total:.1f}s")


def cover_ratio(spans, blocks):
    """参考块时长中，被 spans 覆盖的比例（并集）。"""
    covered = 0.0
    zero = 0
    for b in blocks:
        acc = 0.0
        for s, e in spans:
            acc += max(0.0, min(e, b["end"]) - max(s, b["start"]))
        covered += min(acc, b["end"] - b["start"])
        if acc <= 1e-6:
            zero += 1
    return covered / max(ref_total, 1e-9), zero


CONFIGS = [
    ("whisper实测 0.45/120/150/200", 0.45, 120, 150, 200, 12.0, 0.3),
    ("默认 0.28/100/200/150", 0.28, 100, 200, 150, 20.0, 0.5),
    ("qwen默认 0.28/100/200/150 max16", 0.28, 100, 200, 150, 16.0, 0.5),
    ("低阈值 0.08/100/200/150", 0.08, 100, 200, 150, 16.0, 0.5),
    ("宽松 0.20/80/120/200", 0.20, 80, 120, 200, 16.0, 0.5),
]

vad = load_silero_vad()
rows = []
for name, th, minsp, minsil, pad, maxseg, gap in CONFIGS:
    stamps = get_speech_timestamps(
        torch.from_numpy(audio), vad, sampling_rate=SR,
        threshold=th, min_speech_duration_ms=minsp,
        min_silence_duration_ms=minsil, speech_pad_ms=pad,
        neg_threshold=vad_neg_threshold(th),
    )
    raw = sum((s["end"] - s["start"]) for s in stamps) / SR
    stats = {}
    segs = merge_vad_segments(stamps, max_segment_s=maxseg, merge_gap_s=gap,
                              audio=audio, snap_stats=stats)
    spans = [(s / SR, e / SR) for s, e in segs]
    cov, zero = cover_ratio(spans, ref)
    rows.append(dict(name=name, stamps=len(stamps), raw_s=raw, raw_ratio=raw / total,
                     segs=len(segs), blocks=stats.get("blocks"),
                     forced=stats.get("forced_cuts"), snapped=stats.get("snapped_cuts"),
                     max_block=stats.get("max_block_s"), cover=cov, zero=zero))
    print(f"{name:32s} VAD段{len(stamps):4d} 语音{raw:7.1f}s({raw/total*100:5.1f}%) "
          f"合并块{stats.get('blocks'):3d} 最长{stats.get('max_block_s'):5.1f}s "
          f"强制切分{stats.get('forced_cuts'):3d}/吸附{stats.get('snapped_cuts'):3d} "
          f"→ 参考台词覆盖 {cov*100:5.1f}%  完全未覆盖块 {zero:3d}/{len(ref)}")

json.dump(rows, open(f"{ROOT}/outputs/eval/vad_recall.json", "w"), ensure_ascii=False, indent=1)

# 逐区间：默认参数下哪段台词完全没被覆盖
stamps = get_speech_timestamps(
    torch.from_numpy(audio), vad, sampling_rate=SR, threshold=0.28,
    min_speech_duration_ms=100, min_silence_duration_ms=200, speech_pad_ms=150,
    neg_threshold=vad_neg_threshold(0.28),
)
segs = merge_vad_segments(stamps, max_segment_s=20.0, merge_gap_s=0.5, audio=audio)
spans = [(s / SR, e / SR) for s, e in segs]
print("\n默认参数下完全未被 VAD 覆盖的参考块（前 25 个）:")
n = 0
for b in ref:
    acc = sum(max(0.0, min(e, b["end"]) - max(s, b["start"])) for s, e in spans)
    if acc <= 1e-6:
        n += 1
        if n <= 25:
            print(f"  {fmt_t(b['start'])}→{fmt_t(b['end'])} {b['text'][:44]}")
print(f"  合计 {n} 个")
