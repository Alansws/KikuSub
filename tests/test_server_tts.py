"""TTS 路由：音色列表、合成缓存、切片建音色、上传/重命名/删除与鉴权。

刻意把 ``tts_model_dir`` 指到 tmp_path：测试环境不需要 3GB 的 OmniVoice 权重，
克隆模型不存在时必须稳定降级到 macOS ``say``，而不是让整个接口 500。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "tts-token"


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    config = ServerConfig(
        token=TOKEN,
        output_dir=tmp_path,
        settings_path=tmp_path / "settings.json",
        tts_model_dir=tmp_path / "tts-model",
    )
    return TestClient(create_app(config))


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def write_wav(path: Path, seconds: float = 2.0, sr: int = 24000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    sf.write(str(path), (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), sr)
    return path


requires_say = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("say") is None,
    reason="需要 macOS 的 say 命令",
)
requires_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="需要 ffmpeg")


def test_voices_payload_without_clone_model(client: TestClient) -> None:
    payload = client.get("/api/tts/voices", headers=auth()).json()
    assert payload["engine"]["installed"] is False
    assert payload["engine"]["download"]["status"] == "idle"
    assert "system" in payload and "custom" in payload
    assert payload["default"].startswith("system:") or not payload["system"]
    # 克隆模型不可用时，系统语音仍然要能列出来
    if sys.platform == "darwin":
        assert payload["say"]["available"] is True


@requires_say
def test_voices_and_audio_roundtrip(client: TestClient) -> None:
    voices = client.get("/api/tts/voices", headers=auth()).json()
    assert voices["available"] is True
    assert voices["default"]
    assert all(v["kind"] == "system" for v in voices["system"])

    body = {
        "text": "こんにちは、テストです。",
        "voice_id": voices["default"],
        "speed": 1.0,
    }
    first = client.post("/api/tts/synthesize", headers=auth(), json=body)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["cached"] is False
    assert result["engine"] == "mac_say"
    assert Path(result["filename"]).suffix == ".wav"
    assert result["duration"] > 0

    second = client.post("/api/tts/synthesize", headers=auth(), json=body).json()
    assert second["cached"] is True
    assert second["filename"] == result["filename"]

    audio = client.get(f"/media/tts/{result['filename']}?token={TOKEN}")
    assert audio.status_code == 200
    assert audio.content[:4] == b"RIFF"
    assert audio.headers["content-type"].startswith("audio/wav")

    assert client.get(f"/media/tts/{result['filename']}").status_code == 401
    assert client.get(f"/media/tts/../../etc/passwd?token={TOKEN}").status_code == 404


@requires_say
def test_legacy_endpoint_still_works(client: TestClient) -> None:
    voices = client.get("/api/tts/voices", headers=auth()).json()
    name = voices["system"][0]["name"]
    response = client.post(
        "/api/tts",
        headers=auth(),
        json={"text": "こんにちは", "voice": name, "rate": 175},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["voice"] == name
    assert body["rate"] == 175
    assert body["filename"].endswith(".wav")


@requires_say
def test_tts_validation(client: TestClient) -> None:
    assert (
        client.post("/api/tts/synthesize", headers=auth(), json={"text": "   "}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/tts/synthesize", headers=auth(), json={"text": "あ" * 601}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/tts/synthesize",
            headers=auth(),
            json={"text": "あ", "voice_id": "system:NoSuchVoice"},
        ).status_code
        == 404
    )


@requires_ffmpeg
def test_extract_voice_from_media_roundtrip(client: TestClient, tmp_path: Path) -> None:
    media = write_wav(tmp_path / "media.wav", 2.0)
    imported = client.post(
        "/api/media", headers=auth(), json={"path": str(media)}
    ).json()
    media_id = imported["id"]

    response = client.post(
        "/api/tts/voices/extract-from-media",
        headers=auth(),
        json={
            "media_id": media_id,
            "start": 0.3,
            "end": 1.3,
            "name": "女主角",
            "text": "テストです",
        },
    )
    assert response.status_code == 200, response.text
    voice = response.json()
    assert voice["kind"] == "clone"
    assert voice["name"] == "女主角"
    assert voice["ref_text"] == "テストです"
    assert 0.8 <= voice["duration"] <= 1.5

    payload = client.get("/api/tts/voices", headers=auth()).json()
    assert [item["id"] for item in payload["custom"]] == [voice["id"]]

    renamed = client.patch(
        f"/api/tts/voices/{voice['id']}", headers=auth(), json={"name": "幼なじみ"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "幼なじみ"

    # 克隆模型没装：合成必须给可读的 503，而不是 500
    synth = client.post(
        "/api/tts/synthesize",
        headers=auth(),
        json={"text": "こんにちは", "voice_id": voice["id"]},
    )
    assert synth.status_code == 503
    assert "克隆模型" in synth.json()["detail"]

    deleted = client.delete(f"/api/tts/voices/{voice['id']}", headers=auth())
    assert deleted.status_code == 200
    assert client.get("/api/tts/voices", headers=auth()).json()["custom"] == []


@requires_ffmpeg
def test_upload_and_ref_text(client: TestClient, tmp_path: Path) -> None:
    ref = write_wav(tmp_path / "upload.wav", 2.0)
    response = client.post(
        "/api/tts/voices/upload",
        headers=auth(),
        json={"path": str(ref), "name": "上传声线", "ref_text": "こんにちは"},
    )
    assert response.status_code == 200, response.text
    voice = response.json()
    updated = client.put(
        f"/api/tts/voices/{voice['id']}/ref-text",
        headers=auth(),
        json={"ref_text": "さようなら"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["ref_text"] == "さようなら"

    bad = client.post(
        "/api/tts/voices/upload",
        headers=auth(),
        json={"path": str(tmp_path / "missing.wav"), "name": "x"},
    )
    assert bad.status_code == 422


def test_model_status_endpoint(client: TestClient) -> None:
    status_payload = client.get("/api/tts/model/status", headers=auth()).json()
    assert status_payload["installed"] is False
    assert status_payload["repo"] == "k2-fsa/OmniVoice"
