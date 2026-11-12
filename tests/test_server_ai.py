"""AI 提案的服务化接口：读取 / 保存 / 应用（开发文档 §4.2）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from core import ai_proposal as ap  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "ai-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

CUES = [
    {"start": 0.5, "end": 1.5, "text": "おはよう"},
    {"start": 2.0, "end": 3.0, "text": "今日は雨だ"},
    {"start": 3.5, "end": 4.5, "text": "行ってきます"},
]
TEXTS = [c["text"] for c in CUES]


def make_proposal(after=None, texts=None, kind="polish"):
    texts = list(TEXTS if texts is None else texts)
    after = list(texts if after is None else after)
    items = [
        {"i": idx, "before": texts[idx - 1], "after": after[idx - 1], "note": "同音误识"}
        for idx in range(1, len(texts) + 1)
    ]
    return ap.build_proposal(kind=kind, src_lang="ja", texts=texts, items=items, model="test")


@pytest.fixture()
def ctx(tmp_path: Path):
    app = create_app(
        ServerConfig(
            token=TOKEN,
            output_dir=tmp_path,
            # 设置必须落 tmp：默认值指向仓库里的 settings.json，不能污染
            settings_path=tmp_path / "settings.json",
        )
    )
    client = TestClient(app)

    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    media_id = client.post("/api/media", headers=AUTH, json={"path": str(media)}).json()["id"]
    client.post("/api/session/bind", headers=AUTH, json={"media_id": media_id})
    res = client.post("/api/cues", headers=AUTH, json={"cues": CUES})
    assert res.status_code == 200, res.text
    return client, tmp_path / "episode.ai-polish.json"


def _texts(client) -> list[str]:
    return [c["text"] for c in client.get("/api/cues", headers=AUTH).json()["cues"]]


# --------------------------------------------------------------------------- 读取 / 保存


def test_get_proposal_returns_409_when_missing(ctx):
    client, _ = ctx
    res = client.get("/api/ai/proposal", headers=AUTH)
    assert res.status_code == 409
    assert "还没有提案文件" in res.json()["detail"]


def test_save_then_get_roundtrip(ctx):
    client, path = ctx
    data = make_proposal()

    saved = client.post("/api/ai/proposal", headers=AUTH, json={"proposal": data})
    assert saved.status_code == 201, saved.text
    assert Path(saved.json()["path"]) == path
    assert path.exists()

    got = client.get("/api/ai/proposal", headers=AUTH)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["ok"] is True
    assert body["digest_match"] is True
    assert body["current_count"] == len(TEXTS)
    assert body["proposal"]["items"] == data["items"]


def test_save_rejects_invalid_proposal_and_writes_nothing(ctx):
    client, path = ctx
    data = make_proposal()
    data["items"] = data["items"][:2]  # 少一条

    res = client.post("/api/ai/proposal", headers=AUTH, json={"proposal": data})
    assert res.status_code == 422
    assert not path.exists()


def test_save_requires_token(ctx):
    client, _ = ctx
    assert client.post("/api/ai/proposal", json={"proposal": make_proposal()}).status_code in (401, 403)


# --------------------------------------------------------------------------- 应用


def test_apply_changes_text_and_keeps_timeline(ctx):
    client, _ = ctx
    data = make_proposal(after=["おはよう", "今日は飴だ", "行ってきます"])

    res = client.post("/api/ai/apply", headers=AUTH, json={"proposal": data})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["changed"] == 1
    assert body["can_undo"] is True

    cues = body["cues"]
    assert [(c["start"], c["end"]) for c in cues] == [(c["start"], c["end"]) for c in CUES]
    assert cues[1]["text"] == "今日は飴だ"


def test_apply_is_single_undo_step(ctx):
    client, _ = ctx
    data = make_proposal(after=["A", "B", "C"])

    res = client.post("/api/ai/apply", headers=AUTH, json={"proposal": data})
    assert res.status_code == 200
    assert res.json()["changed"] == 3
    assert _texts(client) == ["A", "B", "C"]

    undone = client.post("/api/cues/undo", headers=AUTH).json()
    assert [c["text"] for c in undone["cues"]] == TEXTS


def test_apply_rejects_digest_mismatch_and_keeps_cues(ctx):
    client, _ = ctx
    data = make_proposal(texts=["别", "的", "字幕"])  # 为另一版字幕生成

    res = client.post("/api/ai/apply", headers=AUTH, json={"proposal": data})
    assert res.status_code == 409
    assert res.json()["digest_match"] is False
    assert _texts(client) == TEXTS


def test_apply_rejects_missing_item_and_keeps_cues(ctx):
    client, _ = ctx
    data = make_proposal()
    data["items"] = data["items"][:-1]

    res = client.post("/api/ai/apply", headers=AUTH, json={"proposal": data})
    assert res.status_code == 422
    assert _texts(client) == TEXTS


def test_apply_with_empty_accept_is_noop_and_pushes_no_history(ctx):
    client, _ = ctx
    data = make_proposal(after=["A", "B", "C"])
    before = client.get("/api/cues", headers=AUTH).json()["can_undo"]

    res = client.post("/api/ai/apply", headers=AUTH, json={"proposal": data, "accept": []})
    assert res.status_code == 200
    assert res.json()["changed"] == 0
    assert res.json()["can_undo"] == before
    assert _texts(client) == TEXTS


def test_apply_accepts_subset(ctx):
    client, _ = ctx
    data = make_proposal(after=["A", "B", "C"])

    res = client.post("/api/ai/apply", headers=AUTH, json={"proposal": data, "accept": [2]})
    assert res.status_code == 200
    assert res.json()["changed"] == 1
    assert _texts(client) == ["おはよう", "B", "行ってきます"]


def test_apply_edits_override_proposal(ctx):
    client, _ = ctx
    data = make_proposal(after=["A", "B", "C"])

    res = client.post(
        "/api/ai/apply",
        headers=AUTH,
        json={"proposal": data, "accept": [1], "edits": {"1": "手改的"}},
    )
    assert res.status_code == 200, res.text
    assert _texts(client) == ["手改的", "今日は雨だ", "行ってきます"]


def test_apply_falls_back_to_disk_proposal(ctx):
    client, _ = ctx
    data = make_proposal(after=["A", "B", "C"])
    client.post("/api/ai/proposal", headers=AUTH, json={"proposal": data})

    res = client.post("/api/ai/apply", headers=AUTH, json={})
    assert res.status_code == 200, res.text
    assert _texts(client) == ["A", "B", "C"]


def test_apply_rejects_translate_kind_in_m1(ctx):
    client, _ = ctx
    data = make_proposal(kind="translate")
    res = client.post(
        "/api/ai/apply",
        headers=AUTH,
        json={"proposal": data, "kind": "translate", "lang": "zh-Hans"},
    )
    assert res.status_code == 422
    assert _texts(client) == TEXTS


def test_translate_proposal_requires_lang(ctx):
    client, _ = ctx
    res = client.get("/api/ai/proposal?kind=translate", headers=AUTH)
    assert res.status_code == 422


# --------------------------------------------------------------------------- 配置


def test_get_config_has_defaults(ctx):
    client, _ = ctx
    res = client.get("/api/ai/config", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is False
    assert body["base_url"].startswith("http")
    assert body["key_held_by"] == "renderer"
    assert "key" not in json.dumps({k: v for k, v in body.items() if k != "key_held_by"})


def test_patch_config_persists(ctx):
    client, proposal_path = ctx
    res = client.patch(
        "/api/ai/config",
        headers=AUTH,
        json={"enabled": True, "model": "deepseek-flash", "chunk_cues": 64},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["enabled"] is True and body["chunk_cues"] == 64

    again = client.get("/api/ai/config", headers=AUTH).json()
    assert again["enabled"] is True

    # 真的落到了 tmp 的 settings.json，而不是仓库里那份
    saved = json.loads((proposal_path.parent / "settings.json").read_text(encoding="utf-8"))
    assert saved["ai_enabled"] is True


def test_patch_config_rejects_bad_url(ctx):
    client, _ = ctx
    res = client.patch("/api/ai/config", headers=AUTH, json={"base_url": "ftp://x"})
    assert res.status_code == 422


def test_patch_config_clamps_chunk_size(ctx):
    client, _ = ctx
    res = client.patch("/api/ai/config", headers=AUTH, json={"chunk_cues": 5})
    assert res.json()["chunk_cues"] >= 20


# --------------------------------------------------------------------------- 测试连接


def test_ai_test_uses_header_key_only(ctx, monkeypatch):
    from core import ai_client

    seen = {}

    def fake_test(config):
        seen["key"] = config.api_key
        return {"ok": True, "latency_ms": 12, "model": config.model, "host": "x"}

    monkeypatch.setattr(ai_client, "test_connection", fake_test)
    client, _ = ctx
    res = client.post(
        "/api/ai/test",
        headers={**AUTH, "X-AI-Key": "sk-hidden"},
        json={"base_url": "https://api.example.com/v1", "model": "m"},
    )
    assert res.status_code == 200
    assert seen["key"] == "sk-hidden"
    assert "sk-hidden" not in res.text


def test_ai_test_reports_upstream_failure(ctx, monkeypatch):
    from core import ai_client

    def boom(config):
        raise ai_client.AiError("模型服务暂时不可用（503）", status=503)

    monkeypatch.setattr(ai_client, "test_connection", boom)
    client, _ = ctx
    res = client.post("/api/ai/test", headers={**AUTH, "X-AI-Key": "k"}, json={})
    assert res.status_code == 424


# --------------------------------------------------------------------------- 生成任务


def _enable_ai(client):
    res = client.patch("/api/ai/config", headers=AUTH, json={"enabled": True})
    assert res.status_code == 200


def _wait_job(client, job_id: str, timeout: float = 5.0) -> dict:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if body["status"] in ("done", "error", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"任务没有在 {timeout}s 内结束")


def test_create_ai_job_requires_enabled(ctx):
    client, _ = ctx
    res = client.post("/api/ai/jobs", headers={**AUTH, "X-AI-Key": "k"}, json={})
    assert res.status_code == 503


def test_create_ai_job_requires_key(ctx):
    client, _ = ctx
    _enable_ai(client)
    res = client.post("/api/ai/jobs", headers=AUTH, json={})
    assert res.status_code == 401


def test_create_ai_job_writes_proposal(ctx, monkeypatch):
    from core import ai_polish, ai_proposal

    def fake_run(texts, config, **kw):
        proposal = ai_proposal.build_proposal(
            kind="polish",
            src_lang="ja",
            texts=texts,
            items=[
                {"i": i, "before": t, "after": t, "note": ""}
                for i, t in enumerate(texts, start=1)
            ],
            model=config.model,
        )
        on_progress = kw.get("on_progress")
        if on_progress:
            on_progress(1.0, "校验提案")
        return proposal, []

    monkeypatch.setattr(ai_polish, "run_polish", fake_run)

    client, _ = ctx
    _enable_ai(client)
    res = client.post("/api/ai/jobs", headers={**AUTH, "X-AI-Key": "sk-secret"}, json={})
    assert res.status_code == 201, res.text
    job_id = res.json()["id"]

    job = _wait_job(client, job_id)
    assert job["status"] == "done", job
    assert job["result"]["pending_apply"] is True
    assert Path(job["result"]["proposal_path"]).exists()

    # 密钥绝不进任务快照
    assert "sk-secret" not in json.dumps(job)


def test_create_ai_job_conflict_while_busy(ctx, monkeypatch):
    from core import ai_polish, ai_proposal
    import time as _time

    def slow_run(texts, config, **kw):
        _time.sleep(0.3)
        return (
            ai_proposal.build_proposal(
                kind="polish",
                src_lang="ja",
                texts=texts,
                items=[
                    {"i": i, "before": t, "after": t, "note": ""}
                    for i, t in enumerate(texts, start=1)
                ],
            ),
            [],
        )

    monkeypatch.setattr(ai_polish, "run_polish", slow_run)
    client, _ = ctx
    _enable_ai(client)
    first = client.post("/api/ai/jobs", headers={**AUTH, "X-AI-Key": "k"}, json={})
    assert first.status_code == 201
    second = client.post("/api/ai/jobs", headers={**AUTH, "X-AI-Key": "k"}, json={})
    assert second.status_code == 409
    _wait_job(client, first.json()["id"])


# --------------------------------------------------------------------------- 手动粘贴通道

SRT_PASTED = """1
00:00:00,500 --> 00:00:01,500
早上好

