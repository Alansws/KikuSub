"""逐字对齐文案（纯函数）：分母是语音段、不是字幕条数，未对齐的三类要分开说。"""

from __future__ import annotations

from types import SimpleNamespace

from core.report import _align_stats_headline, align_progress_note, build_report_data


def _stats(**over):
    base = {
        "enabled": True,
        "segments": 257,
        "aligned": 230,
        "noop": 5,
        "degraded": 20,
        "empty": 2,
        "align_chars": 1000,
        "interp_chars": 50,
        "truncated": 0,
        "capped_repeat": 0,
    }
    base.update(over)
    return base


def test_progress_note_names_segments_and_buckets():
    note = align_progress_note(_stats())
    assert "230/257 个语音段" in note
    assert "其余 27 段" in note
    assert "降级 20" in note
    assert "纯符号 5" in note
    assert "无台词 2" in note


def test_progress_note_all_aligned():
    assert align_progress_note(_stats(aligned=257, noop=0, degraded=0, empty=0)) == (
        "（逐字对齐 257/257 个语音段）"
    )


def test_progress_note_hidden_for_disabled_or_empty_stats():
    assert align_progress_note(None) == ""
    assert align_progress_note(_stats(enabled=False)) == ""
    assert align_progress_note(_stats(segments=0, aligned=0)) == ""


def test_headline_says_voice_segments():
    headline = _align_stats_headline(_stats(), "qwen")
    assert headline.startswith("共 257 个语音段")


def _report(family: str):
    return build_report_data(
        media_name="episode.mkv",
        out_filename="episode.Qwen3-ASR.srt",
        out_path="/tmp/episode.Qwen3-ASR.srt",
        engine_name="Qwen3-ASR",
        output_format="SRT",
        elapsed_time=12.0,
        cue_count=2,
        char_count=20,
        is_qwen=family == "qwen",
        engine_family=family,
        config=SimpleNamespace(),
        align_stats=_stats(),
    )


def test_alignment_section_explains_buckets_for_qwen_only():
    qwen = {s["id"]: s for s in _report("qwen")["sections"]}
    assert "不是字幕条数" in qwen["alignment"]["note"]
    sherpa = {s["id"]: s for s in _report("sherpa")["sections"]}
    assert sherpa["alignment"].get("note") == ""
