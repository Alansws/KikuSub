"""质检队列与任务详报的服务化接口。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from core import audit  # noqa: E402
from core.audit import make_audit_payload, write_audit_payload  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "qa-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def ctx(tmp_path: Path, monkeypatch):
    """建一个绑定好媒体的客户端，并把质检 payload 落到 tmp_path。"""
    monkeypatch.setattr(audit, "OUTPUT_DIR", tmp_path, raising=False)
    app = create_app(ServerConfig(token=TOKEN, output_dir=tmp_path))
    client = TestClient(app)

    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    media_id = client.post("/api/media", headers=AUTH, json={"path": str(media)}).json()["id"]
    client.post("/api/session/bind", headers=AUTH, json={"media_id": media_id})

    items = [
        {
            "id": "missed:1000:2000",
            "kind": "missed",
            "start": 1.0,
            "end": 2.0,
            "dur": 1.0,
            "text": "",
            "cues": [],
        },
        {
            "id": "suspect:3000:4000",
            "kind": "suspect",
            "start": 3.0,
            "end": 4.0,
            "dur": 1.0,
            "text": "ねぇ…",
            "cues": [{"start": 3.0, "end": 4.0, "text": "ねぇ…"}],
        },
    ]
    payload = make_audit_payload(
        "episode.mkv", items, {}, 1, 0, engine="whisper", phase="done",
        scanned={"segments": 4, "cues": 1},
    )
    write_audit_payload(str(media), payload)
    return client, media, items


def test_qa_queue_is_readable(ctx):
    client, _, _ = ctx
    data = client.get("/api/qa", headers=AUTH).json()
    assert data["media"] == "episode.mkv"
    assert data["phase"] == "done"
    assert len(data["items"]) == 2
    assert data["counts"]["pending"] == 2


def test_mark_action_marks_item_done(ctx):
    client, _, _ = ctx
    resp = client.post(
        "/api/qa/action",
        headers=AUTH,
        json={"id": "missed:1000:2000", "action": "mark", "status": "done", "resolution": "not-speech"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["cues_changed"] is False
    assert "不是台词" in data["message"]
    assert data["qa"]["counts"]["pending"] == 1
    assert data["qa"]["statuses"]["missed:1000:2000"]["status"] == "done"


def test_delete_cue_changes_session_and_undo_works(ctx):
    client, _, _ = ctx
    # 先给会话铺一条基线字幕
    client.post(
        "/api/cues",
        headers=AUTH,
        json={"cues": [{"start": 3.0, "end": 4.0, "text": "ねぇ…"}]},
    )
    data = client.post(
        "/api/qa/action", headers=AUTH, json={"id": "suspect:3000:4000", "action": "delete_cue"}
    ).json()
    assert data["cues_changed"] is True
    assert data["cues"] == []
    assert data["can_undo"] is True

    restored = client.post("/api/cues/undo", headers=AUTH).json()
    assert len(restored["cues"]) == 1


def test_restore_reinserts_text(ctx):
    client, _, _ = ctx
    data = client.post(
        "/api/qa/action", headers=AUTH, json={"id": "suspect:3000:4000", "action": "restore"}
    ).json()
    assert data["cues_changed"] is True
    assert data["cues"][0]["text"] == "ねぇ…"
    assert data["qa"]["statuses"]["suspect:3000:4000"]["resolution"] == "restored"


def test_focus_returns_edit_fields(ctx):
    client, _, _ = ctx
    data = client.post(
        "/api/qa/action", headers=AUTH, json={"id": "suspect:3000:4000", "action": "focus"}
    ).json()
    assert data["cues_changed"] is False
    assert data["focus"]["start"] == "00:00:03,000"
    assert data["focus"]["end"] == "00:00:04,000"
    assert data["focus"]["text"] == "ねぇ…"


def test_unknown_item_returns_warning_not_exception(ctx):
    client, _, _ = ctx
    resp = client.post(
        "/api/qa/action", headers=AUTH, json={"id": "ghost", "action": "mark"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "没有找到" in data["warning"]


def test_qa_without_bound_media_is_409(tmp_path):
    app = create_app(ServerConfig(token=TOKEN, output_dir=tmp_path))
    client = TestClient(app)
    assert client.get("/api/qa", headers=AUTH).status_code == 200
    assert client.post(
        "/api/qa/action", headers=AUTH, json={"id": "x", "action": "mark"}
    ).status_code == 409


def test_report_404_before_any_job(tmp_path):
    app = create_app(ServerConfig(token=TOKEN, output_dir=tmp_path))
    client = TestClient(app)
    resp = client.get("/api/report", headers=AUTH)
    assert resp.status_code == 404
    assert "还没有完成过转写" in resp.json()["detail"]


def test_report_data_structure(tmp_path):
    """结构化报告：字段齐全、口径与文本一致。"""
    from core.report import build_report_data
    from core.transcribe import WhisperVadConfig

    data = build_report_data(
        media_name="a.mkv",
        out_filename="a.srt",
        out_path="/x/a.srt",
        engine_name="Anime Whisper",
        output_format="SRT",
        elapsed_time=12.5,
        cue_count=3,
        char_count=30,
        is_qwen=False,
        config=WhisperVadConfig(),
        missed_spans=[{"start": 1.0, "end": 2.0, "dur": 1.0, "reason": "empty-after-retry", "peak": 0.5}],
        segment_stats={"hallucination_drops": 1, "suspect_cues": 0, "hallucination_spans": [
            {"start": 3, "end": 4, "dur": 1, "rule": "repeat", "verdict": "dropped", "text": "ああ"},
        ]},
        align_stats={"segments": 5, "degraded": 0, "spans": []},
    )
    assert [s["id"] for s in data["sections"]] == [
        "coverage", "missed", "cut_snap", "onset_pad",
        "hallucination_dropped", "hallucination_suspect", "alignment",
    ]
    assert data["quality"]["coverage"] == 0
    assert data["quality"]["missed"] == 1
    assert data["quality"]["dropped"] == 1
    assert data["sections"][1]["items"][0]["reason_text"] == "重试后仍为空"
    assert "媒体源文件" in {row["label"] for row in data["overview"]}
    # raw_text 与旧文本报告逐字一致
    assert "【任务概览】" in data["raw_text"]
    assert "a.srt" in data["raw_text"]


def test_qwen_report_marks_hallucination_disabled():
    from core.report import build_report_data
    from core.qwen_ctc import QwenCtcConfig

    data = build_report_data(
        media_name="b.mkv", out_filename="b.srt", out_path="/x/b.srt",
        engine_name="Qwen3-ASR", output_format="SRT", elapsed_time=3.0,
        cue_count=1, char_count=5, is_qwen=True, config=QwenCtcConfig(),
    )
    sections = {s["id"]: s for s in data["sections"]}
    assert sections["hallucination"]["disabled"] is True
    assert data["quality"]["qwen_limited"] is True
    assert "不启用" in data["quality"]["headline"] or data["quality"]["dropped"] == 0


def test_qa_payload_survives_reload(ctx):
    """动作写盘后重新读 /api/qa 应该看到同一份状态（跨请求一致）。"""
    client, media, _ = ctx
    client.post("/api/qa/action", headers=AUTH, json={"id": "missed:1000:2000", "action": "skip"})
    reloaded = json.loads((Path(str(media)).parent / f"{Path(str(media)).stem}.qa.json").read_text(encoding="utf-8"))
    assert reloaded["statuses"]["missed:1000:2000"]["status"] == "skipped"
    assert client.get("/api/qa", headers=AUTH).json()["counts"]["skipped"] == 1


def _write_srt(path: Path, text: str) -> str:
    path.write_text(
        f"1\n00:00:01,000 --> 00:00:02,000\n{text}\n",
        encoding="utf-8",
    )
    return str(path)


def test_imported_subtitle_detaches_stale_qa_queue(ctx, tmp_path):
    """导入另一版字幕后，媒体同名的旧队列不能再作用于当前表。"""
    client, _, _ = ctx
    imported = client.post(
        "/api/cues/import",
        headers=AUTH,
        json={"path": _write_srt(tmp_path / "another.srt", "別の字幕")},
    )
    assert imported.status_code == 200, imported.text
    data = imported.json()
    assert data["review_source"]["kind"] == "import"
    assert data["review_source"]["name"] == "another.srt"

    qa = client.get("/api/qa", headers=AUTH).json()
    assert qa["detached"] is True
    assert qa["items"] == []
    assert "another.srt" in qa["detached_reason"]

    # 队列已暂停：不允许再按旧 item 删除 / 补录当前表
    resp = client.post(
        "/api/qa/action", headers=AUTH, json={"id": "missed:1000:2000", "action": "skip"}
    )
    assert resp.status_code == 409


def test_undo_import_restores_previous_review_source(ctx, tmp_path):
    """导入两版字幕后 ⌘Z：字幕和来源必须一起回退。"""
    client, _, _ = ctx
    first = _write_srt(tmp_path / "first.srt", "第一版")
    second = _write_srt(tmp_path / "second.srt", "第二版")
    client.post("/api/cues/import", headers=AUTH, json={"path": first})
    client.post("/api/cues/import", headers=AUTH, json={"path": second})

    undone = client.post("/api/cues/undo", headers=AUTH).json()
    assert undone["cues"][0]["text"] == "第一版"
    assert undone["review_source"]["name"] == "first.srt"
