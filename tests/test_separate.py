"""人声分离缓存与模型路径的纯函数测试（不加载 Demucs）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import audio_cache, separate


def _media(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mkv"
    path.write_bytes(b"x" * 1024)
    return path


def test_vocals_cache_key_is_separate_namespace_and_interval_aware(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_cache, "CACHE_DIR", tmp_path / "cache")
    media = _media(tmp_path)

    base = audio_cache.vocals_cache_key(media, start=1.0, end=2.0)
    assert base != audio_cache.vocals_cache_key(media, start=1.0, end=3.0)
    assert base != audio_cache.vocals_cache_key(media, start=1.0, end=2.0, model="other")
    assert base != audio_cache.cache_key(media, loudnorm=False, start=1.0, end=2.0)
    assert audio_cache.vocals_wav_path(media, start=1.0, end=2.0).name.endswith(
        ".vocals.wav"
    )


def test_ensure_vocals_wav_reuses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(audio_cache, "prune", lambda *a, **k: None)
    media = _media(tmp_path)
    calls: list[tuple[float, float]] = []

    def fake_separator(media_path, out_path, *, start, end, cancel_event=None, progress_cb=None):
        calls.append((start, end))
        Path(out_path).write_bytes(b"RIFF" + b"x" * 100)

    first = audio_cache.ensure_vocals_wav(
        media, start=10.0, end=20.0, separator=fake_separator
    )
    second = audio_cache.ensure_vocals_wav(
        media, start=10.0, end=20.0, separator=fake_separator
    )
    assert first == second
    assert calls == [(10.0, 20.0)]

    other = audio_cache.ensure_vocals_wav(
        media, start=10.0, end=21.0, separator=fake_separator
    )
    assert other != first
    assert calls == [(10.0, 20.0), (10.0, 21.0)]


def test_ensure_vocals_wav_rejects_empty_or_reversed_range(tmp_path):
    media = _media(tmp_path)
    with pytest.raises(ValueError):
        audio_cache.ensure_vocals_wav(media, start=5.0, end=5.0, separator=lambda *a, **k: None)


def test_separate_rejects_overlong_range(tmp_path):
    media = _media(tmp_path)
    with pytest.raises(ValueError, match="最多 30 分钟"):
        separate.separate_to_wav(
            media, tmp_path / "out.wav", start=0.0, end=separate.MAX_RANGE_S + 1
        )


def test_checkpoint_lives_under_managed_models_dir(monkeypatch, tmp_path):
    assert str(separate.CHECKPOINT).startswith(str(separate.MODELS_DIR))
    # model_ready 只看文件大小，不触发网络/模型加载
    fake = tmp_path / separate.MODEL_FILENAME
    monkeypatch.setattr(separate, "CHECKPOINT", fake)
    assert separate.model_ready() is False
    fake.write_bytes(b"x" * (separate.MIN_MODEL_BYTES + 1))
    assert separate.model_ready() is True
