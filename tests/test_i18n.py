"""双语/译文导出与过期判定（开发文档 §6.3 / §6.4）。"""

from __future__ import annotations

from core.i18n import bilingual_cues, bilingual_entries, stale_indices, target_cues
from core.subtitles import SubtitleCue, srt_to_cues, split_multiline_cues

CUES = [
    SubtitleCue(0.0, 1.0, "おはよう"),
    SubtitleCue(1.0, 2.0, "今日は雨だ"),
    SubtitleCue(2.0, 3.0, "またね"),
]
TEXTS = ["早上好", "今天下雨", "再见"]


def test_bilingual_puts_source_first_then_target():
    out = bilingual_cues(CUES, TEXTS)
    assert [c.text for c in out] == ["おはよう\n早上好", "今日は雨だ\n今天下雨", "またね\n再见"]
    assert [(c.start, c.end) for c in out] == [(c.start, c.end) for c in CUES]


def test_bilingual_degrades_to_single_line_when_missing():
    out = bilingual_cues(CUES, ["早上好", "", "再见"])
    assert out[1].text == "今日は雨だ"


def test_bilingual_survives_short_texts():
    out = bilingual_cues(CUES, ["只有一条"])
    assert out[0].text == "おはよう\n只有一条"
    assert out[2].text == "またね"


# --------------------------------------------------- 交付文件：每语种一条 cue


def test_bilingual_entries_puts_each_language_on_its_own_cue():
    out = bilingual_entries(CUES, TEXTS)
    # 三条原文 → 六条交付 cue，原文在前、译文在后，时间轴完全相同
    assert [c.text for c in out] == [
        "おはよう",
        "早上好",
        "今日は雨だ",
        "今天下雨",
        "またね",
        "再见",
    ]
    assert [(c.start, c.end) for c in out] == [
        (0.0, 1.0),
        (0.0, 1.0),
        (1.0, 2.0),
        (1.0, 2.0),
        (2.0, 3.0),
        (2.0, 3.0),
    ]


def test_bilingual_entries_skips_missing_target_without_blank_line():
    out = bilingual_entries(CUES, ["早上好", "", "再见"])
    assert [c.text for c in out] == ["おはよう", "早上好", "今日は雨だ", "またね", "再见"]


def test_bilingual_entries_survive_short_texts():
    out = bilingual_entries(CUES, ["只有一条"])
    assert [c.text for c in out] == ["おはよう", "只有一条", "今日は雨だ", "またね"]


def test_bilingual_entries_roundtrip_keeps_one_line_per_cue():
    """导出 → 写 SRT → 读回：每条单行、时间轴不变（重新导入核对台的前提）。"""
    from core.subtitles import cues_to_srt

    text = cues_to_srt(bilingual_entries(CUES, TEXTS))
    parsed = srt_to_cues(text)
    assert len(parsed) == 6
    assert all("\n" not in cue.text for cue in parsed)
    assert [cue.text for cue in parsed] == ["おはよう", "早上好", "今日は雨だ", "今天下雨", "またね", "再见"]


def test_split_multiline_cues_explodes_legacy_bilingual_cues():
    legacy = [SubtitleCue(0.0, 1.0, "おはよう\n早上好"), SubtitleCue(1.0, 2.0, "またね")]
    out, exploded = split_multiline_cues(legacy)
    assert exploded == 1
    assert [c.text for c in out] == ["おはよう", "早上好", "またね"]
    assert [(c.start, c.end) for c in out] == [(0.0, 1.0), (0.0, 1.0), (1.0, 2.0)]


def test_target_skips_blank_and_counts_them():
    out, skipped = target_cues(CUES, ["早上好", "  ", "再见"])
    assert [c.text for c in out] == ["早上好", "再见"]
    assert skipped == 1
    assert [(c.start, c.end) for c in out] == [(0.0, 1.0), (2.0, 3.0)]


def test_target_keeps_timeline_of_survivors():
    out, _ = target_cues(CUES, TEXTS)
    assert [c.start for c in out] == [0.0, 1.0, 2.0]


# --------------------------------------------------------------------------- 过期


def test_stale_is_empty_when_source_unchanged():
    assert stale_indices(CUES, [c.text for c in CUES]) == []


def test_stale_flags_changed_text_only():
    base = ["おはよう", "今日は雪だ", "またね"]
    assert stale_indices(CUES, base) == [1]


def test_stale_flags_missing_base_entries():
    assert stale_indices(CUES, ["おはよう"]) == [1, 2]


def test_deletion_shifts_everything_after_it_to_stale():
    """删一条会让后面的译文整体错位——必须如实标出来，而不是继续装作对得上。"""
    base = [c.text for c in CUES]
    remaining = [CUES[0], CUES[2]]
    assert stale_indices(remaining, base) == [1]


# --------------------------------------------------- 只动句读的原文改动（2026-11-25）


def test_punctuation_signature_drops_only_noise():
    from core.i18n import is_punctuation_only_change, punctuation_signature

    # 清理标点会删 / 换的字符与空白都不算语义
    assert punctuation_signature("…こんにちは、") == "こんにちは"
    assert punctuation_signature("じゃあ　もう") == "じゃあもう"
    assert is_punctuation_only_change("…こんにちは", "こんにちは")
    assert is_punctuation_only_change("じゃあ、もう", "じゃあ　もう")
    assert is_punctuation_only_change("吸って…。", "吸って")
    # 加字 / 改字 / 去掉问号都算原文真的改了
    assert not is_punctuation_only_change("今日は雨", "今日は雪")
    assert not is_punctuation_only_change("行く？", "行く")
    assert not is_punctuation_only_change("ああ", "ああも")


