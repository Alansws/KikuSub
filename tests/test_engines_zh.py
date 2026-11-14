"""两个中文引擎的接入契约（不加载模型）。

锁住的是「可选装」这件事本身：默认停用、权重不随包、注册表/参数表/报告口径三者对齐。
真实推理不在这里跑（需要 1.4 GB 权重，用 ``-m needs_model`` 的用例单独覆盖）。
"""

from __future__ import annotations

import pytest

from core import audit, engines, params, report
from core.sherpa_asr import FireRedAsrEngine, SenseVoiceEngine, SherpaAsrConfig

ZH_KEYS = ("sensevoice", "firered")


def test_chinese_engines_are_registered_and_optional(monkeypatch, tmp_path):
    monkeypatch.setattr(engines, "MODELS_DIR", tmp_path)

    for key in ZH_KEYS:
        spec = engines.get(key)
        assert spec.family == "sherpa", key
        assert "中文" in spec.languages, key
        assert spec.downloadable is True, key
        assert key not in engines.DEFAULT_ENABLED, f"{key} 不该默认启用（可选装件）"
        assert engines.is_installed(spec) is False

        directory = tmp_path / spec.dir_name
        directory.mkdir()
        for name in spec.required_files:
            (directory / name).write_bytes(b"x")
        assert engines.is_installed(spec) is True

        status = engines.status(spec, include_size=False)
        assert status["family"] == "sherpa"
        assert status["installed"] is True
        assert status["approx_bytes"] > 0


def test_whisper_and_qwen_stay_default_enabled():
    assert set(engines.DEFAULT_ENABLED) == {"whisper", "qwen"}
    assert set(engines.KEYS) == {"whisper", "qwen", *ZH_KEYS}


def test_family_of_rejects_unknown_engine():
    assert engines.family_of("sensevoice") == "sherpa"
    assert engines.family_of("whisper") == "whisper"
    with pytest.raises(KeyError):
        engines.family_of("nope")


def test_sherpa_params_map_onto_one_config_dataclass():
    kwargs = params.config_kwargs(
        "sensevoice",
        {"sensevoice.max_cue_chars": 22, "sensevoice.use_itn": False, "sensevoice.num_threads": 4},
    )
    config = SherpaAsrConfig(**kwargs)
    assert config.max_cue_chars == 22
    assert config.use_itn is False
    assert config.num_threads == 4

    # 跨引擎的键与拼错的键都必须被丢掉，不能把 422 变成 TypeError。
    firered = SherpaAsrConfig(
        **params.config_kwargs(
            "firered",
            {"whisper.vad_threshold": 0.9, "firered.number_of_threads": 8},
        )
    )
    assert firered.vad_threshold == 0.30
    assert firered.num_threads == 2


def test_sherpa_params_are_clamped():
    values = params.normalize("firered", {"firered.max_cue_chars": 999, "firered.vad_threshold": -1})
    assert values["firered.max_cue_chars"] == 35
    assert values["firered.vad_threshold"] == 0.05


def test_engine_classes_point_at_their_own_weights(tmp_path):
    sense = SenseVoiceEngine(model_dir=tmp_path / "sv")
    fired = FireRedAsrEngine(model_dir=tmp_path / "fr")

    assert sense.key == "sensevoice" and fired.key == "firered"
    assert sense.model_dir.name == "sv"
    assert (tmp_path / "sv" / "model.int8.onnx") in [
        sense.model_dir / name for name in sense.required_files
    ]
    assert "encoder.int8.onnx" in fired.required_files


def test_audit_marks_timestamp_review_as_unavailable_for_chinese_engines():
    for key in ZH_KEYS:
        coverage = audit._audit_coverage(key)
        assert coverage["missed"] is True
        assert coverage["dropped"] is False
        assert coverage["suspect"] is False

    assert audit._audit_coverage("whisper")["dropped"] is True
    # idle 态（还没有引擎跑过）沿用旧口径，避免空队列被解释成「本引擎不启用」
    assert audit._audit_coverage("")["dropped"] is True


def _sherpa_report():
    align_stats = {
        "enabled": True,
        "segments": 3,
        "aligned": 2,
        "noop": 0,
        "degraded": 1,
        "empty": 0,
        "align_chars": 40,
        "interp_chars": 0,
        "truncated": 0,
        "capped_repeat": 0,
        "spans": [
            {"start": 10.0, "end": 14.0, "dur": 4.0, "reason": "no-token-timestamps", "chars": 12}
        ],
        "family": "sherpa",
    }
    return report.build_report_data(
        media_name="episode.mkv",
        out_filename="episode.sensevoice.srt",
        out_path="/tmp/episode.sensevoice.srt",
        engine_name="SenseVoice-Small 中文",
        output_format="SRT",
        elapsed_time=12.0,
        cue_count=2,
        char_count=20,
        is_qwen=False,
        engine_family="sherpa",
        config=SherpaAsrConfig(),
        align_stats=align_stats,
    )


def test_report_uses_sherpa_wording():
    data = _sherpa_report()

    assert data["quality"]["engine_family"] == "sherpa"
    # 没有 Whisper 的时间戳复核，就不能把 0 条读成「复查过且干净」
    assert data["quality"]["qwen_limited"] is True
    assert "token 时间戳" in data["raw_text"]
    assert "幻觉门控】未触发" not in data["raw_text"]
    assert "SenseVoice-Small / FireRedASR2-AED" in data["raw_text"]
    sections = {section["id"]: section for section in data["sections"]}
    assert sections["hallucination"].get("disabled") is True
    assert sections["alignment"]["headline"].startswith("共 3 段")


def test_load_rebuilds_recognizer_with_the_per_call_config(monkeypatch, tmp_path):
    """参数面板改了线程数 / ITN 之后，下一次转写必须按新配置重建识别器。"""
    from core import sherpa_asr

    calls: list[tuple[int, bool]] = []

    class _Dummy(SenseVoiceEngine):
        def _create_recognizer(self, sherpa_onnx, cfg):
            calls.append((cfg.num_threads, cfg.use_itn))
            return object()

    engine = _Dummy(model_dir=tmp_path / "sv")
    monkeypatch.setattr(engine, "ensure_model", lambda progress_cb=None: None)
    monkeypatch.setattr(sherpa_asr, "_import_sherpa", lambda: object())
    monkeypatch.setattr(sherpa_asr, "_load_vad", lambda: object())

    engine.load(config=SherpaAsrConfig(num_threads=2, use_itn=True))
    engine.load(config=SherpaAsrConfig(num_threads=2, use_itn=True))
    engine.load(config=SherpaAsrConfig(num_threads=4, use_itn=False))

    assert calls == [(2, True), (4, False)]
