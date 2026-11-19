"""单句 AI 判定：提示词只含文本、分语种、结果校验。"""

from __future__ import annotations

import pytest

from core import ai_arbitrate as arb


def test_ja_prompt_has_context_and_no_timecodes():
    system, user = arb.build_prompt(
        lang="ja",
        text_a="もっとぐちゅぐちゅになっちゃう",
        text_b="もっとぐもぐもになっちゃう",
        before=["はい、続けます", "もう少し"],
        after=["気持ちいい", "そう"],
    )
    assert "日语" in system
    assert "不要时间码" in system
    assert "もっとぐちゅぐちゅになっちゃう" in user
    assert "もっとぐもぐもになっちゃう" in user
    assert "はい、続けます" in user
    assert "00:" not in user
    assert "-->" not in user


def test_zh_prompt_does_not_use_japanese_grammar_rules():
    system, _ = arb.build_prompt(
        lang="zh", text_a="今天天气不错", text_b="今天天气不好", before=[], after=[]
    )
    assert "中文" in system
    assert "不要按日语语法" in system
    assert "助词" not in system


def test_context_keeps_nearest_three_and_drops_empty():
    before = ["前1", "前2", "前3", "前4", "前5"]
    after = ["后1", "", "后2", "后3", "后4"]
    _, user = arb.build_prompt(
        lang="ja", text_a="A", text_b="B", before=before, after=after
    )
    assert "前1" not in user and "前2" not in user
    assert "前3" in user and "前4" in user and "前5" in user
    assert "后1" in user and "后2" in user and "后3" in user
    assert "后4" not in user


def test_empty_side_is_explained_but_both_empty_is_allowed_to_prompt():
    _, user = arb.build_prompt(lang="ja", text_a="", text_b="B", before=[], after=[])
    assert "没有识别到内容" in user
    assert "B" in user


def test_parse_result_normalizes_text_and_truncates_note():
    out = arb.parse_result({"text": "  もっと\nぐちゅ  ", "note": "理由" * 100})
    assert out["text"] == "もっと ぐちゅ"
    assert len(out["note"]) <= arb.MAX_NOTE_CHARS


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"text": ""},
        {"text": "x" * (arb.MAX_TEXT_CHARS + 1)},
        {"text": "00:01.200 --> 00:02.400"},
        {"text": "もっと", "note": 123},
    ],
)
def test_parse_result_rejects_bad_output(data):
    if data == {"text": "もっと", "note": 123}:
        # note 不是字符串时按空理由处理，文本仍然有效
        assert arb.parse_result(data)["note"] == ""
        return
    with pytest.raises(arb.ArbitrationError):
        arb.parse_result(data)


def test_no_think_appends_qwen_switch():
    _, user = arb.build_prompt(
        lang="ja", text_a="A", text_b="B", before=[], after=[], no_think=True
    )
    assert user.endswith("/no_think")
