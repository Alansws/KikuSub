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


def test_hint_only_blind_mode_explains_asr_miss():
    system, user = arb.build_prompt(
        lang="ja", text_a="", text_b="", hint="斯国一 / sugoi", before=[], after=[]
    )
    assert "没有识别到内容" in user
    assert "斯国一" in user and "sugoi" in user
    assert "听音线索" in user
    assert "听音线索" in system
    assert "两个 ASR 引擎都没有识别到内容" in system


def test_single_version_prompt_marks_empty_side():
    system, user = arb.build_prompt(
        lang="ja", text_a="", text_b="すごい", before=[], after=[]
    )
    assert "识别结果（B 版）" in user
    assert "另一个引擎没有识别到内容" in user or "这个引擎没有识别到内容" in user
    assert "只有一个 ASR 引擎识别出了文本" in system


def test_history_keeps_recent_six_rounds_and_drops_oldest():
    history = []
    for i in range(1, 9):
        history.append({"role": "user", "text": f"追问{i}"})
        history.append({"role": "assistant", "text": f"答复{i}"})
    _, user = arb.build_prompt(
        lang="ja", text_a="A", text_b="B", history=history, before=[], after=[]
    )
    for i in range(1, 3):
        assert f"追问{i}" not in user
        assert f"答复{i}" not in user
    for i in range(3, 9):
        assert f"追问{i}" in user
        assert f"答复{i}" in user


def test_history_skips_bad_roles_and_keeps_a_leading_assistant():
    history = [
        {"role": "assistant", "text": "先に AI が話す"},
        {"role": "system", "text": "系统提示"},
        {"role": "user", "text": "用户线索"},
        {"role": "assistant", "text": "AI 回答"},
    ]
    _, user = arb.build_prompt(
        lang="ja", text_a="A", text_b="B", history=history, before=[], after=[]
    )
    # 首轮判定可能没有用户线索，那条 AI 结论仍是后续追问的上下文。
    assert "先に AI が話す" in user
    assert "系统提示" not in user
    assert "用户线索" in user and "AI 回答" in user


def test_latest_hint_comes_after_history():
    _, user = arb.build_prompt(
        lang="ja",
        text_a="A",
        text_b="B",
        hint="最新的线索",
        history=[
            {"role": "user", "text": "旧线索"},
            {"role": "assistant", "text": "旧回答"},
        ],
    )
    assert user.index("旧回答") < user.index("最新的线索")


def test_prompt_stays_within_local_2048_budget():
    """最坏材料组合也不能超过给 2048 context 留的字符预算。"""
    history = []
    for i in range(12):
        history.append({"role": "user", "text": "听" * 400})
        history.append({"role": "assistant", "text": "答" * 400})
    system, user = arb.build_prompt(
        lang="ja",
        text_a="あ" * 500,
        text_b="い" * 500,
        hint="う" * 500,
        before=["前" * 300 for _ in range(5)],
        after=["後" * 300 for _ in range(5)],
        history=history,
    )
    assert len(user) <= arb.MAX_USER_CHARS
    assert len(system) + len(user) <= 1900


def test_hint_is_capped_in_prompt():
    _, user = arb.build_prompt(
        lang="ja", text_a="A", text_b="B", hint="あ" * 800, before=[], after=[]
    )
    assert "あ" * (arb.MAX_HINT_CHARS + 1) not in user
    assert "あ" * arb.MAX_HINT_CHARS in user
