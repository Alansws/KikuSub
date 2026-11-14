"""双源润色：digest_b 契约、时间轴不变、分段粘贴与序号容错。"""

from __future__ import annotations

import json

import pytest

from core import ai_client as client
from core import ai_polish as polish
from core import ai_proposal as proposals
from core.subtitles import SubtitleCue

CUES_A = [
    SubtitleCue(0.5, 1.5, "おはよう"),
    SubtitleCue(2.0, 3.0, "今日は雨だ"),
    SubtitleCue(3.5, 4.5, "行ってきます"),
]
TEXTS_A = [c.text for c in CUES_A]
TEXTS_B = ["おはよう", "今日は飴だ", "行ってきます"]


def proposal_for(texts, after, *, texts_b=None):
    items = [
        {"i": idx, "before": texts[idx - 1], "after": after[idx - 1]}
        for idx in range(1, len(texts) + 1)
    ]
    return proposals.build_proposal(
        kind="polish", src_lang="ja", texts=texts, texts_b=texts_b, items=items
    )


def test_build_proposal_records_digest_b():
    data = proposal_for(TEXTS_A, TEXTS_B, texts_b=TEXTS_B)
    assert data["source"]["digest_b"] == proposals.source_digest(TEXTS_B)
    assert data["source"]["count_b"] == len(TEXTS_B)


def test_single_source_proposal_stays_valid_when_alt_exists():
    """旧单源提案（没有 digest_b）在存在第二版时仍可应用。"""
    data = proposal_for(TEXTS_A, [t + "!" for t in TEXTS_A])
    check = proposals.validate_proposal(data, TEXTS_A, TEXTS_B)
    assert check.ok


def test_dual_proposal_requires_matching_digest_b():
    data = proposal_for(TEXTS_A, TEXTS_B, texts_b=TEXTS_B)
    assert proposals.validate_proposal(data, TEXTS_A, TEXTS_B).ok

    changed_b = list(TEXTS_B)
    changed_b[1] = "今日は雷だ"
    check = proposals.validate_proposal(data, TEXTS_A, changed_b)
    assert not check.ok and check.status == 409
    assert "第二版" in check.errors[0]

    missing_b = proposals.validate_proposal(data, TEXTS_A, None)
    assert not missing_b.ok and missing_b.status == 409


def test_apply_dual_keeps_timeline_exactly():
    data = proposal_for(TEXTS_A, TEXTS_B, texts_b=TEXTS_B)
    cues, changed = proposals.apply_polish(CUES_A, data["items"])
    assert changed == 1
    assert [(c.start, c.end) for c in cues] == [(c.start, c.end) for c in CUES_A]
    assert [c.text for c in cues] == TEXTS_B


# --------------------------------------------------------------------------- 生成


def _cfg() -> client.AiConfig:
    return client.AiConfig(base_url="https://api.example.com/v1", model="m", api_key="k")


def test_dual_run_polish_sends_a_and_b_with_timestamps(monkeypatch):
    seen: list[dict] = []

    def chat(cfg, system, user, **kw):
        payload = json.loads(user)
        seen.append({"system": system, "payload": payload})
        return {
            "items": [{"i": item["i"], "text": item["text"], "note": ""} for item in payload["items"]]
        }

    monkeypatch.setattr(client, "chat_json", chat)
    proposal, warnings = polish.run_polish(
        TEXTS_A,
        _cfg(),
        chunk_cues=2,
        texts_b=TEXTS_B,
        cues_a=CUES_A,
        cues_b=[SubtitleCue(c.start, c.end, t) for c, t in zip(CUES_A, TEXTS_B)],
    )
    assert proposal["source"]["digest_b"] == proposals.source_digest(TEXTS_B)
    assert [it["i"] for it in proposal["items"]] == [1, 2, 3]
    assert warnings == [] or isinstance(warnings, list)

    assert seen, "必须至少请求一块"
    payload = seen[0]["payload"]
    assert "subtitle_a" in payload and "subtitle_b" in payload
    assert "00:00:00,500" in payload["subtitle_a"]  # A 的全局时间戳
    assert "B（参考稿）" not in seen[0]["system"]  # system 也不应混入占位符
    # 输出仍只回 {i, text}，没有时间码
    assert all("start" not in json.dumps(item) for item in payload["items"])


def test_dual_run_accepts_different_b_counts(monkeypatch):
    """B 可以多几句/少几句：A 仍是 3 条输出，B 的条数不参与提案条数校验。"""
    seen: list[dict] = []

    def chat(cfg, system, user, **kw):
        payload = json.loads(user)
        seen.append(payload)
        return {
            "items": [
                {"i": item["i"], "text": item["text"], "note": ""}
                for item in payload["items"]
            ]
        }

    monkeypatch.setattr(client, "chat_json", chat)
    texts_b_five = list(TEXTS_B) + ["追加 B1", "追加 B2"]
    cues_b_five = [SubtitleCue(c.start, c.end, t) for c, t in zip(CUES_A, TEXTS_B)]
    cues_b_five += [
        SubtitleCue(5.0, 6.0, "追加 B1"),
        SubtitleCue(6.0, 7.0, "追加 B2"),
    ]
    proposal, _ = polish.run_polish(
        TEXTS_A,
        _cfg(),
        chunk_cues=2,
        texts_b=texts_b_five,
        cues_a=CUES_A,
        cues_b=cues_b_five,
    )
    assert [item["i"] for item in proposal["items"]] == [1, 2, 3]
    assert proposal["source"]["count_b"] == 5
    assert proposal["source"]["digest_b"] == proposals.source_digest(texts_b_five)
    assert proposals.validate_proposal(proposal, TEXTS_A, texts_b_five).ok
    assert seen and len(seen[0]["items"]) <= 2


# --------------------------------------------------------------------------- 分段粘贴


SRT_GLOBAL = """1
00:00:00,500 --> 00:00:01,500
おはよう

2
00:00:02,000 --> 00:00:03,000
今日は飴だ
"""

SRT_RELATIVE = """1
00:00:00,000 --> 00:00:01,000
おはよう

2
00:00:01,000 --> 00:00:02,000
今日は飴だ
"""


@pytest.mark.parametrize("srt", [SRT_GLOBAL, SRT_RELATIVE])
def test_from_srt_maps_segment_by_order(srt):
    """全局序号或相对序号都能用：只按顺序回填到第 k..m 条。"""
    proposal, warnings = polish.proposal_from_srt(
        srt, CUES_A, from_index=1, to_index=2
    )
    assert [it["after"] for it in proposal["items"]] == ["おはよう", "今日は飴だ", "行ってきます"]
    assert any("回填" in w for w in warnings)


def test_from_srt_segment_count_mismatch_is_diagnosable():
    one_line = """1
00:00:00,500 --> 00:00:01,500
おはよう
"""
    with pytest.raises(client.AiError) as info:
        polish.proposal_from_srt(one_line, CUES_A, from_index=2, to_index=3)
    message = str(info.value)
    assert "本段期望第 2–3 条" in message
    assert "共 2 条" in message
    assert "解析到 1 条" in message
