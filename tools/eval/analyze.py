"""基线评测 + 误差归因（不跑模型，只用已有产物与 VAD）。

产物：outputs/eval/analysis.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_lib import (  # noqa: E402
    evaluate, load_reference, parse_srt, region_slice, fmt_t,
)
from transcribe import merge_vad_segments, vad_neg_threshold  # noqa: E402
from silero_vad import get_speech_timestamps, load_silero_vad  # noqa: E402

SR = 16000
SONG_T0 = 2514.0          # 主题歌《Rain》起点：参考字幕里是歌词，ASR 本就对不上，单独统计
BGM_T0, BGM_T1 = 2520.0, 2660.0   # 用户指定的 BGM 区间 42:00 → 44:20

audio, sr = sf.read(f"{ROOT}/outputs/eval/full16k.wav", dtype="float32")
assert sr == SR
DUR = len(audio) / SR
ref_all = load_reference(f"{ROOT}/测试用_言叶之庭_中日双语.srt")
raw = parse_srt(f"{ROOT}/outputs/测试用_言叶之庭.srt")
clean = parse_srt(f"{ROOT}/outputs/测试用_言叶之庭.clean.srt")

# 默认用用户交付的 clean 版；可传参指定其它产物
HYP_PATH = sys.argv[1] if len(sys.argv) > 1 else f"{ROOT}/outputs/测试用_言叶之庭.clean.srt"
OUT_PATH = sys.argv[2] if len(sys.argv) > 2 else f"{ROOT}/outputs/eval/analysis.json"
hyp = parse_srt(HYP_PATH)


def ov(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def coverage(blocks, spans):
    out = []
    for b in blocks:
        acc = sum(ov(b["start"], b["end"], s, e) for s, e in spans)
        out.append(min(acc, b["end"] - b["start"]))
    return out


def summarize(tag, blocks, cues):
    ev = evaluate(blocks, cues)
    return {
        "tag": tag,
        "n_blocks": len(blocks),
        "n_ref_chars": ev["n_ref_chars"],
        "cer": ev["cer"], "sub": ev["sub"], "del": ev["del"], "ins": ev["ins"],
        "acc_mean": ev["acc_mean"], "acc_median": ev["acc_median"],
        "p95": ev["p95"], "p90": ev["p90"], "p80": ev["p80"], "p50": ev["p50"],
        "miss_blocks": len(ev["miss_blocks"]),
        "del_spans": ev["del_spans"],
        "ins_spans": ev["ins_spans"],
        "boundary": ev["boundary"],
        "cps": {k: v for k, v in ev["cps"].items() if k != "worst"},
        "blocks": ev["blocks"],
        "ev": ev,
    }


def cues_in(cues, t0, t1):
    return [c for c in cues if ov(c["start"], c["end"], t0, t1) > 0]


# ---------------- 1. 全片 / 分区 ----------------
full = summarize("full", ref_all, hyp)
no_song = summarize("no_song", [b for b in ref_all if b["start"] < SONG_T0],
                    cues_in(hyp, 0, SONG_T0))
song = summarize("song", [b for b in ref_all if b["start"] >= SONG_T0],
                 cues_in(hyp, SONG_T0, DUR))
bgm = summarize("bgm_42-44m20", region_slice(ref_all, BGM_T0, BGM_T1),
                cues_in(hyp, BGM_T0, BGM_T1))
pre_song = summarize("bgm_42-44m20_no_song", region_slice(ref_all, BGM_T0, min(BGM_T1, SONG_T0)),
                     cues_in(hyp, BGM_T0, min(BGM_T1, SONG_T0)))

print(f"音频 {DUR:.1f}s  参考块 {len(ref_all)}  产物条 {len(hyp)}（raw {len(raw)}）")
for s in (full, no_song, song, bgm):
    c = s["cps"]
    print(f"{s['tag']:22s} 块{s['n_blocks']:4d} 字{s['n_ref_chars']:5d} "
          f"CER {s['cer']*100:5.2f}% (S{s['sub']}/D{s['del']}/I{s['ins']}) "
          f"块均{s['acc_mean']*100:5.1f}% 漏块{s['miss_blocks']:3d} "
          f"cps中位{c.get('cps_median',0):4.1f} 最长条{c.get('dur_max',0):4.1f}s")

# ---------------- 2. VAD 覆盖（用户那次的参数） ----------------
vad = load_silero_vad()
stamps = get_speech_timestamps(
    torch.from_numpy(audio), vad, sampling_rate=SR, threshold=0.45,
    min_speech_duration_ms=120, min_silence_duration_ms=150, speech_pad_ms=200,
    neg_threshold=vad_neg_threshold(0.45),
)
seg_stats = {}
segs = merge_vad_segments(stamps, max_segment_s=12.0, merge_gap_s=0.3,
                          min_speech_s=0.08, audio=audio, snap_stats=seg_stats)
spans = [(s / SR, e / SR) for s, e in segs]
print(f"VAD: {len(stamps)} 段 / {sum((s['end']-s['start']) for s in stamps)/SR:.1f}s  "
      f"合并块 {seg_stats['blocks']} 最长 {seg_stats['max_block_s']:.2f}s "
      f"强制切分 {seg_stats['forced_cuts']} 吸附 {seg_stats['snapped_cuts']}")

# A1 关闭（cut_snap_s=0）与开启的段边界差异
segs_off = merge_vad_segments(stamps, max_segment_s=12.0, merge_gap_s=0.3,
                              min_speech_s=0.08, audio=audio, cut_snap_s=0.0)
print(f"cut_snap 0 vs 0.4 段边界完全一致: {segs == segs_off}")

# ---------------- 3. 逐块归因 ----------------
ref_cov = coverage(ref_all, spans)
hyp_cov = coverage(ref_all, [(c["start"], c["end"]) for c in hyp])
buckets = {"ok": [], "wrong": [], "model_miss": [], "vad_miss": []}
for b, vc, hc in zip(full["blocks"], ref_cov, hyp_cov):
    dur = b["end"] - b["start"]
    if b["acc"] >= 0.6:
        buckets["ok"].append((b, vc, hc))
    elif not (vc >= 0.3 and vc >= 0.25 * dur):
        buckets["vad_miss"].append((b, vc, hc))
    elif hc < 0.25:
        buckets["model_miss"].append((b, vc, hc))
    else:
        buckets["wrong"].append((b, vc, hc))

print("\n逐块归因：")
attr = {}
for k, label in (("ok", "基本正确≥60%"), ("wrong", "识别错"), ("model_miss", "VAD有覆盖但没出字"), ("vad_miss", "VAD没覆盖")):
    v = buckets[k]
    chars = sum(b["chars"] for b, _, _ in v)
    attr[k] = {"blocks": len(v), "chars": chars,
               "items": [{"start": b["start"], "end": b["end"], "ref": b["ref"],
                          "acc": b["acc"], "chars": b["chars"],
                          "vad_cov": round(vc, 2), "hyp_cov": round(hc, 2)} for b, vc, hc in v]}
    print(f"  {label:16s} {len(v):4d} 块 / {chars:5d} 字 ({len(v)/len(full['blocks'])*100:5.1f}%)")

# 删除字数的归因（按参考字符被删的位置落进哪一类块）
dele_by_bucket = {k: 0 for k in buckets}
pos = 0
acc_map = {}
for k, v in buckets.items():
    for b, _, _ in v:
        acc_map[round(b["start"], 3)] = k
for b in full["blocks"]:
    k = acc_map.get(round(b["start"], 3), "ok")
    dele_by_bucket[k] += b["chars"] - b["matched"]
print("删除/替换字数按归因分档：", {k: v for k, v in dele_by_bucket.items()},
      "合计", sum(dele_by_bucket.values()), "/", full["n_ref_chars"])

# ---------------- 4. A3 漏句记录核对 ----------------
MISSED_PATH = sys.argv[3] if len(sys.argv) > 3 else f"{ROOT}/outputs/测试用_言叶之庭.missed.json"
missed = json.load(open(MISSED_PATH))
a3 = []
for sp in missed["spans"]:
    hit = [b for b in full["blocks"] if ov(sp["start"], sp["end"], b["start"], b["end"]) > 0.05]
    seg = audio[int(sp["start"] * SR):int(sp["end"] * SR)]
    rms = float(np.sqrt(np.mean(seg ** 2))) if seg.size else 0.0
    a3.append({
        "start": sp["start"], "end": sp["end"], "dur": sp["dur"],
        "ref_blocks": [{"start": b["start"], "end": b["end"], "ref": b["ref"], "acc": b["acc"]} for b in hit],
        "rms": round(rms, 5),
        "peak": round(float(np.max(np.abs(seg))) if seg.size else 0.0, 4),
    })
    print(f"\nA3 漏句 {fmt_t(sp['start'])}→{fmt_t(sp['end'])} ({sp['dur']}s) rms={rms:.4f} "
          f"参考块 {[b['ref'] for b in hit] or '无（参考字幕此处无台词）'}")

# 参考台词里"完全没出字"的块（模型漏），A3 的漏句清单是否覆盖
ref_silent = [b for b, hc in zip(full["blocks"], hyp_cov) if hc < 0.25]
covered_by_a3 = [b for b in ref_silent
                 if any(ov(b["start"], b["end"], s["start"], s["end"]) > 0.1 for s in missed["spans"])]
print(f"\n参考有台词但产物无覆盖的块 {len(ref_silent)} 个，其中被 A3 漏句清单覆盖 {len(covered_by_a3)} 个")

# ---------------- 5. BGM 区间细节 ----------------
bgm_cues = [c for c in hyp if ov(c["start"], c["end"], BGM_T0, BGM_T1) > 0]
bgm_ref = region_slice(ref_all, BGM_T0, BGM_T1)
print(f"\nBGM 区间 {BGM_T0/60:.0f}:00-{BGM_T1/60:.1f}  参考块 {len(bgm_ref)}  产物条 {len(bgm_cues)}")
print("  BGM 区间插入（幻觉候选，>=2字）:")
for s in bgm["ins_spans"][:15]:
    print(f"    {fmt_t(s['start'])} {s['chars']:2d}字 {s['text'][:40]}")
print(f"  合计插入 {sum(s['chars'] for s in bgm['ins_spans'])} 字 / 删除 {sum(s['chars'] for s in bgm['del_spans'])} 字")

# ---------------- 6. 逐 5 分钟 ----------------
print("\n逐 5 分钟：")
per = []
for t0 in range(0, int(DUR), 300):
    t1 = t0 + 300
    blocks = region_slice(ref_all, t0, t1)
    cues = [c for c in hyp if ov(c["start"], c["end"], t0, t1) > 0]
    if not blocks:
        continue
    ev = evaluate(blocks, cues)
    row = {"t0": t0, "blocks": len(blocks), "cues": len(cues), "cer": ev["cer"],
           "acc": ev["acc_mean"], "miss": len(ev["miss_blocks"]),
           "ins": sum(s["chars"] for s in ev["ins_spans"]),
           "del": sum(s["chars"] for s in ev["del_spans"])}
    per.append(row)
    print(f"  {t0//60:2d}-{t1//60:2d}min 块{row['blocks']:3d} 条{row['cues']:3d} "
          f"CER{row['cer']*100:6.2f}% 块均{row['acc']*100:5.1f}% 漏块{row['miss']:3d} "
          f"多{row['ins']:3d}字 少{row['del']:3d}字")

json.dump({
    "duration": DUR,
    "vad": {"stamps": len(stamps), "blocks": seg_stats["blocks"],
            "max_block_s": seg_stats["max_block_s"],
            "forced_cuts": seg_stats["forced_cuts"], "snapped_cuts": seg_stats["snapped_cuts"],
            "segs_off_equals_on": segs == segs_off},
    "metrics": {k: {kk: vv for kk, vv in v.items() if kk not in ("blocks", "ev")}
                for k, v in (("full", full), ("no_song", no_song), ("song", song), ("bgm", bgm))},
    "attribution": attr,
    "deleted_chars_by_bucket": dele_by_bucket,
    "a3_spans": a3,
    "ref_silent_blocks": len(ref_silent),
    "ref_silent_covered_by_a3": len(covered_by_a3),
    "per_5min": per,
    "bgm": {"t0": BGM_T0, "t1": BGM_T1, "ref_blocks": len(bgm_ref), "cues": len(bgm_cues),
            "ins_spans": bgm["ins_spans"], "del_spans": bgm["del_spans"]},
}, open(OUT_PATH, "w"), ensure_ascii=False, indent=1)
print("\n→", OUT_PATH)
