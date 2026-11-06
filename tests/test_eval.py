"""评测台纯函数测试（无第三方依赖，CI 直接跑）。"""

from __future__ import annotations

from tools.eval.score_srt import (
    Cue,
    edit_ops,
    filter_language,
    filter_time,
    levenshtein,
    normalize_text,
    parse_srt,
    parse_time_token,
    score,
)


def _srt(*cues: tuple[str, str, str]) -> str:
    blocks = []
    for index, (start, end, text) in enumerate(cues, start=1):
        blocks.append(f"{index}\n{start} --> {end}\n{text}")
    return "\n\n".join(blocks) + "\n"


def test_parse_time_token_variants():
    assert parse_time_token("00:00:38,570") == 38.57
    assert parse_time_token("01:02") == 62.0
    assert parse_time_token("83.456") == 83.456


def test_parse_srt_handles_bom_and_multiline():
    raw = "\ufeff1\r\n00:00:01,000 --> 00:00:02,000\r\n日文\n中文\r\n"
    cues = parse_srt(raw)
    assert len(cues) == 1
    assert cues[0].text == "日文\n中文"
    assert cues[0].start == 1.0


def test_normalize_removes_punctuation_and_space():
    assert normalize_text("こういうことを、 2ヶ月前") == "こういうことを2ヶ月前"


def test_japanese_filter_removes_chinese_only_lines():
    cues = [
        Cue(1, 2, "こういうことを"),
        Cue(1, 2, "直到两个月前"),
        Cue(3, 4, "本字幕由诸神字幕组制作"),
    ]
    assert [c.text for c in filter_language(cues, "ja")] == ["こういうことを"]


def test_time_filter_keeps_overlapping_cues():
    cues = [Cue(0, 1, "a"), Cue(5, 6, "b"), Cue(10, 11, "c")]
    assert [c.text for c in filter_time(cues, 5.5, 10.5)] == ["b", "c"]


def test_levenshtein_and_ops():
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "abc") == 3
    subs, dels, ins = edit_ops("abc", "axc")
    assert (subs, dels, ins) == (1, 0, 0)


def test_exact_match_scores_zero_cer():
    ref = parse_srt(_srt(("00:00:01,000", "00:00:02,000", "こんにちは")))
    result = score(ref, ref)
    assert result["cer"] == 0.0
    assert result["block_accuracy"] == 1.0
    assert result["missed_blocks"] == 0


def test_substitution_increases_cer():
    ref = parse_srt(_srt(("00:00:01,000", "00:00:02,000", "こんにちは")))
    hyp = parse_srt(_srt(("00:00:01,000", "00:00:02,000", "こんにちわ")))
    result = score(ref, hyp)
    assert result["cer"] > 0
    assert result["block_accuracy"] < 1.0


def test_particle_start_is_counted():
    ref = parse_srt(_srt(("00:00:01,000", "00:00:03,000", "空はもっと")))
    hyp = parse_srt(
        _srt(
            ("00:00:01,000", "00:00:02,000", "空"),
            ("00:00:02,000", "00:00:03,000", "はもっと"),
        )
    )
    result = score(ref, hyp)
    assert result["particle_start_cues"] == 1


def test_json_serializable_result():
    import json

    ref = parse_srt(_srt(("00:00:01,000", "00:00:02,000", "あ")))
    result = score(ref, ref)
    assert json.loads(json.dumps(result, ensure_ascii=False))["cer"] == 0.0
