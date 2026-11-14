"""结构建议（Phase 1）：解析、校验、冲突、原子应用。"""

from __future__ import annotations

import pytest

from core import ai_structure as structure
from core.subtitles import SubtitleCue

CUES = [
    SubtitleCue(1.0, 2.0, "あ"),
    SubtitleCue(2.0, 3.0, "い"),
    SubtitleCue(3.0, 4.0, "う"),
    SubtitleCue(4.0, 5.0, "え"),
]


def preview(ops, *, langs=None):
    return structure.preview(CUES, ops, translation_langs=langs)


# --------------------------------------------------------------------------- 解析


def test_extract_ops_tolerates_fence_and_prose():
    text = '好的，建议如下：\n```json\n{"ops":[{"op":"merge","from":1,"to":2}]}\n```\n完毕。'
    assert structure.extract_ops(text) == [{"op": "merge", "from": 1, "to": 2}]


def test_extract_ops_accepts_bare_array_and_empty():
    assert structure.extract_ops('[{"op":"delete","i":1}]')[0]["op"] == "delete"
    assert structure.extract_ops('{"ops":[]}') == []


def test_extract_ops_rejects_unknown_op():
    with pytest.raises(structure.StructureError) as info:
        structure.extract_ops('{"ops":[{"op":"split","i":1}]}')
    assert "不支持" in str(info.value)


def test_extract_ops_rejects_bad_json():
    with pytest.raises(structure.StructureError):
        structure.extract_ops("模型说：好的，这是结果。")


# --------------------------------------------------------------------------- 预览 / 应用


def test_replace_text_keeps_exact_timestamps():
    cues = [SubtitleCue(1.234567, 2.345678, "あ")]
    new_cues, applied = structure.apply_selected(
        cues, [{"op": "replace_text", "i": 1, "after": "ああ"}], [0]
    )
    assert applied == 1
    assert (new_cues[0].start, new_cues[0].end) == (1.234567, 2.345678)


def test_merge_uses_optional_text_and_time_span():
    auto = preview([{"op": "merge", "from": 1, "to": 2}]).ops[0]
    assert auto["before"] == "あい"
    assert auto["after"] == "あい"
    assert (auto["old_start"], auto["old_end"]) == (1.0, 3.0)

    fixed = preview([{"op": "merge", "from": 1, "to": 2, "text": "あい！"}]).ops[0]
    assert fixed["after"] == "あい！"


def test_insert_after_zero_goes_first():
    result = preview(
        [{"op": "insert", "after": 0, "start": 0.1, "end": 0.9, "text": "前"}]
    )
    assert [(c.text, c.start, c.end) for c in result.cues] == [
        ("前", 0.1, 0.9),
        ("あ", 1.0, 2.0),
        ("い", 2.0, 3.0),
        ("う", 3.0, 4.0),
        ("え", 4.0, 5.0),
    ]


def test_ops_are_applied_against_pre_apply_indices():
    """insert / merge / delete / replace 混在一起时，下标仍是原 1-based。"""
    ops = [
        {"op": "insert", "after": 0, "start": 0.1, "end": 0.9, "text": "前"},
        {"op": "merge", "from": 1, "to": 2, "text": "あい"},
        {"op": "replace_text", "i": 3, "after": "うう"},
        {"op": "delete", "i": 4},
    ]
    result = preview(ops)
    assert result.summary["conflicts"] == 0
    assert [(c.text, c.start, c.end) for c in result.cues] == [
        ("前", 0.1, 0.9),
        ("あい", 1.0, 3.0),
        ("うう", 3.0, 4.0),
    ]


def test_apply_selected_only_uses_selected_ops():
    ops = [
        {"op": "merge", "from": 1, "to": 2},
        {"op": "replace_text", "i": 3, "after": "うう"},
        {"op": "delete", "i": 4},
    ]
    new_cues, applied = structure.apply_selected(CUES, ops, [0, 1])
    assert applied == 2
    assert [c.text for c in new_cues] == ["あい", "うう", "え"]


def test_apply_selected_empty_is_noop():
    new_cues, applied = structure.apply_selected(CUES, [{"op": "delete", "i": 1}], [])
    assert applied == 0
    assert new_cues == CUES


# --------------------------------------------------------------------------- 冲突


def test_merge_and_delete_same_cue_conflict():
    result = preview(
        [{"op": "merge", "from": 1, "to": 2}, {"op": "delete", "i": 1}]
    )
    conflicts = [op["conflict"] for op in result.ops]
    assert conflicts[0] and conflicts[1]
    with pytest.raises(structure.StructureConflict):
        structure.apply_selected(
            CUES,
            [{"op": "merge", "from": 1, "to": 2}, {"op": "delete", "i": 1}],
            [0, 1],
        )


def test_insert_inside_merge_conflicts():
    result = preview(
        [
            {"op": "merge", "from": 1, "to": 2},
            {"op": "insert", "after": 1, "start": 2.1, "end": 2.9, "text": "中"},
        ]
    )
    assert result.ops[1]["conflict"]


def test_retime_overlap_conflicts():
    result = preview([{"op": "retime", "i": 2, "start": 1.5, "end": 2.5}])
    assert result.ops[0]["conflict"]
    assert "时间重叠" in result.ops[0]["conflict"][0]


def test_bad_retime_is_conflict_not_crash():
    result = preview([{"op": "retime", "i": 2, "start": 3.0, "end": 2.0}])
    assert result.ops[0]["conflict"]


def test_translation_guard_blocks_count_changing_only():
    ops = [
        {"op": "merge", "from": 1, "to": 2},
        {"op": "retime", "i": 3, "start": 3.1, "end": 4.1},
        {"op": "insert", "after": 4, "start": 5.1, "end": 5.9, "text": "後"},
        {"op": "delete", "i": 4},
    ]
    result = preview(ops, langs=["zh-Hans"])
    assert result.ops[0]["conflict"]
    assert not result.ops[1]["conflict"]
    assert result.ops[2]["conflict"]
    assert result.ops[3]["conflict"]
    with pytest.raises(structure.StructureConflict):
        structure.apply_selected(CUES, ops, [0], translation_langs=["zh-Hans"])


def test_apply_selected_revalidates_only_selected_subset():
    """merge 因未选中的 delete 被标红时，单独选 merge 仍然可以应用。"""
    ops = [
        {"op": "merge", "from": 1, "to": 2},
        {"op": "delete", "i": 1},
    ]
    whole = preview(ops)
    assert whole.ops[0]["conflict"]
    new_cues, applied = structure.apply_selected(CUES, ops, [0])
    assert applied == 1
    assert [c.text for c in new_cues] == ["あい", "う", "え"]


# --------------------------------------------------------------------------- 提案文件 / 提示词


def test_proposal_roundtrip_binds_digest(tmp_path):
    proposal = structure.build_proposal(CUES, [{"op": "delete", "i": 1}])
    path = structure.structure_path(tmp_path, "episode")
    path.write_text(structure.dump_proposal(proposal), encoding="utf-8")
    loaded = structure.load_proposal(path)
    assert loaded is not None
    assert structure.source_matches(loaded, CUES)
    changed = [SubtitleCue(1.0, 2.0, "あ！")]
    assert not structure.source_matches(loaded, changed)


def test_prompt_asks_only_for_ops():
    prompt = structure.build_prompt(CUES)
    assert '"ops"' in prompt
    assert "digest" not in prompt
    assert "version" not in prompt
    assert "不要使用 split" in prompt
    assert "あ" in prompt
