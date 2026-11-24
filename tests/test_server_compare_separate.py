"""`listen --separate`：复核窗口先分离人声，再把分离轨送引擎。"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from core.engine_idle import EngineIdleReleaser  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402
from server.jobs import JobManager  # noqa: E402

TOKEN = "compare-sep-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class _FakeEngine:
    def __init__(self) -> None:
        self.chunks: list[int] = []

    def transcribe_window(self, chunk, *, config=None) -> str:
        self.chunks.append(int(chunk.size))
        return "分离后听到的话"


class _Idle(EngineIdleReleaser):
    def __init__(self) -> None:
        super().__init__(idle_seconds=10, release=lambda key: True, autostart=False)
        self.released: list[str] = []

    def release_now(self, reason: str = "") -> list[str]:  # type: ignore[override]
        self.released.append(reason)
        return []

    def release_others(self, keep: str, reason: str = "") -> list[str]:  # type: ignore[override]
        return []

    def touch(self, engine_key: str) -> None:  # type: ignore[override]
        return None


@pytest.fixture()
def ctx(tmp_path: Path, monkeypatch):
    called: dict = {}

    def fake_vocals(media, *, start, end, separator, cancel_event=None, progress_cb=None):
        called.setdefault("windows", []).append((start, end))
        if progress_cb:
            progress_cb(1.0, "分离完成")
        return tmp_path / "vocals.wav"

    monkeypatch.setattr("core.separate.available", lambda: True)
    monkeypatch.setattr("core.audio_cache.ensure_vocals_wav", fake_vocals)
    monkeypatch.setattr(
        "core.transcribe.load_audio_for_transcription",
        lambda *a, **k: np.zeros(1600, dtype=np.float32),
    )

    engine = _FakeEngine()
    idle = _Idle()
    app = create_app(
        ServerConfig(token=TOKEN, output_dir=tmp_path, settings_path=tmp_path / "settings.json")
    )
    app.state.jobs = JobManager(tmp_path, engine_resolver=lambda key: engine, idle_releaser=idle)
    client = TestClient(app)

    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    media_id = client.post("/api/media", headers=AUTH, json={"path": str(media)}).json()["id"]
    return client, media_id, engine, idle, called


def _wait(client: TestClient, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if snapshot["status"] in {"done", "error", "cancelled"}:
            return snapshot
        time.sleep(0.02)
    raise AssertionError("任务没有在超时内结束")


def test_compare_with_separate_vocals(ctx):
    client, media_id, engine, idle, called = ctx
    created = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "kind": "compare",
            "engine": "qwen",
            "separate_vocals": True,
            "ranges": [{"index": 7, "start": 10.0, "end": 12.0}],
        },
    )
    assert created.status_code == 201, created.text
    snapshot = _wait(client, created.json()["id"])

    assert snapshot["status"] == "done", snapshot
    result = snapshot["result"]
    assert result["separate"] is True
    assert result["texts"][0]["index"] == 7
    assert result["texts"][0]["text"] == "分离后听到的话"
    # 窗口已经由复核逻辑扩过 0.25s；分离用的是扩过的区间
    assert called["windows"] == [(9.75, 12.25)]
    # 分离前让出显存
    assert any("人声分离" in reason for reason in idle.released)
    # 送进引擎的是分离后的 16k 数组（替身固定 1600 采样）
    assert engine.chunks == [1600]


def test_compare_without_separate_does_not_touch_separator(ctx, monkeypatch):
    client, media_id, _engine, idle, called = ctx

    def boom(*a, **k):
        raise AssertionError("没有 --separate 不应调用分离")

    monkeypatch.setattr("core.audio_cache.ensure_vocals_wav", boom)
    monkeypatch.setattr(
        "core.second_opinion.transcribe_windows",
        lambda engine, windows, **k: [
            {"index": w["index"], "start": w["start"], "end": w["end"], "text": "原声"}
            for w in windows
        ],
    )
    created = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "kind": "compare",
            "engine": "qwen",
            "ranges": [{"index": 1, "start": 1.0, "end": 2.0}],
        },
    )
    snapshot = _wait(client, created.json()["id"])
    assert snapshot["status"] == "done", snapshot
    assert snapshot["result"]["separate"] is False
    assert snapshot["result"]["texts"][0]["text"] == "原声"
    assert called.get("windows") is None
