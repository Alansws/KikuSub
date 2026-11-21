"""双引擎复核的纯函数：时间重叠 + 相似度配对、逐字 diff、边界情况。"""

from __future__ import annotations

from core.dual_review import build_review, char_ops, text_similarity
from core.subtitles import SubtitleCue

C = SubtitleCue


def kinds(review: dict) -> list[str]:
    return [row["kind"] for row in review["rows"]]


def test_identical_lists_are_all_same():
    a = [C(0, 1, "おはよう"), C(1, 2, "今日は雨だ")]
    review = build_review(a, [C(0, 1, "おはよう"), C(1, 2, "今日は雨だ")])
    assert kinds(review) == ["same", "same"]
    assert review["stats"]["diff"] == 0
    assert review["stats"]["badge"] == 0


def test_text_difference_marks_diff_with_char_ops():
    review = build_review([C(0, 1, "今日は雨だ")], [C(0, 1, "今日は飴だ")])
    assert kinds(review) == ["diff"]
    assert review["stats"]["diff"] == 1
    ops = review["rows"][0]["char_ops"]
    assert [op["op"] for op in ops] == ["eq", "del", "ins", "eq"]
    assert any(op["text"] == "雨" for op in ops)
    assert any(op["text"] == "飴" for op in ops)


def test_one_sentence_split_into_two_keeps_the_extra_line_visible():
    """一句被对方拆成两句：只配一句，另一句必须是独立 + 行。"""
    review = build_review(
        [C(0, 4, "おはようございます、今日はいい天気ですね")],
        [C(0, 2, "おはようございます"), C(2, 4, "今日はいい天気ですね")],
    )
    assert len(review["rows"]) == 2
    assert [row["kind"] for row in review["rows"]] == ["diff", "only_b"]
    pair = review["rows"][0]
    assert pair["a_indices"] == [0] and len(pair["b_indices"]) == 1
    assert review["rows"][1]["b_indices"] == [1]
    assert review["stats"]["paired"] == 1
    assert review["stats"]["only_b"] == 1


def test_global_offset_still_pairs():
    review = build_review(
        [C(0.0, 1.0, "abc"), C(1.5, 2.5, "def")],
        [C(0.2, 1.2, "abc"), C(1.7, 2.7, "def")],
    )
    assert kinds(review) == ["same", "same"]


def test_only_a_and_only_b():
    review = build_review([C(0, 1, "A")], [])
    assert kinds(review) == ["only_a"]
    assert review["stats"]["only_a"] == 1
    assert review["stats"]["badge"] == 0

    review = build_review([], [C(0, 1, "B")])
    assert kinds(review) == ["only_b"]
    assert review["stats"]["only_b"] == 1

    review = build_review([], [])
    assert review["rows"] == []
    assert review["stats"]["total"] == 0


def test_missing_line_is_not_paired_with_neighbour():
    review = build_review(
        [C(0, 1, "一"), C(1, 2, "二"), C(2, 3, "三")],
        [C(0, 1, "一"), C(2, 3, "三")],
    )
    assert kinds(review) == ["same", "only_a", "same"]
    assert review["stats"]["only_a"] == 1


def test_stats_never_hide_extra_lines():
    """A/B 条数不同时，必须满足 A=配对+仅A、B=配对+仅B。"""
    a = [C(i * 2.0, i * 2.0 + 1.0, f"A{i}") for i in range(83)]
    b = []
    for i in range(89):
        text = f"A{i}" if i < 83 else f"B{i}"
        b.append(C(i * 1.8, i * 1.8 + 1.0, text))
    review = build_review(a, b, gap=0.1)
    stats = review["stats"]
    assert stats["a_count"] == stats["paired"] + stats["only_a"]
    assert stats["b_count"] == stats["paired"] + stats["only_b"]
    # 每条 row 最多一个 A / 一个 B，不再出现合并行
    assert all(len(row["a_indices"]) <= 1 and len(row["b_indices"]) <= 1 for row in review["rows"])


