"""证据接口：单句电平 / 帧 / 音频 / 第二版对照（CLI 的只读证据来源）。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("fastapi")
sf = pytest.importorskip("soundfile")

from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "evidence-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
CUES = [
    {"start": 0.0, "end": 1.0, "text": "おはよう"},
    {"start": 2.0, "end": 3.0, "text": "今日は雨だ"},
]


def _tone(path: Path, value: float, *, rate: int = 16000, seconds: float = 4.0, channels: int = 1):
    data = np.full(int(rate * seconds), value, dtype=np.float32)
    if channels == 2:
        data = np.stack([data, data], axis=1)
    sf.write(path, data, rate, subtype="PCM_16")
    return path


@pytest.fixture()
def ctx(tmp_path: Path, monkeypatch):
    raw = _tone(tmp_path / "raw.wav", 0.01)
    vocals = _tone(tmp_path / "vocals.wav", 0.001, rate=44100, channels=2)

    app = create_app(
        ServerConfig(token=TOKEN, output_dir=tmp_path, settings_path=tmp_path / "settings.json")
    )
    client = TestClient(app)
    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    media_id = client.post("/api/media", headers=AUTH, json={"path": str(media)}).json()["id"]
    client.post("/api/session/bind", headers=AUTH, json={"media_id": media_id})
    client.post("/api/cues", headers=AUTH, json={"cues": CUES})

    import server.routes_evidence as evidence

    calls: dict = {"vocals": vocals}

    monkeypatch.setattr(evidence.audio_cache, "ensure_wav", lambda *a, **k: raw)
    monkeypatch.setattr(
        evidence.audio_cache,
        "vocals_wav_path",
        lambda media, *, start, end: calls["vocals"],
    )
    return client, raw, vocals


def test_batch_evidence_reports_raw_and_vocals_levels(ctx):
    client, _raw, _vocals = ctx
    res = client.get("/api/evidence/cues", headers=AUTH)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["vocals_cached"] is True
    assert [item["i"] for item in body["items"]] == [1, 2]
    for item in body["items"]:
        assert item["raw_dbfs"] == pytest.approx(-40.0, abs=0.3)
        assert item["vocals_dbfs"] == pytest.approx(-60.0, abs=0.4)


def test_evidence_without_vocals_cache_returns_null(ctx, monkeypatch):
    client, _raw, _vocals = ctx
    import server.routes_evidence as evidence

    missing = Path("/nonexistent/vocals.wav")
    monkeypatch.setattr(
        evidence.audio_cache, "vocals_wav_path", lambda *a, **k: missing
    )
    body = client.get("/api/evidence/cues/1", headers=AUTH).json()
    assert body["vocals_cached"] is False
    assert body["vocals_dbfs"] is None


def test_single_cue_with_second_opinion(ctx, tmp_path: Path):
    client, _raw, _vocals = ctx
    alt = tmp_path / "alt.srt"
    alt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nおはようございます\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\n今日は雨ですね\n",
        "utf-8",
    )
    imported = client.post("/api/alt-review/import", headers=AUTH, json={"path": str(alt)})
    assert imported.status_code == 200, imported.text

    body = client.get("/api/evidence/cues/1?with_b=1", headers=AUTH).json()
    assert body["text"] == "おはよう"
    assert body["b"]["text"] == "おはようございます"
    assert body["b"]["kind"] in {"diff", "same"}


def test_frame_and_audio_endpoints(ctx, monkeypatch):
    client, _raw, _vocals = ctx
    import server.routes_evidence as evidence

    monkeypatch.setattr(evidence, "_frame_bytes", lambda media, at: b"\xff\xd8\xff\xe0fakejpg")
    frame = client.get("/api/evidence/cues/1/frame", headers=AUTH)
    assert frame.status_code == 200
    assert frame.headers["content-type"] == "image/jpeg"
    assert frame.content.startswith(b"\xff\xd8")

    audio = client.get("/api/evidence/cues/1/audio?track=original", headers=AUTH)
    assert audio.status_code == 200, audio.text
    assert audio.content[:4] == b"RIFF"

    vocals = client.get("/api/evidence/cues/1/audio?track=vocals", headers=AUTH)
    assert vocals.status_code == 200, vocals.text
    assert vocals.content[:4] == b"RIFF"


def test_vocals_audio_409_when_not_cached(ctx, monkeypatch):
    client, _raw, _vocals = ctx
    import server.routes_evidence as evidence

    monkeypatch.setattr(
        evidence.audio_cache, "vocals_wav_path", lambda *a, **k: Path("/nope.wav")
    )
    res = client.get("/api/evidence/cues/1/audio?track=vocals", headers=AUTH)
    assert res.status_code == 409
    assert "分离人声" in res.json()["detail"]


def test_out_of_range_cue_is_404(ctx):
    client, _raw, _vocals = ctx
    assert client.get("/api/evidence/cues/9", headers=AUTH).status_code == 404
