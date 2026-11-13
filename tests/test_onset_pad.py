"""句首补回（`extend_segment_onsets`）的纯函数测试：不加载模型，CI 直接跑。

看守三件事：左扩的边界（不越过上一块、不越过 0）、三种闸门的判定口径、
以及「0 就是旧行为」这条兼容承诺。
"""

from __future__ import annotations

import numpy as np
import pytest

from core import params
from core.transcribe import (
    ONSET_GATE_NONE,
    ONSET_GATE_SNR,
    ONSET_GATE_SNR_CAP,
    ONSET_PAD_MAX_MS,
    _gate_threshold,
    build_whisper_config,
    extend_segment_onsets,
)

SR = 16000


def _audio(seconds: float, amp: float = 0.0, sr: int = SR) -> np.ndarray:
    return np.full(int(seconds * sr), amp, dtype=np.float32)


def _fill(audio: np.ndarray, start_s: float, end_s: float, amp: float) -> np.ndarray:
    audio[int(start_s * SR) : int(end_s * SR)] = amp
    return audio


def _seconds(segments: list[tuple[int, int]]) -> list[tuple[float, float]]:
    return [(round(s / SR, 3), round(e / SR, 3)) for s, e in segments]


# --------------------------------------------------------------------------- 边界


def test_zero_pad_is_a_noop():
    segments = [(SR, 2 * SR), (3 * SR, 4 * SR)]
    audio = _audio(10, 0.1)
    stats: dict = {}
    assert extend_segment_onsets(segments, audio, pad_ms=0, stats=stats) == segments
    assert stats["onset_pad_ms"] == 0
    assert stats["onset_extended"] == 0


def test_pad_moves_start_left_by_exactly_pad():
    audio = _audio(10, 0.1)
    out = extend_segment_onsets([(5 * SR, 6 * SR)], audio, pad_ms=400)
    assert _seconds(out) == [(4.6, 6.0)]


def test_pad_clamps_at_zero():
    audio = _audio(10, 0.1)
    out = extend_segment_onsets([(int(0.2 * SR), SR)], audio, pad_ms=600)
    assert _seconds(out) == [(0.0, 1.0)]


def test_pad_never_eats_previous_segment():
    # 上一块在 1.0s 结束，80ms 保护间隔 → 第二块最早只能到 1.08s。
    audio = _audio(10, 0.1)
    out = extend_segment_onsets([(SR, int(1.0 * SR)), (int(1.2 * SR), 2 * SR)], audio, pad_ms=400)
    # 第一块起点受 0 约束（1.0 → 0.6）；第二块被上一块的末端 +80ms 卡住（1.2 → 1.08）。
    assert _seconds(out) == [(0.6, 1.0), (1.08, 2.0)]


def test_pad_over_limit_is_clamped():
    audio = _audio(10, 0.1)
    stats: dict = {}
    out = extend_segment_onsets([(5 * SR, 6 * SR)], audio, pad_ms=5000, stats=stats)
    assert stats["onset_pad_ms"] == ONSET_PAD_MAX_MS
    assert _seconds(out) == [(5 - ONSET_PAD_MAX_MS / 1000, 6.0)]


def test_negative_pad_is_disabled():
    audio = _audio(10, 0.1)
    segments = [(5 * SR, 6 * SR)]
    assert extend_segment_onsets(segments, audio, pad_ms=-100) == segments


# --------------------------------------------------------------------------- 闸门


def test_snr_gate_blocks_silent_lookback():
    audio = _audio(10, 0.001)  # 底噪：安静但非零，10% 分位≈0.001
    _fill(audio, 5.0, 6.0, 0.5)  # 只在块内是语音
    stats: dict = {}
    out = extend_segment_onsets(
        [(5 * SR, 6 * SR)], audio, pad_ms=400, gate=ONSET_GATE_SNR, stats=stats
    )
    assert _seconds(out) == [(5.0, 6.0)]
    assert stats["onset_gated"] == 1
    assert stats["onset_extended"] == 0


def test_snr_gate_allows_quiet_onset_above_floor():
    # 回看窗里有 -40dB 的轻声起音；底噪 -60dB + 6dB → 门槛 -54dB，应当放行。
    audio = _audio(10, 0.001)
    _fill(audio, 4.6, 5.0, 0.01)
    _fill(audio, 5.0, 6.0, 0.5)
    out = extend_segment_onsets([(5 * SR, 6 * SR)], audio, pad_ms=400, gate=ONSET_GATE_SNR)
    assert _seconds(out) == [(4.6, 6.0)]


