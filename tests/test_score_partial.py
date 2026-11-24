"""稀疏参考字幕评测的口径测试（纯函数，不加载模型）。

守的是「只在参考覆盖到的区间上比」这条口径本身——它和 `score_srt.py` 的
整片拼接是**两套数字**，混用会让同一份素材报出 15% 和 160% 两个 CER。
"""

from __future__ import annotations

import pytest

from tools.eval.score_partial import (
    coverage_spans,
    normalize,
    score_partial,
)
from tools.eval.score_srt import Cue


def _cue(start: float, end: float, text: str) -> Cue:
    return Cue(start=start, end=end, text=text)


def test_normalize_keeps_long_vowel_and_drops_punct():
    # 「ー」可能是词的一部分，不能当标点删掉（与 score_srt 同口径）。
    assert normalize("ちょっとー…") == "ちょっとー"
    assert normalize("ママ、ママー！") == "ママママー"
    # NFKC：全角数字压成半角。
    assert normalize("１２３") == "123"


def test_coverage_spans_merges_and_pads():
    refs = [_cue(10.0, 12.0, "あ"), _cue(12.5, 14.0, "い"), _cue(30.0, 31.0, "う")]
    spans = coverage_spans(refs, pad_s=0.6)
    # 前两条 ±0.6 后重叠，应并成一条；第三条独立。
    assert spans == [(9.4, 14.6), (29.4, 31.6)]


def test_text_outside_reference_windows_is_not_counted_as_insertion():
    """参考窗口外的合法字幕不算插入——这是本脚本存在的理由。"""
    refs = [_cue(10.0, 12.0, "こんにちは")]
    # 同样一句，外加一条远离参考窗口的字幕。
    hyp = [_cue(10.0, 12.0, "こんにちは"), _cue(100.0, 102.0, "余計な一言")]
    result = score_partial(refs, hyp)
    assert result["cer"] == pytest.approx(0.0, abs=1e-6)
    assert result["cues"] == 2  # 条数照报，只是不参与窗口内的文本比较


def test_cer_counts_errors_inside_window():
    refs = [_cue(10.0, 12.0, "こんにちは")]
    hyp = [_cue(10.0, 12.0, "こんばんは")]  # 2 字不同 / 5 字
    result = score_partial(refs, hyp)
    assert result["cer"] == pytest.approx(2 / 5, abs=1e-6)
    assert result["block_acc"] == pytest.approx(1 - 2 / 5, abs=1e-6)


def test_missed_block_needs_three_chars_and_low_accuracy():
    refs = [_cue(10.0, 12.0, "こんにちは")]  # 5 字，全错 → 漏块
    assert score_partial(refs, [])["missed"] == [10.0]
    # 两字参考即使全错也不算漏块（阈值 >=3 字）。
    short = [_cue(10.0, 12.0, "はい")]
    assert score_partial(short, [])["missed"] == []


def test_split_counts_boundary_inside_reference_cue():
    refs = [_cue(10.0, 14.0, "あ" * 10)]
    # 在参考 cue 内部 12.0 处断开 → 算一次劈词。
    hyp = [_cue(10.0, 12.0, "あ" * 5), _cue(12.0, 14.0, "あ" * 5)]
    assert score_partial(refs, hyp)["splits"] == 1
    # 边界贴在参考 cue 的首尾（在 0.15s 余量内）不算劈词。
    edge = [_cue(10.0, 10.1, "あ"), _cue(10.1, 14.0, "あ" * 9)]
    assert score_partial(refs, edge)["splits"] == 0


def test_long_cues_are_counted():
    refs = [_cue(0.0, 10.0, "あ")]
    hyp = [_cue(0.0, 4.5, "あ"), _cue(4.5, 10.0, "あ")]
    result = score_partial(refs, hyp)
    assert result["over42"] == 2
    assert result["max_cue"] == pytest.approx(5.5, abs=1e-6)


def test_method_tag_and_empty_reference():
    """结果带口径标签，防止和 score_srt.py 的数字混用。"""
    result = score_partial([], [])
    assert result["method"] == "partial-reference-v1"
    assert result["cer"] == 0.0
    assert result["covered_s"] == 0.0