def test_rebase_punctuation_base_only_touches_noise():
    from core.i18n import rebase_punctuation_base

    cues = [
        SubtitleCue(0.0, 1.0, "こんにちは"),
        SubtitleCue(1.0, 2.0, "今日は雪だ"),
        SubtitleCue(2.0, 3.0, "またね"),
    ]
    base = ["…こんにちは", "今日は雨だ", "またね"]
    out, rebased = rebase_punctuation_base(cues, base)
    assert rebased == [0]
    assert out == ["こんにちは", "今日は雨だ", "またね"]


def test_rebase_punctuation_base_survives_short_base():
    from core.i18n import rebase_punctuation_base

    out, rebased = rebase_punctuation_base(CUES, ["…おはよう"])
    assert rebased == [0]
    assert out == ["おはよう"]


# ------------------------------------------------- 局部转写后的译文轨映射（2026-11-25）


def test_remap_track_keeps_exact_matches_and_blanks_new_cue():
    from core.i18n import remap_track

    old = [
        SubtitleCue(0.0, 1.0, "おはよう"),
        SubtitleCue(2.0, 3.0, "またね"),
    ]
    new = [
        SubtitleCue(0.0, 1.0, "おはよう"),
        SubtitleCue(1.1, 1.9, "射精管理"),  # 局部转写新加的一句
        SubtitleCue(2.0, 3.0, "またね"),
    ]
    texts, base, stats = remap_track(old, new, ["早上好", "再见"], ["おはよう", "またね"])
    # 新句留空 → 待译；前后两条原样对齐，后面的译文没有整体前移
    assert texts == ["早上好", "", "再见"]
    assert base == ["おはよう", "射精管理", "またね"]
    assert stats == {"kept": 2, "moved": 0, "blank": 1, "dropped": 0}


def test_remap_track_moves_rewritten_text_and_keeps_base_as_stale():
    from core.i18n import remap_track

    old = [SubtitleCue(0.0, 2.0, "わかってる")]
    new = [SubtitleCue(0.0, 2.0, "わかってる？")]  # 只差句读：不能丢译文
    texts, base, stats = remap_track(old, new, ["你明白吗"], ["わかってる"])
    assert texts == ["你明白吗"]
    # base 保留旧快照（原文真的改过时界面要如实提示）；句读差异由 rebase 处理
    assert base == ["わかってる"]
    assert stats["moved"] == 1


def test_remap_track_does_not_give_a_translation_to_a_different_line():
    from core.i18n import remap_track

    # 时间完全不重叠：宁可留空，也不要把上一句的译文塞给新句
    old = [SubtitleCue(0.0, 1.0, "おはよう")]
    new = [SubtitleCue(50.0, 51.0, "こんばんは")]
    texts, _base, stats = remap_track(old, new, ["早上好"], ["おはよう"])
    assert texts == [""]
    assert stats == {"kept": 0, "moved": 0, "blank": 1, "dropped": 1}


def test_remap_track_survives_short_or_missing_arrays():
    from core.i18n import remap_track

    old = [SubtitleCue(0.0, 1.0, "A"), SubtitleCue(1.0, 2.0, "B")]
    new = [SubtitleCue(0.0, 1.0, "A")]
    texts, base, _stats = remap_track(old, new, [], [])
    assert texts == [""]
    assert base == ["A"]


def test_merge_translation_texts_only_writes_listed_slots():
    from core.i18n import merge_translation_texts

    source = ["おはよう", "今日は雨だ", "またね"]
    texts = ["早上好", "今天下雨", "再见"]
    base = list(source)
    merged, merged_base, changed, kept = merge_translation_texts(
        source, texts, base, {1: "今天下雨了"}
    )
    # 只有第 2 条被写；其余逐字节不动
    assert merged == ["早上好", "今天下雨了", "再见"]
    assert changed == [1]
    assert kept == 0
    assert merged_base == source


def test_merge_translation_texts_empty_never_clears_existing_text():
    from core.i18n import merge_translation_texts

    source = ["A", "B", "C"]
    texts = ["甲", "乙", "丙"]
    merged, _base, changed, kept = merge_translation_texts(
        source, texts, source, {1: "", 2: "   "}
    )
    # 空 / 纯空白只表示「本次没有这一条」，不表示删除
    assert merged == ["甲", "乙", "丙"]
    assert changed == []
    assert kept == 2


def test_merge_translation_texts_allow_empty_when_authoritative():
    from core.i18n import merge_translation_texts

    source = ["A", "B"]
    merged, _base, changed, _kept = merge_translation_texts(
        source, ["甲", "乙"], source, {1: ""}, skip_empty=False
    )
    assert merged == ["甲", ""]
    assert changed == [1]


def test_merge_translation_texts_keeps_stale_base_for_untouched_rows():
    """批量替换只改文本：没改的条目不重设 base，「原文已改」标记不能因此消失。"""
    from core.i18n import merge_translation_texts

    source = ["新A", "B"]
    texts = ["甲", "乙"]
    base = ["旧A", "B"]  # 第 1 条本来是 stale
    merged, merged_base, changed, _kept = merge_translation_texts(
        source, texts, base, {1: "乙改"}, sync_unchanged_base=False
    )
    assert merged == ["甲", "乙改"]
    assert merged_base == ["旧A", "B"]
    assert changed == [1]


def test_merge_translation_texts_rebuilds_when_track_misaligned():
    from core.i18n import merge_translation_texts

    source = ["A", "B", "C"]
    merged, merged_base, changed, _kept = merge_translation_texts(
        source, ["甲"], ["旧A"], {2: "丙"}
    )
    assert merged == ["", "", "丙"]
    assert merged_base == source
    assert changed == [2]