def test_snr_cap_threshold_is_a_clamp_not_a_max():
    # `peak×0.08` 会随段内大声喘息抬高；上限（底噪+18dB）必须把它压回去，
    # 否则「峰值带偏」会挡住轻声起音（路线文档 P0-1 专门写了这条）。
    noise = 0.001
    low = noise * 10 ** (6 / 20)
    high = noise * 10 ** (18 / 20)
    assert _gate_threshold(ONSET_GATE_SNR_CAP, noise=noise, peak=0.9) == pytest.approx(high)
    assert high < 0.9 * 0.08  # 不设上限时会被 0.072 挡住
    assert _gate_threshold(ONSET_GATE_SNR_CAP, noise=noise, peak=0.01) == pytest.approx(low)
    assert _gate_threshold(ONSET_GATE_NONE, noise=noise, peak=0.9) == 0.0


def test_gate_without_enough_audio_falls_back_to_none():
    # 音频短于一帧时没有 RMS 序列：闸门无法判定，不能因此全部拦掉。
    audio = _audio(0.01, 0.1)
    out = extend_segment_onsets([(8, 160)], audio, pad_ms=4, gate=ONSET_GATE_SNR)
    assert _seconds(out) == [(0.0, 0.01)]


# --------------------------------------------------------------------------- 统计与配置


def test_stats_counts_and_mean_shift():
    audio = _audio(10, 0.1)
    stats: dict = {}
    out = extend_segment_onsets(
        [(SR, 2 * SR), (4 * SR, 5 * SR)], audio, pad_ms=400, stats=stats
    )
    assert _seconds(out) == [(0.6, 2.0), (3.6, 5.0)]
    assert stats["onset_extended"] == 2
    assert stats["onset_gated"] == 0
    assert stats["onset_shift_s"] == pytest.approx(0.4)


def test_build_whisper_config_clamps_onset_pad():
    assert build_whisper_config(onset_pad_ms=5000).onset_pad_ms == ONSET_PAD_MAX_MS
    assert build_whisper_config(onset_pad_ms=-10).onset_pad_ms == 0


def test_params_defaults_match_the_ab_decision():
    # 2026-11-13 的 A/B 结论：qwen 默认 400 ms（Test 二 −1.95pt、句首缺字 5→1），
    # whisper 不启用（扩窗会把气声幻觉成字幕，CER +1.61pt）。
    assert params.config_kwargs("qwen", {})["vad_onset_pad_ms"] == 400
    assert params.config_kwargs("whisper", {})["onset_pad_ms"] == 0
    # 0 必须能完全回到旧行为（两边的显式覆写都认）。
    assert params.config_kwargs("qwen", {"qwen.vad_onset_pad_ms": 0})["vad_onset_pad_ms"] == 0
    assert params.config_kwargs("whisper", {"whisper.vad_onset_pad_ms": 400})["onset_pad_ms"] == 400


# --------------------------------------------------------------------------- 报告


def test_report_mentions_onset_extension():
    from core.report import _onset_summary

    assert "未启用" in _onset_summary({})
    assert "9 段，平均 +0.42s" in _onset_summary(
        {"onset_pad_ms": 400, "onset_extended": 9, "onset_shift_s": 0.42}
    )
    assert "2 段被能量闸门拦回" in _onset_summary(
        {"onset_pad_ms": 400, "onset_extended": 9, "onset_shift_s": 0.42, "onset_gated": 2}
    )


def test_report_param_list_gains_onset_row_only_when_enabled():
    from core.report import param_pairs
    from core.qwen_ctc import QwenCtcConfig

    def rows(config, is_qwen=True):
        pairs = param_pairs(
            is_qwen=is_qwen, config=config, ngram=5, penalty=1.15, use_alignment=True
        )
        return dict(pairs)

    assert "句首提前 (onset_pad_ms)" not in rows(QwenCtcConfig(vad_onset_pad_ms=0))
    assert rows(QwenCtcConfig(vad_onset_pad_ms=400))["句首提前 (onset_pad_ms)"] == "400 ms"


def test_qwen_config_default_matches_param_default():
    from core.qwen_ctc import QwenCtcConfig

    assert QwenCtcConfig().vad_onset_pad_ms == params.config_kwargs("qwen", {})["vad_onset_pad_ms"]
