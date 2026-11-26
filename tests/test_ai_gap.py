"""补译批次（gap fill）：提示词、解析、回填，以及「只写这些下标」的硬保证。

用户场景（2026-11-25）：逐句核对完一章后只剩几条待译（局部转写新加的行、或人工
删掉的坏译文）。外部模型只翻这几条，回填时**不能**碰到其余已核对过的译文。

这里同时守住两条契约：

- 返回的 SRT 序号是**全片条号**，回填按序号落位，不做时间轴对齐；
- ``POST /api/translations/gap`` 只写请求里列出的下标，其余条目逐字节不变。
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from core import ai_gap  # noqa: E402
from core.ai_proposal import build_proposal  # noqa: E402
from core.subtitles import SubtitleCue  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "gap-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

CUES = [
    {"start": 0.0, "end": 1.0, "text": "おはよう"},
    {"start": 1.0, "end": 2.0, "text": "今日は雨だ"},
    {"start": 2.0, "end": 3.0, "text": "またね"},
    {"start": 3.0, "end": 4.0, "text": "気をつけて"},
]
TEXTS = [cue["text"] for cue in CUES]
# 第 2 / 4 条故意留空 → 待译
ZH = ["早上好", "", "再见", ""]
SUBTITLE_CUES = [SubtitleCue(c["start"], c["end"], c["text"]) for c in CUES]

GAP_SRT = """2
00:00:01,000 --> 00:00:02,000
今天下雨了

4
00:00:03,000 --> 00:00:04,000
小心点
"""


@pytest.fixture()
def ctx(tmp_path):
    app = create_app(
        ServerConfig(
            token=TOKEN,
            output_dir=tmp_path,
            settings_path=tmp_path / "settings.json",
        )
    )
    client = TestClient(app)
    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    media_id = client.post("/api/media", headers=AUTH, json={"path": str(media)}).json()["id"]
    client.post("/api/session/bind", headers=AUTH, json={"media_id": media_id})
    assert client.post("/api/cues", headers=AUTH, json={"cues": CUES}).status_code == 200
    assert (
        client.post(
            "/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH}
        ).status_code
        == 201
    )
    return client, tmp_path


def _track(client):
    return client.get("/api/translations", headers=AUTH).json()["items"][0]


# --------------------------------------------------------------------------- 纯函数


def test_normalize_indices_sorts_dedupes_and_checks_bounds():
    assert ai_gap.normalize_indices("4, 2,2", 10) == [2, 4]
    assert ai_gap.normalize_indices([3, 1], 10) == [1, 3]
    assert ai_gap.normalize_indices("", 10) == []
    with pytest.raises(ai_gap.GapError):
        ai_gap.normalize_indices("0", 10)
    with pytest.raises(ai_gap.GapError):
        ai_gap.normalize_indices("11", 10)
    with pytest.raises(ai_gap.GapError):
        ai_gap.normalize_indices("abc", 10)


def test_gap_srt_uses_global_numbers():
    block = ai_gap.gap_srt(SUBTITLE_CUES, [2, 4])
    assert block.startswith("2\n00:00:01,000 --> 00:00:02,000\n今日は雨だ")
    assert "\n4\n00:00:03,000 --> 00:00:04,000\n気をつけて" in block
    # 不在集合里的条目不能出现
    assert "おはよう" not in block
    assert "またね" not in block


def test_context_block_skips_gap_lines_and_keeps_neighbour_translation():
    block = ai_gap.context_block(SUBTITLE_CUES, ZH, [2, 4])
    assert "#1  おはよう  ｜译：早上好" in block
    assert "#3  またね  ｜译：再见" in block
    assert "#2 " not in block and "#4 " not in block
    assert "仅参考" in block


def test_parse_gap_reply_maps_by_number_first():
    items, warnings = ai_gap.parse_gap_reply(GAP_SRT, SUBTITLE_CUES, [2, 4])
    assert [item["i"] for item in items] == [2, 4]
    assert [item["after"] for item in items] == ["今天下雨了", "小心点"]
    assert items[0]["before"] == "今日は雨だ"
    assert warnings == []


def test_parse_gap_reply_falls_back_to_order_with_warning():
    renumbered = """1
00:00:01,000 --> 00:00:02,000
今天下雨了

2
00:00:03,000 --> 00:00:04,000
小心点
"""
    items, warnings = ai_gap.parse_gap_reply(renumbered, SUBTITLE_CUES, [2, 4])
    assert [item["i"] for item in items] == [2, 4]
    assert [item["after"] for item in items] == ["今天下雨了", "小心点"]
    assert warnings and "序号" in warnings[0]


def test_parse_gap_reply_rejects_count_mismatch_and_names_missing_numbers():
    only_one = """2
