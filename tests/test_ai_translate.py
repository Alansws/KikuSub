"""翻译的分块、术语表与失败语义（开发文档 §6.2）。全部用替身。"""

from __future__ import annotations

import json

import pytest

from core import ai_client as client
from core import ai_proposal as proposals
from core import ai_translate as tr

TEXTS = ["おはよう", "今日は雨だ", "行ってきます", "気をつけて", "またね"]


def payload_of(user: str) -> dict:
    marker = tr.STRICT_HINT
    if marker in user:
        user = user.split(marker)[0]
    return json.loads(user)


def mock_chat(translate=None, glossary=None, drop_first=False, glossary_fails=False):
    """按调用的 system 内容区分"抽术语"还是"翻译"。"""
    state = {"glossary_calls": 0, "chunk_calls": 0, "chunk_payloads": []}

    def chat(cfg, system, user, **kw):
        if "术语整理员" in system:
            state["glossary_calls"] += 1
            if glossary_fails:
                raise client.AiError("术语表挂了", status=500)
            return {"glossary": glossary or [{"src": "雨", "dst": "rain"}]}

        state["chunk_calls"] += 1
        data = payload_of(user)
        state["chunk_payloads"].append(data)
        items = [
            {
                "i": item["i"],
                "text": translate(item["text"]) if translate else f"[{item['text']}]",
                "note": "",
            }
            for item in data["items"]
        ]
        if drop_first and state["chunk_calls"] == 1:
            items = items[:-1]
        return {"items": items}

    return chat, state


def cfg() -> client.AiConfig:
    return client.AiConfig(base_url="https://api.example.com", model="m", api_key="k")


# --------------------------------------------------------------------------- prompt


def test_prompt_has_no_timestamps_and_absolute_index():
    chunk = tr.plan_chunks(5, 3)[0]
    data = payload_of(
        tr.build_user_prompt(TEXTS, chunk, 2, [{"src": "雨", "dst": "雨"}], "zh-Hans", 2)
    )
    assert [it["i"] for it in data["items"]] == [1, 2, 3]
    assert data["dst_lang"] == "简体中文"
    assert data["glossary"] == [{"src": "雨", "dst": "雨"}]
    assert "start" not in json.dumps(data) and "end" not in json.dumps(data)


def test_prompt_carries_both_sides_of_context():
    chunk = tr.plan_chunks(5, 3)[1]
    data = payload_of(tr.build_user_prompt(TEXTS, chunk, 1, [], "en", 2))
    assert data["context_before"] == ["行ってきます"]
    assert data["context_after"] == []


# --------------------------------------------------------------------------- 单块


def test_single_chunk_skips_glossary(monkeypatch):
    """整片一次调用时模型自己就能保持全文一致，不该多花一次请求。"""
    chat, state = mock_chat()
    monkeypatch.setattr(client, "chat_json", chat)
    proposal, _, glossary = tr.run_translate(TEXTS, cfg(), dst_lang="zh-Hans", chunk_cues=200)
    assert state["glossary_calls"] == 0
    assert state["chunk_calls"] == 1
    assert glossary == []
    assert proposal["kind"] == "translate"
    assert proposal["dst_lang"] == "zh-Hans"
    assert [it["i"] for it in proposal["items"]] == [1, 2, 3, 4, 5]


def test_single_chunk_result_passes_validation(monkeypatch):
    chat, _ = mock_chat()
    monkeypatch.setattr(client, "chat_json", chat)
    proposal, _, _ = tr.run_translate(TEXTS, cfg(), dst_lang="zh-Hans", chunk_cues=200)
    assert proposals.validate_proposal(proposal, TEXTS).ok


# --------------------------------------------------------------------------- 分块 + 术语表


def test_multi_chunk_runs_glossary_once_then_chunks(monkeypatch):
    chat, state = mock_chat()
    monkeypatch.setattr(client, "chat_json", chat)
    proposal, _, glossary = tr.run_translate(TEXTS, cfg(), dst_lang="zh-Hans", chunk_cues=2)

    assert state["glossary_calls"] == 1
    assert state["chunk_calls"] == 3
    assert len(glossary) == 1
    assert proposal["glossary"] == glossary
    # 术语表注入了每一块
    for payload in state["chunk_payloads"]:
        assert payload["glossary"] == glossary


def test_glossary_failure_degrades_instead_of_aborting(monkeypatch):
    chat, state = mock_chat(glossary_fails=True)
    monkeypatch.setattr(client, "chat_json", chat)
    proposal, _, glossary = tr.run_translate(TEXTS, cfg(), dst_lang="zh-Hans", chunk_cues=2)
    assert glossary == []
    assert proposal.get("glossary") in (None, [])
    assert state["chunk_calls"] == 3


def test_glossary_is_trimmed_and_deduped_shapes(monkeypatch):
    def chat(cfg_, system, user, **kw):
        if "术语整理员" in system:
            # 混入两种写法与一条空值，都应被收拾干净
            return {
                "glossary": [
                    {"src": "千尋", "dst": "千寻"},
                    ["湯婆婆", "汤婆婆"],
                    {"src": "", "dst": "x"},
                    {"src": "同", "dst": "同"},
                ]
            }
        data = payload_of(user)
        return {"items": [{"i": it["i"], "text": "译", "note": ""} for it in data["items"]]}

    monkeypatch.setattr(client, "chat_json", chat)
    _, _, glossary = tr.run_translate(TEXTS, cfg(), dst_lang="zh-Hans", chunk_cues=2)
    assert glossary == [{"src": "千尋", "dst": "千寻"}, {"src": "湯婆婆", "dst": "汤婆婆"}]


