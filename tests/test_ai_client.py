"""AI 客户端：解析、重试、取消、密钥不外泄（开发文档 §5.3.1）。

全部用替身 `_post`，不打真实网络。
"""

from __future__ import annotations

import json

import pytest

from core import ai_client as client


def envelope(payload: dict) -> str:
    """OpenAI 兼容的响应外壳，content 里放我们要的 JSON。"""
    return json.dumps(
        {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]},
        ensure_ascii=False,
    )


def cfg(**kw) -> client.AiConfig:
    base = client.AiConfig(base_url="https://api.example.com/v1", model="m", api_key="sk-secret")
    for key, value in kw.items():
        setattr(base, key, value)
    return base


# --------------------------------------------------------------------------- 基础


def test_chat_json_returns_parsed_object(monkeypatch):
    calls = []

    def fake(url, payload, conf):
        calls.append((url, payload))
        return 200, envelope({"items": [{"i": 1, "text": "あ"}]})

    monkeypatch.setattr(client, "_post", fake)
    out = client.chat_json(cfg(), "sys", "user")
    assert out == {"items": [{"i": 1, "text": "あ"}]}
    assert calls[0][0] == "https://api.example.com/v1/chat/completions"


def test_endpoint_accepts_full_url():
    assert client.endpoint("https://x/v1") == "https://x/v1/chat/completions"
    assert client.endpoint("https://x/v1/") == "https://x/v1/chat/completions"
    assert (
        client.endpoint("https://x/v1/chat/completions") == "https://x/v1/chat/completions"
    )


def test_json_from_text_strips_markdown_fence():
    assert client.json_from_text('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_from_text_finds_object_inside_prose():
    assert client.json_from_text('好的，结果如下：{"a": 2} 以上。') == {"a": 2}


def test_json_from_text_rejects_non_json():
    with pytest.raises(client.AiError):
        client.json_from_text("这不是 JSON")


# --------------------------------------------------------------------------- 配置校验


def test_ensure_ready_rejects_missing_key():
    with pytest.raises(client.AiError) as info:
        cfg(api_key="").ensure_ready()
    assert "API Key" in str(info.value)


def test_ensure_ready_rejects_missing_model():
    with pytest.raises(client.AiError):
        cfg(model="").ensure_ready()


def test_ensure_ready_rejects_bad_scheme():
    with pytest.raises(client.AiError):
        cfg(base_url="ftp://x").ensure_ready()


# --------------------------------------------------------------------------- 重试


def test_retries_5xx_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    def fake(url, payload, conf):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return 503, "upstream down"
        return 200, envelope({"ok": True})

    monkeypatch.setattr(client, "_post", fake)
    monkeypatch.setattr(client, "RETRY_BACKOFF", (0.0, 0.0))
    assert client.chat_json(cfg(), "s", "u") == {"ok": True}
    assert attempts["n"] == 2


def test_gives_up_after_retries(monkeypatch):
    def fake(url, payload, conf):
        return 500, "boom"

    monkeypatch.setattr(client, "_post", fake)
    monkeypatch.setattr(client, "RETRY_BACKOFF", (0.0, 0.0))
    with pytest.raises(client.AiError) as info:
        client.chat_json(cfg(), "s", "u", retries=1)
    assert info.value.status == 500


def test_does_not_retry_401(monkeypatch):
    attempts = {"n": 0}

    def fake(url, payload, conf):
        attempts["n"] += 1
        return 401, "bad key"

    monkeypatch.setattr(client, "_post", fake)
    with pytest.raises(client.AiError):
        client.chat_json(cfg(), "s", "u")
    assert attempts["n"] == 1


def test_falls_back_when_gateway_rejects_response_format(monkeypatch):
    seen = []

    def fake(url, payload, conf):
        seen.append(dict(payload))
        if "response_format" in payload:
            return 400, '{"error":"response_format is not supported"}'
        return 200, envelope({"ok": True})

    monkeypatch.setattr(client, "_post", fake)
    assert client.chat_json(cfg(), "s", "u") == {"ok": True}
    assert "response_format" in seen[0]
    assert "response_format" not in seen[1]


# --------------------------------------------------------------------------- 安全


def test_key_never_leaks_into_errors(monkeypatch):
    def fake(url, payload, conf):
        return 401, "invalid api key sk-secret for this request"

    monkeypatch.setattr(client, "_post", fake)
    with pytest.raises(client.AiError) as info:
        client.chat_json(cfg(), "s", "u")
    # 异常文本只带状态码与消息，不带 Authorization 头本身
    assert "Bearer" not in str(info.value)


def test_config_repr_hides_key():
    assert "sk-secret" not in repr(cfg())


# --------------------------------------------------------------------------- 取消


def test_cancel_before_request_stops_immediately(monkeypatch):
    from core.jobs import CancelToken

    def fake(url, payload, conf):
        raise AssertionError("取消后不应再发请求")

    monkeypatch.setattr(client, "_post", fake)
    token = CancelToken(job_id="j", session_hash="s")
    token.cancel()
    with pytest.raises(client.AiCancelled):
        client.chat_json(cfg(), "s", "u", cancel=token)


# --------------------------------------------------------------------------- 测试连接


def test_connection_reports_latency(monkeypatch):
    monkeypatch.setattr(client, "_post", lambda *a: (200, envelope({"ok": True})))
    result = client.test_connection(cfg())
    assert result["ok"] is True
    assert result["host"] == "api.example.com"
    assert isinstance(result["latency_ms"], int)


def test_unrelated_400_still_tries_plain_once_then_reports(monkeypatch):
    """400 未必是 response_format 引起的：降级一次后仍失败，要如实上报，不能吞掉。"""
    seen = []

    def fake(url, payload, conf):
        seen.append("plain" if "response_format" not in payload else "json")
        return 400, '{"error":"model not found"}'

    monkeypatch.setattr(client, "_post", fake)
    with pytest.raises(client.AiError) as info:
        client.chat_json(cfg(), "s", "u")
    assert seen == ["json", "plain"]
    assert info.value.status == 400
    assert "model not found" in info.value.detail


def test_json_from_text_strips_think_and_fence():
    text = '好的。\n<think>先想一下，不要输出这个。</think>\n```json\n{"text": "もっと"}\n```'
    assert client.json_from_text(text) == {"text": "もっと"}


def test_json_from_text_strips_special_tokens():
    assert client.json_from_text('<|im_start|>{"ok": true}<|im_end|>') == {"ok": True}


def test_ensure_ready_allows_no_key_for_local():
    client.AiConfig(
        base_url="http://127.0.0.1:1234/v1", model="local", api_key="", allow_no_key=True
    ).ensure_ready()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1:1234/v1", True),
        ("http://localhost:11434/v1", True),
        ("http://[::1]:8080/v1", True),
        ("http://192.168.1.20:1234/v1", True),
        ("http://10.0.0.5:8000/v1", True),
        ("http://my-mac.local:1234/v1", True),
        ("http://host.docker.internal:1234/v1", True),
        ("https://api.deepseek.com", False),
        ("https://example.com/v1", False),
        ("not a url", False),
    ],
)
def test_is_local_url(url, expected):
    assert client.is_local_url(url) is expected


