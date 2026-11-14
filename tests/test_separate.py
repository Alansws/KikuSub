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


def test_separate_rejects_reversed_range(tmp_path):
    media = _media(tmp_path)
    with pytest.raises(ValueError, match="结束必须大于开始"):
        separate.separate_to_wav(media, tmp_path / "out.wav", start=5.0, end=5.0)


def test_plan_chunks_splits_long_ranges_with_crossfade():
    total = 30 * 60
    plan = separate.plan_chunks(total)
    assert len(plan) == 2
    assert [p[0] for p in plan] == [0.0, separate.CHUNK_S]
    # 核心区间首尾相接、覆盖整段；read 区间两侧各多一个交叉淡化长度
    assert plan[0][1] == plan[1][0]
    assert plan[-1][1] == total
    assert plan[0][2] == 0.0
    assert plan[0][3] == separate.CHUNK_S + separate.CROSSFADE_S
    assert plan[1][2] == separate.CHUNK_S - separate.CROSSFADE_S
    assert plan[1][3] == total


def test_plan_chunks_keeps_short_range_as_one_chunk():
    plan = separate.plan_chunks(4 * 60 + 5)
    assert plan == [(0.0, 245.0, 0.0, 245.0)]


def test_plan_chunks_clamps_last_chunk_to_total():
    total = 20 * 60 + 3
    plan = separate.plan_chunks(total)
    assert len(plan) == 2
    assert plan[-1][1] == total
    assert plan[-1][3] == total
    assert all(0.0 <= p[2] <= p[0] < p[1] <= p[3] <= total for p in plan)


def test_checkpoint_lives_under_managed_models_dir(monkeypatch, tmp_path):
    assert str(separate.CHECKPOINT).startswith(str(separate.MODELS_DIR))
    # model_ready 只看文件大小，不触发网络/模型加载
    fake = tmp_path / separate.MODEL_FILENAME
    monkeypatch.setattr(separate, "CHECKPOINT", fake)
    assert separate.model_ready() is False
    fake.write_bytes(b"x" * (separate.MIN_MODEL_BYTES + 1))
    assert separate.model_ready() is True
