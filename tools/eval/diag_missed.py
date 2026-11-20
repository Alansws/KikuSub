#!/usr/bin/env python3
"""逐条核对「漏块」：把评测口径里的 missed block 还原成一次真实的流水线事件。

    ../.venv/bin/python tools/eval/diag_missed.py \
        --media ../Jap_test_2.mp4 --ref ../Jap_test_2_perfect.srt --fixtures .. \
        --set whisper.vad_backend=whisperseg --set whisper.vad_threshold=0.35 \
        --out outputs/eval/p1/diag_v3b --json outputs/eval/p1/diag_v3b.json

`score_srt.py` 的 missed_blocks 只回答「块准确率 < 35% 且参考 >= 3 字」。
这个脚本回答「为什么」：

* 该块有没有被 VAD 段覆盖（段 id / 段长 / 段内文本）；
* 与它重叠的最终字幕是什么（跨块合并、卡在边界、假名写法差异）；
* 该时间窗内有没有被幻觉门控丢弃 / 纯发声跳过 / 空结果重试的记录。

只供排查，不参与产品流程；输出 JSON 与 Markdown 明细。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.eval.score_srt import (  # noqa: E402
    _overlaps,
    filter_language,
    levenshtein,
    normalize_text,
    parse_srt,
)
from tools.eval.scorecard import resolve_fixture_path, resolve_fixtures  # noqa: E402


def _span_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _best_window_match(needle: str, haystack: str) -> float:
    """needle 在 haystack 里的最佳局部相似度（跨块合并时用）。"""
    if not needle:
        return 1.0
    if needle in haystack:
        return 1.0
    if not haystack:
        return 0.0
    best = 0.0
    width = len(needle)
    for i in range(0, max(1, len(haystack) - width + 1)):
        piece = haystack[i : i + width]
        score = 1.0 - levenshtein(needle, piece) / len(needle)
        best = max(best, score)
    return best


def _segments_for_run(audio, overrides: dict) -> list[tuple[int, int]]:
    """按本次参数重算 VAD 段（只读，不重复跑 ASR）。"""
    from tools.eval.run_clip import _engine_configs

    whisper_config, _qwen_config, _passthrough, _resolved = _engine_configs(
        "whisper", overrides
    )
    from core.transcribe import detect_speech_stamps, merge_vad_segments

    stamps = detect_speech_stamps(
        audio,
        None,
        threshold=whisper_config.threshold,
        min_speech_ms=whisper_config.min_speech_ms,
        min_silence_ms=whisper_config.min_silence_ms,
        speech_pad_ms=whisper_config.speech_pad_ms,
        backend=whisper_config.vad_backend,
    )
    stats: dict = {}
    return merge_vad_segments(
        stamps,
        max_segment_s=whisper_config.max_segment_s,
        merge_gap_s=whisper_config.merge_gap_s,
        min_speech_s=whisper_config.min_speech_s,
        audio=audio,
        snap_stats=stats,
    ), stats


def _classify(
    *,
    ref,
    ref_norm: str,
    hyp_cues,
    hyp_all,
    missed_spans,
    hallu_spans,
    nonverbal_spans,
    segments,
    sample_rate=16000,
) -> dict:
    overlapped = [h for h in hyp_cues if _overlaps(ref, h)]
    texts = [normalize_text(h.text) for h in overlapped]
    hyp_text = "".join(texts)
    exact = bool(ref_norm) and ref_norm in hyp_text
    window_text = "".join(
        normalize_text(h.text)
        for h in hyp_all
        if h.end >= ref.start - 1.0 and h.start <= ref.end + 1.0
    )
    local = _best_window_match(ref_norm, window_text)

    # 每条重叠字幕是否越过参考块边界（跨块合并的直接证据）
    spill = []
    for h in overlapped:
        over = max(0.0, h.start - ref.start) + max(0.0, ref.end - h.end)
        if over > 0.15:
            spill.append({"start": h.start, "end": h.end, "spill_s": round(over, 2),
                          "text": h.text})

    cover = []
    for idx, (a, b) in enumerate(segments):
        a_s, b_s = a / sample_rate, b / sample_rate
        ratio = _span_overlap(a_s, b_s, ref.start, ref.end) / max(1e-9, ref.end - ref.start)
        if ratio > 0:
            cover.append({"seg": idx, "start": round(a_s, 2), "end": round(b_s, 2),
                          "dur": round(b_s - a_s, 2), "cover": round(ratio, 2)})

    dropped = [
        {**s, "kind": "hallucination"} for s in hallu_spans
        if _span_overlap(s["start"], s["end"], ref.start, ref.end) > 0
    ]
    nonverbal = [
        {**s, "kind": "nonverbal"} for s in nonverbal_spans
        if _span_overlap(s["start"], s["end"], ref.start, ref.end) > 0
    ]
    empty = [
        {**s, "kind": "empty"} for s in missed_spans
        if _span_overlap(s["start"], s["end"], ref.start, ref.end) > 0
    ]

    if exact:
        status = "text-present-exact"
    elif local >= 0.6:
        status = "text-present-local"
    elif dropped:
        status = "dropped-hallucination"
    elif nonverbal:
        status = "skipped-nonverbal"
    elif empty:
        status = "empty-after-retry"
    elif not cover:
        status = "no-vad-cover"
    else:
        status = "other"

    return {
        "status": status,
        "ref_text": ref.text,
        "ref_norm": ref_norm,
        "overlap_cues": [
            {"start": round(h.start, 2), "end": round(h.end, 2), "text": h.text}
            for h in overlapped
        ],
        "spill_cues": spill,
        "local_match": round(local, 2),
        "vad_segments": cover,
        "dropped_spans": dropped,
        "nonverbal_spans": nonverbal,
        "empty_spans": empty,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="逐条还原 missed block 的流水线状态")
    parser.add_argument("--media", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--fixtures", default=None)
    parser.add_argument("--out", type=Path, required=True, help="SRT/JSON 输出目录")
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--set", dest="overrides", action="append", default=[])
    args = parser.parse_args(argv)

    from tools.eval.run_clip import _transcribe
    from tools.eval.scorecard import OverrideError, apply_overrides
    from core.transcribe import load_audio_for_transcription

    fixtures = resolve_fixtures(args.fixtures)
    media = resolve_fixture_path(args.media, fixtures)
    ref_path = resolve_fixture_path(args.ref, fixtures)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        overrides = apply_overrides("whisper", args.overrides)
    except OverrideError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    audio = load_audio_for_transcription(media)
    segments, snap_stats = _segments_for_run(audio, overrides)

    result, resolved = _transcribe(media, "whisper", overrides, out_dir, progress=True)
    hyp = parse_srt(Path(result.out_path).read_text(encoding="utf-8-sig"))
    refs = filter_language(parse_srt(ref_path.read_text(encoding="utf-8-sig")), "ja")

    stats = result.segment_stats or {}
    hallu = stats.get("hallucination_spans") or []
    nonverbal = stats.get("nonverbal_spans") or []
    empty = result.missed_spans or []

    missed = []
    for idx, ref in enumerate(refs, start=1):
        ref_norm = normalize_text(ref.text)
        if len(ref_norm) < 3:
            continue
        overlapped = [h for h in hyp if _overlaps(ref, h)]
        block_text = "".join(normalize_text(h.text) for h in overlapped)
        acc = 1.0 - levenshtein(ref_norm, block_text) / len(ref_norm)
        if acc >= 0.35:
            continue
        detail = _classify(
            ref=ref,
            ref_norm=ref_norm,
            hyp_cues=hyp,
            hyp_all=hyp,
            missed_spans=empty,
            hallu_spans=hallu,
            nonverbal_spans=nonverbal,
            segments=segments,
        )
        missed.append({
            "ref_index": idx,
            "start": round(ref.start, 2),
            "end": round(ref.end, 2),
            "accuracy": round(max(0.0, acc), 2),
            **detail,
        })

    payload = {
        "media": media.name,
        "reference": ref_path.name,
        "srt": str(result.out_path),
        "params": resolved,
        "snap_stats": snap_stats,
        "elapsed_s": round(result.elapsed, 2),
        "cues": len(hyp),
        "pending_qa": result.pending_qa,
        "counts": {
            "missed_blocks": len(missed),
            "hallucination_dropped": stats.get("hallucination_drops", 0),
            "nonverbal_skips": stats.get("nonverbal_skips", 0),
            "empty_after_retry": len(empty),
        },
        "missed": missed,
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")

    print(f"\n漏块 {len(missed)} 条")
    for item in missed:
        print(f"#{item['ref_index']} {item['start']}-{item['end']} "
              f"acc={item['accuracy']} status={item['status']} "
              f"match={item['local_match']} ref={item['ref_text']!r}")
        for cue in item["overlap_cues"]:
            print(f"    H {cue['start']}-{cue['end']} {cue['text']!r}")
        if item["vad_segments"]:
            seg_text = ", ".join(
                f"#{s['seg']} {s['start']}-{s['end']}({s['dur']}s,{s['cover']})"
                for s in item["vad_segments"]
            )
            print(f"    VAD {seg_text}")
        for span in item["dropped_spans"] + item["nonverbal_spans"] + item["empty_spans"]:
            print(f"    {span['kind']} {span['start']}-{span['end']} {span!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
