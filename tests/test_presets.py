"""presets.json 读写与向后兼容测试（仅依赖标准库，可在轻量 CI 中运行）。"""

from __future__ import annotations

import json

import pytest

from core.presets import (
    PresetEngineMismatch,
    PresetError,
    PresetNotFound,
    PresetStore,
    clean_name,
)


@pytest.fixture()
def store(tmp_path):
    return PresetStore(tmp_path / "presets.json")


def test_save_load_and_overwrite(store):
    name, created = store.save("动漫默认", {"whisper.vad_threshold": 0.3}, engine="whisper")
    assert (name, created) == ("动漫默认", True)
    assert store.get(name)["引擎"] == "whisper"

    _, created_again = store.save("动漫默认", {"whisper.vad_threshold": 0.25}, engine="whisper")
    assert created_again is False
    assert store.get("动漫默认")["参数"]["whisper.vad_threshold"] == 0.25


def test_reload_from_disk(tmp_path):
    path = tmp_path / "presets.json"
    store = PresetStore(path)
    store.save("p1", {"qwen.max_cue_dur": 4.3}, engine="qwen")
    again = PresetStore(path)
    assert again.names() == ["p1"]
    assert again.get("p1")["引擎"] == "qwen"


def test_rename_and_delete(store):
    store.save("old", {"whisper.vad_threshold": 0.3}, engine="whisper")
    assert store.rename("old", "new") == ("new", False)
    assert store.names() == ["new"]
    assert store.delete("new") == "new"
    assert store.names() == []


def test_invalid_names_rejected(store):
    for bad in ("", "   ", "a/b", "a\\b", "x" * 41):
        with pytest.raises(PresetError):
            store.save(bad, {}, engine="whisper")


def test_corrupted_file_reports_error_without_crashing(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text("{ not json", encoding="utf-8")
    store = PresetStore(path)
    assert store.names() == []
    assert store.load_error


def test_backward_compatible_flat_entries(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text(
        json.dumps(
            {
                "版本": 1,
                "预设": {
                    "flat": {"whisper.vad_threshold": 0.4},
                    "explicit": {"引擎": "qwen", "参数": {"qwen.max_cue_dur": 4.0}},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = PresetStore(path)
    assert store.get("flat")["引擎"] == "whisper"
    assert store.get("explicit")["引擎"] == "qwen"


def test_clean_name_strips_whitespace():
    assert clean_name("  名称  ") == "名称"


def test_save_requires_engine(store):
    """预设必须绑定引擎：没有引擎的预设无法判断该套到哪个参数面板。"""
    with pytest.raises(PresetError, match="引擎"):
        store.save("无主预设", {"whisper.vad_threshold": 0.3})
    with pytest.raises(PresetError, match="引擎"):
        store.save("坏引擎", {"whisper.vad_threshold": 0.3}, engine="unknown")


def test_save_keeps_only_engine_own_keys_and_fills_defaults(store):
    store.save(
        "混合",
        {
            "whisper.vad_threshold": 0.42,
            "qwen.max_cue_chars": 12,  # 别的引擎的键必须被丢掉
        },
        engine="whisper",
    )
    params = store.get("混合")["参数"]
    assert params["whisper.vad_threshold"] == 0.42
    assert not any(key.startswith("qwen.") for key in params)
    # 没给的键补当前默认值，载入后是一份完整快照，不会和面板里的旧值混在一起
    assert "whisper.vad_max_segment_s" in params


def test_resolve_rejects_cross_engine_load(store):
    store.save("只给 Whisper", {"whisper.vad_threshold": 0.3}, engine="whisper")
    assert store.resolve("只给 Whisper", "whisper")["引擎"] == "whisper"
    with pytest.raises(PresetEngineMismatch, match="不能加载"):
        store.resolve("只给 Whisper", "qwen")
    with pytest.raises(PresetNotFound):
        store.resolve("不存在", "whisper")


def test_cannot_overwrite_another_engines_preset(store):
    store.save("同名", {"whisper.vad_threshold": 0.3}, engine="whisper")
    with pytest.raises(PresetError, match="已绑定"):
        store.save("同名", {"qwen.max_cue_chars": 12}, engine="qwen")
    # 原预设原样保留
    assert store.resolve("同名", "whisper")["参数"]["whisper.vad_threshold"] == 0.3


def test_list_filters_by_engine(store):
    store.save("a", {"whisper.vad_threshold": 0.3}, engine="whisper")
    store.save("b", {"qwen.max_cue_chars": 12}, engine="qwen")
    assert store.list("whisper") == [("a", "whisper")]
    assert store.list("qwen") == [("b", "qwen")]
    assert {name for name, _ in store.list()} == {"a", "b"}


def test_rename_refuses_to_clobber_existing_name(store):
    store.save("a", {"whisper.vad_threshold": 0.3}, engine="whisper")
    store.save("b", {"qwen.max_cue_chars": 12}, engine="qwen")
    with pytest.raises(PresetError, match="同名"):
        store.rename("a", "b")
