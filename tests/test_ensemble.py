"""双引擎补漏候选的纯逻辑回归：不加载模型、不碰 IO。"""

from __future__ import annotations

from core.ensemble import _overlaps_primary, build_ensemble_suggestions
from core.subtitles import SubtitleCue


def cue(start: float, end: float, text: str) -> SubtitleCue:
    return SubtitleCue(start=start, end=end, text=text)


def test_only_b_cue_becomes_suggestion():
    primary = [cue(0.0, 1.0, "おはよう")]
    secondary = [cue(0.0, 1.0, "おはよう"), cue(2.0, 3.2, "今日はいい天気だね")]

    items = build_ensemble_suggestions(primary, secondary, engine="whisper")
    assert [item["text"] for item in items] == ["今日はいい天気だね"]
    assert items[0]["engine"] == "whisper"
    assert items[0]["reason"] == "only_b"
    assert items[0]["duration"] == 1.2
    assert items[0]["nearest_a"] == "おはよう"


def test_short_and_nonverbal_fragments_are_filtered():
    primary = [cue(0.0, 1.0, "おはよう")]
    secondary = [
        cue(0.0, 1.0, "おはよう"),
        cue(2.0, 2.2, "あ"),          # 太短
        cue(3.0, 3.2, "んふ"),        # 时长 < 0.35s
        cue(4.0, 5.0, "……"),          # 归一化后没有实字
    ]
    assert build_ensemble_suggestions(primary, secondary) == []


def test_nearby_same_text_is_a_boundary_artifact_not_a_miss():
    # 主稿在附近已经有同一句：副稿只是把边界切到了这句上。
    primary = [cue(0.0, 1.0, "おはよう"), cue(8.0, 9.0, "また明日")]
    secondary = [cue(0.0, 1.0, "おはよう"), cue(9.2, 10.0, "また明日")]
    assert build_ensemble_suggestions(primary, secondary) == []


def test_same_text_far_away_is_not_treated_as_duplicate():
    # 相隔十几分钟的「はい」是正常重复台词，不能因为全片出现过一次就丢掉。
    primary = [cue(0.0, 1.0, "はい")]
    secondary = [cue(0.0, 1.0, "はい"), cue(900.0, 901.0, "はい")]
    items = build_ensemble_suggestions(primary, secondary)
    assert [item["start"] for item in items] == [900.0]


def test_only_b_repeats_are_kept_when_far_apart():
    primary = [cue(0.0, 1.0, "おはよう")]
    secondary = [
        cue(0.0, 1.0, "おはよう"),
        cue(2.0, 3.0, "今日はいい天気だね"),
        cue(10.0, 11.0, "今日はいい天気だね"),
    ]
    items = build_ensemble_suggestions(primary, secondary)
    assert [item["start"] for item in items] == [2.0, 10.0]


def test_only_b_nearby_repeats_are_deduped():
    primary = [cue(0.0, 1.0, "おはよう")]
    secondary = [
        cue(0.0, 1.0, "おはよう"),
        cue(2.0, 3.0, "今日はいい天気だね"),
        cue(4.0, 5.0, "今日はいい天気だね"),
    ]
    items = build_ensemble_suggestions(primary, secondary)
    assert [item["start"] for item in items] == [2.0]


def test_overlap_with_primary_is_never_a_suggestion():
    # B 只和 A 有 0.2s 交集（不到 12%，不会被 dual_review 配对），但已经够 0.15s，
    # 插回去会叠字幕，必须留在 DualView。
    primary = [cue(0.0, 1.0, "おはよう")]
    secondary = [cue(0.0, 1.0, "おはよう"), cue(0.8, 2.8, "今日はいい天気だね")]
    assert build_ensemble_suggestions(primary, secondary) == []


def test_overlap_helper_ratio_and_absolute_thresholds():
    target = cue(10.0, 12.0, "テスト")
    assert _overlaps_primary(target, [cue(10.0, 10.2, "x")]) is True    # 0.2s
    assert _overlaps_primary(target, [cue(12.0, 13.0, "x")]) is False   # 仅相接
    assert _overlaps_primary(target, [cue(11.5, 12.5, "x")]) is True    # 25%
    assert _overlaps_primary(target, [cue(8.0, 9.9, "x")]) is False     # 无交集


def test_limit_and_time_order():
    primary: list[SubtitleCue] = []
    secondary = [cue(float(i * 2), float(i * 2 + 1), f"台詞{i}です") for i in range(10)]
    items = build_ensemble_suggestions(primary, secondary, limit=3)
    assert [item["start"] for item in items] == [0.0, 2.0, 4.0]


def test_no_secondary_or_zero_limit():
    assert build_ensemble_suggestions([cue(0.0, 1.0, "おはよう")], []) == []
    assert build_ensemble_suggestions(
        [cue(0.0, 1.0, "おはよう")],
        [cue(0.0, 1.0, "おはよう"), cue(2.0, 3.0, "元気")],
        limit=0,
    ) == []


def test_vocalization_only_fragments_are_filtered():
    primary = [cue(0.0, 1.0, "おはよう")]
    secondary = [
        cue(0.0, 1.0, "おはよう"),
        cue(2.0, 2.8, "んー…"),
        cue(3.0, 3.9, "んっ"),
        cue(4.0, 5.0, "んふっ"),
        cue(6.0, 7.0, "必要だね…"),
    ]
    assert [item["text"] for item in build_ensemble_suggestions(primary, secondary)] == [
        "必要だね…"
    ]


def test_onomatopoeia_markers_are_filtered_but_real_kana_lines_kept():
    primary = [cue(0.0, 1.0, "おはよう")]
    secondary = [
        cue(0.0, 1.0, "おはよう"),
        cue(2.0, 2.9, "ぺろっ"),
        cue(3.0, 3.6, "はむぅ…"),
        cue(4.0, 6.8, "んっ…んんっ…"),
        cue(7.0, 8.0, "いいよ…"),
    ]
    assert [item["text"] for item in build_ensemble_suggestions(primary, secondary)] == [
        "いいよ…"
    ]
