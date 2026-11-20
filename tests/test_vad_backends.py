"""VAD 后端的纯逻辑回归：不加载真实模型。"""

from __future__ import annotations

import numpy as np
import pytest

from core import vad


def test_resolve_backend_defaults_and_aliases(monkeypatch):
    monkeypatch.delenv(vad.ENV_BACKEND, raising=False)
    assert vad.resolve_backend() == "whisperseg"
    assert vad.resolve_backend("silero") == "silero"
    assert vad.resolve_backend("silero20") == "silero"
    monkeypatch.setenv(vad.ENV_BACKEND, "whisper_seg")
    assert vad.resolve_backend() == "whisperseg"


def test_resolve_backend_auto_is_alias_for_default(monkeypatch):
    monkeypatch.delenv(vad.ENV_BACKEND, raising=False)
    assert vad.resolve_backend("auto") == "whisperseg"
    monkeypatch.setenv(vad.ENV_BACKEND, "silero")
    assert vad.resolve_backend("auto") == "silero"
    assert vad.resolve_backend() == "silero"


def test_resolve_backend_rejects_unknown(monkeypatch):
    monkeypatch.setenv(vad.ENV_BACKEND, "nope")
    with pytest.raises(vad.VadBackendError):
        vad.resolve_backend()
    # 被否决的实验后端不再能从核心选到。
    with pytest.raises(vad.VadBackendError):
        vad.resolve_backend("ten")
    with pytest.raises(vad.VadBackendError):
        vad.resolve_backend("silero10")


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


def test_detect_dispatches_silero_window(monkeypatch):
    calls = []

    def fake(audio, model, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(vad, "_silero_detect", fake)
    vad.detect_speech_stamps(
        np.zeros(1600, dtype=np.float32), None, threshold=0.25,
        min_speech_ms=80, min_silence_ms=200, speech_pad_ms=250,
        backend="silero", window_s=10.0,
    )
    assert calls and calls[0]["window_s"] == 10.0


def test_whisperseg_asset_reports_missing_files(monkeypatch, tmp_path):
    monkeypatch.setenv(vad.ENV_WHISPERSEG_DIR, str(tmp_path))
    asset = vad.whisperseg_asset()
    assert asset["key"] == "whisperseg"
    assert asset["installed"] is False
    assert asset["approx_bytes"] > 100 * 1024 * 1024
    (tmp_path / "model.onnx").write_bytes(b"x")
    assert vad.whisperseg_asset()["installed"] is False
    (tmp_path / "preprocessor_config.json").write_text("{}", encoding="utf-8")
    assert vad.whisperseg_asset()["installed"] is True


def test_whisperseg_missing_model_is_readable(monkeypatch, tmp_path):
    monkeypatch.setenv(vad.ENV_WHISPERSEG_DIR, str(tmp_path))
    monkeypatch.setattr(vad, "_download_whisperseg", lambda *a, **k: None)
    with pytest.raises(vad.VadBackendError, match="下载不完整"):
        vad._load_whisperseg()


def test_ensure_whisperseg_downloads_via_model_fetch(monkeypatch, tmp_path):
    """权重必须走 model_fetch（镜像回退/进度）并落到 models 目录。"""
    from core import model_fetch

    monkeypatch.setenv(vad.ENV_WHISPERSEG_DIR, str(tmp_path))
    calls = []
    progress = []

    def fake_snapshot(**kwargs):
        calls.append(("snapshot", kwargs["repo_id"], tuple(kwargs["allow_patterns"])))
        (tmp_path / "model.onnx").write_bytes(b"x" * 32)

    def fake_file(**kwargs):
        calls.append(("file", kwargs["repo_id"], kwargs["filename"]))
        (tmp_path / "preprocessor_config.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(model_fetch, "snapshot_download_files", fake_snapshot)
    monkeypatch.setattr(model_fetch, "hf_hub_download_file", fake_file)

    asset = vad.ensure_whisperseg(progress_cb=lambda r, m: progress.append((r, m)))
    assert asset["installed"] is True
    assert calls == [
        ("snapshot", vad.WHISPERSEG_REPO, ("model.onnx",)),
        ("file", vad.WHISPERSEG_FEATURE_REPO, "preprocessor_config.json"),
    ]
    assert progress and progress[-1][0] == 1.0

    # 已就绪时再调不重新下载。
    vad.ensure_whisperseg()
    assert len(calls) == 2
