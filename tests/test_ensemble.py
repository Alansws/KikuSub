"""双引擎补漏候选的纯逻辑回归：不加载模型、不碰 IO。"""

from __future__ import annotations

from core.ensemble import build_ensemble_suggestions
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


def test_same_text_elsewhere_is_a_boundary_artifact_not_a_miss():
    # 主稿在别的时间点已经有同一句：副稿只是把边界切到了这句上。
    primary = [cue(0.0, 1.0, "おはよう"), cue(8.0, 9.0, "また明日")]
    secondary = [cue(0.0, 1.0, "おはよう"), cue(9.2, 10.0, "また明日")]
    assert build_ensemble_suggestions(primary, secondary) == []


def test_duplicate_only_b_text_is_kept_once():
    primary = [cue(0.0, 1.0, "おはよう")]
    secondary = [
        cue(0.0, 1.0, "おはよう"),
        cue(2.0, 3.0, "今日はいい天気だね"),
        cue(10.0, 11.0, "今日はいい天気だね"),
    ]
    items = build_ensemble_suggestions(primary, secondary)
    assert len(items) == 1
    assert items[0]["start"] == 2.0


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
