"""可取消、带超时的子进程执行器。

ffmpeg/ffprobe 这类外部命令如果用 ``subprocess.run`` 阻塞执行，会出现两个问题：

1. 没有超时：损坏文件/等待 stdin 时线程会永久卡住；
2. 无法取消：用户点「打断」后，解码阶段仍要等 ffmpeg 自己结束。

``run_command`` 用 Popen + 读线程 + 轮询实现这两件事，并在取消/超时时
``terminate -> wait(3s) -> kill``，保证不留下孤儿进程。

本模块只依赖标准库，便于在轻量 CI 中直接测试。
"""

from __future__ import annotations

import atexit
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


# 进程内所有由本模块启动的子进程。sidecar 收到 SIGTERM / 父进程消失时，必须
# 把它们一起带走——ffmpeg 是长命进程，光让 Python 退出会把它留给 launchd 继续
# 编码（用户报过「应用都退出了视频还在导出」）。
_ACTIVE_PROCS: set[subprocess.Popen] = set()
_ACTIVE_LOCK = threading.Lock()
# 进程正在关闭时禁止再启动新的外部命令。没有这道闸门，sidecar 收到 SIGTERM
# 后正在收尾，导出线程仍可能再 spawn 一个 ffmpeg；它会成为信号发出后才出生的
# 孤儿进程（用户报过「应用退出了视频还在导出」）。
_SHUTTING_DOWN = threading.Event()
# spawn 与「开始关机」互斥：begin_shutdown() 返回之后，不可能再有新子进程
# 在注册表之外出生。调用方必须把 check + Popen + register 放进这个锁。
SPAWN_LOCK = threading.Lock()


def begin_shutdown() -> None:
    # 先等正在进行的 spawn 完成并登记，再落下闸门；这样 terminate_all_processes
    # 一定能看到刚才那个子进程。拿不到锁（例如解释器退出时线程被冻结）也要落下
    # 闸门：宁可漏掉一次登记，也不能让退出流程卡死在锁上。
    acquired = SPAWN_LOCK.acquire(timeout=1.0)
    try:
        _SHUTTING_DOWN.set()
    finally:
        if acquired:
            SPAWN_LOCK.release()


def reset_shutdown() -> None:
    with SPAWN_LOCK:
        _SHUTTING_DOWN.clear()


def is_shutting_down() -> bool:
    return _SHUTTING_DOWN.is_set()


def register_process(proc: subprocess.Popen) -> None:
    with _ACTIVE_LOCK:
        _ACTIVE_PROCS.add(proc)


def unregister_process(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    with _ACTIVE_LOCK:
        _ACTIVE_PROCS.discard(proc)


def active_processes() -> list[subprocess.Popen]:
    with _ACTIVE_LOCK:
        return list(_ACTIVE_PROCS)


def terminate_all_processes(grace_s: float = 2.0) -> int:
    """终止本进程启动的所有子进程；返回尝试终止的数量。

    幂等、可重复调用；`atexit` 会再兜一次底。先 SIGTERM 再 SIGKILL，
    保证 ffmpeg 不会因为正在写文件而赖着不退。
    """
    procs = active_processes()
    for proc in procs:
        try:
            terminate_process(proc, grace_s=grace_s)
        except Exception:  # noqa: BLE001 - 收尾阶段不能再抛异常
            pass
        unregister_process(proc)
    return len(procs)


def _atexit_cleanup() -> None:
    try:
        terminate_all_processes(1.5)
    except Exception:  # noqa: BLE001
        pass


atexit.register(_atexit_cleanup)


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
    with SPAWN_LOCK:
        if _SHUTTING_DOWN.is_set():
            raise CommandCancelled(argv)
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        register_process(proc)
    if _SHUTTING_DOWN.is_set():
        # 闸门在 spawn 之后才落下：不要把这个刚出生的子进程留给 launchd
        terminate_process(proc)
        unregister_process(proc)
        raise CommandCancelled(argv)
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
        unregister_process(proc)

    stdout = "".join(out_chunks)
    stderr = "".join(err_chunks)
    if cancelled:
        raise CommandCancelled(argv, tail(stderr))
    if timed_out:
        raise CommandTimeout(argv, float(timeout or 0.0), tail(stderr))
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)
