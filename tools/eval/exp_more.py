"""补充实验：A1 对照（等长位移切点）/ A5 干净口径重算 / BGM 区间逐段诊断。

产物：outputs/eval/exp_more.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import soundfile as sf
from rapidfuzz.distance import Levenshtein

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import transcribe as T  # noqa: E402
from eval_lib import load_reference, normalize, region_slice, fmt_t  # noqa: E402

SR = 16000
audio, sr = sf.read(f"{ROOT}/outputs/eval/full16k.wav", dtype="float32")
ref = load_reference(f"{ROOT}/测试用_言叶之庭_中日双语.srt")
cfg = T.build_whisper_config(
    threshold=0.45, min_speech_ms=120, min_silence_ms=150, speech_pad_ms=200,
    merge_gap_s=0.3, max_segment_s=12.0, min_speech_s=0.08, cue_pad_s=0.02,
    enable_sentence_split=True, enable_loudnorm=False,
)
print("加载 Whisper…", flush=True)
eng = T.AnimeWhisperEngine(cfg)
eng.load()
GEN = {"language": "Japanese", "task": "transcribe", "no_repeat_ngram_size": 5, "repetition_penalty": 1.15}


def decode(buf):
    r = eng._pipe({"array": buf, "sampling_rate": SR}, generate_kwargs=GEN, return_timestamps=False)
    return (r.get("text") or "").strip()


def ref_text_in(t0, t1):
    return "".join(b["text"] for b in region_slice(ref, t0, t1))


def cer_of(a, b):
    a, b = normalize(a), normalize(b)
    return Levenshtein.distance(a, b) / len(a) if a else 0.0


out: dict = {}

# ---------------- A1 对照：等长但非能量谷的切点 ----------------
print("\n=== A1 对照（5.6s 等长切点，不做能量吸附）===", flush=True)
WIN = 60.4
ctrl = []
for t0 in (330, 975, 2415):
    seg = audio[t0 * SR:int((t0 + WIN) * SR)]
    one = [{"start": 0, "end": len(seg)}]
    chunks = T.merge_vad_segments(one, max_segment_s=5.6, merge_gap_s=0.3,
                                  min_speech_s=0.08, audio=seg, cut_snap_s=0.0)
    txt = "".join(decode(seg[s:e]) for s, e in chunks)
    c = cer_of(ref_text_in(t0, t0 + WIN), txt)
    ctrl.append({"t0": t0, "chunks": len(chunks), "cer": c, "chars": len(normalize(txt))})
    print(f"  {t0}s 5.6s等长 块{len(chunks)} CER={c*100:5.2f}% 字{len(normalize(txt))}", flush=True)
out["A1_ctrl_5p6"] = ctrl

# ---------------- A5 重算（两端都从同一段文本切，且都不加 padding）----------------
print("\n=== A5 禁切点（干净口径）===", flush=True)
R5 = (600.0, 900.0)
seg_texts: list[dict] = []
orig_split = T.split_text_into_cues


def hook(text, seg_start, seg_end, **kw):
    seg_texts.append({"text": text, "start": seg_start, "end": seg_end})
    return orig_split(text, seg_start, seg_end, **kw)


T.split_text_into_cues = hook
try:
    eng._transcribe_array(audio[int(R5[0] * SR):int(R5[1] * SR)], config=cfg, time_offset=R5[0])
finally:
    T.split_text_into_cues = orig_split

orig_forbidden = T.forbidden_cut_positions


def split_all(texts):
    res = []
    for s in texts:
        res.extend(orig_split(s["text"], s["start"], s["end"],
                              max_cue_dur=cfg.max_cue_dur, max_cue_chars=cfg.max_cue_chars))
    return res


cues_on = split_all(seg_texts)
T.forbidden_cut_positions = lambda text: bytearray(len(text) + 1)
cues_off = split_all(seg_texts)
T.forbidden_cut_positions = orig_forbidden


def audit(segs, cues):
    """同段内相邻字幕的接缝落在禁切位置的个数（两端用同一份段文本）。"""
    blocked = total = 0
    for s in segs:
        mine = [c for c in cues if c.start >= s["start"] - 1e-6 and c.end <= s["end"] + 1e-6]
        if len(mine) < 2:
            continue
        bl = orig_forbidden(s["text"])
        pos = 0
        for c in mine[:-1]:
            pos += len(c.text)
            if pos < len(s["text"]):
                total += 1
                blocked += int(bool(bl[pos]))
    return blocked, total


def cps(cues):
    v = sorted(len(normalize(c.text)) / (c.end - c.start) for c in cues if normalize(c.text) and c.end > c.start)
    return {"max": v[-1], "p95": v[int(0.95 * (len(v) - 1))], "median": v[len(v) // 2]} if v else {}


b_on, t_on = audit(seg_texts, cues_on)
b_off, t_off = audit(seg_texts, cues_off)
ref_txt = ref_text_in(*R5)
a5 = {
    "region": R5, "segments": len(seg_texts),
    "cues_on": len(cues_on), "cues_off": len(cues_off),
    "blocked_on": b_on, "blocked_off": b_off,
    "boundaries_on": t_on, "boundaries_off": t_off,
    "cer_on": cer_of(ref_txt, "".join(c.text for c in cues_on)),
    "cer_off": cer_of(ref_txt, "".join(c.text for c in cues_off)),
    "cps_on": cps(cues_on), "cps_off": cps(cues_off),
    "examples": [],
}
for a, b in zip(cues_on, cues_off):
    if a.text != b.text and len(a5["examples"]) < 6:
        a5["examples"].append({"t": round(a.start, 2), "on": a.text, "off": b.text})
print(f"  段{len(seg_texts)} 条{len(cues_on)}/{len(cues_off)} 禁切接缝 {b_on}/{t_on} vs {b_off}/{t_off} "
      f"max cps {a5['cps_on'].get('max',0):.1f}/{a5['cps_off'].get('max',0):.1f}", flush=True)
out["A5"] = a5

# ---------------- BGM 区间逐段诊断 ----------------
print("\n=== BGM 区间 42:00-44:20 逐段 ===", flush=True)
B0, B1 = 2520.0, 2660.0
cues_bgm = eng._transcribe_array(audio[int(B0 * SR):int(B1 * SR)], config=cfg, time_offset=B0)
st = eng.last_segment_stats
print(f"  VAD 块 {st['blocks']} 最长 {st['max_block_s']:.1f}s 强制切分 {st['forced_cuts']} "
      f"→ 字幕 {len(cues_bgm)} 条，漏句记录 {len(eng.last_missed_spans)} 条", flush=True)
for c in cues_bgm:
    print(f"    {fmt_t(c.start)}-{fmt_t(c.end)} {c.text}", flush=True)
for sp in eng.last_missed_spans:
    print(f"    漏句 {fmt_t(sp['start'])}-{fmt_t(sp['end'])} {sp['reason']}", flush=True)
out["BGM"] = {
    "cues": [{"start": c.start, "end": c.end, "text": c.text} for c in cues_bgm],
    "missed": eng.last_missed_spans,
    "stats": st,
    "ref_blocks": len(region_slice(ref, B0, B1)),
    "ref_chars": len(normalize(ref_text_in(B0, B1))),
    "cer": cer_of(ref_text_in(B0, B1), "".join(c.text for c in cues_bgm)),
}

json.dump(out, open(f"{ROOT}/outputs/eval/exp_more.json", "w"), ensure_ascii=False, indent=1)
print("\n→ outputs/eval/exp_more.json")
