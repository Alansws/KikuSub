"""存储统计与清理测试（需要 gradio 构建 app）。"""

from __future__ import annotations

import pytest

pytest.importorskip("gradio")

import app  # noqa: E402
from helpers import patch_output_dir  # noqa: E402


@pytest.fixture()
def isolated_storage(tmp_path, monkeypatch):
    audio_dir = tmp_path / "audio"
    peaks_dir = tmp_path / "peaks"
    proxy_dir = tmp_path / "proxies"
    log_dir = tmp_path / "logs"
    output_dir = tmp_path / "outputs"
    for path in (audio_dir, peaks_dir, proxy_dir, log_dir, output_dir):
        path.mkdir()
    monkeypatch.setattr(app.audio_cache, "CACHE_DIR", audio_dir)
    monkeypatch.setattr(app, "PEAKS_CACHE_DIR", peaks_dir)
    monkeypatch.setattr(app, "PROXIES_DIR", proxy_dir)
    monkeypatch.setattr(app, "LOG_DIR", log_dir)
    patch_output_dir(monkeypatch, output_dir)
    app.JOB_REGISTRY.reset()
    monkeypatch.setattr(app, "_PROXY_JOB_ACTIVE", False)
    return audio_dir, peaks_dir, proxy_dir, log_dir, output_dir


def test_storage_report_lists_sizes(isolated_storage):
    audio_dir, peaks_dir, proxy_dir, log_dir, output_dir = isolated_storage
    (audio_dir / "a.wav").write_bytes(b"0" * 2048)
    (peaks_dir / "p.npz").write_bytes(b"0" * 512)
    (proxy_dir / "p_preview.mp4").write_bytes(b"0" * 1024)
    report = app.render_storage_report()
    assert "音频缓存" in report
    assert "2 KB" in report
    assert "空闲" in report


def test_cleanup_caches_keeps_subtitles(isolated_storage):
    audio_dir, peaks_dir, _proxy_dir, _log_dir, output_dir = isolated_storage
    (audio_dir / "a.wav").write_bytes(b"0")
    (peaks_dir / "p.npz").write_bytes(b"0")
    subtitle = output_dir / "keep.srt"
    subtitle.write_text("1\n", encoding="utf-8")

    report = app.cleanup_storage("caches")
    assert "已清理" in report
    assert not (audio_dir / "a.wav").exists()
    assert not (peaks_dir / "p.npz").exists()
    assert subtitle.exists()


def test_cleanup_refused_while_job_running(isolated_storage):
    audio_dir, _peaks_dir, _proxy_dir, _log_dir, _output_dir = isolated_storage
    target = audio_dir / "a.wav"
    target.write_bytes(b"0")
    token = app.JOB_REGISTRY.start("s", "测试任务")
    try:
        report = app.cleanup_storage("caches")
        assert "暂不清理" in report
        assert target.exists()
    finally:
        app.JOB_REGISTRY.finish(token)
