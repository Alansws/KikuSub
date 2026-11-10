"""presets.json 读写与向后兼容测试（仅依赖标准库，可在轻量 CI 中运行）。"""

from __future__ import annotations

import json

import pytest

from core.presets import PresetError, PresetStore, clean_name


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
