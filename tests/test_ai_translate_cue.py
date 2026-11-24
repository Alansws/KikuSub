"""单句补译：提示词材料、输出校验与「失败重问一次」。"""

from __future__ import annotations

import json

import pytest

from core import ai_client
from core import ai_translate_cue as cue


def test_prompt_carries_context_and_existing_translation_but_no_timecode():
    prompt = cue.build_prompt(
        "私に",
        before=["これから 7日間", "分かってるかもしれないけど"],
        after=["されるってこと"],
        refs=[{"src": "これから 7日間", "dst": "接下来的7天"}],
        dst_lang="zh-Hans",
    )
    payload = json.loads(prompt)
    assert payload["target"]["text"] == "私に"
    assert payload["context_before"][-1] == "分かってるかもしれないけど"
    assert payload["context_after"] == ["されるってこと"]
    assert payload["references"] == [{"src": "これから 7日間", "dst": "接下来的7天"}]
    assert payload["dst_lang"] == "简体中文"
    assert "-->" not in prompt and "00:01" not in prompt


def test_prompt_drops_context_when_over_budget():
    long = "あ" * cue.MAX_TEXT_CHARS
    prompt = cue.build_prompt(
        "本句", before=[long] * 8, after=[long] * 8, refs=[{"src": long, "dst": "啊" * 60}] * 8
    )
    assert len(prompt) <= cue.MAX_PROMPT_CHARS
    assert json.loads(prompt)["target"]["text"] == "本句"


def test_context_keeps_nearest_four_and_drops_empty():
    prompt = cue.build_prompt(
        "本句",
        before=["1", "", "2", "3", "4", "5"],
        after=["", "a", "b", "c", "d", "e"],
    )
    payload = json.loads(prompt)
    assert payload["context_before"] == ["2", "3", "4", "5"]
    assert payload["context_after"] == ["a", "b", "c", "d"]


def test_parse_result_normalizes_and_truncates_note():
    out = cue.parse_result({"text": "  你\n明白吗  ", "note": "n" * 200})
    assert out["text"] == "你 明白吗"
    assert len(out["note"]) == cue.MAX_NOTE_CHARS


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {},
        {"text": ""},
        {"text": "   "},
        {"text": 123},
        {"text": "字" * (cue.MAX_OUT_CHARS + 1)},
        {"text": "08:00:00 了一句"},
        {"text": "A --> B"},
    ],
)
def test_parse_result_rejects_unusable_output(data):
    with pytest.raises(cue.CueTranslateError):
        cue.parse_result(data)


def _config() -> ai_client.AiConfig:
    return ai_client.AiConfig(
        base_url="http://127.0.0.1:1234/v1",
        model="qwen-test",
        api_key="",
        allow_no_key=True,
    )


def test_translate_cue_retries_once_with_strict_hint(monkeypatch):
    calls = []

    def fake_chat_json(config, system, user, **kwargs):
        calls.append(user)
        if len(calls) == 1:
            return {"text": ""}
        return {"text": "你明白吗"}

    monkeypatch.setattr(cue.client, "chat_json", fake_chat_json)
    out = cue.translate_cue("わかってる？", _config(), dst_lang="zh-Hans")
    assert out["text"] == "你明白吗"
    assert len(calls) == 2
    assert cue.STRICT_HINT.strip() in calls[1]


def test_translate_cue_rejects_blank_source():
    with pytest.raises(cue.CueTranslateError):
        cue.translate_cue("   ", _config())
