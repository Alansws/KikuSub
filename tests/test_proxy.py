"""480p 监看代理：命名规则、复用判定、真实压制、任务接口。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from core import proxy

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _make_source(path: Path, seconds: int = 3) -> Path:
    """造一段足够复杂的测试片源。

    注意：1 秒的 testsrc 压出来只有 ~34 KB，低于 `MIN_PROXY_BYTES`（50 KB）的
    「半成品」阈值，会被正确判成损坏。所以这里用 testsrc2（熵更高）+ 3 秒。
    """
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440",
            "-t", str(seconds), "-pix_fmt", "yuv420p", "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return path


def _make(path: Path, size: int = 60 * 1024) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0" * size)
    return path


@pytest.fixture()
def media(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mkv"
    path.write_bytes(b"v" * 100)
    return path


# ---------------------------------------------------------------------------
# 命名与复用
# ---------------------------------------------------------------------------


def test_proxy_paths_embed_media_size(media, tmp_path):
    standard, partial = proxy.proxy_paths(media, tmp_path)
    assert standard.name == f"clip_{media.stat().st_size}_preview.mp4"
    assert partial.name == f"clip_{media.stat().st_size}_preview.part.mp4"
    assert standard.parent == tmp_path / "web_proxies"


def test_reuses_proxy_with_matching_size(media, tmp_path):
    standard, _ = proxy.proxy_paths(media, tmp_path)
    _make(standard)
    assert proxy.get_existing_proxy(media, tmp_path) == standard


def test_ignores_proxy_from_replaced_media(media, tmp_path):
    folder = tmp_path / "web_proxies"
    _make(folder / "clip_999999_preview.mp4")  # 旧片源留下的代理
    assert proxy.get_existing_proxy(media, tmp_path) is None


def test_ignores_legacy_proxy_without_size(media, tmp_path):
    _make(tmp_path / "web_proxies" / "clip_preview.mp4")
    assert proxy.get_existing_proxy(media, tmp_path) is None


def test_ignores_tiny_broken_proxy(media, tmp_path):
    standard, _ = proxy.proxy_paths(media, tmp_path)
    _make(standard, size=1024)
    assert proxy.get_existing_proxy(media, tmp_path) is None


def test_drop_broken_proxy_removes_file(media, tmp_path):
    _, partial = proxy.proxy_paths(media, tmp_path)
    _make(partial)
    proxy.drop_broken_proxy(partial)
    assert not partial.exists()


def test_reuse_short_circuits_without_ffmpeg(media, tmp_path):
    standard, _ = proxy.proxy_paths(media, tmp_path)
    _make(standard)
    result = proxy.run_proxy_job(media, output_dir=tmp_path)
    assert result.reused is True
    assert result.path == standard


def test_missing_media_raises(media, tmp_path):
    media.unlink()
    with pytest.raises(RuntimeError, match="代理压制未能成功"):
        proxy.run_proxy_job(media, output_dir=tmp_path)


# ---------------------------------------------------------------------------
# 真实压制（需要 ffmpeg）
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_FFMPEG, reason="缺少 ffmpeg")
def test_real_transcode_produces_playable_proxy(tmp_path):
    source = _make_source(tmp_path / "src.mkv")

    events: list[dict] = []
    result = proxy.run_proxy_job(
        source, on_progress=events.append, output_dir=tmp_path
    )

    assert result.reused is False
    assert result.path.exists()
    assert result.path.stat().st_size > proxy.MIN_PROXY_BYTES
    assert result.path.name.endswith("_preview.mp4")
    assert not result.path.name.endswith(".part.mp4")
    # 半成品必须已被 rename 掉
    assert not proxy.proxy_paths(source, tmp_path)[1].exists()

    # 进度事件：percent 单调不减，且最后一条是 100 或 None
    percents = [e["percent"] for e in events if e["percent"] is not None]
    assert percents == sorted(percents)
    assert events, "至少要有一次进度回调"

    # 产物真的能被 ffprobe 解析
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=height",
         "-of", "default=nw=1:nk=1", str(result.path)],
        capture_output=True, text=True, timeout=30,
    )
    assert probe.stdout.strip() == "480"


@pytest.mark.skipif(not HAS_FFMPEG, reason="缺少 ffmpeg")
def test_second_run_reuses_freshly_built_proxy(tmp_path):
    source = _make_source(tmp_path / "src2.mkv")
    first = proxy.run_proxy_job(source, output_dir=tmp_path)
    second = proxy.run_proxy_job(source, output_dir=tmp_path)
    assert first.reused is False
    assert second.reused is True
    assert second.path == first.path


# ---------------------------------------------------------------------------
# 任务接口
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_FFMPEG, reason="缺少 ffmpeg")
def test_api_proxy_job_runs_and_reports(tmp_path):
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.config import ServerConfig

    token = "proxy-token"
    auth = {"Authorization": f"Bearer {token}"}
    app = create_app(ServerConfig(token=token, output_dir=tmp_path))
    client = TestClient(app)

    source = _make_source(tmp_path / "src3.mkv")

    media_id = client.post("/api/media", headers=auth, json={"path": str(source)}).json()["id"]
    created = client.post("/api/jobs", headers=auth, json={"media_id": media_id, "kind": "proxy"})
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    import time

    deadline = time.time() + 120
    snapshot = None
    while time.time() < deadline:
        snapshot = client.get(f"/api/jobs/{job_id}", headers=auth).json()
        if snapshot["status"] in {"done", "error", "cancelled"}:
            break
        time.sleep(0.1)

    assert snapshot["status"] == "done", snapshot
    assert snapshot["result"]["proxy"]["reused"] is False
    assert Path(snapshot["result"]["proxy"]["path"]).exists()
    assert snapshot["result"]["media_id"] == media_id


def test_api_proxy_job_reuses_existing(tmp_path):
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.config import ServerConfig

    token = "proxy-token2"
    auth = {"Authorization": f"Bearer {token}"}
    app = create_app(ServerConfig(token=token, output_dir=tmp_path))
    client = TestClient(app)

    source = tmp_path / "src4.mkv"
    source.write_bytes(b"v" * 100)
    standard, _ = proxy.proxy_paths(source, tmp_path)
    _make(standard)

    media_id = client.post("/api/media", headers=auth, json={"path": str(source)}).json()["id"]
    job_id = client.post(
        "/api/jobs", headers=auth, json={"media_id": media_id, "kind": "proxy"}
    ).json()["id"]

    import time

    deadline = time.time() + 30
    while time.time() < deadline:
        snapshot = client.get(f"/api/jobs/{job_id}", headers=auth).json()
        if snapshot["status"] in {"done", "error", "cancelled"}:
            break
        time.sleep(0.05)
    assert snapshot["status"] == "done"
    assert snapshot["result"]["proxy"]["reused"] is True
