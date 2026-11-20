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
    assert kwargs["enable_start_repair"] is True
    assert kwargs["nonverbal_qa"] is True
    # 透传参数不应出现在 dataclass 参数里
    assert "no_repeat_ngram_size" not in kwargs


def test_qwen_cue_pads_are_independent():
    """起点/终点留白是两个独立滑杆：人工核验版的惯例是提前 0.2s、句尾多停 0.45s。"""
    kwargs = params.config_kwargs(
        "qwen", {"qwen.cue_pad_start_s": 0.2, "qwen.cue_pad_end_s": 0.45}
    )
    assert kwargs["cue_pad_start_s"] == 0.2
    assert kwargs["cue_pad_end_s"] == 0.45
    assert params.defaults_for("qwen")["qwen.cue_pad_end_s"] == 0.45
    assert params.config_kwargs("qwen", {})["nonverbal_qa"] is False


def test_legacy_cue_pad_key_expands():
    """旧预设里的 qwen.cue_pad_s 仍要生效（拆成起点/终点两个键）。"""
    kwargs = params.config_kwargs("qwen", {"qwen.cue_pad_s": 0.08})
    assert kwargs["cue_pad_start_s"] == 0.08
    assert kwargs["cue_pad_end_s"] == 0.08


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


def test_shipped_presets_cover_every_engine_with_its_defaults():
    """仓库里的种子预设 = 每个引擎一份「当前默认参数」快照，且都绑定到该引擎。

    这条守住 2026-11-14 的约定：四个引擎各有一份标定后的默认预设；
    预设不能跨引擎混用，也不允许把别的引擎的键混进来。

    2026-11-15 起 Whisper 额外带一份「歌曲」变体（强 BGM / 歌曲区间用），
    它不是默认快照，只是同引擎的第二个命名方案；除此之外仍只允许每引擎一份默认值。
    """
    store = PresetStore(Path(__file__).resolve().parent.parent / "presets.json")
    assert not store.load_error, store.load_error
    listed = store.list()

    defaults = [
        name
        for name, bound in listed
        if store.get(name)["参数"] == params.defaults_for(bound)
    ]
    assert len(defaults) == len(params.ENGINES), (
        f"每个引擎应恰好有一份等于当前默认值的预设：{listed}"
    )

    extras = [name for name, _bound in listed if name not in defaults]
    assert set(extras) == {"歌曲"}, f"除每引擎默认预设外只允许「歌曲」变体：{extras}"
    assert store.get("歌曲")["引擎"] == "whisper"
    song = store.get("歌曲")["参数"]
    assert song["whisper.vad_max_segment_s"] == 15.0
    assert song["whisper.vad_merge_gap_s"] == 0.5
    assert song["whisper.vad_min_silence_ms"] == 300


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


def test_vad_backend_enum_defaults_and_validation():
    """VAD 切分器只暴露两个验证过的选项；旧值 auto 回落到推荐默认。"""
    assert params.defaults_for("whisper")["whisper.vad_backend"] == "whisperseg"
    assert params.config_kwargs("whisper", {})["vad_backend"] == "whisperseg"
    assert params.config_kwargs(
        "whisper", {"whisper.vad_backend": "silero"}
    )["vad_backend"] == "silero"
    # 非法值（含已否决的 silero10 / 旧 auto）被 normalize 忽略，保留默认。
    for legacy in ("not-a-backend", "silero10", "auto"):
        assert params.normalize(
            "whisper", {"whisper.vad_backend": legacy}
        )["whisper.vad_backend"] == "whisperseg"
    spec = params.BY_KEY["whisper.vad_backend"]
    assert spec.choices == ("whisperseg", "silero")
    assert spec.to_dict()["choices"] == ["whisperseg", "silero"]
    assert spec.to_dict()["choice_labels"] == {
        "whisperseg": "WhisperSeg（推荐）",
        "silero": "Silero 20s（兼容）",
    }


def test_vad_backend_scoped_metadata():
    """参数面板的「仅 Silero 生效」与推荐阈值都来自规格表，前端不另写一份。"""
    onset = params.BY_KEY["whisper.vad_onset_pad_ms"]
    assert onset.backend_only == "silero"
    assert onset.to_dict()["backend_only"] == "silero"

    threshold = params.BY_KEY["whisper.vad_threshold"]
    assert threshold.to_dict()["backend_only"] is None
    notes = threshold.to_dict()["backend_notes"]
    assert "0.35" in notes["whisperseg"]
    assert "0.25" in notes["silero"]
    assert threshold.to_dict()["backend_recommended"] == {
        "whisperseg": 0.35,
        "silero": 0.25,
    }
    # 其余参数不带后端限定，避免前端误置灰。
    assert params.BY_KEY["whisper.vad_min_silence_ms"].backend_only == ""
