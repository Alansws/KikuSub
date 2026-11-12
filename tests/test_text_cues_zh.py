"""中文分句的纯逻辑测试（无 torch / 无模型）。

这里断言的是三条产品约束，不是实现细节：
1. 句末标点是首选切点，一条字幕不会跨越两句；
2. 没有标点（FireRed 原始输出）时按停顿与字数切，且不劈开英文单词；
3. 每条字幕都有可读时长，时间轴单调不重叠。
"""

from __future__ import annotations

from core.text_cues_zh import (
    build_timed_chars,
    split_cues,
    spread_text,
)


def _chars(text: str, step: float = 0.25, start: float = 0.0):
    """按固定节拍造一串中文字符时间戳，模拟模型输出。"""
    tokens = list(text)
    starts = [start + step * index for index in range(len(tokens))]
    return build_timed_chars(tokens, starts, start, start + step * len(tokens))


def test_strong_punctuation_is_preferred_cut():
    text = "今天天气不错。我们出去走走吧。"
    cues = split_cues(_chars(text), seg_start=0.0, seg_end=6.0)

    assert [cue.text for cue in cues] == ["今天天气不错。", "我们出去走走吧。"]
    assert cues[0].end <= cues[1].start + 0.001


def test_comma_breaks_overlong_sentence():
    text = "这个方案呢，我觉得可以先做一个原型试试看再说"
    cues = split_cues(
        _chars(text),
        seg_start=0.0,
        seg_end=8.0,
        max_cue_chars=12,
    )

    assert cues, "应当切出字幕"
    assert all(len(cue.text) <= 12 for cue in cues), [cue.text for cue in cues]
    assert cues[0].text.endswith("，"), cues[0].text


def test_no_punctuation_uses_pauses_and_char_limit():
    # FireRedASR2 的输出通常没有标点，只能靠停顿与字数切。
    tokens = ["这", "是", "第", "一", "种", "第", "二", "种", "叫", "呃", "我", "们"]
    starts = [0.0, 0.3, 0.6, 0.9, 1.2, 1.5, 1.8, 2.1, 2.4, 3.3, 3.6, 3.9]
    chars = build_timed_chars(tokens, starts, 0.0, 4.2)

    cues = split_cues(chars, seg_start=0.0, seg_end=4.2, max_cue_chars=10)

    assert len(cues) >= 2
    assert all(len(cue.text) <= 10 for cue in cues)
    # 3.3s 处有明显停顿（「叫」占了 0.9s），切点应落在停顿之后
    assert cues[0].text == "这是第一种第二种叫", [c.text for c in cues]
    assert cues[1].text.startswith("呃")


def test_english_words_are_not_split():
    tokens = [" the", " tribal", " chief", "tain", " called", " for", " the", " boy"]
    starts = [0.0, 0.4, 0.8, 1.2, 1.6, 2.0, 2.4, 2.8]
    chars = build_timed_chars(tokens, starts, 0.0, 3.2)

    cues = split_cues(chars, seg_start=0.0, seg_end=3.2, max_cue_chars=8)

    joined = " ".join(cue.text for cue in cues)
    assert "the tribal" in joined
    for cue in cues:
        assert "trib al" not in cue.text
        assert not cue.text.startswith(" ") and not cue.text.endswith(" ")


def test_mixed_chinese_english_keeps_spaces():
    tokens = ["开", "饭", "时间", " ", "AM", " 九", "点"]
    starts = [0.0, 0.3, 0.6, 1.0, 1.1, 1.5, 1.8]
    chars = build_timed_chars(tokens, starts, 0.0, 2.2)
    text = "".join(char.ch for char in chars)

    assert text == "开饭时间 AM 九点", text


def test_cues_are_monotonic_and_readable():
    cues = split_cues(_chars("没有标点的一长串语音内容需要被切成多条字幕才行"), seg_start=0.0, seg_end=10.0)

    assert cues
    previous = 0.0
    for cue in cues:
        assert cue.start >= previous - 0.001, (cue, previous)
        assert cue.end - cue.start >= 0.25, cue
        previous = cue.end


def test_empty_inputs():
    assert build_timed_chars([], [], 0.0, 1.0) == []
    assert split_cues([], seg_start=0.0, seg_end=1.0) == []
    assert spread_text("   ", 0.0, 1.0) == []


def test_spread_text_fills_segment():
    chars = spread_text("你好世界", 2.0, 4.0)

    assert "".join(char.ch for char in chars) == "你好世界"
    assert chars[0].start == 2.0
    assert abs(chars[-1].end - 4.0) < 1e-6


def test_no_cue_starts_with_punctuation():
    """标点必须跟着上一句：产出一条只有「。」的字幕是明显的事故。"""
    text = "开放时间早上9点至下午5点。"
    chars = _chars(text, step=0.36)
    cues = split_cues(chars, seg_start=0.0, seg_end=6.0, max_cue_dur=4.3)

    assert cues, "应当切出字幕"
    for cue in cues:
        assert not cue.text.startswith(("。", "，", "、", "！", "？")), [c.text for c in cues]
    assert "".join(cue.text for cue in cues) == text
