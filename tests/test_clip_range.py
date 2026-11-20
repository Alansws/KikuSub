"""片段范围裁剪的纯函数回归（`core/clip_range.py`）。

用户场景：长片只精修一段，打了一个大区间章节（`0:10 → 24:22 章节1`）和一个
内部时刻点（`22:55 发射点`），然后只处理 / 只导出这一段。这里把三件事冻住：

1. 首尾蹭边（<0.1s）的邻句不算命中，整条落在区间内的短句不能误杀；
2. 平移后夹紧到 `[0, duration]`，片段外的条目丢弃；
3. 章节按原样搬（大区间不被时刻点拆开），时刻点精确减 `start`
   （22:55 → 22:45），落在片段终点的时刻点丢弃。
"""

from __future__ import annotations

import pytest

from core import chapters as chapter_store
from core.clip_range import (
    ClipWindow,
    clip_tag,
    clip_window,
    clock_label,
    safe_label,
    select_cues_in_range,
    shift_chapters_to_clip,
    shift_cues_to_clip,
)
from core.chapters import ChapterMark
from core.subtitles import SubtitleCue


def _cues(*spans: tuple[float, float, str]) -> list[SubtitleCue]:
    return [SubtitleCue(start=a, end=b, text=t) for a, b, t in spans]


# --------------------------------------------------------------------------- 窗口


def test_clip_window_none_means_full_film() -> None:
    assert clip_window(0, 0) is None
    assert clip_window(None, None) is None
    assert clip_window(12.0, None) is None


def test_clip_window_clamps_to_media_duration() -> None:
    window = clip_window(5.0, 999.0, duration=100.0)
    assert window == ClipWindow(start=5.0, end=100.0)
    assert window is not None and window.duration == pytest.approx(95.0)


def test_clip_window_rejects_too_short() -> None:
    with pytest.raises(ValueError):
        clip_window(10.0, 10.05)
    with pytest.raises(ValueError):
        clip_window(120.0, 999.0, duration=100.0)  # 起点已在片尾之后


def test_clip_window_clamp() -> None:
    window = clip_window(10.0, 20.0)
    assert window is not None
    assert window.clamp(5.0) == 0.0
    assert window.clamp(15.0) == pytest.approx(5.0)
    assert window.clamp(99.0) == pytest.approx(10.0)


# --------------------------------------------------------------------------- 字幕筛选


def test_select_ignores_short_edge_overlap() -> None:
    cues = _cues(
        (8.0, 10.05, "上一个场景的尾巴"),  # 只蹭到 0.05s
        (9.0, 12.0, "跨过片头但真的在说话"),
        (12.5, 12.56, "はい"),  # 整条都在区间内的短句：必须保留
        (19.9, 20.02, "片尾蹦字"),
        (20.5, 22.0, "片段之后"),
    )
    picked = select_cues_in_range(cues, 10.0, 20.0)
    assert [cue.text for cue in picked.cues] == [
        "跨过片头但真的在说话",
        "はい",
        "片尾蹦字",
    ]
    assert picked.indices == [1, 2, 3]
    assert (picked.from_index, picked.to_index, picked.count) == (2, 4, 3)
    assert picked.contiguous is True


def test_select_keeps_contiguous_span_of_hits() -> None:
    cues = _cues(
        (0.0, 1.0, "a"),
        (1.0, 2.0, "b"),
        (2.0, 3.0, "c"),
        (30.0, 31.0, "d"),
    )
    picked = select_cues_in_range(cues, 0.5, 2.5)
    assert [cue.text for cue in picked.cues] == ["a", "b", "c"]
    assert picked.contiguous is True
    empty = select_cues_in_range(cues, 10.0, 20.0)
    assert empty.count == 0
    assert empty.from_index == 0 and empty.to_index == 0


def test_select_empty_for_inverted_range() -> None:
    picked = select_cues_in_range(_cues((1.0, 2.0, "a")), 5.0, 4.0)
    assert picked.count == 0


# --------------------------------------------------------------------------- 字幕平移


def test_shift_cues_clamps_and_keeps_translations() -> None:
    cues = _cues(
        (9.0, 12.0, "跨界句"),
        (12.0, 14.0, "第一句"),
        (18.0, 20.5, "尾部跨界句"),
        (21.0, 22.0, "片段之后"),
    )
    shifted, texts = shift_cues_to_clip(cues, ["A", "B", "C", "D"], 10.0, 20.0)
    assert [(c.start, c.end) for c in shifted] == [
        (0.0, 2.0),
        (2.0, 4.0),
        (8.0, 10.0),
    ]
    assert [c.text for c in shifted] == ["跨界句", "第一句", "尾部跨界句"]
    assert texts == ["A", "B", "C"]


