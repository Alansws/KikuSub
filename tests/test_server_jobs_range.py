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


def test_first_cue_in_range_skips_padding_gap():
    """选区转写完成后前端要跳到「第一条新句」，不能落在 padding 的空白里。"""
    from core.subtitles import SubtitleCue
    from server.jobs import first_cue_in_range

    merged = [
        SubtitleCue(0.0, 2.0, "前一句"),
        SubtitleCue(5.1, 7.8, "这次转出的第一句"),
        SubtitleCue(8.2, 10.0, "第二句"),
        SubtitleCue(12.0, 13.0, "后一句"),
    ]
    # 选区 5.0–8.0 带 0.1 的 padding：合并后 5.1 才是新句
    assert first_cue_in_range(merged, 5.0, 8.0) == 1
    # 区间内没有字幕时返回 None，前端退回播放头定位
    assert first_cue_in_range(merged, 10.1, 11.9) is None


def test_first_cue_prefers_fresh_result_over_overlapping_neighbour():
    """区间起点可能压着上一句的尾巴：应选这次新转出的句子，而不是邻句。"""
    from core.subtitles import SubtitleCue
    from server.jobs import first_cue_in_range, merge_replace_range, target_cue_index

    review = [
        SubtitleCue(0.0, 2.0, "前一句"),
        SubtitleCue(4.9, 5.08, "上一句的尾巴"),
        SubtitleCue(12.0, 13.0, "后一句"),
    ]
    fresh = [SubtitleCue(5.1, 7.8, "这次转出的第一句")]
    merged = merge_replace_range(review, fresh, 5.0, 8.0)
    # 合并后的第一条重叠者是旧邻句
    assert first_cue_in_range(merged, 5.0, 8.0) == 1
    # 但前端应该选中的是 fresh 里的第一句，它的下标是 2
    assert target_cue_index(merged, fresh, 5.0, 8.0) == 2


def test_full_transcription_marks_review_source(tmp_path):
    """整片转写完成后，核对台来源必须是这次任务；局部修正不能顶掉它。"""
    from types import SimpleNamespace

    from server.jobs import JobManager, JobRecord
    from server.sessions import Session

    manager = JobManager(tmp_path)
    session = Session(id="s")
    request = SimpleNamespace(start_s=None, end_s=None, media_path=tmp_path / "demo.mkv")
    job = JobRecord(id="job-full", kind="transcribe")
    job.result = {"out_filename": "demo.srt", "out_path": str(tmp_path / "demo.srt")}

    manager._apply_cues(session, request, [SubtitleCue(0.0, 1.0, "一句")], "replace", job)
    assert session.review_source["kind"] == "transcription"
    assert session.review_source["job_id"] == "job-full"
    assert session.review_source["name"] == "demo.srt"

    # 选区修正保留整片那次任务的来源：报告仍然对得上。
    range_request = SimpleNamespace(start_s=0.0, end_s=2.0, media_path=request.media_path)
    range_job = JobRecord(id="job-range", kind="transcribe")
    range_job.result = {"out_filename": "demo_00m00s-00m02s.srt", "out_path": ""}
    manager._apply_cues(
        session, range_request, [SubtitleCue(0.0, 1.0, "改过")], "replace_range", range_job
    )
    assert session.review_source["job_id"] == "job-full"

    # 第一次 ⌘Z 回到整片转写状态；再退一步回到转写前，来源一起回退。
    session.undo()
    assert session.review_source["job_id"] == "job-full"
    session.undo()
    assert session.review_source == {}
