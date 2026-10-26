"""可复现性检验：同一代码、同一参数、同一音频，全片再跑一次，与第一次逐条比对。

产物：outputs/eval/full_rerun2.srt + outputs/eval/exp_det.json
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
from eval_lib import parse_srt  # noqa: E402

SR = 16000
audio, _ = sf.read(f"{ROOT}/outputs/eval/full16k.wav", dtype="float32")
cfg = T.build_whisper_config(
    threshold=0.45, min_speech_ms=120, min_silence_ms=150, speech_pad_ms=200,
    merge_gap_s=0.3, max_segment_s=12.0, min_speech_s=0.08, cue_pad_s=0.02,
    enable_sentence_split=True, enable_loudnorm=False,
)
print("加载 Whisper…", flush=True)
eng = T.AnimeWhisperEngine(cfg)
eng.load()
t = time.time()
cues = eng._transcribe_array(audio, config=cfg, no_repeat_ngram_size=5, repetition_penalty=1.15)
print(f"第二次全片 {time.time()-t:.1f}s → {len(cues)} 条，漏句 {len(eng.last_missed_spans)}", flush=True)
open(f"{ROOT}/outputs/eval/full_rerun2.srt", "w").write(T.cues_to_srt(cues))

a = parse_srt(f"{ROOT}/outputs/eval/full_rerun.srt")
b = parse_srt(f"{ROOT}/outputs/eval/full_rerun2.srt")
d = parse_srt(f"{ROOT}/测试用_言叶之庭.whisper.srt")


def key(c):
    return (round(c["start"], 3), round(c["end"], 3), c["text"])


same = [key(x) for x in a] == [key(x) for x in b]
diff = [(x, y) for x, y in zip(a, b) if key(x) != key(y)]
print(f"两次重跑逐条一致: {same}（{len(a)} vs {len(b)}），差异 {len(diff)} 条", flush=True)
for x, y in diff[:5]:
    print(f"  {x['start']:7.1f} {x['text'][:26]!r} | {y['text'][:26]!r}", flush=True)


def cnt(cs, t0, t1):
    return sum(1 for c in cs if c["end"] > t0 and c["start"] < t1)


print(f"42:00-44:20：交付 {cnt(d,2520,2660)} 条 / 重跑1 {cnt(a,2520,2660)} / 重跑2 {cnt(b,2520,2660)}", flush=True)
json.dump({"same": same, "n1": len(a), "n2": len(b), "n_user": len(d),
           "diff": [{"t": x["start"], "a": x["text"], "b": y["text"]} for x, y in diff[:40]],
           "bgm": {"user": cnt(d, 2520, 2660), "run1": cnt(a, 2520, 2660), "run2": cnt(b, 2520, 2660)}},
          open(f"{ROOT}/outputs/eval/exp_det.json", "w"), ensure_ascii=False, indent=1)
print("→ outputs/eval/exp_det.json")
