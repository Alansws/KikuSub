"""双语/译文导出与过期判定（开发文档 §6.3 / §6.4）。"""

from __future__ import annotations

from core.i18n import bilingual_cues, stale_indices, target_cues
from core.subtitles import SubtitleCue

CUES = [
    SubtitleCue(0.0, 1.0, "おはよう"),
    SubtitleCue(1.0, 2.0, "今日は雨だ"),
    SubtitleCue(2.0, 3.0, "またね"),
]
TEXTS = ["早上好", "今天下雨", "再见"]


def test_bilingual_puts_source_first_then_target():
    out = bilingual_cues(CUES, TEXTS)
    assert [c.text for c in out] == ["おはよう\n早上好", "今日は雨だ\n今天下雨", "またね\n再见"]
    assert [(c.start, c.end) for c in out] == [(c.start, c.end) for c in CUES]


def test_bilingual_degrades_to_single_line_when_missing():
    out = bilingual_cues(CUES, ["早上好", "", "再见"])
    assert out[1].text == "今日は雨だ"


def test_bilingual_survives_short_texts():
    out = bilingual_cues(CUES, ["只有一条"])
    assert out[0].text == "おはよう\n只有一条"
    assert out[2].text == "またね"


def test_target_skips_blank_and_counts_them():
    out, skipped = target_cues(CUES, ["早上好", "  ", "再见"])
    assert [c.text for c in out] == ["早上好", "再见"]
    assert skipped == 1
    assert [(c.start, c.end) for c in out] == [(0.0, 1.0), (2.0, 3.0)]


def test_target_keeps_timeline_of_survivors():
    out, _ = target_cues(CUES, TEXTS)
    assert [c.start for c in out] == [0.0, 1.0, 2.0]


# --------------------------------------------------------------------------- 过期


def test_stale_is_empty_when_source_unchanged():
    assert stale_indices(CUES, [c.text for c in CUES]) == []


def test_stale_flags_changed_text_only():
    base = ["おはよう", "今日は雪だ", "またね"]
    assert stale_indices(CUES, base) == [1]


def test_stale_flags_missing_base_entries():
    assert stale_indices(CUES, ["おはよう"]) == [1, 2]


def test_deletion_shifts_everything_after_it_to_stale():
    """删一条会让后面的译文整体错位——必须如实标出来，而不是继续装作对得上。"""
    base = [c.text for c in CUES]
    remaining = [CUES[0], CUES[2]]
    assert stale_indices(remaining, base) == [1]
