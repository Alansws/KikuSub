"""服务层回归：鉴权、媒体导入、Range 流、波形、字幕 CRUD、预设。

用 FastAPI 的 TestClient 在进程内跑，不需要真实监听端口。
握手协议（stdout 首行）单独在 `test_handshake_prints_port_and_token` 里用子进程验证。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
MEDIA = REPO_ROOT.parent / "测试用_言叶之庭.mkv"
TOKEN = "test-token-abc"


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    config = ServerConfig(
        token=TOKEN,
        legacy=False,
        output_dir=tmp_path,
        settings_path=tmp_path / "settings.json",
    )
    return TestClient(create_app(config))


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


# ---------------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------------


def test_health_is_open(client: TestClient) -> None:
    assert client.get("/api/health").json()["ok"] is True


@pytest.mark.parametrize("path", ["/api/config", "/api/media", "/api/cues", "/api/presets", "/api/params"])
def test_api_requires_token(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401


def test_wrong_token_rejected(client: TestClient) -> None:
    resp = client.get("/api/config", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_token_accepted_as_query_param(client: TestClient) -> None:
    """/media 只能走查询参数——`<video src>` 发不了自定义头。"""
    resp = client.get(f"/media/whatever?token={TOKEN}")
    # 鉴权通过但媒体不存在 → 404（不是 401）
    assert resp.status_code == 404


def test_config_reports_device_and_engines(client: TestClient) -> None:
    data = client.get("/api/config", headers=auth()).json()
    # 设备探测在后台预热线程里做；刚启动时可能是 unknown，前端会在几秒后刷新。
    assert data["device"] in {"mps", "cuda", "cpu", "unknown", "unavailable"}
    assert {e["key"] for e in data["engines"]} == {"whisper", "qwen"}
    assert all("enabled" in e and "installed" in e for e in data["engines"])


# ---------------------------------------------------------------------------
# 媒体
# ---------------------------------------------------------------------------


def test_import_rejects_missing_file(client: TestClient) -> None:
    resp = client.post("/api/media", headers=auth(), json={"path": "/nope/missing.mkv"})
    assert resp.status_code == 400
    assert "不存在" in resp.json()["detail"]


def test_import_rejects_unsupported_suffix(client: TestClient, tmp_path: Path) -> None:
    bad = tmp_path / "notes.txt"
    bad.write_text("hello", encoding="utf-8")
    resp = client.post("/api/media", headers=auth(), json={"path": str(bad)})
    assert resp.status_code == 400
    assert "不支持" in resp.json()["detail"]


@pytest.mark.skipif(not MEDIA.exists(), reason="缺少本地测试素材")
def test_import_is_idempotent(client: TestClient) -> None:
    first = client.post("/api/media", headers=auth(), json={"path": str(MEDIA)}).json()
    second = client.post("/api/media", headers=auth(), json={"path": str(MEDIA)}).json()
    assert first["id"] == second["id"]
    assert first["duration"] > 0
    assert first["name"] == MEDIA.name


@pytest.mark.skipif(not MEDIA.exists(), reason="缺少本地测试素材")
def test_range_request_returns_partial_content(client: TestClient) -> None:
    media_id = client.post("/api/media", headers=auth(), json={"path": str(MEDIA)}).json()["id"]
    resp = client.get(f"/media/{media_id}?token={TOKEN}", headers={"Range": "bytes=0-1023"})
    assert resp.status_code == 206
    assert len(resp.content) == 1024
    assert resp.headers["content-range"].startswith("bytes 0-1023/")


@pytest.mark.skipif(not MEDIA.exists(), reason="缺少本地测试素材")
def test_peaks_are_normalised(client: TestClient) -> None:
    media_id = client.post("/api/media", headers=auth(), json={"path": str(MEDIA)}).json()["id"]
    data = client.get(f"/api/media/{media_id}/peaks?bins=512", headers=auth()).json()
    assert data["bins"] == 512
    assert data["duration"] > 0
    peaks = data["peaks"]
    assert len(peaks) == 512
    assert max(peaks) <= 1.0 and min(peaks) >= 0.0
    assert max(peaks) > 0.5, "归一化后峰值应接近 1"


# ---------------------------------------------------------------------------
# 字幕
# ---------------------------------------------------------------------------


def test_cue_crud_and_undo_redo(client: TestClient) -> None:
    client.get("/api/health")  # 建立 cookie 会话
    body = {"cues": [
        {"start": 0.0, "end": 1.0, "text": "一"},
        {"start": 1.0, "end": 2.0, "text": "二"},
    ]}
    data = client.post("/api/cues", headers=auth(), json=body).json()
    assert data["count"] == 2

    data = client.patch("/api/cues/0", headers=auth(), json={"text": "改过"}).json()
    assert data["cues"][0]["text"] == "改过"
    assert data["can_undo"] is True

    data = client.post("/api/cues/undo", headers=auth()).json()
    assert data["cues"][0]["text"] == "一"
    assert data["can_redo"] is True

    data = client.post("/api/cues/redo", headers=auth()).json()
    assert data["cues"][0]["text"] == "改过"

    data = client.delete("/api/cues/1", headers=auth()).json()
    assert data["count"] == 1


def test_invalid_time_range_is_422(client: TestClient) -> None:
    client.post("/api/cues", headers=auth(), json={"cues": [{"start": 0.0, "end": 1.0, "text": "x"}]})
    resp = client.patch("/api/cues/0", headers=auth(), json={"start": 5.0, "end": 1.0})
    assert resp.status_code == 422


def test_undo_without_history_is_409(client: TestClient) -> None:
    assert client.post("/api/cues/undo", headers=auth()).status_code == 409


def test_export_writes_file(client: TestClient, tmp_path: Path) -> None:
    client.post("/api/cues", headers=auth(), json={"cues": [{"start": 0.0, "end": 1.0, "text": "テスト"}]})
    data = client.post("/api/cues/export", headers=auth(), json={"format": "SRT"}).json()
    out = Path(data["path"])
    assert out.exists()
    assert "テスト" in out.read_text(encoding="utf-8")
    assert data["format"] == "SRT"


# ---------------------------------------------------------------------------
# 预设
# ---------------------------------------------------------------------------


def test_preset_roundtrip(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # PresetStore 在 create_app 时用默认路径构造，这里换到临时文件避免污染仓库
    store_path = tmp_path / "presets.json"
    client.app.state.presets.path = store_path
    client.app.state.presets.reload()

    assert client.post("/api/presets", headers=auth(),
                       json={"name": "冒烟", "engine": "whisper", "values": {"whisper.beam_size": 5}}
                       ).status_code == 201
    items = client.get("/api/presets", headers=auth()).json()["items"]
    assert items == [{"name": "冒烟", "engine": "whisper"}]

    got = client.get("/api/presets/冒烟", headers=auth()).json()
    assert got["values"]["whisper.beam_size"] == 5

    assert client.put("/api/presets/冒烟", headers=auth(), json={"new_name": "改名"}).json()["renamed"] is True
    assert client.delete("/api/presets/改名", headers=auth()).json()["deleted"] == "改名"
    assert client.get("/api/presets", headers=auth()).json()["items"] == []


def test_preset_invalid_name_is_422(client: TestClient, tmp_path: Path) -> None:
    client.app.state.presets.path = tmp_path / "presets.json"
    client.app.state.presets.reload()
    resp = client.post("/api/presets", headers=auth(), json={"name": "  ", "values": {}})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 握手协议
# ---------------------------------------------------------------------------


def test_handshake_prints_port_and_token() -> None:
    """sidecar 的第一行 stdout 必须是 ready 握手，Electron 主进程靠它拿端口与 token。"""
    proc = subprocess.Popen(
        [sys.executable, "-m", "server", "--port", "0", "--log-level", "critical"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        line = proc.stdout.readline()
        payload = json.loads(line)
        assert payload["event"] == "ready"
        assert isinstance(payload["port"], int) and payload["port"] > 0
        assert len(payload["token"]) >= 20
        assert payload["legacy"] is False
    finally:
        proc.terminate()
        proc.wait(timeout=15)


# ---------------------------------------------------------------------------
# 波形窗口（核对台缩放/平移的数据源）
# ---------------------------------------------------------------------------


def _make_two_second_wav(tmp_path: Path) -> Path:
    """前半秒有音、后半段静音的 16k 单声道 wav。"""
    import numpy as np
    import soundfile as sf

    sr = 16000
    t = np.arange(sr * 2) / sr
    tone = np.where(t < 1.0, np.sin(2 * np.pi * 440 * t) * 0.8, 0.0).astype("float32")
    path = tmp_path / "tone.wav"
    sf.write(path, tone, sr)
    return path


def test_params_endpoint_exposes_groups_and_defaults(client: TestClient) -> None:
    data = client.get("/api/params", headers=auth()).json()
    engines = {e["key"]: e for e in data["engines"]}
    assert set(engines) == {"whisper", "qwen"}
    keys = {p["key"] for p in engines["whisper"]["groups"][0]["params"]}
    assert "whisper.vad_threshold" in {
        p["key"] for g in engines["whisper"]["groups"] for p in g["params"]
    }
    assert engines["whisper"]["defaults"]["whisper.vad_threshold"] == 0.30
    assert keys  # 第一组不能为空


def test_peaks_window_returns_requested_window(client: TestClient, tmp_path: Path) -> None:
    wav = _make_two_second_wav(tmp_path)
    media_id = client.post("/api/media", headers=auth(), json={"path": str(wav)}).json()["id"]

    loud = client.get(
        f"/api/media/{media_id}/peaks",
        headers=auth(),
        params={"from": 0.0, "to": 1.0, "bins": 80},
    ).json()
    quiet = client.get(
        f"/api/media/{media_id}/peaks",
        headers=auth(),
        params={"from": 1.0, "to": 2.0, "bins": 80},
    ).json()

    assert loud["bins"] == 80 == len(loud["peaks"])
    assert max(loud["peaks"]) == pytest.approx(1.0, abs=0.02)
    assert max(quiet["peaks"]) == pytest.approx(0.0, abs=0.001)
    assert loud["start"] == 0.0 and loud["end"] == 1.0


def test_import_srt_replaces_review_cues(client: TestClient, tmp_path: Path) -> None:
    srt = tmp_path / "episode.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:02,500\nおはよう\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\nまたね\n",
        encoding="utf-8",
    )
    resp = client.post("/api/cues/import", headers=auth(), json={"path": str(srt)})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["count"] == 2
    assert data["cues"][0]["text"] == "おはよう"
    assert data["cues"][1]["start"] == 3.0

    # 整表替换压入撤回栈
    assert data["can_undo"] is True
    assert client.post("/api/cues/undo", headers=auth()).json()["count"] == 0


def test_import_rejects_unknown_suffix(client: TestClient, tmp_path: Path) -> None:
    bad = tmp_path / "episode.ass"
    bad.write_text("whatever", encoding="utf-8")
    resp = client.post("/api/cues/import", headers=auth(), json={"path": str(bad)})
    assert resp.status_code == 422
