"""片段范围（clip scope）的服务化回归：局部润色 / 局部翻译合并 / 局部提示词。

用户场景：长片只核对第 1–291 条，只对这一段润色、只对这一段翻译，范围外原样保留。
这里把四条最容易漂移的语义冻住：

1. 提案的 digest 只绑这一段（范围外改了字幕不会 409），``items`` 的 ``i`` 仍是
   全片序号；应用只替换这一段，一次 ⌘Z 全退回；
2. 译文按原始索引**局部合并**进整片平行轨：范围外已有译文与空位都原样保留；
3. 手动提示词 / 粘贴回填只包含这一段（含长片分段的段内区间）；
4. AI 任务真的按 ``from_index``–``to_index`` 生成提案（用替身模型，不打网络）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from core import ai_client  # noqa: E402
from core import ai_polish  # noqa: E402
from core import ai_proposal as ap  # noqa: E402
from core import ai_translate  # noqa: E402
from core.subtitles import SubtitleCue  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "clip-scope-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

CUES = [
    {"start": 0.5, "end": 1.5, "text": "おはよう"},
    {"start": 2.0, "end": 3.0, "text": "今日は雨だ"},
    {"start": 3.5, "end": 4.5, "text": "行ってきます"},
    {"start": 5.0, "end": 6.0, "text": "気をつけて"},
    {"start": 6.5, "end": 7.5, "text": "またね"},
]
TEXTS = [c["text"] for c in CUES]


def make_scoped_proposal(after, first=2, last=3, kind="polish", texts=None):
    """第 first–last 条的提案：digest 只绑这一段，i 用全片序号。"""
    texts = list(TEXTS if texts is None else texts)
    scope = texts[first - 1 : last]
    items = [
        {"i": first + offset, "before": before, "after": after[offset], "note": "测试"}
        for offset, before in enumerate(scope)
    ]
    return ap.build_proposal(
        kind=kind,
        src_lang="ja",
        texts=scope,
        items=items,
        model="test",
        dst_lang="zh-Hans" if kind == "translate" else "",
        cue_span=(first, last),
    )


@pytest.fixture()
def ctx(tmp_path: Path):
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
    return client


def _texts(client) -> list[str]:
    return [c["text"] for c in client.get("/api/cues", headers=AUTH).json()["cues"]]


# --------------------------------------------------------------------------- 核心纯函数


def test_scoped_items_keep_global_indices_and_slice_digest():
    data = make_scoped_proposal(["晴れだ", "行ってらっしゃい"])
    assert data["source"]["range"] == {"from": 2, "to": 3, "count": 2}
    assert data["source"]["digest"] == ap.source_digest(TEXTS[1:3])
    assert [item["i"] for item in data["items"]] == [2, 3]
    check = ap.validate_proposal(data, TEXTS[1:3], span=(2, 3))
    assert check.ok
    assert check.effective[2] == "晴れだ"


def test_apply_polish_range_only_touches_span():
    cues = [SubtitleCue(start=c["start"], end=c["end"], text=c["text"]) for c in CUES]
    data = make_scoped_proposal(["晴れだ", "行ってらっしゃい"])
    new_cues, changed = ap.apply_polish_range(
        cues, data["items"], (2, 3), accept={2, 3}
    )
    assert changed == 2
    assert [cue.text for cue in new_cues] == [
        "おはよう",
        "晴れだ",
        "行ってらっしゃい",
        "気をつけて",
        "またね",
    ]
    assert [(c.start, c.end) for c in new_cues] == [(c["start"], c["end"]) for c in CUES]
    # 只采纳第 2 条时，第 3 条保持原文
    partial, changed = ap.apply_polish_range(cues, data["items"], (2, 3), accept={2})
    assert changed == 1
    assert partial[2].text == "行ってきます"


def test_run_polish_with_cue_span(monkeypatch):
    """替身模型：只收到这 2 条，产出的是全片序号的片段提案。"""
    seen: list[dict] = []

    def chat(cfg, system, user, **kw):
        data = json.loads(user.split(ai_polish.STRICT_HINT)[0])
        seen.append(data)
        return {"items": [{"i": it["i"], "text": it["text"] + "!", "note": ""} for it in data["items"]]}

    monkeypatch.setattr(ai_client, "chat_json", chat)
    cfg = ai_client.AiConfig(base_url="https://api.example.com/v1", model="m", api_key="k")
    proposal, _warnings = ai_polish.run_polish(
        TEXTS[1:3],
        cfg,
        chunk_cues=100,
        context_cues=0,
        cue_span=(2, 3),
        cues_a=[
            SubtitleCue(start=c["start"], end=c["end"], text=c["text"]) for c in CUES
        ][1:3],
    )
    assert seen and [it["i"] for it in seen[0]["items"]] == [1, 2]
    assert proposal["source"]["range"] == {"from": 2, "to": 3, "count": 2}
    assert [item["i"] for item in proposal["items"]] == [2, 3]
    check = ap.validate_proposal(proposal, TEXTS[1:3], span=(2, 3))
    assert check.ok


def test_proposal_from_srt_scoped_segment():
    """分段粘贴：内容只是段内第 2–3 条，提案覆盖整段、段外保持原文。"""
    srt = "1\n00:00:00,000 --> 00:00:01,000\n晴れだ\n\n2\n00:00:01,000 --> 00:00:02,000\n行ってらっしゃい\n"
    cues = [SubtitleCue(start=c["start"], end=c["end"], text=c["text"]) for c in CUES]
    proposal, _warnings = ai_polish.proposal_from_srt(
        srt,
        cues,
        from_index=2,
        to_index=3,
        range_from=2,
        range_to=4,
    )
    assert proposal["source"]["range"] == {"from": 2, "to": 4, "count": 3}
    assert [(it["i"], it["after"]) for it in proposal["items"]] == [
        (2, "晴れだ"),
        (3, "行ってらっしゃい"),
        (4, TEXTS[3]),
    ]
    check = ap.validate_proposal(proposal, TEXTS[1:4], span=(2, 4))
    assert check.ok


# --------------------------------------------------------------------------- 服务层


def test_apply_scoped_polish_keeps_outside_and_undoes_once(ctx):
    client = ctx
    data = make_scoped_proposal(["晴れだ", "行ってらっしゃい"])

    res = client.post(
        "/api/ai/apply",
        headers=AUTH,
        json={"kind": "polish", "proposal": data, "accept": [2, 3]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["changed"] == 2
    assert body["range"] == {"from": 2, "to": 3}
    assert _texts(client) == ["おはよう", "晴れだ", "行ってらっしゃい", "気をつけて", "またね"]
    assert body["can_undo"] is True

    undo = client.post("/api/cues/undo", headers=AUTH)
    assert undo.status_code == 200, undo.text
    assert _texts(client) == TEXTS


def test_scoped_digest_ignores_changes_outside_range(ctx):
    client = ctx
    data = make_scoped_proposal(["晴れだ", "行ってらっしゃい"])
    # 范围外（第 1 条，0 基下标 0）改了字幕：片段提案不该被 409 拒绝
    patch = client.patch("/api/cues/0", headers=AUTH, json={"text": "おはよう！"})
    assert patch.status_code == 200, patch.text
    res = client.post(
        "/api/ai/apply",
        headers=AUTH,
        json={"kind": "polish", "proposal": data, "accept": [2, 3]},
    )
    assert res.status_code == 200, res.text
    assert _texts(client)[1:3] == ["晴れだ", "行ってらっしゃい"]
    assert _texts(client)[0] == "おはよう！"


def test_scoped_digest_rejects_changes_inside_range(ctx):
    client = ctx
    data = make_scoped_proposal(["晴れだ", "行ってらっしゃい"])
    assert client.patch("/api/cues/1", headers=AUTH, json={"text": "今日は雪だ"}).status_code == 200
    res = client.post(
        "/api/ai/apply",
        headers=AUTH,
        json={"kind": "polish", "proposal": data, "accept": [2, 3]},
    )
    assert res.status_code == 409, res.text
    assert "源文本已变化" in res.json()["detail"]


def test_apply_scoped_translation_merges_by_index(ctx):
    client = ctx
    # 先整片应用一版译文（范围外有内容，#5 故意留空位）
    full = ["早上好", "今天下雨", "我出门了", "小心点", ""]
    applied = client.post(
        "/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": full}
    )
    assert applied.status_code == 201, applied.text

    scoped = make_scoped_proposal(["下着雨呢", "我走了"], kind="translate")
    res = client.post(
        "/api/translations",
        headers=AUTH,
        json={"lang": "zh-Hans", "proposal": scoped},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["partial"] is True
    assert body["range"] == {"from": 2, "to": 3}
    assert body["texts"] == ["早上好", "下着雨呢", "我走了", "小心点", ""]
    assert body["count"] == 5

    # 只压一步历史：⌘Z 退回整条平行轨（范围外原样回来）
    undo = client.post("/api/cues/undo", headers=AUTH)
    assert undo.status_code == 200, undo.text
    assert client.get("/api/translations", headers=AUTH).json()["items"][0]["texts"] == full


def test_apply_scoped_translation_creates_track_when_missing(ctx):
    client = ctx
    scoped = make_scoped_proposal(["下着雨呢", "我走了"], kind="translate")
    res = client.post(
        "/api/translations",
        headers=AUTH,
        json={"lang": "zh-Hans", "proposal": scoped},
    )
    assert res.status_code == 201, res.text
    texts = res.json()["texts"]
    assert len(texts) == len(TEXTS)
    assert texts[1:3] == ["下着雨呢", "我走了"]
    assert texts[0] == "" and texts[3] == "" and texts[4] == ""


def test_manual_prompt_only_contains_scope(ctx):
    client = ctx
    res = client.get(
        "/api/ai/prompt",
        headers=AUTH,
        params={"kind": "translate", "lang": "zh-Hans", "range_from": 2, "range_to": 4},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == 3
    assert body["range_from"] == 2 and body["range_to"] == 4
    for inside in TEXTS[1:4]:
        assert inside in body["prompt"]
    for outside in (TEXTS[0], TEXTS[4]):
        assert outside not in body["prompt"]
    # 范围说明只出现一次：模板自带占位符时不能重复插入
    assert body["prompt"].count("本次只处理片段第 2–4 条") == 1


def test_manual_batch_prompt_is_subrange_of_scope(ctx):
    """处理范围之内再切批次：提示词只含这段，范围说明同时交代两层区间。"""
    client = ctx
    res = client.get(
        "/api/ai/prompt",
        headers=AUTH,
        params={
            "kind": "translate",
            "lang": "zh-Hans",
            "range_from": 2,
            "range_to": 4,
            "from_index": 3,
            "to_index": 3,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == 1
    assert (body["from"], body["to"]) == (3, 3)
    assert (body["range_from"], body["range_to"]) == (2, 4)
    assert TEXTS[2] in body["prompt"]
    for outside in (TEXTS[0], TEXTS[1], TEXTS[3], TEXTS[4]):
        assert outside not in body["prompt"]
    assert "本次只处理片段第 2–4 条" in body["prompt"]
    assert "当前分段是其中第 3–3 条" in body["prompt"]


def test_paste_back_scoped_proposal(ctx):
    client = ctx
    srt = "1\n00:00:00,000 --> 00:00:01,000\n晴れだ\n\n2\n00:00:01,000 --> 00:00:02,000\n行ってらっしゃい\n"
    res = client.post(
        "/api/ai/from-srt",
        headers=AUTH,
        json={
            "kind": "polish",
            "mode": "single",
            "text": srt,
            "from_index": 2,
            "to_index": 3,
            "range_from": 2,
            "range_to": 3,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == 2
    assert body["proposal"]["source"]["range"] == {"from": 2, "to": 3, "count": 2}

    applied = client.post(
        "/api/ai/apply",
        headers=AUTH,
        json={"kind": "polish", "proposal": body["proposal"], "accept": [2, 3]},
    )
    assert applied.status_code == 200, applied.text
    assert _texts(client) == ["おはよう", "晴れだ", "行ってらっしゃい", "気をつけて", "またね"]


def test_invalid_scope_is_422(ctx):
    client = ctx
    res = client.get(
        "/api/ai/prompt",
        headers=AUTH,
        params={"kind": "polish", "range_from": 4, "range_to": 2},
    )
    assert res.status_code == 422
    res = client.post(
        "/api/ai/from-srt",
        headers=AUTH,
        json={"kind": "polish", "text": "1\n00:00:00,000 --> 00:00:01,000\nx\n", "range_from": 9},
    )
    assert res.status_code == 422


def test_ai_job_generates_scoped_proposal(ctx, tmp_path: Path, monkeypatch):
    """任务链路：from_index/to_index 只把这一段交给模型，落盘提案带 range。"""
    client = ctx
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "ai_enabled": True,
                "ai_base_url": "https://api.example.com/v1",
                "ai_model": "m",
                "ai_max_chunk_cues": 100,
                "ai_context_cues": 0,
            }
        ),
        encoding="utf-8",
    )

    def chat(cfg, system, user, **kw):
        data = json.loads(user.split(ai_polish.STRICT_HINT)[0])
        return {
            "items": [
                {"i": it["i"], "text": it["text"] + "！", "note": ""} for it in data["items"]
            ]
        }

    monkeypatch.setattr(ai_client, "chat_json", chat)
    created = client.post(
        "/api/ai/jobs",
        headers={**AUTH, "x-ai-key": "k"},
        json={"kind": "polish", "chunk_cues": 100, "from_index": 2, "to_index": 3},
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]
    deadline = time.time() + 20
    snap = {}
    while time.time() < deadline:
        snap = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if snap["status"] in {"done", "error", "cancelled"}:
            break
        time.sleep(0.05)
    assert snap.get("status") == "done", snap
    assert snap["result"]["count"] == 2
    assert snap["result"]["range"] == {"from": 2, "to": 3, "count": 2}

    payload = client.get("/api/ai/proposal", headers=AUTH).json()
    assert payload["proposal"]["source"]["range"] == {"from": 2, "to": 3, "count": 2}
    assert payload["range"] == {"from": 2, "to": 3}
    assert payload["current_count"] == 2
    assert payload["total_count"] == len(TEXTS)
    assert payload["ok"] is True