def test_badge_counts_diff_rows_only():
    review = build_review(
        [C(0, 1, "同じ"), C(1, 2, "違う"), C(2, 3, "だけA")],
        [C(0, 1, "同じ"), C(1, 2, "異なる"), C(3, 4, "だけB")],
    )
    stats = review["stats"]
    assert stats["diff"] == 1
    assert stats["only_a"] == 1
    assert stats["only_b"] == 1
    assert stats["badge"] == 1
    assert stats["a_count"] == stats["paired"] + stats["only_a"]
    assert stats["b_count"] == stats["paired"] + stats["only_b"]


def test_char_ops_for_insert_delete():
    ops = char_ops("abc", "axc")
    assert [op["op"] for op in ops] == ["eq", "del", "ins", "eq"]
    assert text_similarity("abc", "abc") == 1.0
    assert text_similarity("", "x") == 0.0


# ---------------------------------------------------------------------------
# ignore_punct（2026-11-21 界面重构 Step 2）
#
# 两个引擎的标点取舍不是听写分歧：默认把它们判为一致，只留真正「听不同」的行。
# 守护三个方向：默认滤掉、关掉还原、真差异（含数字里的 . ）绝不能被滤掉。
# ---------------------------------------------------------------------------


def test_ignore_punct_hides_punct_only_difference():
    """计划里那条：んんっ だーめ vs んんっ、だーめ 默认算一致。"""
    a = [C(0.0, 2.0, "んんっ だーめ")]
    b = [C(0.0, 2.0, "んんっ、だーめ")]

    review = build_review(a, b)
    assert kinds(review) == ["same"]
    stats = review["stats"]
    assert stats["diff"] == 0
    assert stats["badge"] == 0
    assert stats["same"] == 1
    assert stats["punct_only"] == 1
    # 行上留了标记，界面能解释「为什么它变成了 = 」
    assert review["rows"][0]["punct_only"] is True
    assert review["rows"][0]["a_text"] == "んんっ だーめ"  # 原始文本不被改写


def test_ignore_punct_off_restores_strict_compare():
    a = [C(0.0, 2.0, "んんっ だーめ")]
    b = [C(0.0, 2.0, "んんっ、だーめ")]

    review = build_review(a, b, ignore_punct=False)
    assert kinds(review) == ["diff"]
    stats = review["stats"]
    assert stats["diff"] == 1
    assert stats["badge"] == 1
    assert stats["punct_only"] == 0
    assert "punct_only" not in review["rows"][0]
    assert review["rows"][0]["char_ops"]


def test_ignore_punct_keeps_real_text_difference():
    """真听写差异（雨 / 飴）不能被过滤掉，哪怕两边标点也不同。"""
    review = build_review(
        [C(0, 1, "今日は雨だ。")],
        [C(0, 1, "今日は飴だ")],
    )
    assert kinds(review) == ["diff"]
    assert review["stats"]["diff"] == 1
    assert review["stats"]["punct_only"] == 0


def test_ignore_punct_does_not_strip_ascii_dots_in_numbers():
    """``.`` / ``,`` 故意不在忽略表里：1.5 与 15 是两个数，滤掉就成了藏错。"""
    review = build_review([C(0, 1, "残り 1.5 秒")], [C(0, 1, "残り 15 秒")])
    assert kinds(review) == ["diff"]
    assert review["stats"]["diff"] == 1


def test_ignore_punct_keeps_counts_invariant():
    """过滤只改 same/diff 的归属，不改配对：A=配对+仅A、B=配对+仅B 仍成立。"""
    a = [C(0, 1, "あ。"), C(1, 2, "い、"), C(2, 3, "う")]
    b = [C(0, 1, "あ"), C(1, 2, "い。"), C(2, 3, "ゔ")]
    review = build_review(a, b)
    stats = review["stats"]
    assert stats["a_count"] == stats["paired"] + stats["only_a"]
    assert stats["b_count"] == stats["paired"] + stats["only_b"]
    assert stats["punct_only"] == 2
    assert stats["diff"] == 1
