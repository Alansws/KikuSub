"""CTC 目标编码的索引契约（回归：标点导致字级时间整体错位）。"""

from __future__ import annotations

import pytest

pytest.importorskip("torch")

from core.qwen_ctc import FoldedText, encode_target  # noqa: E402


def test_positions_stay_aligned_with_ids_across_punctuation():
    folded = FoldedText("よう、久しぶり。お前は？")
    chars = "よう久しぶりお前は"
    lookup = {ch: i + 2 for i, ch in enumerate(chars)}
    ids, positions = encode_target(folded, lookup, 1)

    assert len(ids) == len(positions) == len(chars)
    # 每个 id 的位置必须指回该 id 对应的字，而不是被标点挤后一拍。
    assert [folded.folded[p] for p in positions] == list(chars)


def test_unknown_char_keeps_a_slot_but_no_position():
    folded = FoldedText("あ、漢")
    lookup = {"あ": 2}
    ids, positions = encode_target(folded, lookup, 1)

    assert len(ids) == len(positions) == 2
    assert positions[0] == folded.folded.index("あ")
    assert ids[1] == 1          # unk
    assert positions[1] is None  # 未知字交给 _fill_unaligned 插值