def test_post_omits_authorization_when_key_empty(monkeypatch):
    seen = []

    class Response:
        status = 200

        def read(self):
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        seen.append(request)
        return Response()

    monkeypatch.setattr(client.urllib.request, "urlopen", fake_urlopen)
    status, _ = client._post(
        "http://127.0.0.1:1234/v1/chat/completions",
        {"model": "local"},
        client.AiConfig(base_url="http://127.0.0.1:1234/v1", model="local", allow_no_key=True),
    )
    assert status == 200
    assert seen[0].get_header("Authorization") is None


def test_post_sends_authorization_when_key_present(monkeypatch):
    seen = []

    class Response:
        status = 200

        def read(self):
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(client.urllib.request, "urlopen", lambda request, timeout: (seen.append(request) or Response()))
    client._post(
        "https://api.example.com/v1/chat/completions",
        {"model": "m"},
        client.AiConfig(base_url="https://api.example.com/v1", model="m", api_key="sk-secret"),
    )
    assert seen[0].get_header("Authorization") == "Bearer sk-secret"


def test_falls_back_on_422_response_format(monkeypatch):
    seen = []

    def fake(url, payload, conf):
        seen.append("response_format" in payload)
        if "response_format" in payload:
            return 422, "unsupported field"
        return 200, envelope({"ok": True})

    monkeypatch.setattr(client, "_post", fake)
    assert client.chat_json(cfg(), "s", "u") == {"ok": True}
    assert seen == [True, False]


def test_extract_content_falls_back_to_reasoning_content():
    body = json.dumps(
        {
            "choices": [
                {"message": {"content": "", "reasoning_content": '{"text": "ok"}'}}
            ]
        }
    )
    assert client._extract_content(body) == '{"text": "ok"}'
    assert client.json_from_text(client._extract_content(body)) == {"text": "ok"}
