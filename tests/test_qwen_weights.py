"""Qwen 权重完整性检查：缺 shard 时不能显示“已就绪”。"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("torch")

from core.qwen_ctc import HEAD_FILE, QwenCtcEngine  # noqa: E402


def _fake_model_dir(tmp_path, *, with_shard: bool):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / HEAD_FILE).write_bytes(b"0")
    (tmp_path / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"layer": "model-00001-of-00001.safetensors"}}),
        encoding="utf-8",
    )
    if with_shard:
        (tmp_path / "model-00001-of-00001.safetensors").write_bytes(b"0")
    return tmp_path


def test_missing_shard_is_not_available(tmp_path):
    engine = QwenCtcEngine(model_dir=_fake_model_dir(tmp_path, with_shard=False))
    assert engine.model_available is False


def test_complete_shards_are_available(tmp_path):
    engine = QwenCtcEngine(model_dir=_fake_model_dir(tmp_path, with_shard=True))
    assert engine.model_available is True