# --------------------------------------------------------------------------- 失败与取消


def test_structure_failure_retried_once(monkeypatch):
    chat, state = mock_chat(drop_first=True)
    monkeypatch.setattr(client, "chat_json", chat)
    proposal, _, _ = tr.run_translate(TEXTS, cfg(), dst_lang="zh-Hans", chunk_cues=200)
    assert state["chunk_calls"] == 2
    assert len(proposal["items"]) == 5


def test_persistent_structure_failure_raises(monkeypatch):
    def chat(cfg_, system, user, **kw):
        if "术语整理员" in system:
            return {"glossary": []}
        return {"items": []}

    monkeypatch.setattr(client, "chat_json", chat)
    with pytest.raises(client.AiError):
        tr.run_translate(TEXTS, cfg(), dst_lang="zh-Hans", chunk_cues=200)


def test_transport_error_aborts(monkeypatch):
    def chat(*a, **kw):
        raise client.AiError("boom", status=503, retryable=True)

    monkeypatch.setattr(client, "chat_json", chat)
    with pytest.raises(client.AiError):
        tr.run_translate(TEXTS, cfg(), dst_lang="zh-Hans", chunk_cues=200)


def test_missing_dst_lang_is_rejected(monkeypatch):
    with pytest.raises(client.AiError):
        tr.run_translate(TEXTS, cfg(), dst_lang="  ")


def test_empty_texts_rejected():
    with pytest.raises(client.AiError):
        tr.run_translate([], cfg(), dst_lang="zh-Hans")


def test_cancel_between_chunks(monkeypatch):
    from core import ai_polish
    from core.jobs import CancelToken

    chat, state = mock_chat()
    monkeypatch.setattr(client, "chat_json", chat)
    token = CancelToken(job_id="j", session_hash="s")

    with pytest.raises(ai_polish.AiPolishCancelled):
        tr.run_translate(
            TEXTS,
            cfg(),
            dst_lang="zh-Hans",
            chunk_cues=2,
            cancel=token,
            on_progress=lambda ratio, stage: token.cancel() if ratio > 0.1 else None,
        )


# --------------------------------------------------------------------------- 手动粘贴通道

SRT = """1
00:00:00,500 --> 00:00:01,500
早上好

2
00:00:02,000 --> 00:00:03,000
今天下雨

3
00:00:03,500 --> 00:00:04,500
路上小心

4
00:00:05,000 --> 00:00:06,000
再见

5
00:00:06,500 --> 00:00:07,500
回头见
"""


def cues_of(texts):
    """与下面 SRT 夹具的时间码一致，避免把"夹具不同步"误判成漂移。"""
    from core.subtitles import SubtitleCue

    times = [0.5, 2.0, 3.5, 5.0, 6.5]
    return [SubtitleCue(t, t + 1.0, text) for t, text in zip(times, texts)]


def test_manual_prompt_contains_srt_and_language():
    prompt = tr.build_manual_prompt("1\n00:00:01,000 --> 00:00:02,000\nおはよう", "zh-Hans")
    assert "翻译为简体中文" in prompt
    assert "<subtitles>" in prompt and "</subtitles>" in prompt
    assert "00:00:01,000 --> 00:00:02,000" in prompt
    assert "おはよう" in prompt
    assert "严格保留原 SRT 的序号和时间戳不变" in prompt


def test_proposal_from_srt_maps_text_in_order():
    proposal, warnings = tr.proposal_from_srt(SRT, cues_of(TEXTS), "zh-Hans")
    assert [it["after"] for it in proposal["items"]] == ["早上好", "今天下雨", "路上小心", "再见", "回头见"]
    assert proposal["kind"] == "translate"
    assert proposal["dst_lang"] == "zh-Hans"
    assert proposal["entry"] == "manual"
    assert warnings == []


def test_proposal_from_srt_ignores_returned_timestamps():
    """模型把时间轴改坏了也不能影响我们——时间码一律取原文。"""
    shifted = SRT.replace("00:00:00,500 --> 00:00:01,500", "00:00:09,000 --> 00:00:11,000")
    proposal, warnings = tr.proposal_from_srt(shifted, cues_of(TEXTS), "zh-Hans")
    assert proposal["items"][0]["after"] == "早上好"
    assert any("时间戳" in w for w in warnings)


def test_proposal_from_srt_rejects_count_mismatch():
    short = "\n".join(SRT.split("\n\n")[:3]) + "\n"
    with pytest.raises(client.AiError) as info:
        tr.proposal_from_srt(short, cues_of(TEXTS), "zh-Hans")
    assert "条数对不上" in str(info.value)


def test_proposal_from_srt_rejects_garbage():
    with pytest.raises(client.AiError):
        tr.proposal_from_srt("模型说：好的，这是翻译结果。", cues_of(TEXTS), "zh-Hans")


def test_proposal_from_srt_accepts_fenced_srt():
    fenced = "```srt\n" + SRT + "```\n"
    proposal, _ = tr.proposal_from_srt(fenced, cues_of(TEXTS), "zh-Hans")
    assert len(proposal["items"]) == 5
