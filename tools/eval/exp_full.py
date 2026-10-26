"""复现用户那次全片转写（同一份代码、同一组参数、同一份 16k 音频）。

目的：
1. 验证产物可复现（条数/文本是否一致）；
2. 解释「交付字幕在 42:00–44:20 只有 1 条，而单跑该区间却有 25 条」的差异来源。
产物：outputs/eval/exp_full.json + outputs/eval/full_rerun.srt
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import time

import soundfile as sf

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import transcribe as T  # noqa: E402
from eval_lib import load_reference, parse_srt, evaluate  # noqa: E402

SR = 16000
audio, _ = sf.read(f"{ROOT}/outputs/eval/full16k.wav", dtype="float32")
ref = load_reference(f"{ROOT}/测试用_言叶之庭_中日双语.srt")
user = parse_srt(f"{ROOT}/测试用_言叶之庭.whisper.srt")

cfg = T.build_whisper_config(
    threshold=0.45, min_speech_ms=120, min_silence_ms=150, speech_pad_ms=200,
    merge_gap_s=0.3, max_segment_s=12.0, min_speech_s=0.08, cue_pad_s=0.02,
    enable_sentence_split=True, enable_loudnorm=False,
)
print("加载 Whisper…", flush=True)
eng = T.AnimeWhisperEngine(cfg)
eng.load()
print("开始全片转写…", flush=True)
t = time.time()
cues = eng._transcribe_array(audio, config=cfg, no_repeat_ngram_size=5, repetition_penalty=1.15)
dt = time.time() - t
print(f"完成 {dt:.1f}s，{len(cues)} 条，漏句 {len(eng.last_missed_spans)} 条", flush=True)

open(f"{ROOT}/outputs/eval/full_rerun.srt", "w").write(T.cues_to_srt(cues))

# 与交付版逐条比对
def key(c):
    return (round(c.start, 3), round(c.end, 3), c.text)


uset = [key(c) for c in user]
nset = [key(c) for c in cues]
same = uset == nset
common = len(set(uset) & set(nset))
print(f"与交付版逐条一致: {same}  交集 {common}/{len(uset)}（重跑 {len(nset)}）", flush=True)

# 文本差异（按顺序）
diff = [(a, b) for a, b in zip(user, cues) if key(a) != key(b)]
print(f"顺序差异条数 {len(diff)}，前 6 条：", flush=True)
for a, b in diff[:6]:
    print(f"  交付 {a.start:7.1f} {a.text[:30]!r}\n  重跑 {b.start:7.1f} {b.text[:30]!r}", flush=True)

def region_cues(t0, t1):
    return [c for c in cues if c.end > t0 and c.start < t1]

B0, B1 = 2520.0, 2660.0
print(f"\n42:00-44:20 重跑 {len(region_cues(B0, B1))} 条 / 交付 {len([c for c in user if c.end > B0 and c.start < B1])} 条", flush=True)
for c in region_cues(B0, B1)[:30]:
    print(f"  {c.start:7.1f}-{c.end:7.1f} {c.text}", flush=True)

ev_new = evaluate(ref, [{"start": c.start, "end": c.end, "text": c.text} for c in cues])
ev_old = evaluate(ref, [{"start": c.start, "end": c.end, "text": c.text} for c in user])
print(f"\n全片 CER 重跑 {ev_new['cer']*100:.2f}% / 交付 {ev_old['cer']*100:.2f}%", flush=True)

json.dump({
    "secs": round(dt, 1), "cues": len(cues), "missed": eng.last_missed_spans,
    "stats": eng.last_segment_stats,
    "identical": same, "common": common,
    "cer_new": ev_new["cer"], "cer_old": ev_old["cer"],
    "bgm_cues": [{"start": c.start, "end": c.end, "text": c.text} for c in region_cues(B0, B1)],
    "diffs": [{"user": a.text, "rerun": b.text, "t": a.start} for a, b in diff[:40]],
}, open(f"{ROOT}/outputs/eval/exp_full.json", "w"), ensure_ascii=False, indent=1)
print("→ outputs/eval/exp_full.json")
