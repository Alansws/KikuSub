"""通用对齐层（core/align_layer.py）与「借 Qwen 对齐头给 Whisper」的守卫。

重点不是精度（精度在 docs/转录标定-Qwen-2026-11.md 里有实测数字），而是
**不能因为对齐层不可用就把已经识别好的文本丢掉**。
"""

from __future__ import annotations

import numpy as np
import pytest

from core.align_layer import LAYER, CtcAlignLayer
from core.qwen_ctc import QwenCtcConfig
from core.transcribe import AnimeWhisperEngine, WhisperVadConfig


def test_split_without_loaded_engine_is_a_clean_failure():
    layer = CtcAlignLayer()
    out = layer.split(np.zeros(16000, dtype=np.float32), "テスト", offset=0.0)
    assert out.ok is False
    assert out.reason == "aligner-not-loaded"
    assert out.cues is None


def test_align_without_engine_reports_reason():
    layer = CtcAlignLayer()
    result = layer.align(np.zeros(1600, dtype=np.float32), "あ")
    assert result.ok is False
    assert result.reason == "aligner-not-loaded"


def test_weights_present_never_raises():
    # 权重不在时返回 False，权重在时返回 True——两种机器都要能跑这条断言。
    assert isinstance(CtcAlignLayer.weights_present(), bool)


def test_whisper_ctc_alignment_is_opt_in():
    assert WhisperVadConfig().use_ctc_alignment is False


@pytest.mark.parametrize("field", ["cue_pad_start_s", "cue_pad_end_s"])
def test_qwen_cue_pads_are_separate_fields(field):
    cfg = QwenCtcConfig()
    assert getattr(cfg, field) > 0


def test_aligned_pass_releases_whisper_before_loading_aligner(monkeypatch):
    """两遍的顺序是硬要求：先卸 Whisper，再装对齐器，否则两份权重会叠在一起。"""
    engine = AnimeWhisperEngine()
    order: list[str] = []
    monkeypatch.setattr(engine, "release", lambda: order.append("release"))

    def fake_ensure(_cb=None):
        order.append("aligner-load")
        return False

    monkeypatch.setattr(LAYER, "ensure_loaded", fake_ensure)
    monkeypatch.setattr(LAYER, "unload", lambda: order.append("aligner-unload"))

    stats = {"segments": 0, "chars": 0, "degraded": 0}
    engine._aligned_pass(
        [(0, 16000, "どうしたの?", 300.0, 301.0)],
        np.zeros(16000, dtype=np.float32),
        WhisperVadConfig(use_ctc_alignment=True),
        stats,
    )
    assert order == ["release", "aligner-load", "aligner-unload"]
    assert stats["degraded"] == 1

def test_aligned_pass_falls_back_without_dropping_text():
    class _Dead:
        def ensure_loaded(self, _cb=None):
            return False

        def split(self, *_a, **_k):  # pragma: no cover - 不该被调用
            raise AssertionError("对齐器不可用时不应调用 split")

        def unload(self):
            pass

    import core.align_layer as mod

    engine = AnimeWhisperEngine()
    engine.release = lambda: None
    original = mod.LAYER
    mod.LAYER = _Dead()
    try:
        stats = {"segments": 0, "chars": 0, "degraded": 0}
        cues = engine._aligned_pass(
            [(0, 16000, "どうしたの?", 300.0, 301.0)],
            np.zeros(16000, dtype=np.float32),
            WhisperVadConfig(use_ctc_alignment=True),
            stats,
        )
    finally:
        mod.LAYER = original
    assert cues, "对齐不可用时必须回退出字幕，不能整段消失"
    assert "".join(c.text for c in cues).strip()
