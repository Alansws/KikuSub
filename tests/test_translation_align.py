"""译文时间轴对齐（2026-11-20）：条数可以不同，但必须按时间戳挂回原句槽位。

用户场景：长片第 1–291 条复制出去翻译，模型把相邻两句合并成一条，粘回 288 条。
默认（严格条数开关关闭）应按时间戳区间交集对齐：

- 一条译文跨多句 → 主译文写第一条，其余槽位置空并标「合并覆盖」；
- 后续条起严格对齐，不会因为少了几条就整体错行；
- 起止偏差 > 0.5s 标 drift；整条落在时间窗外标 out_of_range；未匹配原句标 missing；
- 纯文本（无时间轴）条数不同仍然拦截；
- 应用只写本批槽位，空槽位不把日文原文填进译文轨。
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from core import ai_client  # noqa: E402
from core import ai_proposal as ap  # noqa: E402
from core import ai_translate as tr  # noqa: E402
from core.proposal_srt import (  # noqa: E402
    TRANSLATION_DRIFT_TOLERANCE,
    align_translation_cues,
    align_translation_srt,
)
from core.subtitles import SubtitleCue  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

CUES = [
    {"start": 0.5, "end": 1.5, "text": "おはよう"},
    {"start": 2.0, "end": 3.0, "text": "今日は雨だ"},
    {"start": 3.5, "end": 4.5, "text": "行ってきます"},
    {"start": 5.0, "end": 6.0, "text": "気をつけて"},
    {"start": 6.5, "end": 7.5, "text": "またね"},
]
TEXTS = [c["text"] for c in CUES]

SRT_MERGED = """1
00:00:00,500 --> 00:00:03,000
早上好，今天下雨

2
00:00:03,500 --> 00:00:04,500
路上小心

3
00:00:06,500 --> 00:00:07,500
回头见
"""


def cues_of(cues=CUES):
    return [SubtitleCue(c["start"], c["end"], c["text"]) for c in cues]


# --------------------------------------------------------------------------- 纯函数


def test_alignment_merges_source_slots_and_keeps_following_rows_in_sync():
    result = align_translation_srt(SRT_MERGED, cues_of())
    assert result.texts == ["早上好，今天下雨", "", "路上小心", "", "回头见"]
    assert result.counts["merged"] == 2  # #1 主译文 + #2 被覆盖
    assert result.counts["missing"] == 1  # #4 没有译文
    assert result.counts["out_of_range"] == 0
    assert result.rows[0]["state"] == "merged"
    assert result.rows[0]["merged_to"] == 2
    assert result.rows[1]["state"] == "merged"
    assert result.rows[1]["merged_into"] == 1
    assert result.rows[1]["text"] == ""
    # 合并覆盖之后 #3 仍严格对齐，没有错行
    assert result.rows[2]["state"] == "ok"
    assert result.rows[3]["state"] == "missing"
    assert result.rows[4]["state"] == "ok"


def test_alignment_flags_timestamp_drift_over_threshold():
    srt = SRT_MERGED.replace("00:00:06,500 --> 00:00:07,500", "00:00:07,400 --> 00:00:08,400")
    result = align_translation_srt(srt, cues_of())
    # 第 5 条整体后移 0.9s：仍挂到 #5，但起止偏差超过 0.5s
    assert result.texts[4] == "回头见"
    assert result.rows[4]["state"] == "ok"
    assert result.rows[4]["drift"] > TRANSLATION_DRIFT_TOLERANCE
    assert any("时间戳" in warning for warning in result.warnings)
    assert result.counts["drift"] >= 1


def test_alignment_marks_entries_outside_batch_time_window():
    out = """1
00:10:00,000 --> 00:10:02,000
跑到范围外

