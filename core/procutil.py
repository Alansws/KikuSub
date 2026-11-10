"""可取消、带超时的子进程执行器。

ffmpeg/ffprobe 这类外部命令如果用 ``subprocess.run`` 阻塞执行，会出现两个问题：

1. 没有超时：损坏文件/等待 stdin 时线程会永久卡住；
2. 无法取消：用户点「打断」后，解码阶段仍要等 ffmpeg 自己结束。

``run_command`` 用 Popen + 读线程 + 轮询实现这两件事，并在取消/超时时
``terminate -> wait(3s) -> kill``，保证不留下孤儿进程。

本模块只依赖标准库，便于在轻量 CI 中直接测试。
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Protocol, Sequence


class _CancelLike(Protocol):
    def is_set(self) -> bool: ...


class CommandCancelled(RuntimeError):
    """调用方通过 cancel_event 取消了命令。"""

    def __init__(self, cmd: Sequence[str], stderr: str = "") -> None:
        self.cmd = list(cmd)
        self.stderr = stderr
        super().__init__(f"命令已取消：{Path(str(self.cmd[0])).name if self.cmd else '?'}")


class CommandTimeout(RuntimeError):
    """命令超过 timeout 秒仍未结束。"""

    def __init__(self, cmd: Sequence[str], timeout: float, stderr: str = "") -> None:
        self.cmd = list(cmd)
        self.timeout = timeout
        self.stderr = stderr
        super().__init__(f"命令超时（>{timeout:.0f}s）：{Path(str(self.cmd[0])).name if self.cmd else '?'}")


def tail(text: str | None, limit: int = 2000) -> str:
    """取文本末尾，用于错误信息和日志，避免把几 MB 的 ffmpeg 日志全塞进界面。"""
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return "…" + value[-limit:]


def terminate_process(proc: subprocess.Popen, grace_s: float = 3.0) -> None:
    """优雅终止，超时再强杀。对已退出进程是 no-op。"""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except OSError:
        return
    try:
        proc.wait(timeout=grace_s)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except OSError:
        return
    try:
        proc.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        pass


def _drain(pipe, sink: list[str]) -> None:
    try:
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                break
            sink.append(chunk)
    except Exception:
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def run_command(
    cmd: Sequence[str | Path],
    *,
    timeout: float | None = None,
    cancel_event: _CancelLike | None = None,
    poll_interval: float = 0.1,
) -> subprocess.CompletedProcess:
    """执行命令并返回 CompletedProcess；非零退出码由调用方判断。

    超时抛 :class:`CommandTimeout`，取消抛 :class:`CommandCancelled`；
    两种情况都会先终止子进程再抛异常。
    """
    argv = [str(part) for part in cmd]
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None and proc.stderr is not None
    out_chunks: list[str] = []
    err_chunks: list[str] = []
    readers = [
        threading.Thread(target=_drain, args=(proc.stdout, out_chunks), daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, err_chunks), daemon=True),
    ]
    for reader in readers:
        reader.start()

    deadline = (time.monotonic() + timeout) if timeout and timeout > 0 else None
    cancelled = False
    timed_out = False
    try:
        while proc.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                terminate_process(proc)
                break
            if deadline is not None and time.monotonic() >= deadline:
                timed_out = True
                terminate_process(proc)
                break
            time.sleep(max(0.02, poll_interval))
        returncode = proc.wait()
    finally:
        for reader in readers:
            reader.join(timeout=2.0)

    stdout = "".join(out_chunks)
    stderr = "".join(err_chunks)
    if cancelled:
        raise CommandCancelled(argv, tail(stderr))
    if timed_out:
        raise CommandTimeout(argv, float(timeout or 0.0), tail(stderr))
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)
