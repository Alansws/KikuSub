"""分离人声 VAD 参考的绝对能量门控。

背景（2026-11-21 dpmx-014）：Demucs 的 vocals 在纯音乐段不是绝对零，WhisperSeg
会把 -76～-85 dBFS 的串音判成语音，ASR 随后产出「ちゅぅ…」这类幻觉。门控只服务
**分离人声做 VAD 参考**的路径，原声路径必须逐字节不变。
"""

from __future__ import annotations

import numpy as np

from core import vad

SR = 16000


def test_gate_drops_silence_and_keeps_speech():
    audio = np.zeros(SR * 4, dtype=np.float32)
    audio[0:SR] = 0.02  # ≈ -34 dBFS
    audio[2 * SR : 3 * SR] = 0.0003  # ≈ -70 dBFS

    stamps = [
        {"start": 0, "end": SR},
        {"start": 2 * SR, "end": 3 * SR},
    ]
    stats: dict = {}

    kept = vad.gate_stamps_by_energy(stamps, audio, floor_dbfs=-60.0, stats=stats)

    assert kept == [{"start": 0, "end": SR}]
    assert stats["input"] == 2
    assert stats["kept"] == 1
    assert stats["dropped"] == 1
    assert stats["dropped_s"] == 1.0
    assert -35.0 < stats["min_kept_dbfs"] < -33.0
    assert -71.0 < stats["max_dropped_dbfs"] < -70.0


def test_gate_keeps_all_when_floor_is_none_like():
    audio = np.full(SR * 2, 0.02, dtype=np.float32)
    stamps = [{"start": 0, "end": SR}, {"start": SR, "end": 2 * SR}]

    kept = vad.gate_stamps_by_energy(stamps, audio, floor_dbfs=-120.0)

    assert kept == stamps


def test_detect_speech_stamps_applies_energy_gate(monkeypatch):
    audio = np.zeros(SR * 4, dtype=np.float32)
    audio[0:SR] = 0.02
    audio[2 * SR : 3 * SR] = 0.0003
    stamps = [
        {"start": 0, "end": SR},
        {"start": 2 * SR, "end": 3 * SR},
    ]

    monkeypatch.setattr(vad, "_silero_detect", lambda *a, **k: list(stamps))
    stats: dict = {}

    kept = vad.detect_speech_stamps(
        audio,
        None,
        threshold=0.30,
        min_speech_ms=100,
        min_silence_ms=200,
        speech_pad_ms=250,
        backend="silero",
        energy_gate_dbfs=-60.0,
        energy_gate_stats=stats,
    )

    assert kept == [{"start": 0, "end": SR}]
    assert stats["dropped"] == 1


def test_detect_speech_stamps_without_gate_is_unchanged(monkeypatch):
    audio = np.zeros(SR * 2, dtype=np.float32)
    stamps = [{"start": 0, "end": SR}]
    monkeypatch.setattr(vad, "_silero_detect", lambda *a, **k: list(stamps))

    kept = vad.detect_speech_stamps(
        audio,
        None,
        threshold=0.30,
        min_speech_ms=100,
        min_silence_ms=200,
        speech_pad_ms=250,
        backend="silero",
    )

    assert kept == stamps
