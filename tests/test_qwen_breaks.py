"""Qwen 断句词边界（P1-1）的纯函数测试。"""

from __future__ import annotations

import pytest

pytest.importorskip("torch")

from qwen_ctc import (  # noqa: E402
    BREAK_FORBIDDEN,
    BREAK_PARTICLE,
    FoldedText,
    _break_costs,
)


def _costs(text: str) -> list[float]:
    folded = FoldedText(text)
    return _break_costs(folded, list(range(len(folded.folded))))


def test_break_before_particle_is_forbidden():
    costs = _costs("空はもっと")
    assert costs[1] == BREAK_FORBIDDEN          # 空|は
    assert costs[2] == BREAK_PARTICLE           # 空は|もっと（「もっと」是词）


def test_break_before_copula_particle_is_forbidden():
    costs = _costs("好きで")
    assert costs[2] == BREAK_FORBIDDEN          # 好き|で


def test_break_before_auxiliary_is_forbidden():
    assert _costs("くれる")[2] == BREAK_FORBIDDEN       # くれ|る
    assert _costs("来る")[1] == BREAK_FORBIDDEN         # 来|る


def test_break_before_object_particle_is_forbidden():
    costs = _costs("匂いを")
    assert costs[2] == BREAK_FORBIDDEN          # 匂い|を


def test_punctuation_bonus_lands_after_aligned_punctuation():
    costs = _costs("子供の頃、空は")
    assert costs[5] == 0.0                      # 「、」之后
    assert costs[6] == BREAK_FORBIDDEN          # 空|は


def test_comma_stays_free_even_with_particle_words():
    costs = _costs("雨は好きで、")
    assert costs[4] == BREAK_FORBIDDEN          # 好き|で
    assert costs[6] == 0.0                      # 「、」之后
