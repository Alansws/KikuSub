"""JobRegistry / CancelToken 的并发语义测试（无第三方依赖）。"""

from __future__ import annotations

import threading
import time

import pytest

from jobs import JobBusy, JobRegistry


def test_start_and_finish_release_slot():
    registry = JobRegistry()
    token = registry.start("session-a", "转写 A")
    assert registry.active() is token
    assert token.is_set() is False

    assert registry.finish(token) is True
    assert registry.active() is None
    assert token.finished is True


def test_second_start_is_rejected_while_active():
    registry = JobRegistry()
    first = registry.start("session-a", "转写 A")
    with pytest.raises(JobBusy) as info:
        registry.start("session-b", "转写 B")
    assert info.value.active is first
    assert "转写 A" in registry.busy_reason()


def test_only_owner_session_can_cancel():
    registry = JobRegistry()
    token = registry.start("session-a", "转写 A")

    ok, _ = registry.cancel_for_session("session-b")
    assert ok is False
    assert token.is_set() is False

    ok, message = registry.cancel_for_session("session-a")
    assert ok is True
    assert token.is_set() is True
    assert token.short_id() in message


def test_cancel_without_active_job_is_harmless():
    registry = JobRegistry()
    ok, message = registry.cancel_for_session("session-a")
    assert ok is False
    assert "没有正在运行" in message


def test_stale_finish_cannot_release_new_job():
    registry = JobRegistry()
    first = registry.start("session-a", "第一个")
    registry.finish(first)
    second = registry.start("session-b", "第二个")

    assert registry.finish(first) is False
    assert registry.active() is second


def test_anonymous_sessions_still_isolated():
    registry = JobRegistry()
    token = registry.start(None, "匿名任务")
    # None 会被规范化为 anonymous；未知会话不能取消它
    ok, _ = registry.cancel_for_session("someone-else")
    assert ok is False
    ok, _ = registry.cancel_for_session(None)
    assert ok is True
    assert token.is_set()


def test_cancel_event_can_wake_waiters():
    registry = JobRegistry()
    token = registry.start("s", "等待")
    woke = threading.Event()

    def waiter():
        token.wait(2.0)
        woke.set()

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.05)
    token.cancel()
    assert woke.wait(1.0)
    thread.join(timeout=1.0)


def test_reset_clears_slot():
    registry = JobRegistry()
    token = registry.start("s", "x")
    registry.reset()
    assert registry.active() is None
    assert token.finished is True
    # reset 后可以重新占用
    registry.start("s2", "y")
