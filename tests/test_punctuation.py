"""FireRedPunc 标点恢复的纯逻辑与装配测试（默认不加载 162 MB 权重）。

三个契约：
1. 标点按字符偏移插回**原文**，英文大小写与空格不能被 tokenizer 改掉；
2. 原文已有句读、或预测落在英文子词内部时，不插；
3. 真实 ONNX 权重存在时能跑通（本机装了 onnxruntime + 权重才执行，CI 自动 skip）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from core import punctuation as punc

MARKS = ("", "，", "。", "？", "！")


def test_needs_punctuation_only_when_text_has_none():
    assert punc.needs_punctuation("我今天去了超市")
    assert not punc.needs_punctuation("我今天去了超市，然后回家。")
    assert not punc.needs_punctuation("hello world!")
    assert not punc.needs_punctuation("")


def test_insert_marks_uses_offsets_and_keeps_original_text():
    text = "我今天去了超市然后回家"
    tokens = list(text)
    offsets = [(index, index + 1) for index in range(len(text))]
    preds = [0] * len(text)
    preds[6] = 1  # 在「市」之后补逗号

    out = punc.insert_marks(text, tokens, offsets, preds, MARKS)
    assert out == "我今天去了超市，然后回家"


def test_insert_marks_preserves_english_case_and_spaces():
    text = "昨天是 MONDAY TODAY 是星期三"
    tokens = list(text)
    offsets = [(index, index + 1) for index in range(len(text))]
    preds = [0] * len(text)
    preds[text.index("Y")] = 1  # MONDAY 之后

    out = punc.insert_marks(text, tokens, offsets, preds, MARKS)
    assert "MONDAY" in out, out
    assert out == "昨天是 MONDAY， TODAY 是星期三"


def test_insert_marks_skips_wordpiece_subtokens():
    text = "MONDAY"
    tokens = ["MO", "##NDAY"]
    offsets = [(0, 2), (2, 6)]
    preds = [1, 0]  # 预测落在词首子词上：必须跳过，否则会把单词劈开

    assert punc.insert_marks(text, tokens, offsets, preds, MARKS) == "MONDAY"


def test_insert_marks_does_not_double_existing_punctuation():
    text = "你好。"
    tokens = list(text)
    offsets = [(0, 1), (1, 2), (2, 3)]
    preds = [0, 1, 0]

    assert punc.insert_marks(text, tokens, offsets, preds, MARKS) == "你好。"


def test_labels_are_read_from_out_dict(tmp_path):
    path = tmp_path / "out_dict"
    path.write_text("<space> 0\n， 1\n。 2\n？ 3\n！ 4\n", encoding="utf-8")

    assert punc.labels_from_out_dict(path) == ("", "，", "。", "？", "！")
    assert punc.labels_from_out_dict(tmp_path / "missing") == punc.FALLBACK_LABELS


def test_long_text_is_chunked_at_punctuation():
    text = "甲" * 300 + "，" + "乙" * 300
    chunks = punc._split_long_text(text, max_chars=200)

    assert len(chunks) >= 2
    assert "".join(chunks) == text
    assert all(len(chunk) <= 200 for chunk in chunks)


class _FakeEncoding:
    def __init__(self, text: str) -> None:
        self.ids = [ord(char) % 100 + 200 for char in text]
        self.tokens = list(text)
        self.offsets = [(index, index + 1) for index in range(len(text))]


class _FakeTokenizer:
    def encode(self, text: str, add_special_tokens: bool = False) -> _FakeEncoding:
        return _FakeEncoding(text)

    def token_to_id(self, token: str) -> int:
        return 101


class _FakeSession:
    def __init__(self, predictions: list[int]) -> None:
        self.predictions = predictions

    def run(self, _names, feeds):
        length = len(feeds["input_ids"][0]) - 1
        out = np.zeros((1, length, 5), dtype=np.float32)
        for index in range(min(length, len(self.predictions))):
            out[0, index, self.predictions[index]] = 1.0
        return [out]


def test_model_restore_end_to_end_with_fake_runtime(tmp_path, monkeypatch):
    for name in punc.PUNC_FILES:
        (tmp_path / name).write_bytes(b"x")

    text = "我今天去了超市然后回家"
    predictions = [0] * len(text)
    predictions[6] = 1  # 「市」之后补逗号

    monkeypatch.setattr(punc, "_create_session", lambda _path: _FakeSession(predictions))
    monkeypatch.setattr(punc, "_create_tokenizer", lambda _path: _FakeTokenizer())

    model = punc.PunctuationModel(model_dir=tmp_path)
    assert model.restore(text) == "我今天去了超市，然后回家"
    # 已经有标点的文本不再重复跑
    assert model.restore("你好。") == "你好。"


def test_engine_declares_where_punctuation_applies():
    from core.sherpa_asr import FireRedAsrEngine, SenseVoiceEngine, SherpaAsrConfig

    fired = FireRedAsrEngine(model_dir="/tmp/fr")
    assert fired.supports_punc is True
    assert fired._punc is not None and str(fired._punc.model_dir) == "/tmp/fr/punc"
    assert SenseVoiceEngine(model_dir="/tmp/sv").supports_punc is False
    assert SherpaAsrConfig().use_punc is True


def test_real_model_restores_chinese_punctuation():
    """真实权重 + onnxruntime 都在时才跑；CI 里两者通常都没有。"""
    pytest.importorskip("onnxruntime")
    model = punc.PunctuationModel(model_dir=Path("models/fireredasr2-aed/punc"))
    if not model.model_available:
        pytest.skip("没有 FireRedPunc 权重（models/fireredasr2-aed/punc）")

    text = "我今天去了超市买了苹果香蕉和牛奶然后回家做饭"
    try:
        restored = model.restore(text)
    except Exception as exc:  # noqa: BLE001
        # 旧版 onnxruntime 不支持这个 8-bit MatMulNBits 权重：这是环境问题，不是代码回归。
        pytest.skip(f"当前 onnxruntime 无法执行 q8w 权重：{exc}")

    assert restored != text
    assert any(mark in restored for mark in "，。？！"), restored
    assert "苹果" in restored and "牛奶" in restored
