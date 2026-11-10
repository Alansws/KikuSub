"""任务与 WebSocket 进度流：生命周期、事件帧、取消、单槽并发。

用替身 runner 驱动，不加载任何模型。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from core.pipeline import TranscribeResult  # noqa: E402
from core.transcribe import SubtitleCue  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402
from server.jobs import JobManager  # noqa: E402

TOKEN = "job-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _result(tmp_path: Path) -> TranscribeResult:
    out = tmp_path / "episode.srt"
    out.write_text("1\n00:00:00,000 --> 00:00:01,000\nテスト\n", encoding="utf-8")
    return TranscribeResult(
        cues=[SubtitleCue(0.0, 1.0, "テスト")],
        out_path=out,
        out_filename=out.name,
        elapsed=1.5,
        char_count=3,
        interrupted=False,
        report_text="报告",
        audit_payload="{}",
        pending_qa=0,
        status_summary="✅ 转写完成",
        final_progress="✅ 转录完成！",
        preview="[0.00 → 1.00] テスト",
        table=[[1, "00:00:00,000", "00:00:01,000", "テスト"]],
    )


class _SlowRunner:
    """发几帧进度、等一小会儿，再返回结果。"""

    def __init__(self, tmp_path: Path, steps: int = 3, delay: float = 0.02) -> None:
        self.tmp_path = tmp_path
        self.steps = steps
        self.delay = delay
        self.cancelled = threading.Event()

    def __call__(self, request, *, on_progress, cancel_event, output_dir):
        for i in range(1, self.steps + 1):
            if cancel_event is not None and cancel_event.is_set():
                self.cancelled.set()
                raise RuntimeError("cancelled")
            on_progress(i / self.steps, f"第 {i}/{self.steps} 段")
            time.sleep(self.delay)
        return _result(self.tmp_path)


@pytest.fixture()
def make_client(tmp_path: Path):
    def _factory(runner=None) -> TestClient:
        app = create_app(ServerConfig(token=TOKEN, output_dir=tmp_path))
        app.state.jobs = JobManager(tmp_path, runner=runner or _SlowRunner(tmp_path))
        return TestClient(app)

    return _factory


def _import_media(client: TestClient, tmp_path: Path) -> str:
    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    resp = client.post("/api/media", headers=AUTH, json={"path": str(media)})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_job_runs_to_completion_and_reports_result(make_client, tmp_path):
    client = make_client()
    media_id = _import_media(client, tmp_path)

    created = client.post("/api/jobs", headers=AUTH, json={"media_id": media_id})
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    deadline = time.time() + 10
    while time.time() < deadline:
        snapshot = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if snapshot["status"] in {"done", "error"}:
            break
        time.sleep(0.02)

    assert snapshot["status"] == "done"
    assert snapshot["percent"] == 100
    assert snapshot["result"]["cue_count"] == 1
    assert snapshot["result"]["out_filename"] == "episode.srt"


def test_websocket_streams_progress_then_done(make_client, tmp_path):
    client = make_client()
    media_id = _import_media(client, tmp_path)
    job_id = client.post("/api/jobs", headers=AUTH, json={"media_id": media_id}).json()["id"]

    frames: list[dict] = []
    with client.websocket_connect(f"/ws/jobs/{job_id}?token={TOKEN}") as ws:
        while True:
            frame = ws.receive_json()
            frames.append(frame)
            if frame["type"] in {"done", "error", "cancelled"}:
                break

    types = [f["type"] for f in frames]
    assert types[0] == "snapshot"
    assert "progress" in types
    assert types[-1] == "done"

    percents = [f["percent"] for f in frames if f["type"] == "progress"]
    assert percents == sorted(percents), "进度必须单调递增，不能倒退"
    assert percents[-1] == 100


def test_websocket_rejects_bad_token(make_client, tmp_path):
    client = make_client()
    media_id = _import_media(client, tmp_path)
    job_id = client.post("/api/jobs", headers=AUTH, json={"media_id": media_id}).json()["id"]

    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/jobs/{job_id}?token=wrong") as ws:
            ws.receive_json()


def test_second_job_is_rejected_while_one_runs(make_client, tmp_path):
    client = make_client(_SlowRunner(tmp_path, steps=20, delay=0.05))
    media_id = _import_media(client, tmp_path)

    first = client.post("/api/jobs", headers=AUTH, json={"media_id": media_id})
    assert first.status_code == 201
    second = client.post("/api/jobs", headers=AUTH, json={"media_id": media_id})
    assert second.status_code == 409
    assert "已有任务在运行" in second.json()["detail"]


def test_cancel_marks_job_cancelled(make_client, tmp_path):
    client = make_client(_SlowRunner(tmp_path, steps=40, delay=0.05))
    media_id = _import_media(client, tmp_path)
    job_id = client.post("/api/jobs", headers=AUTH, json={"media_id": media_id}).json()["id"]

    time.sleep(0.05)
    assert client.delete(f"/api/jobs/{job_id}", headers=AUTH).json()["cancelled"] is True

    deadline = time.time() + 10
    while time.time() < deadline:
        snapshot = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if snapshot["status"] in {"cancelled", "error", "done"}:
            break
        time.sleep(0.02)
    assert snapshot["status"] == "cancelled"


def test_unknown_media_and_job_are_404(make_client, tmp_path):
    client = make_client()
    assert client.post("/api/jobs", headers=AUTH, json={"media_id": "nope"}).status_code == 404
    assert client.get("/api/jobs/nope", headers=AUTH).status_code == 404
    assert client.delete("/api/jobs/nope", headers=AUTH).status_code == 404


def test_invalid_time_range_is_422(make_client, tmp_path):
    client = make_client()
    media_id = _import_media(client, tmp_path)
    resp = client.post(
        "/api/jobs", headers=AUTH, json={"media_id": media_id, "start": 10, "end": 5}
    )
    assert resp.status_code == 422


def test_unknown_engine_param_is_rejected(make_client, tmp_path):
    client = make_client()
    media_id = _import_media(client, tmp_path)
    # 只过滤 dataclass 认识的字段，所以多余的键不会炸；真正非法的值才会
    resp = client.post(
        "/api/jobs",
        headers=AUTH,
        json={"media_id": media_id, "engine": "whisper", "params": {"threshold": "not-a-float"}},
    )
    assert resp.status_code in {201, 422}


# ---------------------------------------------------------------------------
# 转写结果必须写回会话（2026-11 修复：桌面端「转写完成但核对台为空」）
# ---------------------------------------------------------------------------

SESSION = {"X-Kikusub-Session": "job-test-session"}
AUTH_SESSION = {**AUTH, **SESSION}


def _cues_result(tmp_path: Path, cues: list[SubtitleCue]) -> TranscribeResult:
    out = tmp_path / "episode.srt"
    out.write_text("1\n00:00:00,000 --> 00:00:01,000\nテスト\n", encoding="utf-8")
    return TranscribeResult(
        cues=cues,
        out_path=out,
        out_filename=out.name,
        elapsed=0.5,
        char_count=sum(len(c.text) for c in cues),
        interrupted=False,
        report_text="报告",
        audit_payload="{}",
        pending_qa=0,
        status_summary="✅ 转写完成",
        final_progress="✅ 转录完成！",
        preview="",
    )


class _FixedRunner:
    def __init__(self, tmp_path: Path, cues: list[SubtitleCue]) -> None:
        self.tmp_path = tmp_path
        self.cues = cues

    def __call__(self, request, *, on_progress, cancel_event, output_dir):
        return _cues_result(self.tmp_path, self.cues)


def _wait_done(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 10
    snapshot: dict = {}
    while time.time() < deadline:
        snapshot = client.get(f"/api/jobs/{job_id}", headers=AUTH_SESSION).json()
        if snapshot["status"] in {"done", "error", "cancelled"}:
            return snapshot
        time.sleep(0.02)
    raise AssertionError(f"任务未在限定时间内结束：{snapshot}")


def _post_job(client: TestClient, media_id: str, **extra) -> dict:
    resp = client.post(
        "/api/jobs", headers=AUTH_SESSION, json={"media_id": media_id, **extra}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_transcribe_result_is_written_back_to_session(make_client, tmp_path):
    client = make_client(_FixedRunner(tmp_path, [SubtitleCue(2.0, 3.0, "書き戻し")]))
    media_id = _import_media(client, tmp_path)
    job = _post_job(client, media_id)
    snapshot = _wait_done(client, job["id"])

    assert snapshot["status"] == "done"
    cues = client.get("/api/cues", headers=AUTH_SESSION).json()
    assert cues["count"] == 1
    assert cues["cues"][0]["text"] == "書き戻し"
    assert snapshot["result"]["applied"] == "replace"


def test_append_mode_merges_and_dedupes(make_client, tmp_path):
    client = make_client(_FixedRunner(tmp_path, [SubtitleCue(5.0, 6.0, "新規")]))
    media_id = _import_media(client, tmp_path)
    client.post(
        "/api/cues",
        headers=AUTH_SESSION,
        json={"cues": [{"start": 0.0, "end": 1.0, "text": "既存"}]},
    )
    job = _post_job(client, media_id, apply="append", start=4.5, end=6.5)
    snapshot = _wait_done(client, job["id"])

    assert snapshot["status"] == "done"
    cues = client.get("/api/cues", headers=AUTH_SESSION).json()["cues"]
    assert [c["text"] for c in cues] == ["既存", "新規"]
    assert snapshot["result"]["added"] == 1


def test_replace_range_only_touches_that_span(make_client, tmp_path):
    client = make_client(_FixedRunner(tmp_path, [SubtitleCue(5.1, 6.2, "直した")]))
    media_id = _import_media(client, tmp_path)
    client.post(
        "/api/cues",
        headers=AUTH_SESSION,
        json={
            "cues": [
                {"start": 0.0, "end": 1.0, "text": "前"},
                {"start": 5.0, "end": 6.0, "text": "旧い"},
                {"start": 9.0, "end": 10.0, "text": "後"},
            ]
        },
    )
    job = _post_job(client, media_id, apply="replace_range", start=4.8, end=6.4)
    snapshot = _wait_done(client, job["id"])

    cues = client.get("/api/cues", headers=AUTH_SESSION).json()["cues"]
    assert [c["text"] for c in cues] == ["前", "直した", "後"]
    assert snapshot["result"]["removed"] == 1
    assert snapshot["result"]["added"] == 0


def test_partial_job_does_not_reset_qa_payload(make_client, tmp_path):
    """局部重转不能把整片质检队列冲掉（写盘由 core.pipeline 负责）。"""
    seen: dict = {}

    class _Recorder(_FixedRunner):
        def __call__(self, request, *, on_progress, cancel_event, output_dir):
            seen["write_audit"] = request.write_audit
            return super().__call__(
                request, on_progress=on_progress, cancel_event=cancel_event, output_dir=output_dir
            )

    client = make_client(_Recorder(tmp_path, [SubtitleCue(5.0, 6.0, "局部")]))
    media_id = _import_media(client, tmp_path)
    job = _post_job(client, media_id, apply="replace_range", start=4.8, end=6.4)
    _wait_done(client, job["id"])
    assert seen["write_audit"] is False
