"""AI 提案：源指纹、结构校验、应用（开发文档 §3 / §4）。

这些是纯函数用例，不碰 fastapi / torch——`core/` 的边界由 test_core_boundary 看守。
"""

from __future__ import annotations

import hashlib

from core import ai_proposal as ap
from core.subtitles import SubtitleCue

CUES = [
    SubtitleCue(0.5, 1.5, "おはよう"),
    SubtitleCue(2.0, 3.0, "今日は雨だ"),
    SubtitleCue(3.5, 4.5, "行ってきます"),
]
TEXTS = [c.text for c in CUES]


def proposal_for(texts=None, after=None, *, kind="polish", notes=None, **kw):
    """按 §3.1 造一份合法提案；after 缺省时等于原文。"""
    texts = list(TEXTS if texts is None else texts)
    after = list(texts if after is None else after)
    notes = list([""] * len(after) if notes is None else notes)
    items = [
        {"i": idx, "before": texts[idx - 1], "after": after[idx - 1], "note": notes[idx - 1]}
        for idx in range(1, len(texts) + 1)
    ]
    return ap.build_proposal(kind=kind, src_lang="ja", texts=texts, items=items, **kw)


# --------------------------------------------------------------------------- 源指纹


def test_digest_matches_documented_algorithm():
    """与文档 §3.2 逐字节一致：序号 + \\t + 去首尾空白，\\n 连接，末尾不加换行。"""
    expected = hashlib.sha256("1\tA\n2\tB".encode("utf-8")).hexdigest()
    assert ap.source_digest(["A", "B"]) == expected


def test_digest_ignores_outer_whitespace_only():
    assert ap.source_digest(["  A  ", "B"]) == ap.source_digest(["A", "B"])


def test_digest_changes_with_text():
    assert ap.source_digest(["A", "B"]) != ap.source_digest(["A", "C"])


# --------------------------------------------------------------------------- 校验


def test_validate_accepts_wellformed_proposal():
    check = ap.validate_proposal(proposal_for(), TEXTS)
    assert check.ok and check.status == 200
    assert check.digest_match
    assert check.effective[2] == "今日は雨だ"


def test_validate_rejects_wrong_version():
    data = proposal_for()
    data["version"] = 2
    check = ap.validate_proposal(data, TEXTS)
    assert not check.ok and check.status == 422


def test_validate_rejects_unknown_kind():
    data = proposal_for()
    data["kind"] = "rewrite"
    check = ap.validate_proposal(data, TEXTS)
    assert not check.ok and check.status == 422


def test_validate_rejects_count_mismatch():
    data = proposal_for()
    data["items"] = data["items"][:-1]
    check = ap.validate_proposal(data, TEXTS)
    assert not check.ok and check.status == 422
    assert "条目数不符" in check.errors[0]


def test_validate_rejects_duplicate_index():
    data = proposal_for()
    data["items"][1]["i"] = 1
    check = ap.validate_proposal(data, TEXTS)
    assert not check.ok and check.status == 422
    assert "重复" in check.errors[0]


def test_validate_rejects_out_of_range_index():
    data = proposal_for()
    data["items"][0]["i"] = 99
    check = ap.validate_proposal(data, TEXTS)
    assert not check.ok and check.status == 422


def test_validate_rejects_non_string_after():
    data = proposal_for()
    data["items"][0]["after"] = {"text": "x"}
    check = ap.validate_proposal(data, TEXTS)
    assert not check.ok and check.status == 422


def test_validate_reports_digest_mismatch_as_409():
    data = proposal_for(texts=["A", "B", "C"])  # 针对另一版字幕生成
    check = ap.validate_proposal(data, TEXTS)
    assert not check.ok and check.status == 409
    assert check.digest_match is False


def test_validate_warns_when_changed_without_note():
    data = proposal_for(after=["おはよう", "今日は飴だ", "行ってきます"])
    check = ap.validate_proposal(data, TEXTS)
    assert check.ok
    assert any("没有写理由" in w for w in check.warnings)


def test_validate_falls_back_on_empty_text():
    data = proposal_for(after=["おはよう", "", "行ってきます"])
    check = ap.validate_proposal(data, TEXTS)
    assert check.ok
    assert check.effective[2] == "今日は雨だ"
    assert any("空文本" in w for w in check.warnings)


def test_validate_falls_back_on_absurd_length():
    data = proposal_for(after=["おはよう", "あ" * 40, "行ってきます"])
    check = ap.validate_proposal(data, TEXTS)
    assert check.ok
    assert check.effective[2] == "今日は雨だ"
    assert any("长度异常" in w for w in check.warnings)


def test_validate_warns_on_high_change_rate():
    data = proposal_for(after=["A", "B", "C"])
    check = ap.validate_proposal(data, TEXTS)
    assert check.ok
    assert any("改动率" in w for w in check.warnings)


# --------------------------------------------------------------------------- 应用


def test_apply_keeps_timestamps_exactly():
    data = proposal_for(after=["おはよう", "今日は飴だ", "行ってきます"])
    cues, changed = ap.apply_polish(CUES, data["items"])
    assert changed == 1
    assert [(c.start, c.end) for c in cues] == [(c.start, c.end) for c in CUES]
    assert cues[1].text == "今日は飴だ"


def test_apply_does_not_mutate_source():
    data = proposal_for(after=["A", "B", "C"])
    ap.apply_polish(CUES, data["items"])
    assert [c.text for c in CUES] == TEXTS


def test_apply_respects_accept_subset():
    data = proposal_for(after=["A", "B", "C"])
    cues, changed = ap.apply_polish(CUES, data["items"], accept={2})
    assert changed == 1
    assert cues[0].text == TEXTS[0]
    assert cues[1].text == "B"
    assert cues[2].text == TEXTS[2]


def test_apply_with_empty_accept_changes_nothing():
    data = proposal_for(after=["A", "B", "C"])
    cues, changed = ap.apply_polish(CUES, data["items"], accept=set())
    assert changed == 0
    assert [c.text for c in cues] == TEXTS


def test_apply_edits_override_proposal():
    data = proposal_for(after=["A", "B", "C"])
    cues, changed = ap.apply_polish(CUES, data["items"], edits={1: "手改的"})
    assert cues[0].text == "手改的"
    assert changed == 3


def test_apply_guards_blank_edit():
    data = proposal_for(after=["A", "B", "C"])
    cues, _ = ap.apply_polish(CUES, data["items"], edits={1: "   "})
    assert cues[0].text == TEXTS[0]


# --------------------------------------------------------------------------- 路径


def test_proposal_paths_are_distinct(tmp_path):
    polish = ap.proposal_path(tmp_path, "film", "polish")
    translate = ap.proposal_path(tmp_path, "film", "translate", "zh-Hans")
    assert polish.name == "film.ai-polish.json"
    assert translate.name == "film.zh-Hans.ai-translate.json"
    assert polish != translate


def test_proposal_path_falls_back_when_stem_empty(tmp_path):
    assert ap.proposal_path(tmp_path, "", "polish").name == "subtitles.ai-polish.json"


def test_dump_and_load_roundtrip(tmp_path):
    data = proposal_for()
    path = tmp_path / "p.json"
    path.write_text(ap.dump_proposal(data), encoding="utf-8")
    assert ap.load_proposal(path) == data


def test_load_proposal_returns_none_for_broken_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    assert ap.load_proposal(path) is None


def test_load_proposal_returns_none_when_missing(tmp_path):
    assert ap.load_proposal(tmp_path / "nope.json") is None