2
00:00:02,000 --> 00:00:03,000
今天下雨

3
00:00:03,500 --> 00:00:04,500
路上小心
"""


def test_manual_prompt_contains_current_srt(ctx):
    client, _ = ctx
    res = client.get("/api/ai/prompt?kind=translate&lang=zh-Hans", headers=AUTH)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == len(TEXTS)
    prompt = body["prompt"]
    # 时间码来自我们自己的 cues_to_srt，与导出完全一致
    assert "00:00:00,500 --> 00:00:01,500" in prompt
    assert "おはよう" in prompt
    assert "翻译为简体中文" in prompt
    assert "<subtitles>" in prompt


def test_manual_prompt_supports_polish(ctx):
    client, _ = ctx
    res = client.get("/api/ai/prompt?kind=polish", headers=AUTH)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == len(TEXTS)
    assert "校对" in body["prompt"]
    assert "おはよう" in body["prompt"]
    assert "<subtitles>" in body["prompt"]


def test_from_srt_builds_proposal_without_touching_cues(ctx):
    client, _ = ctx
    res = client.post(
        "/api/ai/from-srt",
        headers=AUTH,
        json={"kind": "translate", "lang": "zh-Hans", "text": SRT_PASTED},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == len(TEXTS)
    assert [it["after"] for it in body["proposal"]["items"]] == ["早上好", "今天下雨", "路上小心"]
    assert body["proposal"]["kind"] == "translate"
    # 只解析，不改字幕
    assert _texts(client) == TEXTS


SRT_POLISHED = """1
00:00:00,500 --> 00:00:01,500
おはよう

