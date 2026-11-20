#!/usr/bin/env python3
"""VAD 后端 A/B 的「只看切分」部分：不跑 ASR，产出覆盖率/负样本/耗时表。

    ../.venv/bin/python tools/eval/ab_vad.py --media ../Jap_test_2.mp4 \
        --ref ../Jap_test_2_perfect.srt --fixtures .. \
        --json outputs/eval/p1_vad_ab.json --markdown outputs/eval/p1_vad_ab.md

ASR 侧数字仍由 run_clip.py / score_srt.py 产出；两者用同一个后端环境变量。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.eval.score_srt import filter_language, parse_srt  # noqa: E402


CONFIGS = [
    {"id": "v0_silero20", "backend": "silero", "threshold": 0.25, "window_s": 20.0},
    {"id": "v1_silero10", "backend": "silero10", "threshold": 0.25, "window_s": 10.0},
    {"id": "v2a_ten35", "backend": "ten", "threshold": 0.35, "window_s": 20.0},
    {"id": "v2b_ten45", "backend": "ten", "threshold": 0.45, "window_s": 20.0},
    {"id": "v2c_ten55", "backend": "ten", "threshold": 0.55, "window_s": 20.0},
    {"id": "v3a_whisperseg25", "backend": "whisperseg", "threshold": 0.25, "window_s": 30.0},
    {"id": "v3b_whisperseg35", "backend": "whisperseg", "threshold": 0.35, "window_s": 30.0},
]

MERGE_GAP_S = 0.3
MAX_SEGMENT_S = 9.0
MIN_SPEECH_S = 0.08
NEG_WINDOW_S = 60.0


def _merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(spans):
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _covered(intervals: list[tuple[float, float]], start: float, end: float) -> float:
    if end <= start:
        return 0.0
    total = 0.0
    for a, b in intervals:
        lo, hi = max(start, a), min(end, b)
        if hi > lo:
            total += hi - lo
    return total / (end - start)


def _longest_negative_window(cues, duration_s: float, window_s: float) -> tuple[float, float]:
    """取最长无参考字幕的窗口，四周留 2s 余量，避免切到台词。"""
    spans = [(max(0.0, c.start), min(duration_s, c.end)) for c in cues]
    gaps: list[tuple[float, float]] = []
    prev = 0.0
    for a, b in spans:
        if a - prev >= window_s + 4.0:
            gaps.append((prev, a))
        prev = max(prev, b)
    if duration_s - prev >= window_s + 4.0:
        gaps.append((prev, duration_s))
    if not gaps:
        return 0.0, min(window_s, duration_s)
    a, b = max(gaps, key=lambda x: x[1] - x[0])
    mid = (a + b) / 2
    start = max(a + 2.0, mid - window_s / 2)
    return start, min(start + window_s, b - 2.0)


def _score_config(audio, cues, backend, threshold, window_s, duration_s, negative):
    from core.transcribe import merge_vad_segments
    from core.vad import detect_speech_stamps

    started = time.perf_counter()
    stamps = detect_speech_stamps(
        audio,
        None,
        threshold=threshold,
        min_speech_ms=80,
        min_silence_ms=200,
        speech_pad_ms=250,
        window_s=window_s,
        backend=backend,
    )
    elapsed = time.perf_counter() - started
    segments = merge_vad_segments(
        stamps,
        max_segment_s=MAX_SEGMENT_S,
        merge_gap_s=MERGE_GAP_S,
        min_speech_s=MIN_SPEECH_S,
    )
    intervals = [(a / 16000.0, b / 16000.0) for a, b in segments]
    union = _merge_spans(intervals)
    speech_s = sum(b - a for a, b in union)

    cue_rms = []
    for cue in cues:
        a = max(0, int(cue.start * 16000))
        b = min(len(audio), int(cue.end * 16000))
        chunk = audio[a:b]
        cue_rms.append(float(np.sqrt(np.mean(chunk ** 2))) if chunk.size else 0.0)
    order = np.argsort(cue_rms)
    low_n = max(1, int(round(len(cues) * 0.2)))
    low_idx = set(int(i) for i in order[:low_n])

    covered = [_covered(union, c.start, c.end) >= 0.9 for c in cues]
    low_covered = [covered[i] for i in low_idx]
    neg_a, neg_b = negative
    neg_segments = [
        (a, b) for a, b in intervals if b > neg_a and a < neg_b
    ]
    neg_speech = sum(
        max(0.0, min(b, neg_b) - max(a, neg_a)) for a, b in neg_segments
    )
    return {
        "backend": backend,
        "threshold": threshold,
        "window_s": window_s,
        "stamps": len(stamps),
        "blocks": len(segments),
        "speech_ratio": round(speech_s / duration_s * 100, 2),
        "elapsed_s": round(elapsed, 2),
        "ref_covered": sum(covered),
        "ref_total": len(cues),
        "ref_cover_pct": round(sum(covered) / max(1, len(cues)) * 100, 2),
        "low_covered": sum(low_covered),
        "low_total": len(low_covered),
        "low_cover_pct": round(sum(low_covered) / max(1, len(low_covered)) * 100, 2),
        "neg_segments": len(neg_segments),
        "neg_speech_pct": round(neg_speech / max(1e-9, neg_b - neg_a) * 100, 2),
        "neg_window": [round(neg_a, 2), round(neg_b, 2)],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VAD 后端 A/B：切分覆盖率 / 负样本 / 耗时")
    parser.add_argument("--media", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--fixtures", default=None)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--markdown", type=Path, default=None)
    parser.add_argument(
        "--configs", default=None,
        help="逗号分隔的配置 id；默认全部（v0_silero20,v1_silero10,...）",
    )
    args = parser.parse_args(argv)

    from tools.eval.scorecard import resolve_fixture_path, resolve_fixtures
    from core.transcribe import load_audio_for_transcription

    fixtures = resolve_fixtures(args.fixtures)
    media = resolve_fixture_path(args.media, fixtures)
    ref = resolve_fixture_path(args.ref, fixtures)
    # 复用评测缓存的 16k/loudnorm 音频，避免每组重新解码。
    audio = load_audio_for_transcription(media)
    duration_s = len(audio) / 16000.0
    cues = filter_language(parse_srt(ref.read_text(encoding="utf-8-sig")), "ja")
    cues = [c for c in cues if c.end > c.start]
    negative = _longest_negative_window(cues, duration_s, NEG_WINDOW_S)

    wanted = set((args.configs or "").split(",")) if args.configs else None
    rows = []
    for cfg in CONFIGS:
        if wanted and cfg["id"] not in wanted:
            continue
        print(f"跑 {cfg['id']} …", file=sys.stderr, flush=True)
        try:
            row = _score_config(
                audio, cues, cfg["backend"], cfg["threshold"], cfg["window_s"],
                duration_s, negative,
            )
        except Exception as exc:  # noqa: BLE001 - 单个后端失败不应杀掉整张表
            row = {"backend": cfg["backend"], "threshold": cfg["threshold"],
                   "window_s": cfg["window_s"], "error": f"{type(exc).__name__}: {exc}"}
        row["id"] = cfg["id"]
        rows.append(row)

    payload = {
        "media": media.name,
        "reference": ref.name,
        "duration_s": round(duration_s, 3),
        "negative_window": [round(negative[0], 2), round(negative[1], 2)],
        "merge_gap_s": MERGE_GAP_S,
        "max_segment_s": MAX_SEGMENT_S,
        "rows": rows,
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    header = ("| 组 | 后端 | 阈值 | 参考覆盖 | 低能量覆盖 | 段数 | 语音占比 | "
              "负样本段 | 负样本语音 | 耗时 |")
    lines = [header, "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['id']} | {r['backend']} | {r['threshold']} | "
                         f"ERROR | | | | | | {r['error']} |")
            continue
        lines.append(
            f"| {r['id']} | {r['backend']} | {r['threshold']} | "
            f"{r['ref_covered']}/{r['ref_total']} ({r['ref_cover_pct']}%) | "
            f"{r['low_covered']}/{r['low_total']} ({r['low_cover_pct']}%) | "
            f"{r['blocks']} | {r['speech_ratio']}% | {r['neg_segments']} | "
            f"{r['neg_speech_pct']}% | {r['elapsed_s']}s |"
        )
    table = "\n".join(lines)
    print(table)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(table + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