00:00:01,000 --> 00:00:02,000
今天下雨了
"""
    with pytest.raises(ai_gap.GapError) as info:
        ai_gap.parse_gap_reply(only_one, SUBTITLE_CUES, [2, 4])
    assert "期望 2 条" in str(info.value)
    assert "#4" in str(info.value)


def test_parse_gap_reply_reports_empty_entry_as_missing_number():
    # 空文本条目会被 SRT 解析器丢弃（与导入路径同一口径），于是条数不符；
    # 错误里必须点名缺的是哪一条，而不是一句笼统的「解析失败」。
    empty_one = """2
00:00:01,000 --> 00:00:02,000


4
00:00:03,000 --> 00:00:04,000
小心点
"""
    with pytest.raises(ai_gap.GapError) as info:
        ai_gap.parse_gap_reply(empty_one, SUBTITLE_CUES, [2, 4])
    assert "条数不符" in str(info.value)
    assert "#2" in str(info.value)


def test_parse_gap_reply_strips_markdown_fence():
    fenced = "```srt\n" + GAP_SRT + "```\n"
    items, _warnings = ai_gap.parse_gap_reply(fenced, SUBTITLE_CUES, [2, 4])
    assert [item["after"] for item in items] == ["今天下雨了", "小心点"]


def test_validate_gap_items_checks_before_and_empty():
    class Item:
        def __init__(self, i, before="", after=""):
            self.i, self.before, self.after = i, before, after

    ok = ai_gap.validate_gap_items([Item(2, "今日は雨だ", "今天下雨了")], SUBTITLE_CUES)
    assert ok == {1: "今天下雨了"}

    with pytest.raises(ai_gap.GapError) as stale:
        ai_gap.validate_gap_items([Item(2, "旧原文", "今天下雨了")], SUBTITLE_CUES)
    assert stale.value.status == 409
    with pytest.raises(ai_gap.GapError):
        ai_gap.validate_gap_items([Item(2, "今日は雨だ", "")], SUBTITLE_CUES)


# --------------------------------------------------------------------------- 接口


def test_prompt_contains_only_requested_indices(ctx):
    client, _ = ctx
    res = client.get(
        "/api/ai/prompt",
        headers=AUTH,
        params={"kind": "translate", "lang": "zh-Hans", "indices": "2,4"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sparse"] is True
    assert body["indices"] == [2, 4]
    assert body["count"] == 2
    assert body["digest"]

    prompt = body["prompt"]
    assert "【补译批次】" in prompt
    block = prompt[prompt.index("<subtitles>") : prompt.index("</subtitles>")]
    assert "\n2\n" in block and "\n4\n" in block
    assert "\n1\n" not in block and "\n3\n" not in block
    assert "おはよう" not in block
    # 邻居原文与已有译文只出现在上下文块里
    assert "#1  おはよう  ｜译：早上好" in prompt
    assert "仅参考" in prompt


def test_prompt_rejects_indices_outside_scope(ctx):
    client, _ = ctx
    res = client.get(
        "/api/ai/prompt",
        headers=AUTH,
        params={
            "kind": "translate",
            "lang": "zh-Hans",
            "indices": "2,4",
            "range_from": "3",
            "range_to": "4",
        },
    )
    assert res.status_code == 422, res.text


def test_prompt_rejects_invalid_indices(ctx):
    client, _ = ctx
    for raw in ("0", "9", "abc"):
        res = client.get(
            "/api/ai/prompt",
            headers=AUTH,
            params={"kind": "translate", "lang": "zh-Hans", "indices": raw},
        )
        assert res.status_code == 422, (raw, res.text)


def test_prompt_indices_are_translate_only(ctx):
    client, _ = ctx
    res = client.get(
        "/api/ai/prompt",
        headers=AUTH,
        params={"kind": "polish", "indices": "2"},
    )
    assert res.status_code == 422, res.text


def test_gap_from_srt_round_trip(ctx):
    client, _ = ctx
    prompt = client.get(
        "/api/ai/prompt",
        headers=AUTH,
        params={"kind": "translate", "lang": "zh-Hans", "indices": "2,4"},
    ).json()
    res = client.post(
        "/api/ai/gap-from-srt",
        headers=AUTH,
        json={"indices": [2, 4], "text": GAP_SRT, "digest": prompt["digest"]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert [item["i"] for item in body["items"]] == [2, 4]
    assert [item["after"] for item in body["items"]] == ["今天下雨了", "小心点"]
    assert body["warnings"] == []


def test_gap_from_srt_rejects_stale_digest(ctx):
    client, _ = ctx
    res = client.post(
        "/api/ai/gap-from-srt",
        headers=AUTH,
        json={"indices": [2, 4], "text": GAP_SRT, "digest": "stale"},
    )
    assert res.status_code == 409, res.text
    assert "原文" in res.json()["detail"]


def test_gap_apply_writes_only_listed_slots_and_is_one_history_step(ctx):
    client, _ = ctx
    before_track = _track(client)
    history_before = len(
        client.get("/api/cues/history", headers=AUTH).json()["items"]
    )

    res = client.post(
        "/api/translations/gap",
        headers=AUTH,
        json={
            "lang": "zh-Hans",
            "items": [
                {"i": 2, "before": "今日は雨だ", "after": "今天下雨了"},
                {"i": 4, "before": "気をつけて", "after": "小心点"},
            ],
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["applied"] == 2
    assert body["kept"] == 2
    assert body["texts"] == ["早上好", "今天下雨了", "再见", "小心点"]
    # 没在名单里的两条逐字节不变（这是「不覆盖已核对译文」的硬保证）
    assert body["texts"][0] == before_track["texts"][0]
    assert body["texts"][2] == before_track["texts"][2]
    assert body["pending"] == 0

    history_after = client.get("/api/cues/history", headers=AUTH).json()
    assert len(history_after["items"]) == history_before + 1
    assert "补译" in history_after["items"][-1]["label"]

    undone = client.post("/api/cues/undo", headers=AUTH)
    assert undone.status_code == 200
    assert _track(client)["texts"] == ZH


def test_gap_apply_rejects_changed_source_without_writing(ctx):
    client, _ = ctx
    res = client.post(
        "/api/translations/gap",
        headers=AUTH,
        json={
            "lang": "zh-Hans",
            "items": [{"i": 2, "before": "旧原文", "after": "今天下雨了"}],
        },
    )
    assert res.status_code == 409, res.text
    assert _track(client)["texts"] == ZH


def test_gap_apply_rejects_level_mismatch(ctx):
    client, _ = ctx
    res = client.post(
        "/api/translations/gap",
        headers=AUTH,
        json={"lang": "zh-Hans", "items": [{"i": 9, "after": "xx"}]},
    )
    assert res.status_code == 422, res.text


# ------------------------------------------------- 应用提案：空槽位不覆盖已有译文


def _proposal(after):
    items = [
        {"i": index + 1, "before": TEXTS[index], "after": after[index], "note": ""}
        for index in range(len(TEXTS))
    ]
    return build_proposal(
        kind="translate", src_lang="ja", dst_lang="zh-Hans", texts=TEXTS, items=items
    )


def test_apply_proposal_keeps_existing_text_on_empty_slot(ctx):
    client, _ = ctx
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ["甲", "乙", "丙", "丁"]})
    res = client.post(
        "/api/translations",
        headers=AUTH,
        json={"lang": "zh-Hans", "proposal": _proposal(["新甲", "", "新丙", "新丁"])},
    )
    assert res.status_code == 201, res.text
    # 第 2 条的 after 是空串 = 本批没有这一条，不是「删掉已核对的译文」
    assert res.json()["texts"] == ["新甲", "乙", "新丙", "新丁"]
    assert res.json()["kept_empty"] == 1


def test_apply_proposal_honours_per_row_accept(ctx):
    client, _ = ctx
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ["甲", "乙", "丙", "丁"]})
    res = client.post(
        "/api/translations",
        headers=AUTH,
        json={
            "lang": "zh-Hans",
            "proposal": _proposal(["A1", "B1", "C1", "D1"]),
            "accept": [1, 3],
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["texts"] == ["A1", "乙", "C1", "丁"]


# ------------------------------------------------- 批量替换只重设改过条目的 base


def test_replace_all_keeps_stale_flags_for_untouched_rows(ctx):
    client, _ = ctx
    # 先让整条轨同步，再把第 1 条原文改掉 → 只有它变 stale
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ["早上好", "今天下雨", "再见", "小心"]})
    patched = client.patch("/api/cues/0", headers=AUTH, json={"text": "おはよう！"})
    assert patched.status_code == 200, patched.text
    assert _track(client)["stale"] == [0]

    res = client.post(
        "/api/cues/replace-all",
        headers=AUTH,
        json={
            "label": "替换 zh-Hans 译文（1 处）",
            "lang": "zh-Hans",
            "texts": ["早上好", "今天下雨", "再会", "小心"],
        },
    )
    assert res.status_code == 200, res.text
    track = _track(client)
    # 第 1 条没被这次替换碰到：base 保持旧原文，stale 必须还在
    assert track["stale"] == [0]
    assert track["texts"] == ["早上好", "今天下雨", "再会", "小心"]


def test_apply_texts_array_is_authoritative_and_can_clear(ctx):
    """直接给 texts 数组 = 每一格都是最终值；只有提案通道才把空槽位当「本批没有」。"""
    client, _ = ctx
    client.post(
        "/api/translations",
        headers=AUTH,
        json={"lang": "zh-Hans", "texts": ["甲", "乙", "丙", "丁"]},
    )
    res = client.post(
        "/api/translations",
        headers=AUTH,
        json={"lang": "zh-Hans", "texts": ["甲", "", "丙", "丁"]},
    )
    assert res.status_code == 201, res.text
    assert res.json()["texts"] == ["甲", "", "丙", "丁"]
