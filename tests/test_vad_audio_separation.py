"""P3：人声分离默认只服务 VAD（`vad_audio`），ASR 音频必须与未开分离逐字节一致。

这一条是 P3 的核心承诺：Demucs 的 vocals 轨会削掉日语清辅音（す/そ/え 的 s 音），
拿它送识别会带来新的错字。默认档只把干净人声喂给 VAD，识别仍读原声；因此
「ASR 解码调用」必须和完全不勾人声分离时一模一样，收益只能来自更干净的边界。
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("torch")

from core import transcribe as tr  # noqa: E402
from core.transcribe import (  # noqa: E402
    AnimeWhisperEngine,
    build_whisper_config,
    clamp_stamps_to_audio,
)

SR = tr.SAMPLE_RATE


def test_clamp_stamps_drops_out_of_range_and_keeps_time_axis():
    stamps = [
        {"start": 0, "end": 100},
        {"start": 200, "end": 500},
        {"start": 900, "end": 2000},  # 超出 1000：夹到尾巴
        {"start": 1200, "end": 1300},  # 完全越界：丢
    ]
    out = clamp_stamps_to_audio(stamps, 1000)
    assert out == [
        {"start": 0, "end": 100},
        {"start": 200, "end": 500},
        {"start": 900, "end": 1000},
    ]


def _engine() -> AnimeWhisperEngine:
    return AnimeWhisperEngine(
        build_whisper_config(
            enable_start_repair=False,
            strip_nonverbal_edges=False,
            vad_backend="silero",
        )
    )


def test_vad_only_uses_clean_audio_for_vad_and_original_for_recognition(monkeypatch):
    """VAD 拿分离人声；送模切片必须来自原声数组（不是分离后的）。"""
    engine = _engine()
    audio = np.full(SR * 2, 0.01, dtype=np.float32)  # 原声：有底噪、清辅音在
    vad_audio = np.zeros(SR * 2, dtype=np.float32)  # 分离人声：只留更干净的峰
    vad_audio[:SR] = 0.5

    seen: dict = {}

    def fake_detect(array, *args, **kwargs):
        seen["vad_input_is_vad_audio"] = array is vad_audio
        return [{"start": 0, "end": SR}]

    monkeypatch.setattr(tr, "detect_speech_stamps", fake_detect)
    monkeypatch.setattr(tr, "merge_vad_segments", lambda segments, **kwargs: [(0, SR)])

    decoded: list[np.ndarray] = []

    def fake_decode(buf, kwargs, timestamps=False, prompt_text=""):
        decoded.append(np.array(buf, copy=True))
        return ""

    engine._decode_chunk = fake_decode

    cues = engine._transcribe_array(audio, config=engine.config, vad_audio=vad_audio)

    assert cues == []
    assert seen["vad_input_is_vad_audio"] is True
    assert decoded, "至少应该把 VAD 切出的那一段送去识别"
    # 原声段是 0.01 的底噪（空文本重试时会被 _retry_gain 抬到 0.08）；
    # 分离人声段含 0.5 的峰，两者不可能混淆。
    assert np.allclose(decoded[0], 0.01)
    for chunk in decoded:
        assert float(np.max(np.abs(chunk))) < 0.1
    assert engine.last_segment_stats["vad_audio"] == "vocals"


def test_transcribe_file_decodes_same_asr_audio_with_and_without_vad_path(
    monkeypatch, tmp_path
):
    """ASR 解码调用（路径 + 区间 + 响度档位）必须逐参数一致。"""
    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    vocals = tmp_path / "vocals.wav"
    vocals.write_bytes(b"x")

    engine = _engine()
    monkeypatch.setattr(engine, "load", lambda **kwargs: None)

    calls: list[dict] = []
    payloads: dict = {}

    def fake_load(media_path, **kwargs):
        calls.append({"path": str(media_path), **kwargs})
        key = str(media_path)
        payloads.setdefault(key, np.full(SR, 0.02, dtype=np.float32))
        return payloads[key]

    monkeypatch.setattr(tr, "load_audio_for_transcription", fake_load)

    captured: list[np.ndarray] = []
    monkeypatch.setattr(
        engine,
        "_transcribe_array",
        lambda audio, **kwargs: captured.append(audio) or [],
    )

    engine.transcribe_file(media, start_time_s=1.0, end_time_s=3.0)
    baseline_calls = [dict(call) for call in calls]
    calls.clear()

    engine.transcribe_file(
        media,
        start_time_s=1.0,
        end_time_s=3.0,
        vad_audio_path=vocals,
    )

    asr_call = calls[0]
    assert baseline_calls[0] == asr_call
    assert asr_call["path"] == str(media)
    assert asr_call["start_time_s"] == 1.0
    assert asr_call["end_time_s"] == 3.0
    assert asr_call["enable_loudnorm"] is True
    # 后两段都是分离人声，而且不带切片（它本身就是本次分离范围）。
    assert [call["path"] for call in calls[1:]] == [str(vocals), str(vocals)]
    for call in calls[1:]:
        assert call.get("start_time_s") is None
        assert call.get("end_time_s") is None
    # VAD 检测仍走 dynaudnorm 档位；另解一份未归一化的真实电平做能量门控。
    assert calls[1]["enable_loudnorm"] is True
    assert calls[2]["enable_loudnorm"] is False
    # 两次送进 _transcribe_array 的 ASR 数组是同一个对象/同一份缓存内容。
    assert np.array_equal(captured[0], captured[1])


def test_vad_only_energy_gate_drops_silent_vad_segments(monkeypatch):
    """VAD 在静音 vocals 上切出的段会被绝对能量门控拦下，不送识别。"""
    engine = _engine()
    audio = np.full(SR * 2, 0.01, dtype=np.float32)
    vad_audio = np.zeros(SR * 2, dtype=np.float32)
    vad_level_audio = np.zeros(SR * 2, dtype=np.float32)

    from core import vad as vad_module

    monkeypatch.setattr(
        vad_module,
        "_silero_detect",
        lambda *args, **kwargs: [{"start": 0, "end": SR}],
    )
    decoded: list[np.ndarray] = []
    engine._decode_chunk = (
        lambda buf, kwargs, timestamps=False, prompt_text="": decoded.append(buf) or ""
    )

    cues = engine._transcribe_array(
        audio,
        config=engine.config,
        vad_audio=vad_audio,
        vad_level_audio=vad_level_audio,
    )

    assert cues == []
    assert decoded == []
    gate = engine.last_segment_stats["vocal_gate"]
    assert gate["dropped"] == 1
    assert gate["kept"] == 0
    assert engine.last_segment_stats["vad_audio"] == "vocals"


def test_onset_pad_is_ignored_for_whisperseg_and_reported(monkeypatch):
    """句首提前只补偿 Silero：WhisperSeg 下不生效，并在报告口径里说明。"""
    engine = AnimeWhisperEngine(
        build_whisper_config(
            enable_start_repair=False,
            strip_nonverbal_edges=False,
            vad_backend="whisperseg",
            onset_pad_ms=400,
        )
    )
    audio = np.full(SR, 0.01, dtype=np.float32)

    monkeypatch.setattr(
        tr, "merge_vad_segments", lambda segments, **kwargs: [(SR // 2, SR)]
    )
    # WhisperSeg 权重不可用时产品会回退 Silero，这里注入「用的就是 WhisperSeg」。
    monkeypatch.setattr(
        tr,
        "detect_speech_stamps",
        lambda array, *a, backend_stats=None, **k: (
            (backend_stats or {}).update(
                {"requested": "whisperseg", "used": "whisperseg", "fallback": False}
            )
            or [{"start": SR // 2, "end": SR}]
        ),
    )
    engine._decode_chunk = lambda buf, kwargs, timestamps=False, prompt_text="": ""

    engine._transcribe_array(audio, config=engine.config)

    assert engine.last_segment_stats["onset_pad_ignored_backend"] == "whisperseg"
    assert engine.last_segment_stats["onset_pad_ms"] == 0

    from core.report import _onset_summary

    assert "仅 Silero 生效" in _onset_summary(engine.last_segment_stats)
