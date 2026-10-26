"""误差归因：把每个参考台词块的错误，归到「VAD 没送模 / 模型没出字 / 识别错」三档。

判据（全部基于用户那次实测的 VAD 参数 0.45/120/150/200 与产物 whisper.srt）：
- VAD 覆盖：该块时长内被 VAD 合并段覆盖 >= 0.3s 且 >= 块时长 25%；
- 产物覆盖：有转录条与该块重叠 >= 0.25s；
- 正确：该块逐字对齐命中率 >= 0.6。
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
from eval_lib import evaluate, fmt_t, load_reference, parse_srt  # noqa: E402

SR = 16000
audio, _ = sf.read(f"{ROOT}/outputs/eval/full16k.wav", dtype="float32")
ref = load_reference(f"{ROOT}/测试用_言叶之庭_中日双语.srt")
hyp = parse_srt(f"{ROOT}/测试用_言叶之庭.whisper.srt")

vad = load_silero_vad()
stamps = get_speech_timestamps(
    torch.from_numpy(audio), vad, sampling_rate=SR, threshold=0.45,
    min_speech_duration_ms=120, min_silence_duration_ms=150, speech_pad_ms=200,
    neg_threshold=vad_neg_threshold(0.45),
)
segs = merge_vad_segments(stamps, max_segment_s=12.0, merge_gap_s=0.3, audio=audio)
spans = [(s / SR, e / SR) for s, e in segs]


def ov(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


ev = evaluate(ref, hyp)
by_start = {round(b["start"], 3): b for b in ev["blocks"]}

buckets = {"vad_miss": [], "model_miss": [], "wrong": [], "ok": []}
for b in ev["blocks"]:
    dur = b["end"] - b["start"]
    vad_cov = sum(ov(b["start"], b["end"], s, e) for s, e in spans)
    hyp_cov = sum(ov(b["start"], b["end"], h["start"], h["end"]) for h in hyp)
    vad_ok = vad_cov >= 0.3 and vad_cov >= 0.25 * dur
    hyp_ok = hyp_cov >= 0.25
    if b["acc"] >= 0.6:
        buckets["ok"].append((b, vad_cov, hyp_cov))
    elif not vad_ok:
        buckets["vad_miss"].append((b, vad_cov, hyp_cov))
    elif not hyp_ok:
        buckets["model_miss"].append((b, vad_cov, hyp_cov))
    else:
        buckets["wrong"].append((b, vad_cov, hyp_cov))

print(f"参考块 {len(ev['blocks'])} 个，逐块归因：")
for k, label in [("ok", "基本正确(≥60%)"), ("wrong", "识别错(有字但错)"),
                 ("model_miss", "VAD有覆盖但没出字"), ("vad_miss", "VAD 完全没覆盖")]:
    v = buckets[k]
    chars = sum(b["chars"] for b, _, _ in v)
    print(f"  {label:22s} {len(v):3d} 块 / {chars:4d} 字  ({len(v)/len(ev['blocks'])*100:4.1f}%)")

print("\n【VAD 完全没覆盖】按时间排序（前 30）:")
for b, vc, hc in sorted(buckets["vad_miss"], key=lambda x: x[0]["start"])[:30]:
    print(f"  {fmt_t(b['start'])}→{fmt_t(b['end'])} {b['chars']:2d}字 {b['ref'][:42]}")

print("\n【VAD 有覆盖但没出字】全部:")
for b, vc, hc in sorted(buckets["model_miss"], key=lambda x: x[0]["start"]):
    print(f"  {fmt_t(b['start'])}→{fmt_t(b['end'])} vad_cov={vc:4.1f}s {b['chars']:2d}字 {b['ref'][:42]}")

print("\n【识别错】准确率最低 15 个:")
for b, vc, hc in sorted(buckets["wrong"], key=lambda x: x[0]["acc"])[:15]:
    print(f"  {fmt_t(b['start'])} acc={b['acc']*100:4.0f}% {b['ref'][:40]}")

json.dump(
    {k: [{"start": b["start"], "end": b["end"], "ref": b["ref"], "acc": b["acc"],
          "vad_cov": vc, "hyp_cov": hc} for b, vc, hc in v] for k, v in buckets.items()},
    open(f"{ROOT}/outputs/eval/attribution.json", "w"), ensure_ascii=False, indent=1)

# 按区间汇总三档占比
print("\n按 10 分钟分档（块数）：")
for t0 in range(0, 2760, 600):
    t1 = t0 + 600
    row = []
    for k in ("ok", "wrong", "model_miss", "vad_miss"):
        row.append(sum(1 for b, _, _ in buckets[k] if t0 <= b["start"] < t1))
    print(f"  {t0//60:2d}-{t1//60:2d}min  正确{row[0]:3d} 错{row[1]:3d} 模型漏{row[2]:3d} VAD漏{row[3]:3d}")
