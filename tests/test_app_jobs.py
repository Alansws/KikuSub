"""应用层的取消归属与并发拒绝测试（需要 gradio）。"""

from __future__ import annotations

import pytest

pytest.importorskip("gradio")

import app  # noqa: E402


class FakeRequest:
    def __init__(self, session_hash: str) -> None:
        self.session_hash = session_hash


@pytest.fixture(autouse=True)
def clean_registry():
    app.JOB_REGISTRY.reset()
    yield
    app.JOB_REGISTRY.reset()


def test_trigger_cancel_only_cancels_owner(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(app.gr, "Warning", lambda message, *a, **k: warnings.append(message))

    token = app.JOB_REGISTRY.start("session-a", "会话 A 的任务")
    app.trigger_cancel(FakeRequest("session-b"))
    assert token.is_set() is False
    assert warnings and "另一个会话" in warnings[-1]

    app.trigger_cancel(FakeRequest("session-a"))
    assert token.is_set() is True
    assert app.JOB_REGISTRY.finish(token) is True


def test_trigger_cancel_without_job_is_harmless(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(app.gr, "Warning", lambda message, *a, **k: warnings.append(message))
    app.trigger_cancel(FakeRequest("session-a"))
    assert warnings and "没有正在运行" in warnings[-1]


def test_transcribe_media_rejects_second_session(tmp_path, monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(app.gr, "Warning", lambda message, *a, **k: warnings.append(message))

    media = tmp_path / "episode.mkv"
    media.write_bytes(b"")
    owner = app.JOB_REGISTRY.start("session-a", "会话 A 的转写")

    defaults = [spec.default for spec in app.PARAMS]
    generator = app.transcribe_media(
        str(media),
        next(iter(app.ENGINES)),
        "SRT",
        False,
        "",
        "",
        True,
        object(),  # progress 在 busy 分支不会被调用
        FakeRequest("session-b"),
        *defaults,
    )
    outputs = next(generator)
    assert len(outputs) == 8
    assert "已有任务在运行" in outputs[-1]
    assert warnings and "已有任务在运行" in warnings[-1]
    assert owner.is_set() is False
    assert app.JOB_REGISTRY.active() is owner


def test_selection_transcription_rejects_second_session(tmp_path, monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(app.gr, "Warning", lambda message, *a, **k: warnings.append(message))

    media = tmp_path / "episode.mkv"
    media.write_bytes(b"")
    owner = app.JOB_REGISTRY.start("session-a", "会话 A 的转写")

    generator = app.transcribe_selection_to_editor(
        str(media),
        next(iter(app.ENGINES)),
        "00:00:01,000",
        "00:00:02,000",
        [],
        [],
        [],
        FakeRequest("session-b"),
        *[spec.default for spec in app.PARAMS],
    )
    outputs = next(generator)
    assert len(outputs) == 10
    assert "已有任务" in outputs[7]
    assert owner.is_set() is False
    assert app.JOB_REGISTRY.active() is owner