2
00:00:02,000 --> 00:00:03,000
今日は雨だ

3
00:00:03,500 --> 00:00:04,500
行ってきます
"""


def test_from_srt_builds_polish_proposal(ctx):
    client, _ = ctx
    res = client.post(
        "/api/ai/from-srt",
        headers=AUTH,
        json={"kind": "polish", "lang": "", "text": SRT_POLISHED},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == len(TEXTS)
    assert body["proposal"]["kind"] == "polish"
    assert [it["after"] for it in body["proposal"]["items"]] == TEXTS
    # 只解析，不改字幕
    assert _texts(client) == TEXTS


def test_pasted_proposal_can_be_applied(ctx):
    client, _ = ctx
    proposal = client.post(
        "/api/ai/from-srt",
        headers=AUTH,
        json={"kind": "translate", "lang": "zh-Hans", "text": SRT_PASTED},
    ).json()["proposal"]

    applied = client.post(
        "/api/translations", headers=AUTH, json={"lang": "zh-Hans", "proposal": proposal}
    )
    assert applied.status_code == 201, applied.text
    assert applied.json()["texts"] == ["早上好", "今天下雨", "路上小心"]
    # 原文与时间轴不动
    assert _texts(client) == TEXTS
    cues = client.get("/api/cues", headers=AUTH).json()["cues"]
    assert [(c["start"], c["end"]) for c in cues] == [(c["start"], c["end"]) for c in CUES]


def test_from_srt_count_mismatch_is_422(ctx):
    client, _ = ctx
    short = SRT_PASTED.replace("\n3\n00:00:03,500 --> 00:00:04,500\n路上小心\n", "")
    res = client.post(
        "/api/ai/from-srt", headers=AUTH, json={"kind": "translate", "lang": "zh-Hans", "text": short}
    )
    assert res.status_code == 422
    assert "条数对不上" in res.json()["detail"]


# --------------------------------------------------------------------------- 丢弃提案


def test_delete_proposal_removes_file(ctx):
    client, path = ctx
    assert client.post("/api/ai/proposal", headers=AUTH, json={"proposal": make_proposal()}).status_code == 201
    assert path.exists()

    res = client.delete("/api/ai/proposal", headers=AUTH)
    assert res.status_code == 200, res.text
    assert res.json()["removed"] is True
    assert not path.exists()
    # 删完之后读，必须是"还没有提案"
    assert client.get("/api/ai/proposal", headers=AUTH).status_code == 409


def test_delete_proposal_is_idempotent(ctx):
    client, _ = ctx
    res = client.delete("/api/ai/proposal", headers=AUTH)
    assert res.status_code == 200
    assert res.json()["removed"] is False


def test_delete_translate_proposal_uses_lang_path(ctx):
    client, polish_path = ctx
    data = make_proposal(kind="translate")
    assert client.post(
        "/api/ai/proposal", headers=AUTH, json={"proposal": data, "kind": "translate", "lang": "zh-Hans"}
    ).status_code == 201
    target = polish_path.parent / "episode.zh-Hans.ai-translate.json"
    assert target.exists()

    assert client.delete("/api/ai/proposal?kind=translate&lang=zh-Hans", headers=AUTH).json()["removed"] is True
    assert not target.exists()
