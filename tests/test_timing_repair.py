"""句首静音拉回的纯函数测试（P0）。

不加载模型；只验证“怎么找发声起点”和“什么时候允许/拒绝拉回”。
真实音频的 CER/漏块验收在 `tools/eval/`，不在 pytest 里。
"""

from __future__ import annotations

import numpy as np
import pytest

from core import timing_repair


def _tone(seconds: float, sample_rate: int = 16000, freq: float = 440.0, amp: float = 0.3):
    t = np.arange(int(seconds * sample_rate), dtype=np.float32) / sample_rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_leading_silence_finds_soft_onset():
    sample_rate = 16000
    audio = np.concatenate(
        [np.zeros(int(0.9 * sample_rate), dtype=np.float32), _tone(0.5, sample_rate)]
    )
    lead = timing_repair.leading_silence_seconds(
        audio, sample_rate, noise_floor=1e-4, consecutive=2
    )
    assert lead == pytest.approx(0.9, abs=0.03)


def test_leading_silence_ignores_single_frame_click():
    sample_rate = 16000
    audio = np.zeros(int(2.0 * sample_rate), dtype=np.float32)
    click = int(0.2 * sample_rate)
    audio[click : click + 160] = 0.5
    audio[int(1.0 * sample_rate) : int(1.5 * sample_rate)] = _tone(0.5, sample_rate)
    lead = timing_repair.leading_silence_seconds(
        audio, sample_rate, noise_floor=1e-4, consecutive=2
    )
    assert lead == pytest.approx(1.0, abs=0.03)


def test_estimate_noise_floor_is_quiet_quantile():
    sample_rate = 16000
    audio = np.concatenate(
        [np.zeros(int(1.0 * sample_rate), dtype=np.float32), _tone(1.0, sample_rate)]
    )
    floor = timing_repair.estimate_noise_floor(audio, sample_rate)
    assert floor == pytest.approx(0.0, abs=1e-5)


def test_plan_pulls_long_lead_but_keeps_end():
    result = timing_repair.plan_start_pull(
        start=10.0,
        end=13.0,
        lead_s=0.9,
        text="あいうえおかきく",
        prev_end=0.0,
    )
    assert result.pulled is True
    assert result.start == pytest.approx(10.85, abs=0.01)
    assert result.start < 13.0
    assert result.pull_s == pytest.approx(0.85, abs=0.01)


def test_plan_skips_head_removed():
    result = timing_repair.plan_start_pull(
        start=10.0, end=13.0, lead_s=0.9, text="あいうえおかきく", head_removed=True
    )
    assert result.pulled is False
    assert result.reason == "head-removed"


def test_plan_skips_ellipsis_prefix_for_short_sigh():
    result = timing_repair.plan_start_pull(
        start=10.0, end=13.0, lead_s=0.9, text="…むぅ"
    )
    assert result.pulled is False
    assert result.reason == "pause-prefix"


def test_plan_pulls_ellipsis_with_enough_text():
    result = timing_repair.plan_start_pull(
        start=10.0, end=13.0, lead_s=0.85, text="…お熱あかろっか"
    )
    assert result.pulled is True
    assert result.start == pytest.approx(10.8, abs=0.01)


def test_plan_skips_nonverbal():
    result = timing_repair.plan_start_pull(
        start=10.0, end=13.0, lead_s=0.9, text="ふふっ", nonverbal=True
    )
    assert result.pulled is False
    assert result.reason == "nonverbal"


def test_plan_skips_short_lead():
    result = timing_repair.plan_start_pull(
        start=10.0, end=13.0, lead_s=0.4, text="あいうえおかきく"
    )
    assert result.pulled is False
    assert result.reason == "short-lead"


def test_plan_skips_short_duration():
    result = timing_repair.plan_start_pull(
        start=10.0, end=11.0, lead_s=0.9, text="あいうえお"
    )
    assert result.pulled is False
    assert result.reason == "short-duration"


def test_plan_skips_normal_cps_and_duration():
    result = timing_repair.plan_start_pull(
        start=10.0, end=13.0, lead_s=0.9, text="あ" * 20
    )
    assert result.pulled is False
    assert result.reason == "not-slow"


def test_plan_protects_single_kana():
    result = timing_repair.plan_start_pull(
        start=10.0, end=12.0, lead_s=0.9, text="え"
    )
    assert result.pulled is True
    # 短叹词最多拉 40%（0.8s），且保底 0.8s
    assert result.start == pytest.approx(10.8, abs=0.01)
    assert 12.0 - result.start == pytest.approx(1.2, abs=0.01)


def test_plan_does_not_overrun_previous_cue():
    result = timing_repair.plan_start_pull(
        start=10.0, end=13.0, lead_s=1.2, text="あいうえお", prev_end=11.8
    )
    assert result.pulled is True
    assert result.start >= 11.85
    assert 13.0 - result.start >= timing_repair.MIN_NEW_DURATION_S


def test_plan_refuses_when_overlap_leaves_no_room():
    result = timing_repair.plan_start_pull(
        start=10.0, end=13.0, lead_s=1.2, text="あいうえお", prev_end=12.8
    )
    assert result.pulled is False
    assert result.reason == "too-small"


def test_stats_round_trip():
    stats = timing_repair.empty_stats()
    pulled = timing_repair.plan_start_pull(
        start=10.0, end=13.0, lead_s=0.9, text="あいうえおかきく"
    )
    timing_repair.record(stats, pulled)
    skipped = timing_repair.plan_start_pull(
        start=20.0, end=23.0, lead_s=0.9, text="…むぅ"
    )
    timing_repair.record(stats, skipped)
    assert stats["considered"] == 2
    assert stats["pulled"] == 1
    assert stats["pause_prefix"] == 1
    assert "拉回 1/2 段" in timing_repair.describe_stats(stats)
