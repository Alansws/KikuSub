"""run_command 的超时/取消/输出捕获测试（无第三方依赖）。"""

from __future__ import annotations

import sys
import threading
import time

import pytest

from core.procutil import CommandCancelled, CommandTimeout, run_command, tail


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_returns_stdout_and_returncode():
    result = run_command(_python("print('hello')"))
    assert result.returncode == 0
    assert "hello" in result.stdout


def test_captures_stderr_and_nonzero_returncode():
    result = run_command(
        _python("import sys; print('bad', file=sys.stderr); sys.exit(3)")
    )
    assert result.returncode == 3
    assert "bad" in result.stderr


def test_timeout_terminates_process_promptly():
    started = time.monotonic()
    with pytest.raises(CommandTimeout) as info:
        run_command(_python("import time; time.sleep(30)"), timeout=0.3)
    elapsed = time.monotonic() - started
    assert elapsed < 5.0
    assert info.value.timeout == pytest.approx(0.3)


def test_cancel_event_terminates_process():
    cancel = threading.Event()
    threading.Timer(0.25, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(CommandCancelled):
        run_command(
            _python("import time; time.sleep(30)"),
            timeout=30,
            cancel_event=cancel,
            poll_interval=0.05,
        )
    assert time.monotonic() - started < 5.0


def test_already_cancelled_event_does_not_run_to_completion():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(CommandCancelled):
        run_command(_python("import time; time.sleep(5)"), cancel_event=cancel)
    # 能走到这里说明没有等满 5 秒；具体耗时由 terminate 决定


def test_tail_keeps_the_end():
    text = "a" * 5000 + "KEY"
    result = tail(text, 100)
    assert result.endswith("KEY")
    assert len(result) <= 101
