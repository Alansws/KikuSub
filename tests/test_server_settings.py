"""设置 / 引擎配置 / 诊断日志接口。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from core import engines  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "settings-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    config = ServerConfig(
        token=TOKEN,
        output_dir=tmp_path,
        settings_path=tmp_path / "settings.json",
    )
    return TestClient(create_app(config))


def test_settings_lists_engines_and_paths(client: TestClient, tmp_path: Path) -> None:
    data = client.get("/api/settings", headers=AUTH).json()
    assert {e["key"] for e in data["engines"]} == {"whisper", "qwen"}
    for engine in data["engines"]:
        assert engine["languages"] == ["日语"]
        assert engine["approx_bytes"] > 0
        assert "installed" in engine and "enabled" in engine
    assert data["settings"]["enabled_engines"] == ["whisper", "qwen"]
    assert data["paths"]["settings_path"] == str(tmp_path / "settings.json")
    assert data["paths"]["log_dir"].endswith("logs")


def test_patch_settings_persists_and_reaches_config(client: TestClient, tmp_path: Path) -> None:
    resp = client.patch(
        "/api/settings", headers=AUTH, json={"enabled_engines": ["qwen"], "auto_proxy": False}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["settings"]["enabled_engines"] == ["qwen"]
    assert data["settings"]["auto_proxy"] is False
    assert (tmp_path / "settings.json").exists()

    config = client.get("/api/config", headers=AUTH).json()
    assert config["settings"]["enabled_engines"] == ["qwen"]
    flags = {e["key"]: e["enabled"] for e in config["engines"]}
    assert flags == {"whisper": False, "qwen": True}


def test_patch_settings_rejects_unknown_engine(client: TestClient) -> None:
    resp = client.patch(
        "/api/settings", headers=AUTH, json={"enabled_engines": ["whisper", "nope"]}
    )
    assert resp.status_code == 422
    assert "nope" in resp.json()["detail"]


def test_download_unknown_engine_is_404(client: TestClient) -> None:
    assert client.post("/api/engines/nope/download", headers=AUTH).status_code == 404


def test_download_job_installs_model(
    client: TestClient, tmp_path: Path, monkeypatch
) -> None:
    model_dir = tmp_path / "anime-whisper"
    monkeypatch.setenv("ANIME_WHISPER_MODEL", str(model_dir))
    engines._size_cache.clear()

    def fake_ensure(key: str, progress_cb=None, cancel_event=None) -> None:
        progress_cb and progress_cb(0.4, "正在下载模型")
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "model.safetensors").write_bytes(b"x" * 16)

    monkeypatch.setattr(engines, "ensure_model", fake_ensure)

    created = client.post("/api/engines/whisper/download", headers=AUTH)
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    deadline = time.time() + 10
    snapshot: dict = {}
    while time.time() < deadline:
        snapshot = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if snapshot["status"] in {"done", "error"}:
            break
        time.sleep(0.02)

    assert snapshot["status"] == "done", snapshot
    assert snapshot["result"]["installed"] is True
    assert (model_dir / "model.safetensors").exists()

    settings = client.get("/api/settings", headers=AUTH).json()
    whisper = next(e for e in settings["engines"] if e["key"] == "whisper")
    assert whisper["installed"] is True
    assert whisper["size_bytes"] > 0


def test_client_log_and_diagnostics(client: TestClient, tmp_path: Path, caplog) -> None:
    caplog.set_level("INFO", logger="kikusub.renderer")
    resp = client.post(
        "/api/log",
        headers=AUTH,
        json={"level": "error", "event": "uncaught", "message": "boom", "detail": "trace"},
    )
    assert resp.status_code == 200
    assert any("boom" in record.message for record in caplog.records)

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "kikusub.log").write_text(
        "2026-01-01 INFO ok\n2026-01-01 ERROR 出事了\n", encoding="utf-8"
    )

    data = client.get("/api/diagnostics", headers=AUTH).json()
    assert data["log_exists"] is True
    assert "出事了" in data["log_tail"]
    assert any("出事了" in line for line in data["recent_problems"])

    tail = client.get("/api/diagnostics/log", headers=AUTH, params={"lines": 1}).json()
    assert tail["text"].strip().endswith("出事了")

    config = client.get("/api/config", headers=AUTH).json()
    assert config["device"] in {"mps", "cuda", "cpu", "unknown", "unavailable"}


def test_clean_logs_endpoint_prunes_backups(client: TestClient, tmp_path: Path) -> None:
    import os

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True)
    active = log_dir / "kikusub.log"
    active.write_text("active", encoding="utf-8")
    old = log_dir / "kikusub.log.2"
    old.write_text("old", encoding="utf-8")
    stale = time.time() - 30 * 24 * 3600
    os.utime(old, (stale, stale))

    resp = client.post("/api/diagnostics/log/clean", headers=AUTH)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["removed"] >= 1
    assert not old.exists()
    assert active.exists()


def test_export_dir_defaults_to_output_dir_and_can_be_changed(
    client: TestClient, tmp_path: Path
) -> None:
    data = client.get("/api/settings", headers=AUTH).json()
    assert data["paths"]["export_dir"] == str(tmp_path)
    assert data["settings"]["export_dir"] == ""

    target = tmp_path / "字幕导出"
    resp = client.patch(
        "/api/settings", headers=AUTH, json={"export_dir": str(target)}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["settings"]["export_dir"] == str(target.resolve())
    assert body["paths"]["export_dir"] == str(target.resolve())
    assert target.is_dir()

    config = client.get("/api/config", headers=AUTH).json()
    assert config["export_dir"] == str(target.resolve())


def test_export_dir_rejects_relative_and_file_paths(client: TestClient, tmp_path: Path) -> None:
    relative = client.patch("/api/settings", headers=AUTH, json={"export_dir": "relative/dir"})
    assert relative.status_code == 422
    assert "绝对路径" in relative.json()["detail"]

    file_path = tmp_path / "not-a-dir.txt"
    file_path.write_text("x", encoding="utf-8")
    bad = client.patch("/api/settings", headers=AUTH, json={"export_dir": str(file_path)})
    assert bad.status_code == 422
    assert "不是文件夹" in bad.json()["detail"]


def test_export_dir_can_be_reset_to_default(client: TestClient, tmp_path: Path) -> None:
    target = tmp_path / "custom"
    assert client.patch(
        "/api/settings", headers=AUTH, json={"export_dir": str(target)}
    ).status_code == 200
    reset = client.patch("/api/settings", headers=AUTH, json={"export_dir": ""})
    assert reset.status_code == 200, reset.text
    assert reset.json()["settings"]["export_dir"] == ""
    assert reset.json()["paths"]["export_dir"] == str(tmp_path)
