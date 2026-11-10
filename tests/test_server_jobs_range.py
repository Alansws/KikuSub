"""replace_range 的边界语义：只替换真正被区间覆盖的旧字幕，不能误删邻句。"""

from __future__ import annotations

from core.transcribe import SubtitleCue
from server.jobs import merge_replace_range


def test_edge_clipped_neighbor_is_kept():
    review = [
        SubtitleCue(10.916, 12.508, "あなたも好きに?"),
        SubtitleCue(20.836, 22.716, "チラチラ見なくていいんだよ"),
        SubtitleCue(25.348, 27.068, "好きなだけ見て"),
    ]
    fresh = [SubtitleCue(19.364, 21.020, "今日は…ちら")]
    merged = merge_replace_range(review, fresh, 18.56, 21.02)
    texts = [cue.text for cue in merged]
    # 邻句只在尾部被切到 0.184s，必须保留；补录句照常插入。
    assert "チラチラ見なくていいんだよ" in texts
    assert "今日は…ちら" in texts
    assert len(merged) == 4


def test_fully_covered_cue_is_replaced():
    review = [SubtitleCue(19.0, 20.0, "旧句")]
    fresh = [SubtitleCue(19.2, 19.8, "新句")]
    merged = merge_replace_range(review, fresh, 18.5, 21.0)
    assert [cue.text for cue in merged] == ["新句"]


def test_cue_before_range_is_kept():
    review = [SubtitleCue(10.0, 11.0, "前句")]
    fresh = [SubtitleCue(19.364, 20.0, "新句")]
    merged = merge_replace_range(review, fresh, 18.5, 21.0)
    assert [cue.text for cue in merged] == ["前句", "新句"]
