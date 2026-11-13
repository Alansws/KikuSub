"""第二引擎复核的纯函数（P1-1 段一）：窗口夹取与逐窗送模。

不加载模型：`transcribe_windows` 的音频由调用方给（测试用小数组），
引擎是替身，只要实现 `transcribe_window(chunk, config=...)`。
"""

from __future__ import annotations

import numpy as np
import pytest

from core.procutil import CommandCancelled
from core.second_opinion import MAX_WINDOWS, clamp_window, transcribe_windows


class _FakeEngine:
    def __init__(self) -> None:
        self.windows: list[int] = []

    def transcribe_window(self, chunk, *, config=None) -> str:
        self.windows.append(int(chunk.size))
        return f"alt{len(self.windows)}"


# --------------------------------------------------------------------------- 窗口


def test_window_pads_both_sides():
    assert clamp_window(10.0, 12.0) == (9.75, 12.25)


def test_window_is_clamped_by_previous_end():
    # 上一句在 9.8s 结束：左边最多到 9.8，不能再往前吃它的尾音。
    lo, hi = clamp_window(10.0, 12.0, prev_end=9.8)
    assert lo == pytest.approx(9.8)
    assert hi == pytest.approx(12.25)


def test_window_is_clamped_by_next_start():
    lo, hi = clamp_window(10.0, 12.0, next_start=12.1)
    assert lo == pytest.approx(9.75)
    assert hi == pytest.approx(12.1)


def test_window_never_goes_negative():
    assert clamp_window(0.1, 0.5) == (0.0, 0.75)


def test_window_falls_back_to_cue_when_neighbours_touch():
    # 字幕首尾相接（前一句结束=后一句开始）：扩窗没有意义，退回原条。
    assert clamp_window(10.0, 10.0, prev_end=10.0, next_start=10.0) == (10.0, 10.0)


def test_window_ignores_overlapping_neighbours_beyond_the_cue():
    # 脏数据：上一句的终点落在本条里面。不能把窗口起点推到本条之后。
    lo, _hi = clamp_window(10.0, 12.0, prev_end=11.0)
    assert lo == pytest.approx(10.0)


# --------------------------------------------------------------------------- 送模


def _audio(seconds: float = 20.0, sr: int = 16000) -> np.ndarray:
    return np.zeros(int(seconds * sr), dtype=np.float32)


def test_transcribe_windows_maps_one_to_one():
    engine = _FakeEngine()
    windows = [
        {"index": 3, "start": 1.0, "end": 2.0},
        {"index": 7, "start": 5.0, "end": 5.5},
    ]
    results = transcribe_windows(engine, windows, audio=_audio())
    assert [item["index"] for item in results] == [3, 7]
    assert [item["text"] for item in results] == ["alt1", "alt2"]
    assert [item["start"] for item in results] == [1.0, 5.0]
    # 每条送进去的样本数 = 窗口时长 * 16k
    assert engine.windows == [16000, 8000]


def test_transcribe_windows_reports_progress():
    seen: list[tuple[int, int]] = []
    transcribe_windows(
        _FakeEngine(),
        [{"start": 0.0, "end": 1.0}, {"start": 2.0, "end": 3.0}],
        audio=_audio(),
        progress_cb=lambda done, total: seen.append((done, total)),
    )
    assert seen == [(1, 2), (2, 2)]


def test_transcribe_windows_respects_cancel_between_windows():
    class _Cancel:
        def __init__(self) -> None:
            self.calls = 0

        def is_set(self) -> bool:
            self.calls += 1
            return self.calls > 1  # 第一条跑完后再取消

    engine = _FakeEngine()
    with pytest.raises(CommandCancelled):
        transcribe_windows(
            engine,
            [{"start": 0.0, "end": 1.0}, {"start": 2.0, "end": 3.0}],
            audio=_audio(),
            cancel_event=_Cancel(),
        )
    assert len(engine.windows) == 1


def test_transcribe_windows_rejects_too_many():
    windows = [{"start": 0.0, "end": 1.0}] * (MAX_WINDOWS + 1)
    with pytest.raises(ValueError):
        transcribe_windows(_FakeEngine(), windows, audio=_audio())


def test_transcribe_windows_requires_a_source():
    with pytest.raises(ValueError):
        transcribe_windows(_FakeEngine(), [{"start": 0.0, "end": 1.0}])


# --------------------------------------------------------------------------- 引擎 seam


def test_both_japanese_engines_expose_the_window_seam():
    """P1-1 依赖两个引擎都有 `transcribe_window`；缺一个功能就只剩半边。"""
    from core.pipeline import resolve_engine

    for key in ("whisper", "qwen"):
        engine = resolve_engine(key)
        assert callable(getattr(engine, "transcribe_window", None)), key
        assert any(
            callable(getattr(engine, name, None)) for name in ("unload", "release")
        ), key


def test_transcribe_windows_wraps_decode_failure(monkeypatch, tmp_path):
    """没有音轨的素材：错误信息要能读懂，不能把 ffmpeg 的整段输出甩给用户。"""
    import core.transcribe as transcribe

    def boom(*_args, **_kwargs):
        raise RuntimeError("ffmpeg 提取音频失败:\n[out#0/wav] Output file does not contain any stream")

    monkeypatch.setattr(transcribe, "load_audio_for_transcription", boom)
    with pytest.raises(RuntimeError) as err:
        transcribe_windows(_FakeEngine(), [{"start": 0.0, "end": 1.0}], media_path=tmp_path / "a.mp4")
    assert "没有音轨" in str(err.value)
    assert "ffmpeg" not in str(err.value)
