"""纯函数回归测试：时间轴、SRT 解析、分句与 VAD 合并。

这些测试不加载任何模型，但需要 torch（transcribe.py 在模块级导入）。
在只有 pytest 的轻量 CI 环境里会整体 skip。
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from core.transcribe import (  # noqa: E402
    SubtitleCue,
    _is_blank,
    SubtitleCue,
    is_nonverbal_only,
    merge_fragmented_cues,
    strip_edge_nonverbal,
    apply_cue_padding,
    cues_to_srt,
    cues_to_vtt,
    forbidden_cut_positions,
    format_srt_timestamp,
    format_vtt_timestamp,
    hallucination_risk,
    hallucination_risk_reason,
    merge_vad_segments,
    nearest_text_cut,
    parse_time_str,
    srt_to_cues,
    split_text_into_cues,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "00:00:00,000"),
        (0.9996, "00:00:01,000"),
        (59.9996, "00:01:00,000"),      # 旧实现会输出 00:00:60,000
        (3599.9996, "01:00:00,000"),    # 旧实现会输出 00:59:60,000
        (60.0, "00:01:00,000"),
    ],
)
def test_format_srt_timestamp_rollover(value, expected):
    assert format_srt_timestamp(value) == expected


def test_format_timestamp_negative_is_clamped():
    assert format_srt_timestamp(-1.0) == "00:00:00,000"


def test_parse_time_str_variants():
    assert parse_time_str("00:01:02,500") == pytest.approx(62.5)
    assert parse_time_str("01:02") == pytest.approx(62.0)
    assert parse_time_str("62.5") == pytest.approx(62.5)
    assert parse_time_str("") is None
    assert parse_time_str("abc") is None


def test_srt_roundtrip_preserves_multiline_text():
    cues = [
        SubtitleCue(1.0, 2.5, "こんにちは\n你好"),
        SubtitleCue(2.5, 4.0, "世界"),
    ]
    parsed = srt_to_cues(cues_to_srt(cues))
    assert len(parsed) == 2
    assert parsed[0].text == "こんにちは\n你好"
    assert parsed[0].start == pytest.approx(1.0)
    assert parsed[1].end == pytest.approx(4.0)


def test_srt_parser_handles_bom_crlf_and_index_lines():
    raw = (
        "\ufeff1\r\n00:00:01,000 --> 00:00:02,000\r\nこんにちは\r\n\r\n"
        "2\r\n00:00:02,000 --> 00:00:03,000\r\n123 番線\r\n"
    )
    cues = srt_to_cues(raw)
    assert [c.text for c in cues] == ["こんにちは", "123 番線"]


def test_vtt_timestamp_uses_dot():
    assert format_vtt_timestamp(1.5) == "00:00:01.500"
    assert cues_to_vtt([SubtitleCue(0.0, 1.0, "x")]).startswith("WEBVTT")


@pytest.mark.parametrize(
    "text",
    [
        "子供の頃、空はもっと、ずっと近かった",
        "こういうことを、2ヶ月前高校に入るまで俺は知らなかった",
        "「ちょっと待って！」と彼女は言った。",
        "今日はとても良い天気ですね。明日は雨が降るでしょう。",
    ],
)
def test_split_text_into_cues_is_lossless_and_non_overlapping(text):
    cues = split_text_into_cues(
        text, 0.0, 12.0, max_cue_dur=4.3, max_cue_chars=21
    )
    assert cues
    assert "".join(c.text for c in cues) == text
    previous_end = -1.0
    for cue in cues:
        assert cue.end > cue.start
        assert cue.start >= previous_end
        assert len(cue.text) <= 21
        previous_end = cue.end


def test_apply_cue_padding_keeps_order_and_bounds():
    cues = [SubtitleCue(1.0, 1.05, "a"), SubtitleCue(1.05, 2.0, "b")]
    padded = apply_cue_padding(cues, 0.2, 3.0)
    assert padded[0].start >= 0.0
    assert padded[0].end <= padded[1].start
    assert padded[-1].end <= 3.0


def test_forbidden_cut_positions_protects_small_kana_and_words():
    blocked = forbidden_cut_positions("ちょっと待って")
    # 「ち|ょ」「っ|と」以及「ちょっと」内部都禁止下刀
    assert blocked[1] == 1
    assert blocked[2] == 1
    text = "ちょっと"
    assert forbidden_cut_positions(text)[2] == 1


def test_nearest_text_cut_never_picks_forbidden_position():
    text = "ちょっと待ってください"
    blocked = forbidden_cut_positions(text)
    for target in range(2, len(text) - 1):
        cut = nearest_text_cut(text, target)
        if cut:
            assert not blocked[cut]


def test_hallucination_risk_flags_repetition_and_short_cues():
    assert hallucination_risk("じゅるっ、じゅるっ、じゅるっ、じゅるっ、じゅるっ、じゅるっ", 1.0, None)
    assert hallucination_risk("はい", 0.5, None)
    assert not hallucination_risk("こんにちは", 2.0, None)
    assert not hallucination_risk("", 1.0, None)


def test_hallucination_risk_reason_names_the_triggered_rule():
    # 复读优先于“短段”：同一段里两条判据都成立时报更具体的复读
    assert hallucination_risk_reason("じゅるっ、じゅるっ、じゅるっ、じゅるっ、じゅるっ、じゅるっ", 1.0) == "repeat"
    assert hallucination_risk_reason("はい", 0.5) == "short"
    assert hallucination_risk_reason("…信じる", 8.0) == "low-density"
    assert hallucination_risk_reason("こんにちは", 2.0) == ""
    assert hallucination_risk_reason("", 1.0) == ""


def test_hallucination_short_rule_does_not_kill_normal_one_second_lines():
    # 「いいよー」这种 1.0s 的正常短句曾被时间戳复核判空、整条丢掉。
    assert hallucination_risk_reason("いいよー", 1.0) == ""
    assert hallucination_risk_reason("いいよー", 0.7) == "short"


def test_strip_edge_nonverbal_removes_laughter_only_at_the_edges():
    assert strip_edge_nonverbal("んふふ、好きなだけ見て") == "好きなだけ見て"
    assert strip_edge_nonverbal("…ふふ、かわいい") == "かわいい"
    assert strip_edge_nonverbal("ねぇ…ふふ") == "ねぇ…"
    # 句中不动：它是这一句的一部分，删掉会让上下文断裂
    assert (
        strip_edge_nonverbal("ほら、いいよ。ふふ、おちんちん触りたいんでしょ?")
        == "ほら、いいよ。ふふ、おちんちん触りたいんでしょ?"
    )
    # 「あー…」可能是台词本身（人工整理版里保留了），不当发声删
    assert strip_edge_nonverbal("あー…すっごい…えへへ") == "あー…すっごい…"
    assert strip_edge_nonverbal("") == ""


class _FakeVad:
    """按帧号返回固定概率曲线，用来测边界收口逻辑（不加载模型）。"""

    def __init__(self, probs):
        self.probs = probs
        self.i = 0

    def __call__(self, chunk, sampling_rate):
        value = self.probs[min(self.i, len(self.probs) - 1)]
        self.i += 1
        return value


def test_refine_bounds_uses_the_pause_between_laughter_and_speech():
    import numpy as np

    from core.transcribe import _refine_bounds_by_pauses

    # 4s：1s 笑声 + 1s 停顿 + 2s 台词（512/16000 = 32ms 一帧，共 125 帧）
    probs = [0.9] * 31 + [0.01] * 31 + [0.9] * 63
    head, tail = _refine_bounds_by_pauses(
        np.zeros(16000 * 4, dtype=np.float32), _FakeVad(probs), head_removed=True, tail_removed=False
    )
    assert 1.9 <= head <= 2.1, head
    assert tail == 4.0

    # 句尾喘气：3s 台词 + 1s 低概率
    probs = [0.9] * 94 + [0.01] * 31
    head, tail = _refine_bounds_by_pauses(
        np.zeros(16000 * 4, dtype=np.float32), _FakeVad(probs), head_removed=False, tail_removed=True
    )
    assert head == 0.0
    assert 2.9 <= tail <= 3.1, tail

    # 段内没有可信停顿时不改边界（宁可字幕长一点，也不猜着切）
    probs = [0.9] * 125
    assert _refine_bounds_by_pauses(
        np.zeros(16000 * 4, dtype=np.float32), _FakeVad(probs), head_removed=True, tail_removed=True
    ) == (0.0, 4.0)


def test_merge_fragmented_cues_joins_half_sentences_only():
    cues = [
        SubtitleCue(0.0, 2.0, "いつも見たそうに"),
        SubtitleCue(2.0, 3.5, "してたもんねー"),
        SubtitleCue(3.55, 5.0, "出ちゃうね…"),
        SubtitleCue(5.0, 6.0, "出ちゃう出ちゃう…"),
    ]
    merged = merge_fragmented_cues(cues)
    assert [c.text for c in merged] == [
        "いつも見たそうにしてたもんねー",
        "出ちゃうね…",
        "出ちゃう出ちゃう…",
    ]
    # 间隔明显属于两句时不并
    gap_cues = [SubtitleCue(0.0, 1.0, "いいよ"), SubtitleCue(1.5, 2.5, "見せて")]
    assert len(merge_fragmented_cues(gap_cues)) == 2
    # 合并后超字数上限也不并
    long_cues = [SubtitleCue(0.0, 1.0, "あ" * 19), SubtitleCue(1.0, 2.0, "い" * 5)]
    assert len(merge_fragmented_cues(long_cues, max_cue_chars=20)) == 2


def test_is_nonverbal_only_drops_fragments_but_keeps_words():
    assert is_nonverbal_only("っ")
    assert is_nonverbal_only("ー")
    assert is_nonverbal_only("ふふっ")
    assert is_nonverbal_only("えへへ…")
    assert is_nonverbal_only("…")
    assert not is_nonverbal_only("はい")
    assert not is_nonverbal_only("ねぇ…")
    assert not is_nonverbal_only("かわいい")
    # 单个假名是正常台词（「え？」「ん…」），不能当碎片丢掉
    assert not is_nonverbal_only("え")
    assert not is_nonverbal_only("へ")
    assert not is_nonverbal_only("ん")
    # 一个假名却占了 2 秒以上：那是把呼吸判成了语音，不是台词
    assert is_nonverbal_only("え", 3.0)
    assert not is_nonverbal_only("え", 0.8)


def test_blank_text_detection_matches_placeholder_outputs():
    assert _is_blank("")
    assert _is_blank("…")
    assert _is_blank("。。。")
    assert not _is_blank("あ")


def test_merge_vad_segments_merges_short_gap():
    stamps = [
        {"start": 0, "end": 1000},
        {"start": 1200, "end": 2500},
    ]
    merged = merge_vad_segments(
        stamps, sample_rate=1000, max_segment_s=3.0, merge_gap_s=0.5, min_speech_s=0.0
    )
    assert merged == [(0, 2500)]


def test_merge_vad_segments_force_splits_long_block():
    stamps = [{"start": 0, "end": 5000}]
    merged = merge_vad_segments(
        stamps, sample_rate=1000, max_segment_s=2.0, merge_gap_s=0.5, min_speech_s=0.0
    )
    assert merged == [(0, 2000), (2000, 4000), (4000, 5000)]


def test_merge_vad_segments_empty_input_stays_empty():
    # 空 VAD 结果不得被上层兜底成「整段音频」，否则静音/音乐会被送进 ASR。
    assert merge_vad_segments([], sample_rate=16000) == []
