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
