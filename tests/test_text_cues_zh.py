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


def test_soft_max_reaches_punctuation_just_past_the_limit():
    """标点只比字数上限晚 3 个字时，宁可这一条多 3 个字，也别把「特别」劈开。"""
    text = "在嘞个就是在情节里面就是感觉戏演得特别好，就是好像"
    chars = _chars(text, step=0.16)

    cues = split_cues(
        chars,
        seg_start=0.0,
        seg_end=0.16 * len(text),
        max_cue_chars=18,
    )

    assert cues
    assert "特别好，" in cues[0].text, [cue.text for cue in cues]
    assert len(cues[0].text) <= 18 + 6


def test_token_timestamps_are_relative_to_segment_start():
    """sherpa 的时间戳相对片段起点；忘了加 offset 会把整段字幕压到 0 秒。

    SenseVoice 默认参数 CER 69% 就是这条：全部字符被 clamp 到 seg_start，
    切出来的字幕互相重叠、被去重逻辑当成重复丢掉。
    """
    chars = build_timed_chars(["你", "好", "世", "界"], [0.0, 0.5, 1.0, 1.5], 10.0, 12.0)

    assert [round(char.start, 2) for char in chars] == [10.0, 10.5, 11.0, 11.5]
    assert chars[-1].end == 12.0


def test_subword_tokens_do_not_get_spaces():
    """token 自带前导空格才是词边界；``E``/``s``/``im`` 是同一个词。"""
    tokens = ["我", "用", "的", "是", "E", "s", "im", "卡"]
    starts = [0.1 * index for index in range(len(tokens))]
    chars = build_timed_chars(tokens, starts, 0.0, 1.3)

    assert "".join(char.ch for char in chars) == "我用的是Esim卡"


def test_soft_max_window_does_not_double_count_start():
    """``_extend_to_marks`` 的窗口是「limit + extra」，不能再加一遍 start。

    真实素材（FireRed 默认参数）里被这条 bug 拉出一条 39 字的字幕，
    同时越过 max_cue_chars 与 max_cue_dur 两条上限。
    """
    text = (
        "事情是这个样子啊大家都知道我有台 ESIM然后呢我用了挺长一段时间"
        "差不多一年的时间马上就要过保了今天应该是保修期的最后一天然后它"
        "也是国内第一台就是支持 ESIM的手机"
    )
    chars = spread_text(text, 0.0, 16.0)

    cues = split_cues(
        chars,
        seg_start=0.0,
        seg_end=16.0,
        max_cue_chars=18,
        max_cue_dur=4.3,
    )

    assert cues
    assert max(len(cue.text) for cue in cues) <= 18 + 6
    assert max(cue.end - cue.start for cue in cues) <= 4.3 * 1.6


def test_energy_spread_keeps_pauses_between_chars(monkeypatch):
    """FireRed 没有时间戳：按能量铺时间时，停顿必须出现在**两个字之间**。

    旧实现在跨停顿的那个字上把时长拉长，切点检测于是切在停顿的「下一个字之后」，
    正好劈开「办理」这种词。
    """
    import numpy as np

    from core.text_cues_zh import spread_text_voiced, voiced_spans

    rate = 16000
    tone = (0.3 * np.sin(2 * np.pi * 220 * np.arange(int(rate * 0.5)) / rate)).astype(np.float32)
    silence = np.zeros(int(rate * 0.3), dtype=np.float32)
    audio = np.concatenate([tone, silence, tone])

    spans = voiced_spans(audio, sample_rate=rate)
    assert len(spans) == 2, spans
    assert spans[0][0] == 0.0 and 0.45 < spans[0][1] < 0.55
    assert 0.75 < spans[1][0] < 0.85

    chars = spread_text_voiced("一二三四", 0.0, 1.3, spans)
    gaps = [round(chars[i + 1].start - chars[i].end, 3) for i in range(len(chars) - 1)]
    # 四个字跨两个有声区间：中间必须有一个非零空隙，其余为 0。
    assert sum(1 for gap in gaps if gap > 0.05) == 1, gaps
    assert chars[0].start >= 0.0 and chars[-1].end <= 1.31


def test_split_never_cuts_inside_a_word(monkeypatch):
    """切点落在 jieba 词的中间时，宁可挪到下一个词首。"""
    import core.text_cues_zh as module

    text = "然后就导致eSIM的办理其实并不是我们想象中那样方便"
    chars = _chars(text, step=0.12)
    # 伪造词边界：办理 / 其实 / 想象 都是词，切点不能落在它们的第二个字前面。
    fake_starts = {0}
    for token in ["然后", "就", "导致", "eSIM", "的", "办理", "其实", "并", "不是", "我们", "想象", "中", "那样", "方便"]:
        fake_starts.add(sum(len(t) for t in ["然后", "就", "导致", "eSIM", "的", "办理", "其实", "并", "不是", "我们", "想象", "中", "那样", "方便"][: len(fake_starts) and 0]))
    # 上面那行太绕：直接按顺序累加。
    fake_starts = {0}
    position = 0
    for token in ["然后", "就", "导致", "eSIM", "的", "办理", "其实", "并", "不是", "我们", "想象", "中", "那样", "方便"]:
        position += len(token)
        fake_starts.add(position)
    monkeypatch.setattr(module, "word_starts", lambda value: set(fake_starts))

    cues = module.split_cues(
        chars,
        seg_start=0.0,
        seg_end=0.12 * len(text),
        max_cue_chars=12,
        max_cue_dur=4.3,
    )

    cursor = 0
    for cue in cues[:-1]:
        cursor += len(cue.text)
        assert cursor in fake_starts or text[cursor - 1] in "，。！？", (cue.text, cursor)


def test_no_cut_between_single_letter_and_word():
    """FireRed 把 eSIM 切成 `E`/`SIM`；切在这两者之间会得到「国内的 E / SIM了」。"""
    text = "我要把这些什么E SIM卡的数据啊全部"
    chars = _chars(text, step=0.12)

    cues = split_cues(chars, seg_start=0.0, seg_end=0.12 * len(text), max_cue_chars=12)

    for cue in cues:
        assert not cue.text.endswith(" E"), [c.text for c in cues]
        assert not cue.text.startswith("SIM"), [c.text for c in cues]


def test_no_cue_starts_with_particle_or_ends_with_adverb():
    """虚词不当行首、副词不当行尾（真实素材：「…碰国内的 / 的eSIM了」）。"""
    from core.text_cues_zh import NO_LINE_END, NO_LINE_START

    text = "我想我以后应该再也不会碰国内的一信了然后就到了后面我们非常非常谨慎地处理"
    chars = _chars(text, step=0.12)

    cues = split_cues(chars, seg_start=0.0, seg_end=0.12 * len(text), max_cue_chars=12)

    assert cues
    for cue in cues:
        assert cue.text[0] not in NO_LINE_START, cue.text
        assert cue.text[-1] not in NO_LINE_END, cue.text
