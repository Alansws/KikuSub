"""纯发声（喘息/笑声/拟声）进质检队列的测试（P0）。"""

from __future__ import annotations

import json

from core import audit, qa, report
from core.transcribe import WhisperVadConfig


def _span(start: float, text: str, *, dur: float = 1.2) -> dict:
    return {
        "start": start,
        "end": start + dur,
        "dur": dur,
        "text": text,
        "rule": "sound-only",
        "peak": 0.2,
        "rms": 0.02,
    }


def test_build_audit_items_adds_nonverbal_item():
    items = audit.build_audit_items(
        [],
        {"nonverbal_spans": [_span(10.0, "ふふっ")]},
        [],
    )
    assert len(items) == 1
    item = items[0]
    assert item["kind"] == "nonverbal"
    assert item["group"] == "low"
    assert item["label"] == "纯发声待核"
    assert item["text"] == "ふふっ"
    assert item["rule_label"] == "纯发声 / 拟声"
    assert item["start"] == 10.0


def test_build_audit_items_caps_nonverbal_at_20():
    spans = [_span(float(i), f"ふふ{i}") for i in range(25)]
    items = audit.build_audit_items([], {"nonverbal_spans": spans}, [])
    nonverbal = [item for item in items if item["kind"] == "nonverbal"]
    assert len(nonverbal) == 20
    # 先按时长/峰值取最值得听的，再按时间排；这里时长相同，取前 20 个起点。
    assert nonverbal[0]["start"] == 0.0
    assert nonverbal[-1]["start"] == 19.0


def test_build_audit_items_skips_empty_nonverbal_text():
    items = audit.build_audit_items(
        [],
        {"nonverbal_spans": [{"start": 1.0, "end": 2.0, "dur": 1.0, "text": " "}]},
        [],
    )
    assert items == []


def test_nonverbal_keep_inserts_cue_and_marks_done():
    items = audit.build_audit_items(
        [],
        {"nonverbal_spans": [_span(10.0, "ふふっ")]},
        [],
    )
    payload = audit.make_audit_payload(
        "episode.mkv", items, {}, 0, engine="whisper", phase="done"
    )
    item = items[0]
    result = qa.apply_action(
        {"action": "mark", "status": "done", "resolution": "kept", "id": item["id"]},
        [],
        media_file=None,
        qa_payload=payload,
    )
    assert result.ok is True
    assert result.cues_changed is True
    assert [cue.text for cue in result.cues] == ["ふふっ"]
    assert result.cues[0].start == 10.0
    data = json.loads(result.qa_payload)
    assert data["statuses"][item["id"]]["status"] == "done"
    assert data["statuses"][item["id"]]["resolution"] == "kept"


def test_nonverbal_confirm_delete_does_not_touch_cues():
    items = audit.build_audit_items(
        [],
        {"nonverbal_spans": [_span(10.0, "ふふっ")]},
        [],
    )
    payload = audit.make_audit_payload(
        "episode.mkv", items, {}, 0, engine="whisper", phase="done"
    )
    item = items[0]
    result = qa.apply_action(
        {"action": "mark", "status": "done", "resolution": "confirmed", "id": item["id"]},
        [],
        media_file=None,
        qa_payload=payload,
    )
    assert result.ok is True
    assert result.cues_changed is False
    data = json.loads(result.qa_payload)
    assert data["statuses"][item["id"]]["resolution"] == "confirmed"


def test_report_counts_nonverbal_and_adds_section():
    data = report.build_report_data(
        media_name="episode.mkv",
        out_filename="episode.AnimeWhisper.srt",
        out_path="/tmp/episode.AnimeWhisper.srt",
        engine_name="Anime Whisper",
        output_format="SRT",
        elapsed_time=10.0,
        cue_count=3,
        char_count=20,
        is_qwen=False,
        config=WhisperVadConfig(),
        engine_family="whisper",
        engine_key="whisper",
        segment_stats={
            "nonverbal_spans": [_span(10.0, "ふふっ")],
            "start_repair": {
                "enabled": True,
                "considered": 2,
                "pulled": 1,
                "total_pull_s": 0.8,
                "max_pull_s": 0.8,
            },
        },
    )
    assert data["quality"]["nonverbal"] == 1
    assert data["quality"]["low_confidence"] == 1
    assert "其中纯发声 1" in data["quality"]["headline"]
    section_ids = [section["id"] for section in data["sections"]]
    assert "nonverbal" in section_ids
    assert "start_repair" in section_ids
    start_section = next(s for s in data["sections"] if s["id"] == "start_repair")
    assert "拉回 1/2 段" in start_section["headline"]
