"""音频覆盖审计：不经过主 VAD 判决，找出空白里还有声音的区间。"""

from __future__ import annotations

import numpy as np

from core.coverage import find_coverage_spans


class _FakeVad:
    def __init__(self, prob: float = 0.9) -> None:
        self.prob = prob
        self.calls = 0

    def reset_states(self) -> None:
        pass

    def __call__(self, chunk, sample_rate):
        self.calls += 1
        return self.prob


def _audio_with_burst(duration: float = 20.0, start: float = 5.0, end: float = 7.0):
    sr = 16000
    rng = np.random.default_rng(7)
    audio = rng.normal(0.0, 0.0008, int(duration * sr)).astype(np.float32)
    t = np.arange(int((end - start) * sr)) / sr
    audio[int(start * sr) : int(end * sr)] += (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    return audio


def _cue(start: float, end: float) -> dict:
    return {"start": start, "end": end}


def test_finds_burst_inside_long_cue_gap():
    audio = _audio_with_burst()
    cues = [_cue(0.0, 3.0), _cue(11.0, 20.0)]
    spans = find_coverage_spans(audio, cues, _FakeVad())
    assert len(spans) == 1
    span = spans[0]
    assert span["gap_start"] == 3.0
    assert span["gap_end"] == 11.0
    assert 4.5 <= span["start"] <= 5.5
    assert 6.5 <= span["end"] <= 7.5
    assert span["vad_mean"] == 0.9


def test_short_gap_is_ignored():
    audio = _audio_with_burst(duration=10.0, start=4.0, end=5.0)
    cues = [_cue(0.0, 2.0), _cue(8.0, 10.0)]
    # 2s-8s 的间隙只有 6s，小于默认 8s
    assert find_coverage_spans(audio, cues, _FakeVad()) == []


def test_silent_gap_is_ignored_even_if_vad_is_positive():
    audio = np.full(16000 * 20, 0.0005, dtype=np.float32)
    cues = [_cue(0.0, 3.0), _cue(11.0, 20.0)]
    assert find_coverage_spans(audio, cues, _FakeVad(0.99)) == []


def test_time_offset_returns_absolute_timeline():
    audio = _audio_with_burst()
    # 音频是 100s-120s 这一段的局部数组；字幕用绝对时间。
    cues = [_cue(100.0, 103.0), _cue(111.0, 120.0)]
    spans = find_coverage_spans(audio, cues, _FakeVad(), time_offset=100.0)
    assert len(spans) == 1
    span = spans[0]
    assert span["gap_start"] == 103.0
    assert span["gap_end"] == 111.0
    assert 104.5 <= span["start"] <= 105.5
    assert 106.5 <= span["end"] <= 107.5


def test_low_local_vad_score_is_filtered():
    audio = _audio_with_burst()
    cues = [_cue(0.0, 3.0), _cue(11.0, 20.0)]
    assert find_coverage_spans(audio, cues, _FakeVad(0.1)) == []
