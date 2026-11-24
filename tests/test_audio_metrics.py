"""片段电平：未归一化的真实 dBFS，供 `kikusub cues/cue` 做证据。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from core import audio_metrics

sf = pytest.importorskip("soundfile")


def test_rms_dbfs_full_scale_and_silence():
    assert audio_metrics.rms_dbfs(np.ones(1600, dtype=np.float32)) == pytest.approx(0.0, abs=0.1)
    assert audio_metrics.rms_dbfs(np.zeros(1600, dtype=np.float32)) == -180.0
    assert audio_metrics.rms_dbfs(np.zeros(0, dtype=np.float32)) is None


def test_segment_dbfs_reads_only_the_window(tmp_path: Path):
    rate = 16000
    audio = np.full(rate * 4, 0.01, dtype=np.float32)  # -40 dBFS
    audio[2 * rate : 3 * rate] = 0.0001  # -80 dBFS
    path = tmp_path / "tone.wav"
    sf.write(path, audio, rate, subtype="PCM_16")

    assert audio_metrics.segment_dbfs(path, 0.0, 1.0) == pytest.approx(-40.0, abs=0.2)
    assert audio_metrics.segment_dbfs(path, 2.0, 3.0) == pytest.approx(-80.8, abs=0.3)
    assert audio_metrics.segment_dbfs(path, 3.0, 3.0) is None
    assert audio_metrics.wav_duration(path) == pytest.approx(4.0, abs=0.01)


def test_segment_dbfs_handles_stereo_vocals(tmp_path: Path):
    rate = 44100
    left = np.full(rate, 0.01, dtype=np.float32)
    right = np.full(rate, 0.01, dtype=np.float32)
    path = tmp_path / "vocals.wav"
    sf.write(path, np.stack([left, right], axis=1), rate, subtype="PCM_16")

    assert audio_metrics.segment_dbfs(path, 0.1, 0.9) == pytest.approx(-40.0, abs=0.2)
    assert audio_metrics.segment_dbfs(tmp_path / "missing.wav", 0.0, 1.0) is None
