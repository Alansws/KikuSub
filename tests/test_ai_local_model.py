"""本地 LM Studio 上下文档位：只做 loopback、卸载后重载、状态探测。"""

from __future__ import annotations

import pytest

from core import ai_local_model as lm


def test_is_loopback():
    assert lm.is_loopback("http://127.0.0.1:1234/v1")
    assert lm.is_loopback("http://localhost:1234/v1")
    assert lm.is_loopback("http://[::1]:1234/v1")
    assert not lm.is_loopback("http://192.168.1.9:1234/v1")
    assert not lm.is_loopback("https://api.deepseek.com")


def _row(context: int | None):
    instances = []
    if context is not None:
        instances.append({"id": "local-model", "config": {"context_length": context}})
    return {
        "key": "local-model",
        "loaded_instances": instances,
        "max_context_length": 262144,
    }


def test_status_reports_loaded_context(monkeypatch):
    monkeypatch.setattr(lm, "_models", lambda base_url, timeout=4.0: [_row(8192)])
    out = lm.status("http://127.0.0.1:1234/v1", "local-model")
    assert out["available"] is True
    assert out["loaded"] is True
    assert out["context_length"] == 8192


def test_status_not_local():
    out = lm.status("http://192.168.1.9:1234/v1", "local-model")
    assert out["available"] is False
    assert out["reason"] == "not_local"


def test_status_missing_model(monkeypatch):
    monkeypatch.setattr(lm, "_models", lambda base_url, timeout=4.0: [_row(None)])
    out = lm.status("http://127.0.0.1:1234/v1", "other")
    assert out["available"] is False
    assert out["reason"] == "model_missing"


def test_load_unloads_then_reloads_at_requested_context(monkeypatch):
    state = {"context": 8192}
    calls = []

    def fake_models(base_url, timeout=4.0):
        return [_row(state["context"])]

    def fake_request(method, url, payload=None, timeout=5.0):
        calls.append((method, url, payload))
        if url.endswith("/api/v1/models/unload"):
            state["context"] = None
            return {"instance_id": payload["instance_id"]}
        if url.endswith("/api/v1/models/load"):
            assert payload["context_length"] == 2048
            state["context"] = 2048
            return {"status": "loaded", "load_time_seconds": 3.2}
        raise AssertionError(f"unexpected {method} {url}")

    monkeypatch.setattr(lm, "_models", fake_models)
    monkeypatch.setattr(lm, "_request_json", fake_request)
    out = lm.load("http://127.0.0.1:1234/v1", "local-model", 2048)
    assert out["reloaded"] is True
    assert out["context_length"] == 2048
    assert [call[1].rsplit("/", 1)[-1] for call in calls] == ["unload", "load"]
    assert calls[0][2] == {"instance_id": "local-model"}


def test_load_same_context_is_noop(monkeypatch):
    monkeypatch.setattr(lm, "_models", lambda base_url, timeout=4.0: [_row(2048)])
    monkeypatch.setattr(
        lm, "_request_json", lambda *a, **kw: pytest.fail("不应重载")
    )
    out = lm.load("http://127.0.0.1:1234/v1", "local-model", 2048)
    assert out["reloaded"] is False


def test_load_rejects_remote_and_bad_context():
    with pytest.raises(lm.LocalModelError):
        lm.load("http://192.168.1.9:1234/v1", "local-model", 2048)
    with pytest.raises(lm.LocalModelError):
        lm.load("http://127.0.0.1:1234/v1", "local-model", 1024)
