"""P2：ensemble 补漏项与空白 QA 的合并升级、采纳动作。"""

from __future__ import annotations

import json

from core import audit, qa


def _ensemble(start: float = 10.05, end: float = 11.2, text: str = "本当は言いたかった") -> dict:
    return {
        "start": start,
        "end": end,
        "duration": round(end - start, 2),
        "text": text,
        "engine": "whisper",
        "reason": "only_b",
        "nearest_a": "……",
    }


def test_ensemble_upgrades_empty_missed_item_in_place():
    items = audit.build_audit_items(
        [{"start": 10.0, "end": 11.0, "dur": 1.0, "reason": "empty-after-retry", "peak": 0.4}],
        {"ensemble_spans": [_ensemble()]},
        [],
    )
    assert len(items) == 1
    item = items[0]
    assert item["kind"] == "ensemble"
    assert item["group"] == "miss"
    assert item["label"] == "双引擎补漏"
    assert item["text"] == "本当は言いたかった"
    assert item["rule_label"] == "副引擎补漏"
    assert item["cues"] == [
        {"start": 10.05, "end": 11.2, "text": "本当は言いたかった"}
    ]


def test_ensemble_upgrades_coverage_gap_that_contains_it():
    items = audit.build_audit_items(
        [],
        {"ensemble_spans": [_ensemble(31.0, 32.0)]},
        [],
        coverage_spans=[
            {"gap_start": 30.0, "gap_end": 40.0, "start": 31.0, "end": 32.0, "dur": 1.0}
        ],
    )
    assert [item["kind"] for item in items] == ["ensemble"]


def test_ensemble_keeps_unrelated_blank_item():
    items = audit.build_audit_items(
        [{"start": 10.0, "end": 11.0, "dur": 1.0, "reason": "empty-after-retry", "peak": 0.4}],
        {"ensemble_spans": [_ensemble(20.0, 21.0)]},
        [],
    )
    assert [item["kind"] for item in items] == ["missed", "ensemble"]


def test_ensemble_keep_inserts_cue_and_marks_adopted():
    items = audit.build_audit_items(
        [{"start": 10.0, "end": 11.0, "dur": 1.0, "reason": "empty-after-retry", "peak": 0.4}],
        {"ensemble_spans": [_ensemble()]},
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
    assert [cue.text for cue in result.cues] == ["本当は言いたかった"]
    assert "采纳补漏" in result.message
    data = json.loads(result.qa_payload)
    assert data["statuses"][item["id"]]["resolution"] == "kept"


def test_ensemble_keep_is_idempotent_when_cue_already_exists():
    items = audit.build_audit_items(
        [], {"ensemble_spans": [_ensemble()]}, []
    )
    payload = audit.make_audit_payload(
        "episode.mkv", items, {}, 0, engine="whisper", phase="done"
    )
    from core.subtitles import SubtitleCue

    existing = [SubtitleCue(10.05, 11.2, "本当は言いたかった")]
    result = qa.apply_action(
        {"action": "mark", "status": "done", "resolution": "kept", "id": items[0]["id"]},
        existing,
        media_file=None,
        qa_payload=payload,
    )
    assert result.cues_changed is False
    assert len(result.cues) == 1
    assert "已经在核对台" in result.message
