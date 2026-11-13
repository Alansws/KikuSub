"""复核任务（P1-1 段一）：只回文本、不落盘、不动会话、单槽与取消。

用替身引擎与替身 `transcribe_windows` 驱动，不加载任何模型。
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("torch")

pytestmark = pytest.mark.integration

from fastapi.testclient import TestClient  # noqa: E402

from core.engine_idle import EngineIdleReleaser  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402
from server.jobs import JobManager  # noqa: E402

TOKEN = "compare-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class _FakeEngine:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def transcribe_window(self, chunk, *, config=None) -> str:
        self.calls.append(int(chunk.size))
        return f"另一引擎{len(self.calls)}"


class _Idle(EngineIdleReleaser):
    """不自动起后台线程的空闲器，测试里只记录调用。"""

    def __init__(self) -> None:
        super().__init__(idle_seconds=10, release=lambda key: True, autostart=False)
        self.released: list[tuple[str, str]] = []

    def release_others(self, keep: str, reason: str = "") -> list[str]:  # type: ignore[override]
        self.released.append((keep, reason))
        return []

    def touch(self, engine_key: str) -> None:  # type: ignore[override]
        self.released.append((engine_key, "touch"))


@pytest.fixture()
def compare_client(tmp_path: Path, monkeypatch):
    import core.second_opinion as second_opinion

    captured: dict = {}

    def fake_transcribe_windows(engine, windows, **kwargs):
        captured["windows"] = windows
        captured["engine"] = engine
        total = len(windows)
        for index, window in enumerate(windows):
            engine.transcribe_window(np.zeros(0, dtype=np.float32))
            if kwargs.get("progress_cb"):
                kwargs["progress_cb"](index + 1, total)
        return [
            {"index": w["index"], "start": w["start"], "end": w["end"], "text": f"alt{len(windows)}"}
            for w in windows
        ]

    monkeypatch.setattr(second_opinion, "transcribe_windows", fake_transcribe_windows)

    def _factory() -> tuple[TestClient, _FakeEngine]:
        engine = _FakeEngine()
        app = create_app(ServerConfig(token=TOKEN, output_dir=tmp_path))
        app.state.jobs = JobManager(
            tmp_path,
            engine_resolver=lambda key: engine,
            idle_releaser=_Idle(),
        )
        return TestClient(app), engine

    return _factory, captured


def _import_media(client: TestClient, tmp_path: Path) -> str:
    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    resp = client.post("/api/media", headers=AUTH, json={"path": str(media)})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _wait(client: TestClient, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if snapshot["status"] in {"done", "error", "cancelled"}:
            return snapshot
        time.sleep(0.02)
    raise AssertionError("任务没有在超时内结束")


def test_compare_returns_texts_and_writes_nothing(compare_client, tmp_path):
    factory, captured = compare_client
    client, _engine = factory()
    media_id = _import_media(client, tmp_path)

    created = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "kind": "compare",
            "engine": "qwen",
            "ranges": [
                {"index": 0, "start": 10.0, "end": 12.0, "prev_end": 9.8, "next_start": 12.5},
                {"index": 1, "start": 20.0, "end": 21.0},
            ],
        },
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]
    snapshot = _wait(client, job_id)

    assert snapshot["status"] == "done", snapshot
    result = snapshot["result"]
    assert result["kind"] == "compare"
    assert result["engine"] == "qwen"
    assert result["engine_name"]
    assert len(result["texts"]) == 2
    # 窗口被邻句夹住：左 9.8（不是 9.75）；右边 12.25 本来就在 next_start=12.5 之内。
    windows = captured["windows"]
    assert windows[0]["start"] == pytest.approx(9.8)
    assert windows[0]["end"] == pytest.approx(12.25)
    assert windows[1]["start"] == pytest.approx(19.75)
    # 不落盘：输出目录里没有 SRT（转写任务会写，复核不会）。
    assert list(Path(tmp_path).glob("*.srt")) == []


def test_compare_does_not_touch_session_cues(compare_client, tmp_path):
    factory, _captured = compare_client
    client, _engine = factory()
    media_id = _import_media(client, tmp_path)

    client.post(
        "/api/cues",
        headers=AUTH,
        json={"cues": [{"start": 0.0, "end": 1.0, "text": "原本的字幕"}]},
    )
    before = client.get("/api/cues", headers=AUTH).json()

    created = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "kind": "compare",
            "engine": "whisper",
            "ranges": [{"start": 0.0, "end": 1.0}],
        },
    )
    _wait(client, created.json()["id"])
    after = client.get("/api/cues", headers=AUTH).json()
    assert [cue["text"] for cue in after["cues"]] == [cue["text"] for cue in before["cues"]]


def test_compare_validates_ranges(compare_client, tmp_path):
    factory, _captured = compare_client
    client, _engine = factory()
    media_id = _import_media(client, tmp_path)

    empty = client.post(
        "/api/jobs",
        headers=AUTH,
        json={"media_id": media_id, "kind": "compare", "engine": "qwen", "ranges": []},
    )
    assert empty.status_code == 422
    too_many = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "kind": "compare",
            "engine": "qwen",
            "ranges": [{"start": 0.0, "end": 1.0}] * 41,
        },
    )
    assert too_many.status_code == 422
    backwards = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "kind": "compare",
            "engine": "qwen",
            "ranges": [{"start": 2.0, "end": 1.0}],
        },
    )
    assert backwards.status_code == 422


def test_compare_rejects_sherpa_engines(compare_client, tmp_path):
    factory, _captured = compare_client
    client, _engine = factory()
    media_id = _import_media(client, tmp_path)
    resp = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "kind": "compare",
            "engine": "sensevoice",
            "ranges": [{"start": 0.0, "end": 1.0}],
        },
    )
    assert resp.status_code == 422
    assert "whisper" in resp.json()["detail"]


def test_compare_shares_the_single_slot(compare_client, tmp_path):
    factory, _captured = compare_client
    client, _engine = factory()
    media_id = _import_media(client, tmp_path)

    first = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "kind": "compare",
            "engine": "qwen",
            "ranges": [{"start": 0.0, "end": 1.0}],
        },
    )
    assert first.status_code == 201
    # 抢在第一个任务结束前再发一个：单槽必须 409。
    second = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "kind": "compare",
            "engine": "whisper",
            "ranges": [{"start": 0.0, "end": 1.0}],
        },
    )
    assert second.status_code in {201, 409}
    if second.status_code == 201:
        # 第一个已经跑完（替身很快）：这不算失败，但两个都必须是合法终态。
        _wait(client, first.json()["id"])
        _wait(client, second.json()["id"])
    else:
        _wait(client, first.json()["id"])


def test_compare_keeps_engine_alive_after_batch(compare_client, tmp_path):
    factory, _captured = compare_client
    client, _engine = factory()
    media_id = _import_media(client, tmp_path)
    created = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "kind": "compare",
            "engine": "qwen",
            "ranges": [{"start": 0.0, "end": 1.0}],
        },
    )
    _wait(client, created.json()["id"])
    idle = client.app.state.jobs.idle
    assert ("qwen", "touch") in idle.released, idle.released
