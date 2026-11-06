"""重任务互斥与取消令牌。

背景：Gradio 的队列默认允许 4 个事件并发，而模型引擎是进程内单例。
如果沿用「模块级 threading.Event」，两个浏览器会话会互相打断，统计字段也会
互相覆盖。这里把「谁能取消谁」收敛到一个显式注册表：

* 同一时刻只允许一个重任务（转写/局部转写）持有令牌；
* 令牌归属于发起它的 Gradio session；
* 只有令牌所属 session 才能取消它，别的会话点「打断」什么也不会发生；
* 任务结束（包括异常/客户端断开）必须调用 ``finish`` 释放槽位。

本模块只依赖标准库，便于在轻量 CI 中直接测试。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


class JobBusy(RuntimeError):
    """已有任务在运行；``active`` 是占用槽位的令牌。"""

    def __init__(self, active: "CancelToken") -> None:
        self.active = active
        super().__init__(f"已有任务在运行：{active.label or active.job_id}")


@dataclass
class CancelToken:
    """一次任务的取消令牌。

    引擎只依赖 ``is_set()``，因此可以直接把令牌传给现有的 ``cancel_event`` 参数；
    它比裸 ``threading.Event`` 多带了任务名、会话和创建时间，方便日志定位。
    """

    job_id: str
    session_hash: str
    label: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    _event: threading.Event = field(default_factory=threading.Event, repr=False)

    def cancel(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    @property
    def finished(self) -> bool:
        return self.finished_at is not None

    def short_id(self) -> str:
        return self.job_id[:8]


class JobRegistry:
    """进程内单槽任务注册表（线程安全）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: CancelToken | None = None

    @staticmethod
    def _session(session_hash: str | None) -> str:
        # Gradio 正常会给 session_hash；直接调用时退化为固定匿名会话，
        # 仍然保持「只有同一会话可取消」的语义。
        return session_hash or "anonymous"

    def start(self, session_hash: str | None, label: str = "") -> CancelToken:
        """占用槽位并返回新令牌；已被占用时抛出 :class:`JobBusy`。"""
        with self._lock:
            if self._active is not None and not self._active.finished:
                raise JobBusy(self._active)
            token = CancelToken(
                job_id=uuid.uuid4().hex,
                session_hash=self._session(session_hash),
                label=label,
            )
            self._active = token
            return token

    def finish(self, token: CancelToken | None) -> bool:
        """释放槽位；只有当前持有者能释放，重复调用是安全的。"""
        if token is None:
            return False
        with self._lock:
            owned = self._active is token
            if owned:
                self._active = None
            token.finished_at = token.finished_at or time.time()
        return owned

    def cancel_for_session(self, session_hash: str | None) -> tuple[bool, str]:
        """取消该会话自己的任务。

        返回 ``(是否真的发出了取消, 给用户的说明)``。别的会话的任务永远不会被取消。
        """
        with self._lock:
            token = self._active
        if token is None or token.finished:
            return False, "当前会话没有正在运行的转写任务。"
        if token.session_hash != self._session(session_hash):
            return False, (
                "另一个会话正在转写，本会话没有可打断的任务；"
                "为避免误伤，已忽略本次打断请求。"
            )
        token.cancel()
        return True, f"已向任务 {token.short_id()} 发送打断指令。"

    def active(self) -> CancelToken | None:
        with self._lock:
            return self._active

    def busy_reason(self) -> str:
        token = self.active()
        if token is None or token.finished:
            return ""
        return (
            f"已有转写任务在运行（{token.label or token.short_id()}）。"
            "同一时间只允许一个任务；请等它结束，或由发起它的窗口点「中断打断」。"
        )

    def reset(self) -> None:
        """主要给测试用：强制清空槽位。"""
        with self._lock:
            if self._active is not None:
                self._active.finished_at = self._active.finished_at or time.time()
            self._active = None