def test_shift_cues_pads_missing_translations() -> None:
    cues = _cues((1.0, 2.0, "甲"), (2.0, 3.0, "乙"))
    shifted, texts = shift_cues_to_clip(cues, ["只有一条"], 0.0, 5.0)
    assert len(shifted) == 2
    assert texts == ["只有一条", ""]


def test_shift_cues_returns_copies() -> None:
    cue = SubtitleCue(start=11.0, end=12.0, text="原文")
    shifted, _ = shift_cues_to_clip([cue], [], 10.0, 20.0)
    assert shifted[0] is not cue
    assert cue.start == 11.0  # 原对象不变


# --------------------------------------------------------------------------- 章节平移


def _marks() -> list[ChapterMark]:
    return [
        ChapterMark(id="scene-1", start=10.0, end=1462.0, title="章节1"),
        ChapterMark(id="launch", start=1375.0, end=None, title="发射点"),
    ]


def test_shift_chapters_matches_user_example() -> None:
    """0:10 章节1 + 22:55 发射点，裁剪 [10s, 1462s] → 0:00 与 22:45。"""
    shifted = shift_chapters_to_clip(_marks(), 10.0, 1462.0)
    assert [(m.start, m.end, m.title) for m in shifted] == [
        (0.0, 1452.0, "章节1"),
        (1365.0, None, "发射点"),
    ]
    layout = chapter_store.layout_chapters(shifted, 1452.0)
    assert [(c.start_ms, c.end_ms, c.title) for c in layout] == [
        (0, 1365_000, "章节1"),
        (1365_000, 1452_000, "发射点"),
    ]


def test_shift_chapters_keeps_range_intact_inside_point() -> None:
    """大区间套小时间点：区间不被拆成两段，时刻点保留在区间内部。"""
    shifted = shift_chapters_to_clip(
        [
            ChapterMark(id="big", start=0.0, end=100.0, title="大章"),
            ChapterMark(id="mid", start=60.0, end=None, title="内部时刻点"),
        ],
        0.0,
        120.0,
    )
    assert [m.id for m in shifted] == ["big", "mid"]
    assert shifted[0].start == 0.0 and shifted[0].end == 100.0
    assert shifted[1].start == 60.0 and shifted[1].end is None


def test_shift_chapters_clamps_partial_overlap() -> None:
    marks = [
        ChapterMark(id="before", start=0.0, end=30.0, title="跨片头"),
        ChapterMark(id="after", start=50.0, end=90.0, title="跨片尾"),
        ChapterMark(id="outside", start=95.0, end=99.0, title="完全在外"),
    ]
    shifted = shift_chapters_to_clip(marks, 20.0, 60.0)
    assert [(m.id, m.start, m.end) for m in shifted] == [
        ("before", 0.0, 10.0),
        ("after", 30.0, 40.0),
    ]


def test_shift_chapters_drops_point_at_clip_end() -> None:
    marks = [
        ChapterMark(id="start", start=10.0, end=None, title="片头点"),
        ChapterMark(id="end", start=20.0, end=None, title="终点上的点"),
    ]
    shifted = shift_chapters_to_clip(marks, 10.0, 20.0)
    assert [(m.id, m.start) for m in shifted] == [("start", 0.0)]


def test_shift_chapters_empty_for_degenerate_window() -> None:
    assert shift_chapters_to_clip(_marks(), 10.0, 10.0) == []


# --------------------------------------------------------------------------- 文件名标签


def test_clock_and_tag_labels() -> None:
    assert clock_label(10) == "00m10s"
    assert clock_label(1462) == "24m22s"
    assert clock_label(3723) == "1h02m03s"
    assert safe_label("场景 1/发射; #点") == "场景-1-发射-点"
    assert clip_tag(10, 1462, "章节1") == "章节1-00m10s-24m22s"
    assert clip_tag(10, 1462) == "00m10s-24m22s"
    # 标题里的路径分隔符与空白不能进文件名
    assert "/" not in clip_tag(0, 60, "a/b c")
    assert safe_label("   ") == ""
