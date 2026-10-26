"""定位「交付字幕在 42:00–44:20 只有 1 条」的原因：响度档位 / 可复现性。

对照同一区间（40:00–45:00）在两种响度档位下的产物。
产物：outputs/eval/exp_bgm_cause.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import soundfile as sf

ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import transcribe as T  # noqa: E402
from eval_lib import load_reference  # noqa: E402

SR = 16000
ref = load_reference(f"{ROOT}/测试用_言叶之庭_中日双语.srt")
cfg = T.build_whisper_config(
    threshold=0.45, min_speech_ms=120, min_silence_ms=150, speech_pad_ms=200,
    merge_gap_s=0.3, max_segment_s=12.0, min_speech_s=0.08, cue_pad_s=0.02,
    enable_sentence_split=True, enable_loudnorm=False,
)
print("加载 Whisper…", flush=True)
eng = T.AnimeWhisperEngine(cfg)
eng.load()

T0, T1 = 2400.0, 2700.0
out = {}
for loud in (False, True):
    tmp = Path(f"/tmp/_slice_{int(loud)}.wav")
    T.decode_wav_16k(Path(ROOT) / "测试用_言叶之庭.mkv", tmp, enable_loudnorm=loud,
                     start_time_s=T0, end_time_s=T1)
    a, _ = sf.read(str(tmp), dtype="float32")
    cues = eng._transcribe_array(a, config=cfg, time_offset=T0)
    st = eng.last_segment_stats
    print(f"loudnorm={loud}: 块{st['blocks']} 最长{st['max_block_s']:.1f}s "
          f"→ {len(cues)} 条，漏句 {len(eng.last_missed_spans)}", flush=True)
    for c in cues:
        if 2500 <= c.start < 2670:
            print(f"    {c.start:7.1f}-{c.end:7.1f} {c.text}", flush=True)
    out[f"loudnorm_{int(loud)}"] = {
        "cues": len(cues), "blocks": st["blocks"], "missed": len(eng.last_missed_spans),
        "in_bgm": sum(1 for c in cues if c.end > 2520 and c.start < 2660),
        "texts": [{"start": c.start, "end": c.end, "text": c.text} for c in cues
                  if c.end > 2500 and c.start < 2670],
    }
    tmp.unlink(missing_ok=True)

json.dump(out, open(f"{ROOT}/outputs/eval/exp_bgm_cause.json", "w"), ensure_ascii=False, indent=1)
print("→ outputs/eval/exp_bgm_cause.json")