2
00:00:00,500 --> 00:00:01,500
早上好
"""
    result = align_translation_srt(out, cues_of())
    assert result.counts["out_of_range"] == 1
    assert result.texts[0] == "早上好"
    assert any("范围外" in warning for warning in result.warnings)


def test_alignment_requires_timecodes():
    with pytest.raises(ai_client.AiError) as info:
        align_translation_srt("1\n你好\n\n2\n世界", cues_of())
    assert "时间戳" in str(info.value)


def test_alignment_is_pure_and_does_not_mutate_inputs():
    cues = cues_of()
    before = [(c.start, c.end, c.text) for c in cues]
    align_translation_srt(SRT_MERGED, cues)
    assert [(c.start, c.end, c.text) for c in cues] == before


# --------------------------------------------------------------------------- 提案构造


def test_proposal_from_srt_strict_default_still_rejects_count_mismatch():
    with pytest.raises(ai_client.AiError) as info:
        tr.proposal_from_srt(SRT_MERGED, cues_of(), "zh-Hans")
    assert "条数对不上" in str(info.value)


def test_proposal_from_srt_ex_aligns_and_writes_alignment():
    proposal, warnings, alignment = tr.proposal_from_srt_ex(
        SRT_MERGED, cues_of(), "zh-Hans", strict_count=False
    )
    assert [item["after"] for item in proposal["items"]] == [
        "早上好，今天下雨",
        "",
        "路上小心",
        "",
        "回头见",
    ]
    assert alignment is not None
    assert proposal["alignment"]["counts"]["merged"] == 2
    assert proposal["alignment"]["rows"][1]["i"] == 2
    assert proposal["alignment"]["rows"][1]["merged_into"] == 1
    assert any("条数不同" in warning for warning in warnings)
    # 校验必须通过，且空槽位不再被警告「空文本已退回原文」
    check = ap.validate_proposal(proposal, TEXTS)
    assert check.ok
    assert not any("空文本" in warning for warning in check.warnings)


def test_plain_text_count_mismatch_is_still_rejected_in_non_strict_mode():
    with pytest.raises(ai_client.AiError):
        tr.proposal_from_srt_ex("你好\n世界\n再见", cues_of(), "zh-Hans", strict_count=False)


# --------------------------------------------------------------------------- HTTP + 应用


TOKEN = "translation-align-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        ServerConfig(token=TOKEN, output_dir=tmp_path, settings_path=tmp_path / "settings.json")
    )
    http = TestClient(app)
    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    media_id = http.post("/api/media", headers=AUTH, json={"path": str(media)}).json()["id"]
    http.post("/api/session/bind", headers=AUTH, json={"media_id": media_id})
    assert http.post("/api/cues", headers=AUTH, json={"cues": CUES}).status_code == 200
    return http


def test_from_srt_non_strict_alignment_then_apply_keeps_empty_slots(client):
    res = client.post(
        "/api/ai/from-srt",
        headers=AUTH,
        json={
            "kind": "translate",
            "lang": "zh-Hans",
            "text": SRT_MERGED,
            "strict_count": False,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["alignment"]["counts"]["merged"] == 2
    assert body["alignment"]["counts"]["missing"] == 1
    proposal = body["proposal"]
    assert [item["after"] for item in proposal["items"]] == [
        "早上好，今天下雨",
        "",
        "路上小心",
        "",
        "回头见",
    ]

    applied = client.post(
        "/api/translations", headers=AUTH, json={"lang": "zh-Hans", "proposal": proposal}
    )
    assert applied.status_code == 201, applied.text
    assert applied.json()["texts"] == ["早上好，今天下雨", "", "路上小心", "", "回头见"]
    # 空槽位不能把日文原文顶进译文轨
    assert "気をつけて" not in applied.json()["texts"]
    # 原文与时间轴一个字节都不改
    assert [c["text"] for c in client.get("/api/cues", headers=AUTH).json()["cues"]] == TEXTS


def test_from_srt_non_strict_scoped_batch_keeps_global_indices(client):
    """处理范围 2–4 之内再对齐：items 的 i 仍是全片序号，应用只写这一段。"""
    srt = """1
00:00:01,900 --> 00:00:04,500
下雨了，我出门了

2
00:00:05,000 --> 00:00:06,000
小心点
"""
    res = client.post(
        "/api/ai/from-srt",
        headers=AUTH,
        json={
            "kind": "translate",
            "lang": "zh-Hans",
            "text": srt,
            "range_from": 2,
            "range_to": 4,
            "from_index": 2,
            "to_index": 4,
            "strict_count": False,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["proposal"]["source"]["range"] == {"from": 2, "to": 4, "count": 3}
    assert [item["i"] for item in body["proposal"]["items"]] == [2, 3, 4]
    assert [item["after"] for item in body["proposal"]["items"]] == ["下雨了，我出门了", "", "小心点"]
    # 对齐行号也是全片序号
    assert [row["i"] for row in body["alignment"]["rows"]] == [2, 3, 4]
    assert body["alignment"]["rows"][1]["merged_into"] == 2

    applied = client.post(
        "/api/translations",
        headers=AUTH,
        json={"lang": "zh-Hans", "proposal": body["proposal"]},
    )
    assert applied.status_code == 201, applied.text
    assert applied.json()["texts"] == ["", "下雨了，我出门了", "", "小心点", ""]


def test_from_srt_strict_count_flag_keeps_old_422(client):
    res = client.post(
        "/api/ai/from-srt",
        headers=AUTH,
        json={
            "kind": "translate",
            "lang": "zh-Hans",
            "text": SRT_MERGED,
            "strict_count": True,
        },
    )
    assert res.status_code == 422
    assert "条数对不上" in res.json()["detail"]


def test_from_srt_polish_ignores_non_strict_flag(client):
    """润色恒为严格 1:1：开关只属于翻译，不能把润色也放成合并。"""
    res = client.post(
        "/api/ai/from-srt",
        headers=AUTH,
        json={
            "kind": "polish",
            "text": SRT_MERGED,
            "strict_count": False,
        },
    )
    assert res.status_code == 422
