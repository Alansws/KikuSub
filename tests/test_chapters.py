"""章节 / 时刻点标记：纯逻辑、持久化与统一历史。

不依赖 ffmpeg：FFMETADATA 的 **实际可读性** 由 `tests/test_export_chapters.py`
用 `ffprobe -show_chapters` 验证；这里锁住归一化、衔接、转义与历史语义。
"""

from __future__ import annotations

import json
from pathlib import Path

from core import chapters
from core.chapters import ChapterMark


def mark(start: float, end: float | None = None, title: str = "", id: str = "") -> ChapterMark:
    return ChapterMark(id=id or f"m{start}", start=start, end=end, title=title)


def test_point_mark_ends_at_next_mark_or_tail():
    marks = [mark(0, 10, "场景1"), mark(23.5, None, "倒计时开始"), mark(25.166, None, "发射点")]
    laid = chapters.layout_chapters(marks, 30, pad_start=False)
    assert [(c.start, c.end) for c in laid] == [(0, 10), (23.5, 25.166), (25.166, 30)]
    assert [c.title for c in laid] == ["场景1", "倒计时开始", "发射点"]


def test_marks_are_sorted_even_if_input_is_shuffled():
    laid = chapters.layout_chapters([mark(10, 12, "B"), mark(0, 4, "A")], 20, pad_start=False)
    assert [c.title for c in laid] == ["A", "B"]


def test_overlapping_intervals_are_clipped_to_the_next_start():
    laid = chapters.layout_chapters([mark(0, 15, "长区间"), mark(8, 12, "后一个")], 20, pad_start=False)
    assert [(c.start, c.end) for c in laid] == [(0, 8), (8, 12)]


def test_interval_is_clamped_to_duration():
    laid = chapters.layout_chapters([mark(0, 999, "超长")], 10, pad_start=False)
    assert [(c.start, c.end) for c in laid] == [(0, 10)]


def test_zero_length_interval_becomes_point_and_tail_marks_drop():
    marks = [mark(5, 5, "零长度"), mark(10, None, "片尾之后")]
    # 零长度区间退化成时刻点（结束于片尾）；起点已在片尾的标记丢弃
    laid = chapters.layout_chapters(marks, 10, pad_start=False)
    assert [(c.start, c.end, c.title) for c in laid] == [(5, 10, "零长度")]


def test_first_mark_after_zero_gets_an_opening_chapter():
    """MP4 会把首章拉回 0：先补一段「开场」，真实起点才保得住。"""
    laid = chapters.layout_chapters([mark(12, None, "倒计时开始")], 60)
    assert [(c.start, c.end, c.title) for c in laid] == [
        (0, 12, "开场"),
        (12, 60, "倒计时开始"),
    ]
    # 忠实布局（不补开场）仍然可用
    assert chapters.layout_chapters([mark(12, 20, "x")], 60, pad_start=False)[0].start == 12
    # 首个标记本来就在 0：不重复补
    assert [c.title for c in chapters.layout_chapters([mark(0, 5, "开场")], 60)] == ["开场"]


def test_duplicate_ids_are_made_unique():
    marks = [mark(0, 1, "A", id="same"), mark(2, 3, "B", id="same")]
    normalized = chapters.normalize_marks(marks, 10)
    assert [m.id for m in normalized] == ["same", "same-2"]


def test_timebase_is_milliseconds_and_sorted():
    text = chapters.ffmetadata_text([mark(0, 5.679, "章节")], 10)
    assert text.startswith(";FFMETADATA1")
    assert "TIMEBASE=1/1000" in text
    assert "START=0" in text
    assert "END=5679" in text


def test_escaping_covers_semicolon_hash_backslash_equal_and_newline():
    escaped = chapters.escape_ffmetadata("a;b#c\\d=e")
    assert escaped == "a\\;b\\#c\\\\d\\=e"
    # 换行 = 反斜杠 + 真实换行（ffmetadata 的行继续）
    assert chapters.escape_ffmetadata("第一行\n第二行") == "第一行\\\n第二行"


def test_persistence_round_trip(tmp_path: Path):
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"x")
    chapters.save_marks(tmp_path, media, [mark(0, 5, "开头"), mark(20, None, "转折")])
    loaded = chapters.load_marks(tmp_path, media)
    assert [(m.start, m.end, m.title) for m in loaded] == [(0, 5, "开头"), (20, None, "转折")]
    # 写在 chapters/ 子目录，且按媒体身份分段（同名不同文件不会串）
    path = chapters.store_path(tmp_path, media)
    assert path.parent.name == "chapters"
    assert path.name.endswith(".chapters.json")
    other = tmp_path / "other.mkv"
    other.write_bytes(b"y")
    assert chapters.store_path(tmp_path, other) != path
    assert chapters.load_marks(tmp_path, other) == []


def test_load_marks_tolerates_broken_files(tmp_path: Path):
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"x")
    path = chapters.store_path(tmp_path, media)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert chapters.load_marks(tmp_path, media) == []


def _session(tmp_path: Path):
    from server.sessions import Session

    media = tmp_path / "movie.mkv"
    media.write_bytes(b"x")
    session = Session(id="sid")
    session.media_path = str(media)
    session.sync_chapters(media_path=str(media), output_dir=tmp_path, duration=30)
    return session, media


def test_chapter_edit_is_one_history_step_and_undo_restores(tmp_path: Path):
    session, media = _session(tmp_path)
    session.set_chapters([{"id": "a", "start": 0, "end": 5, "title": "开场"}], label="新建章节", duration=30)
    session.set_chapters(
        [{"id": "a", "start": 0, "end": 5, "title": "改名后"}], label="重命名章节", duration=30
    )
    assert [m.title for m in session.chapters] == ["改名后"]
    assert session.undo_label() == "重命名章节"

    session.undo()
    assert [m.title for m in session.chapters] == ["开场"]
    # 磁盘也要跟着回到上一版：重启后不能看到撤销前的内容
    assert [m.title for m in chapters.load_marks(tmp_path, media)] == ["开场"]

    session.redo()
    assert [m.title for m in session.chapters] == ["改名后"]


def test_chapters_reload_from_disk_after_binding(tmp_path: Path):
    session, media = _session(tmp_path)
    session.set_chapters([{"id": "a", "start": 3, "end": 8, "title": "保存的章节"}], label="新建", duration=30)
    # 模拟重启：新会话从边车恢复
    from server.sessions import Session

    fresh = Session(id="sid2")
    fresh.media_path = str(media)
    restored = fresh.sync_chapters(media_path=str(media), output_dir=tmp_path, duration=30)
    assert [m.title for m in restored] == ["保存的章节"]


def test_reset_for_media_clears_chapters():
    from server.sessions import Session

    session = Session(id="sid")
    session.chapters = [mark(0, 3, "旧片")]
    session.reset_for_media()
    assert session.chapters == []


def test_save_writes_versioned_json(tmp_path: Path):
    session, media = _session(tmp_path)
    session.set_chapters([{"id": "a", "start": 0, "end": 2, "title": "x"}], label="新建", duration=10)
    raw = json.loads(chapters.store_path(tmp_path, media).read_text(encoding="utf-8"))
    assert raw["version"] == chapters.CHAPTERS_VERSION
    assert raw["marks"][0]["title"] == "x"
