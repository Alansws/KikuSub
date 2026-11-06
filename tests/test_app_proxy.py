"""监看代理复用逻辑测试：同名片源被替换后绝不能复用旧体积的代理。"""

from __future__ import annotations

import pytest

pytest.importorskip("gradio")

import app  # noqa: E402


def _make(path, size=60 * 1024):
    path.write_bytes(b"0" * size)
    return path


@pytest.fixture()
def proxy_dir(tmp_path, monkeypatch):
    proxies = tmp_path / "web_proxies"
    proxies.mkdir()
    monkeypatch.setattr(app, "PROXIES_DIR", proxies)
    media = tmp_path / "clip.mkv"
    media.write_bytes(b"v" * 100)
    return proxies, media


def test_reuses_proxy_with_matching_size(proxy_dir):
    proxies, media = proxy_dir
    expected = _make(proxies / f"clip_{media.stat().st_size}_preview.mp4")
    assert app.get_existing_proxy(media) == expected


def test_ignores_proxy_from_replaced_media(proxy_dir):
    proxies, media = proxy_dir
    _make(proxies / "clip_999999_preview.mp4")  # 旧片源留下的代理
    assert app.get_existing_proxy(media) is None


def test_ignores_legacy_proxy_without_size(proxy_dir):
    proxies, media = proxy_dir
    _make(proxies / "clip_preview.mp4")
    assert app.get_existing_proxy(media) is None


def test_ignores_tiny_broken_proxy(proxy_dir):
    proxies, media = proxy_dir
    _make(proxies / f"clip_{media.stat().st_size}_preview.mp4", size=1024)
    assert app.get_existing_proxy(media) is None
