"""参数规格：键的唯一性、默认值、映射到引擎配置的正确性。

这里最值得守的一条是「预设文件里的键必须都能在规格表里找到」——
否则用户存过的预设载入后参数会静默失效。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import params
from core.presets import PresetStore


def test_keys_are_unique_and_engine_prefixed():
    keys = [spec.key for spec in params.SPECS]
    assert len(keys) == len(set(keys))
    for spec in params.SPECS:
        assert spec.key.startswith(f"{spec.engine}."), spec.key
        assert spec.engine in params.ENGINES


def test_both_engines_have_params():
    for engine in params.ENGINES:
        assert params.specs_for(engine), engine
        assert params.defaults_for(engine)


def test_grouped_preserves_declaration_order():
    groups = params.grouped("whisper")
    names = [g["group"] for g in groups]
    assert names[0] == "基础"
    assert "VAD" in names
    # 每组里的参数都属于该引擎
    for group in groups:
        for item in group["params"]:
            assert item["engine"] == "whisper"


def test_normalize_fills_defaults_and_clamps():
    resolved = params.normalize("whisper", {"whisper.vad_threshold": 99})
    assert resolved["whisper.vad_threshold"] == 0.80  # 夹到上限
    assert resolved["whisper.vad_min_speech_ms"] == 80  # 补默认
    # 别的引擎的键要被丢掉
    assert "qwen.vad_threshold" not in resolved


def test_normalize_ignores_unknown_and_bad_values():
    resolved = params.normalize("whisper", {"whisper.nope": 1, "whisper.vad_threshold": "abc"})
    assert "whisper.nope" not in resolved
    assert resolved["whisper.vad_threshold"] == params.defaults_for("whisper")["whisper.vad_threshold"]


def test_config_kwargs_maps_field_names():
    kwargs = params.config_kwargs("whisper", {"whisper.vad_threshold": 0.25})
    assert kwargs["threshold"] == 0.25
    assert kwargs["enable_sentence_split"] is True
    # 透传参数不应出现在 dataclass 参数里
    assert "no_repeat_ngram_size" not in kwargs


def test_tuple_config_field_fans_out():
    kwargs = params.config_kwargs("qwen", {"qwen.cue_pad_s": 0.2})
    assert kwargs["cue_pad_start_s"] == 0.2
    assert kwargs["cue_pad_end_s"] == 0.2


def test_passthrough_kwargs():
    extra = params.passthrough_kwargs(
        "whisper", {"whisper.no_repeat_ngram_size": 7, "whisper.repetition_penalty": 1.2}
    )
    assert extra["no_repeat_ngram_size"] == 7
    assert extra["repetition_penalty"] == 1.2
    # use_alignment 属于 qwen
    assert "use_alignment" not in extra

    qwen_extra = params.passthrough_kwargs("qwen", {"qwen.use_alignment": False})
    assert qwen_extra["use_alignment"] is False


def test_config_kwargs_are_constructible():
    """映射出来的字段必须真能构造引擎配置，否则转写时才炸。"""
    from core.qwen_ctc import QwenCtcConfig
    from core.transcribe import build_whisper_config

    build_whisper_config(**params.config_kwargs("whisper", params.defaults_for("whisper")))
    QwenCtcConfig(**params.config_kwargs("qwen", params.defaults_for("qwen")))


def test_every_preset_key_exists_in_specs():
    """预设文件里的键必须全部能在规格表里找到。"""
    store = PresetStore(Path(__file__).resolve().parent.parent / "presets.json")
    assert not store.load_error, store.load_error
    assert store.names(), "presets.json 里没有可用预设"

    known = set(params.BY_KEY)
    for name in store.names():
        entry = store.get(name)
        unknown = set(entry["参数"]) - known
        assert not unknown, f"预设「{name}」里有规格表不认识的键：{unknown}"


def test_schema_shape():
    data = params.schema()
    assert {e["key"] for e in data["engines"]} == set(params.ENGINES)
    first = data["engines"][0]
    assert first["groups"] and first["defaults"]


@pytest.mark.parametrize("engine", params.ENGINES)
def test_bool_defaults_are_bool(engine):
    for spec in params.specs_for(engine):
        if spec.kind == "bool":
            assert isinstance(spec.default, bool), spec.key
