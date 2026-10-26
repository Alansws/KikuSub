"""Whisper 侧对照实验：A1 切点吸附 / A3 空段重试 / A5 禁切点。

全部使用真实模型、真实片源，只改一个变量。
产物：outputs/eval/exp_whisper.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from rapidfuzz.distance import Levenshtein

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import transcribe as T  # noqa: E402
from eval_lib import load_reference, normalize, region_slice, fmt_t  # noqa: E402

SR = 16000
OUT = f"{ROOT}/outputs/eval/exp_whisper.json"

audio, sr = sf.read(f"{ROOT}/outputs/eval/full16k.wav", dtype="float32")
assert sr == SR
ref = load_reference(f"{ROOT}/测试用_言叶之庭_中日双语.srt")

cfg = T.build_whisper_config(
    threshold=0.45, min_speech_ms=120, min_silence_ms=150, speech_pad_ms=200,
    merge_gap_s=0.3, max_segment_s=12.0, min_speech_s=0.08, cue_pad_s=0.02,
    enable_sentence_split=True, enable_loudnorm=False,
)
print("加载 Whisper…", flush=True)
eng = T.AnimeWhisperEngine(cfg)
eng.load()
print("加载完成", flush=True)

GEN = {"language": "Japanese", "task": "transcribe", "no_repeat_ngram_size": 5, "repetition_penalty": 1.15}


def decode(buf: np.ndarray) -> str:
    res = eng._pipe({"array": buf, "sampling_rate": SR}, generate_kwargs=GEN, return_timestamps=False)
    return (res.get("text") or "").strip()


def cer_of(ref_text: str, hyp_text: str) -> float:
    a, b = normalize(ref_text), normalize(hyp_text)
    if not a:
        return 0.0
    d = Levenshtein.distance(a, b)
    return d / len(a)


def ref_text_in(t0: float, t1: float) -> str:
    return "".join(b["text"] for b in region_slice(ref, t0, t1))


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0


results: dict = {}

# ============================================================
# A1：强制切分点吸附（构造"单段连续语音超上限"的真实场景）
# ============================================================
print("\n=== A1 切点吸附 ===", flush=True)
stamps_all = T.get_speech_timestamps(
    torch.from_numpy(audio), eng._vad, sampling_rate=SR, threshold=0.45,
    min_speech_duration_ms=120, min_silence_duration_ms=150, speech_pad_ms=200,
    neg_threshold=T.vad_neg_threshold(0.45),
)

# 选 3 个语音最密的 60s 窗口
cov = np.zeros(int(len(audio) / SR) + 1)
for s in stamps_all:
    cov[int(s["start"] / SR): int(np.ceil(s["end"] / SR))] += 1
best, wins = [], []
for t0 in range(30, int(len(audio) / SR) - 90, 15):
    wins.append((cov[t0:t0 + 60].sum(), t0))
wins.sort(reverse=True)
picked = []
for v, t0 in wins:
    if all(abs(t0 - p) > 300 for p in picked):
        picked.append(t0)
    if len(picked) == 3:
        break
picked.sort()
print("选中窗口:", [(t0, int(cov[t0:t0 + 60].sum())) for t0 in picked], flush=True)

a1_rows = []
WIN = 60.4          # 刻意不取 6s 的整数倍：整倍数时 _cut_keeps_segment_count 会拒绝一切吸附
for t0 in picked:
    seg_audio = audio[t0 * SR:int((t0 + WIN) * SR)]
    one = [{"start": 0, "end": len(seg_audio)}]   # 模拟 VAD 没找到停顿：整段连续语音
    ref_txt = ref_text_in(t0, t0 + WIN)
    for snap in (0.0, T.CUT_SNAP_S):
        st = {}
        chunks = T.merge_vad_segments(one, max_segment_s=6.0, merge_gap_s=0.3,
                                      min_speech_s=0.08, audio=seg_audio,
                                      cut_snap_s=snap, snap_stats=st)
        texts, cut_energy = [], []
        med = float(np.median([rms(seg_audio[i:i + SR // 10]) for i in range(0, len(seg_audio) - SR // 10, SR // 10)]))
        for (s, e) in chunks:
            texts.append(decode(seg_audio[s:e]))
            if e < len(seg_audio):
                w = seg_audio[max(0, e - SR // 20): e + SR // 20]
                cut_energy.append(round(rms(w) / max(med, 1e-9), 3))
        joined = "".join(texts)
        row = {
            "t0": t0, "snap": snap, "chunks": len(chunks),
            "forced": st["forced_cuts"], "snapped": st["snapped_cuts"],
            "shift_s": round(st["shift_s"], 3),
            "cer": cer_of(ref_txt, joined),
            "chars": len(normalize(joined)),
            "cut_energy_rel": cut_energy,
            "texts": texts,
            "bounds": [(round(s / SR, 3), round(e / SR, 3)) for s, e in chunks],
        }
        a1_rows.append(row)
        print(f"  {t0:5d}s snap={snap:.2f} 块{len(chunks)} 吸附{st['snapped_cuts']} "
              f"前移{st['shift_s']:.2f}s CER={row['cer']*100:5.2f}% 字{row['chars']}", flush=True)

# 汇总：同一窗口两模式对比
a1_summary = []
for t0 in picked:
    on = next(r for r in a1_rows if r["t0"] == t0 and r["snap"] > 0)
    off = next(r for r in a1_rows if r["t0"] == t0 and r["snap"] == 0)
    diff = sum(1 for a, b in zip(on["texts"], off["texts"]) if a != b)
    a1_summary.append({
        "t0": t0, "cer_off": off["cer"], "cer_on": on["cer"],
        "delta_cer": on["cer"] - off["cer"], "chunks_text_changed": diff,
        "energy_off": round(float(np.mean(off["cut_energy_rel"])), 3) if off["cut_energy_rel"] else None,
        "energy_on": round(float(np.mean(on["cut_energy_rel"])), 3) if on["cut_energy_rel"] else None,
    })
    print(f"  汇总 {t0}s: CER {off['cer']*100:.2f}% → {on['cer']*100:.2f}% "
          f"(Δ{(on['cer']-off['cer'])*100:+.2f}pt) 文本变化块 {diff}/{off['chunks']}", flush=True)
results["A1"] = {"rows": a1_rows, "summary": a1_summary, "windows": picked}

# ============================================================
# A3：空结果段重试 —— 低能量段上"重试能否救回字"
# ============================================================
print("\n=== A3 空段重试 ===", flush=True)
cands = []
for s in stamps_all:
    a, b = s["start"] / SR, s["end"] / SR
    d = b - a
    if 0.3 <= d <= 3.0:
        cands.append((rms(audio[s["start"]:s["end"]]), a, b))
cands.sort()
picked_segs = []
for r, a, b in cands:
    if all(abs(a - p[1]) > 20 for p in picked_segs):
        picked_segs.append((r, a, b))
    if len(picked_segs) == 24:
        break
picked_segs.sort(key=lambda x: x[1])

a3_rows = []
t_retry = 0.0
for r, a, b in picked_segs:
    chunk = audio[int(a * SR):int(b * SR)]
    t1 = decode(chunk)
    boosted = decode(T._retry_gain(chunk))
    blank1, blank2 = T._is_blank(t1), T._is_blank(boosted)
    ref_txt = ref_text_in(a - 0.3, b + 0.3)
    a3_rows.append({
        "start": round(a, 2), "end": round(b, 2), "rms": round(r, 5),
        "raw": t1, "raw_blank": blank1, "boost": boosted, "boost_blank": blank2,
        "ref": ref_txt[:40],
        "boost_cer": cer_of(ref_txt, boosted) if ref_txt and not blank2 else None,
        "raw_cer": cer_of(ref_txt, t1) if ref_txt and not blank1 else None,
    })
    if blank1 and not blank2:
        t_retry += 1
    print(f"  {fmt_t(a)} rms={r:.4f} raw={'BLANK' if blank1 else t1[:20]!r} "
          f"boost={'BLANK' if blank2 else boosted[:20]!r}", flush=True)

n_blank_raw = sum(1 for x in a3_rows if x["raw_blank"])
n_rescued = sum(1 for x in a3_rows if x["raw_blank"] and not x["boost_blank"])
rescued_good = sum(1 for x in a3_rows if x["raw_blank"] and not x["boost_blank"]
                   and x["boost_cer"] is not None and x["boost_cer"] < 0.5)
print(f"  低能量段 {len(a3_rows)} 个：首轮空 {n_blank_raw}，重试救回 {n_rescued}，其中文本基本正确 {rescued_good}", flush=True)

# 用户报告里那两条漏句
missed = json.load(open(f"{ROOT}/outputs/测试用_言叶之庭.missed.json"))
for sp in missed["spans"]:
    chunk = audio[int(sp["start"] * SR):int(sp["end"] * SR)]
    print(f"  报告漏句 {fmt_t(sp['start'])} rms={rms(chunk):.4f} "
          f"raw={decode(chunk)!r} boost={decode(T._retry_gain(chunk))!r}", flush=True)

results["A3"] = {"segments": a3_rows, "n": len(a3_rows),
                 "n_blank_raw": n_blank_raw, "n_rescued": n_rescued,
                 "n_rescued_good": rescued_good}

# ============================================================
# A5：禁切点（同一段文本，只切换禁则）
# ============================================================
print("\n=== A5 禁切点 ===", flush=True)
R5_0, R5_1 = 600.0, 900.0
seg_texts: list[dict] = []
orig_split = T.split_text_into_cues


def hook(text, seg_start, seg_end, **kw):
    seg_texts.append({"text": text, "start": seg_start, "end": seg_end})
    return orig_split(text, seg_start, seg_end, **kw)


T.split_text_into_cues = hook
try:
    cues_on = eng._transcribe_array(audio[int(R5_0 * SR):int(R5_1 * SR)], config=cfg, time_offset=R5_0)
finally:
    T.split_text_into_cues = orig_split

# 关闭禁则：forbidden_cut_positions 全 0（等价于 A5 之前的行为）
orig_forbidden = T.forbidden_cut_positions
T.forbidden_cut_positions = lambda text: bytearray(len(text) + 1)
cues_off = []
for s in seg_texts:
    cues_off.extend(orig_split(s["text"], s["start"], s["end"],
                               max_cue_dur=cfg.max_cue_dur, max_cue_chars=cfg.max_cue_chars))
T.forbidden_cut_positions = orig_forbidden


def boundary_audit(segs, cues):
    """统计每条字幕的切点是否落在禁切位置（同段内相邻两条的接缝）。"""
    blocked = 0
    total = 0
    for s in segs:
        txt = s["text"]
        mine = [c for c in cues if (c.start if hasattr(c, "start") else c["start"]) >= s["start"] - 1e-6
                and (c.end if hasattr(c, "end") else c["end"]) <= s["end"] + 1e-6]
        pos = 0
        bl = orig_forbidden(txt)
        for c in mine[:-1]:
            piece = c.text if hasattr(c, "text") else c["text"]
            pos += len(piece)
            if pos < len(txt):
                total += 1
                if bl[pos]:
                    blocked += 1
    return blocked, total


def to_dicts(cues):
    return [{"start": c.start, "end": c.end, "text": c.text} for c in cues]


d_on, d_off = to_dicts(cues_on), to_dicts(cues_off)
b_on, t_on = boundary_audit(seg_texts, d_on)
b_off, t_off = boundary_audit(seg_texts, d_off)
ref_txt = ref_text_in(R5_0, R5_1)


def cps_stats(cues):
    v = []
    for c in cues:
        txt = normalize(c["text"])
        d = c["end"] - c["start"]
        if txt and d > 0:
            v.append(len(txt) / d)
    v.sort()
    return {"max": v[-1] if v else 0, "p95": v[int(0.95 * (len(v) - 1))] if v else 0,
            "median": v[len(v) // 2] if v else 0}


a5 = {
    "region": [R5_0, R5_1],
    "segments": len(seg_texts),
    "cues_on": len(d_on), "cues_off": len(d_off),
    "blocked_on": b_on, "blocked_off": b_off,
    "boundaries_on": t_on, "boundaries_off": t_off,
    "cer_on": cer_of(ref_txt, "".join(c["text"] for c in d_on)),
    "cer_off": cer_of(ref_txt, "".join(c["text"] for c in d_off)),
    "cps_on": cps_stats(d_on), "cps_off": cps_stats(d_off),
    "diff_cues": sum(1 for a, b in zip(d_on, d_off) if a != b),
    "examples": [],
}
# 具体差异例子
for i, (a, b) in enumerate(zip(d_on, d_off)):
    if a["text"] != b["text"] and len(a5["examples"]) < 8:
        a5["examples"].append({"on": a["text"], "off": b["text"], "t": round(a["start"], 2)})
print(f"  段 {len(seg_texts)}  条 {len(d_on)} vs {len(d_off)}  "
      f"禁切接缝 {b_on}/{t_on} vs {b_off}/{t_off}  "
      f"CER {a5['cer_on']*100:.2f}% vs {a5['cer_off']*100:.2f}%  "
      f"max cps {a5['cps_on']['max']:.1f} vs {a5['cps_off']['max']:.1f}", flush=True)
results["A5"] = a5

json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=1)
print("\n→", OUT, flush=True)
