"""VAD 后端抽象的纯逻辑回归：不加载真实模型。"""

from __future__ import annotations

import numpy as np
import pytest

from core import vad


def test_resolve_backend_defaults_and_aliases(monkeypatch):
    monkeypatch.delenv(vad.ENV_BACKEND, raising=False)
    assert vad.resolve_backend() == "silero"
    assert vad.resolve_backend("silero20") == "silero"
    assert vad.resolve_backend("ten-vad") == "ten"
    monkeypatch.setenv(vad.ENV_BACKEND, "whisper_seg")
    assert vad.resolve_backend() == "whisperseg"


def test_resolve_backend_auto_follows_env(monkeypatch):
    monkeypatch.setenv(vad.ENV_BACKEND, "silero10")
    assert vad.resolve_backend("auto") == "silero10"
    assert vad.resolve_backend() == "silero10"


def test_resolve_backend_rejects_unknown(monkeypatch):
    monkeypatch.setenv(vad.ENV_BACKEND, "nope")
    with pytest.raises(vad.VadBackendError):
        vad.resolve_backend()


def test_frames_to_stamps_short_noise_is_dropped():
    probs = np.zeros(100, dtype=np.float32)
    probs[10:12] = 0.9  # 2 帧 = 32ms，低于 80ms 最短语音
    assert vad._frames_to_stamps(
        probs, frame_samples=320, total_samples=32000, threshold=0.5,
        min_speech_ms=80, min_silence_ms=200, speech_pad_ms=0,
    ) == []


def test_frames_to_stamps_hysteresis_and_padding():
    probs = np.zeros(200, dtype=np.float32)
    probs[50:100] = 0.9
    # 中间 5 帧跌到 0.3：高于 neg(0.25)，不切断；再加 5 帧 0.1 才切。
    probs[100:110] = 0.1
    probs[110:150] = 0.9
    stamps = vad._frames_to_stamps(
        probs, frame_samples=320, total_samples=64000, threshold=0.4,
        min_speech_ms=80, min_silence_ms=100, speech_pad_ms=40,
    )
    assert len(stamps) == 2
    assert stamps[0]["start"] == 50 * 320 - 2 * 320
    assert stamps[0]["end"] == 100 * 320 + 2 * 320
    assert stamps[1]["start"] == 110 * 320 - 2 * 320
    assert stamps[1]["end"] == 150 * 320 + 2 * 320


def test_frames_to_stamps_does_not_overlap_neighbours():
    probs = np.zeros(60, dtype=np.float32)
    probs[10:20] = 0.9
    probs[20:24] = 0.1
    probs[24:30] = 0.9
    stamps = vad._frames_to_stamps(
        probs, frame_samples=320, total_samples=20000, threshold=0.5,
        min_speech_ms=20, min_silence_ms=20, speech_pad_ms=200,
    )
    assert len(stamps) == 2
    assert stamps[0]["end"] <= stamps[1]["start"]


def test_flag_runs_merge_short_gaps_and_filter():
    flags = np.zeros(100, dtype=bool)
    flags[10:20] = True
    flags[21:30] = True  # 1 帧静音，合并
    flags[60:62] = True  # 太短，丢弃
    stamps = vad._flag_runs_to_stamps(
        flags, frame_samples=256, total_samples=25600,
        min_speech_ms=80, min_silence_ms=100, speech_pad_ms=0,
    )
    assert len(stamps) == 1
    assert stamps[0]["start"] == 10 * 256
    assert stamps[0]["end"] == 30 * 256


def test_detect_dispatches_silero10(monkeypatch):
    calls = []

    def fake(audio, model, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(vad, "_silero_detect", fake)
    vad.detect_speech_stamps(
        np.zeros(1600, dtype=np.float32), None, threshold=0.25,
        min_speech_ms=80, min_silence_ms=200, speech_pad_ms=250,
        backend="silero10",
    )
    assert calls and calls[0]["window_s"] == 10.0


def test_whisperseg_missing_model_is_readable(monkeypatch, tmp_path):
    monkeypatch.setenv(vad.ENV_WHISPERSEG_DIR, str(tmp_path))
    monkeypatch.setattr(vad, "_download_whisperseg", lambda *a, **k: None)
    with pytest.raises(vad.VadBackendError, match="下载不完整"):
        vad._load_whisperseg()
