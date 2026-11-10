"""润色分块、合并与失败语义（开发文档 §5.3）。全部用替身，不打网络。"""

from __future__ import annotations

import json

import pytest

from core import ai_client as client
from core import ai_proposal as proposals
from core import ai_polish as polish

TEXTS = ["おはよう", "今日は雨だ", "行ってきます", "気をつけて", "またね"]


def payload_of(user: str) -> dict:
    """把 prompt 还原成 dict；结构重问时末尾会追加 STRICT_HINT，先切掉。"""
    marker = polish.STRICT_HINT
    if marker in user:
        user = user.split(marker)[0]
    return json.loads(user)


def fake_chat(transform=None, drop_first=False):
    """按块返回结果；drop_first 让第一次调用少返回一条（触发结构重问）。"""
    state = {"n": 0, "payloads": []}

    def chat(cfg, system, user, **kw):
        state["n"] += 1
        data = payload_of(user)
        state["payloads"].append(data)
        items = []
        for item in data["items"]:
            text = transform(item["text"]) if transform else item["text"]
            items.append({"i": item["i"], "text": text, "note": "改"})
        if drop_first and state["n"] == 1:
            items = items[:-1]
        return {"items": items}

    return chat, state


def cfg() -> client.AiConfig:
    return client.AiConfig(base_url="https://api.example.com/v1", model="m", api_key="k")


# --------------------------------------------------------------------------- 分块


def test_plan_chunks_covers_all_without_overlap():
    chunks = polish.plan_chunks(5, 2)
    assert [(c.start, c.end) for c in chunks] == [(0, 2), (2, 4), (4, 5)]
    assert [c.index for c in chunks] == [1, 2, 3]


def test_plan_chunks_handles_short_input():
    assert [(c.start, c.end) for c in polish.plan_chunks(3, 200)] == [(0, 3)]


def test_prompt_has_no_timestamps_and_uses_absolute_index():
    chunk = polish.plan_chunks(5, 3)[0]
    data = payload_of(polish.build_user_prompt(TEXTS, chunk, 2, "ja", total_chunks=2))

    assert [it["i"] for it in data["items"]] == [1, 2, 3]
    assert data["context_before"] == []
    assert data["context_after"] == ["気をつけて", "またね"]
    assert "start" not in json.dumps(data)
    assert "end" not in json.dumps(data)


def test_prompt_carries_previous_context_for_later_chunk():
    chunk = polish.plan_chunks(5, 3)[1]
    data = payload_of(polish.build_user_prompt(TEXTS, chunk, 2, "ja", total_chunks=2))
    assert data["context_before"] == ["今日は雨だ", "行ってきます"]
    assert [it["i"] for it in data["items"]] == [4, 5]


# --------------------------------------------------------------------------- 合并


def test_run_polish_merges_chunks_into_full_proposal(monkeypatch):
    chat, state = fake_chat(transform=lambda t: t.replace("雨", "飴"))
    monkeypatch.setattr(client, "chat_json", chat)

    proposal, warnings = polish.run_polish(TEXTS, cfg(), chunk_cues=2, context_cues=1)

    assert len(state["payloads"]) == 3
    assert [it["i"] for it in proposal["items"]] == [1, 2, 3, 4, 5]
    assert proposal["items"][1]["after"] == "今日は飴だ"
    assert proposal["kind"] == "polish"
    assert proposal["source"]["count"] == len(TEXTS)
    assert proposal["source"]["digest"] == proposals.source_digest(TEXTS)
    assert isinstance(warnings, list)


def test_run_polish_result_passes_validation(monkeypatch):
    chat, _ = fake_chat()
    monkeypatch.setattr(client, "chat_json", chat)
    proposal, _ = polish.run_polish(TEXTS, cfg(), chunk_cues=2)
    assert proposals.validate_proposal(proposal, TEXTS).ok


def test_progress_callback_is_monotonic(monkeypatch):
    chat, _ = fake_chat()
    monkeypatch.setattr(client, "chat_json", chat)
    seen = []
    polish.run_polish(
        TEXTS, cfg(), chunk_cues=2, on_progress=lambda ratio, stage: seen.append(ratio)
    )
    assert seen == sorted(seen)
    assert seen[-1] == 1.0


# --------------------------------------------------------------------------- 失败与重问


def test_structure_failure_is_retried_once_with_strict_hint(monkeypatch):
    chat, state = fake_chat(drop_first=True)
    monkeypatch.setattr(client, "chat_json", chat)

    proposal, _ = polish.run_polish(TEXTS, cfg(), chunk_cues=5)

    assert state["n"] == 2
    assert [it["i"] for it in proposal["items"]] == [1, 2, 3, 4, 5]


def test_persistent_structure_failure_raises(monkeypatch):
    def chat(cfg_, system, user, **kw):
        return {"items": []}  # 永远缺条

    monkeypatch.setattr(client, "chat_json", chat)
    with pytest.raises(client.AiError) as info:
        polish.run_polish(TEXTS, cfg(), chunk_cues=5)
    assert "缺少" in str(info.value)


def test_transport_error_aborts_whole_proposal(monkeypatch):
    def chat(cfg_, system, user, **kw):
        raise client.AiError("boom", status=500, retryable=True)

    monkeypatch.setattr(client, "chat_json", chat)
    with pytest.raises(client.AiError):
        polish.run_polish(TEXTS, cfg(), chunk_cues=2)


def test_too_many_chunks_is_refused(monkeypatch):
    monkeypatch.setattr(client, "chat_json", lambda *a, **k: {"items": []})
    with pytest.raises(client.AiError) as info:
        polish.run_polish(TEXTS * 100, cfg(), chunk_cues=20)
    assert "分块太多" in str(info.value)


def test_empty_texts_rejected(monkeypatch):
    with pytest.raises(client.AiError):
        polish.run_polish([], cfg())


# --------------------------------------------------------------------------- 取消


def test_cancel_between_chunks_raises(monkeypatch):
    from core.jobs import CancelToken

    chat, state = fake_chat()
    monkeypatch.setattr(client, "chat_json", chat)

    token = CancelToken(job_id="j", session_hash="s")
    with pytest.raises(polish.AiPolishCancelled):
        polish.run_polish(
            TEXTS,
            cfg(),
            chunk_cues=2,
            cancel=token,
            on_progress=lambda ratio, stage: token.cancel(),
        )
    # 第一块跑完、第二块开始前就停了
    assert state["n"] == 1
