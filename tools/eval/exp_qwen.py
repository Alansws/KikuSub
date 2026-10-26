"""Qwen3-ASR + CTC 侧实验：A6 对齐降级可观测性 / P4 撞上限分类。

产物：outputs/eval/exp_qwen.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import time

import soundfile as sf
from rapidfuzz.distance import Levenshtein

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import qwen_ctc as Q  # noqa: E402
from eval_lib import load_reference, normalize, region_slice, fmt_t  # noqa: E402

SR = 16000
OUT = f"{ROOT}/outputs/eval/exp_qwen.json"
audio, sr = sf.read(f"{ROOT}/outputs/eval/full16k.wav", dtype="float32")
ref = load_reference(f"{ROOT}/测试用_言叶之庭_中日双语.srt")


def ref_text_in(t0, t1):
    return "".join(b["text"] for b in region_slice(ref, t0, t1))


def cer_of(a_text, b_text):
    a, b = normalize(a_text), normalize(b_text)
    if not a:
        return None
    return Levenshtein.distance(a, b) / len(a)


print("加载 Qwen3-ASR + CTC head…", flush=True)
t0 = time.time()
eng = Q.QwenCtcEngine()
eng.load()
print(f"加载完成 {time.time()-t0:.1f}s", flush=True)

records: list[dict] = []
seg_box: dict = {}
orig_align = eng.align
orig_merge = Q.merge_vad_segments


def patched_merge(*a, **kw):
    segs = orig_merge(*a, **kw)
    seg_box["segs"] = [(s / SR, e / SR) for s, e in segs]
    return segs


def patched_align(chunk, text):
    res = orig_align(chunk, text)
    records.append({
        "text": text, "ok": res.ok, "reason": res.reason,
        "interp": res.interpolated, "chars": len(res.chars) if res.chars else 0,
        "dur": len(chunk) / SR,
    })
    return res


eng.align = patched_align
Q.merge_vad_segments = patched_merge

REGIONS = [
    ("misrecog_290-330", 290.0, 330.0),
    ("repeat_95-110", 95.0, 110.0),
    ("bgm_song_2520-2560", 2520.0, 2560.0),
]
out = []
for name, a, b in REGIONS:
    records.clear()
    seg_box.clear()
    seg = audio[int(a * SR):int(b * SR)]
    t = time.time()
    cues = eng.transcribe_array(seg, use_alignment=True, time_offset=a)
    dt = time.time() - t
    st = dict(eng.last_align_stats)
    # 把 align 记录按顺序对回 VAD 段（空段不调用 align，用时长对齐）
    segs = seg_box.get("segs", [])
    idx = 0
    for r in records:
        while idx < len(segs) and abs((segs[idx][1] - segs[idx][0]) - r["dur"]) > 0.02:
            idx += 1
        if idx < len(segs):
            r["start"], r["end"] = round(segs[idx][0] + a, 2), round(segs[idx][1] + a, 2)
            idx += 1
        else:
            r["start"], r["end"] = None, None
        r["ref"] = ref_text_in((r["start"] or a) - 0.2, (r["end"] or b) + 0.2)
        r["cer"] = cer_of(r["ref"], r["text"])
    total = sum(len(normalize(r["text"])) for r in records)
    interp = sum(r["interp"] for r in records)
    row = {
        "name": name, "region": [a, b], "secs": round(dt, 1),
        "cues": len(cues), "stats": st,
        "interp_ratio": interp / max(total, 1),
        "region_cer": cer_of(ref_text_in(a, b), "".join(c.text for c in cues)),
        "segments": [dict(x) for x in records],
    }
    out.append(row)
    print(f"{name:20s} {dt:5.1f}s 段{st['segments']:3d} 对齐{st['aligned']:3d} "
          f"退化{st['degraded']:2d} 空{st['empty']:2d} 插值{st['interp_chars']}/{st['align_chars']}"
          f"({row['interp_ratio']*100:.1f}%) 截断{st['truncated']} 复读{st['capped_repeat']} "
          f"CER={(row['region_cer'] or 0)*100:.1f}% 条{len(cues)}", flush=True)

rows = [r for reg in out for r in reg["segments"]
        if r["ok"] and r["chars"] >= 6 and r["cer"] is not None and r["start"] is not None]
rows.sort(key=lambda r: -(r["interp"] / max(r["chars"], 1)))
print("\n插值率最高的 8 段：")
for r in rows[:8]:
    print(f"  {fmt_t(r['start'])} 插值{r['interp']:3d}/{r['chars']:3d} "
          f"({r['interp']/max(r['chars'],1)*100:4.0f}%) CER={r['cer']*100:5.1f}%  "
          f"{r['text'][:26]} ← {r['ref'][:26]}")
print("插值率最低的 8 段：")
for r in rows[-8:]:
    print(f"  {fmt_t(r['start'])} 插值{r['interp']:3d}/{r['chars']:3d} CER={r['cer']*100:5.1f}% {r['text'][:26]}")


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


hi = [r for r in rows if r["interp"] / max(r["chars"], 1) > 0.15]
lo = [r for r in rows if r["interp"] / max(r["chars"], 1) <= 0.15]
print(f"\n插值率>15% 的段 {len(hi)} 个，平均 CER {mean([r['cer'] for r in hi])*100:.1f}%")
print(f"插值率≤15% 的段 {len(lo)} 个，平均 CER {mean([r['cer'] for r in lo])*100:.1f}%")
json.dump({"regions": out,
           "interp_hi": {"n": len(hi), "cer": mean([r["cer"] for r in hi])},
           "interp_lo": {"n": len(lo), "cer": mean([r["cer"] for r in lo])}},
          open(OUT, "w"), ensure_ascii=False, indent=1)
print("\n→", OUT)
