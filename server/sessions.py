"""会话状态：替代 Gradio 的 `gr.State`。

旧实现把四份状态放在 `gr.State` 里（转写结果 / 核对基线 / 撤销栈 / 重做栈），
只能被 Gradio 的会话机制持有。新架构改成 **`session_id` cookie + 进程内字典**，
沿用规划 §4 的结论：服务端仍是唯一真源，前端撤销栈只做乐观回显。

一个会话同一时间只服务一个媒体文件（和桌面端「一次核对一部片」的用法一致）。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from core.subtitles import SubtitleCue

# 撤销栈上限：100 步足够覆盖一次核对里的连续操作，再大只是占内存。
UNDO_LIMIT = 100
# 会话空闲多久回收（秒）。桌面端通常只有一个会话，这里防的是频繁开关窗口。
SESSION_TTL_S = 12 * 3600


def _copy(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    return [SubtitleCue(start=c.start, end=c.end, text=c.text) for c in cues]


@dataclass
class Session:
    id: str
    media_id: str | None = None
    # 最近一次转写结果
    latest_cues: list[SubtitleCue] = field(default_factory=list)
    # 核对基线（可编辑，所有 cue 增删改都作用在它上面）
    review_cues: list[SubtitleCue] = field(default_factory=list)
    undo_stack: list[list[SubtitleCue]] = field(default_factory=list)
    redo_stack: list[list[SubtitleCue]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)
    # 转写任务在 worker 线程里回写结果，请求线程同时在读；一把会话锁避免
    # 「列表一半是旧结果一半是新结果」这种撕裂。
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # -- 历史 ---------------------------------------------------------------

    def _push_history(self) -> None:
        self.undo_stack.append(_copy(self.review_cues))
        if len(self.undo_stack) > UNDO_LIMIT:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.updated_at = time.time()

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(_copy(self.review_cues))
        self.review_cues = self.undo_stack.pop()
        self.updated_at = time.time()
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(_copy(self.review_cues))
        self.review_cues = self.redo_stack.pop()
        self.updated_at = time.time()
        return True

    # -- 变更（全部返回是否成功，越界不抛异常） ------------------------------

    def replace_review(self, cues: list[SubtitleCue]) -> None:
        self._push_history()
        self.review_cues = _copy(cues)

    def update_cue(self, index: int, start: float, end: float, text: str) -> bool:
        if not 0 <= index < len(self.review_cues):
            return False
        self._push_history()
        self.review_cues[index] = SubtitleCue(start=start, end=end, text=text)
        return True

    def delete_cue(self, index: int) -> bool:
        if not 0 <= index < len(self.review_cues):
            return False
        self._push_history()
        del self.review_cues[index]
        return True

    def insert_cue(self, index: int, start: float, end: float, text: str) -> bool:
        if not 0 <= index <= len(self.review_cues):
            return False
        self._push_history()
        self.review_cues.insert(index, SubtitleCue(start=start, end=end, text=text))
        return True

    def clear_review(self) -> None:
        self._push_history()
        self.review_cues = []


class SessionStore:
    """线程安全的会话表。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, Session] = {}

    def get(self, session_id: str | None) -> Session:
        with self._lock:
            if session_id:
                found = self._sessions.get(session_id)
                if found is not None:
                    found.updated_at = time.time()
                    return found
            sid = session_id or uuid.uuid4().hex
            session = Session(id=sid)
            self._sessions[sid] = session
            self._prune_locked()
            return session

    def peek(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _prune_locked(self) -> None:
        now = time.time()
        stale = [
            sid for sid, s in self._sessions.items() if now - s.updated_at > SESSION_TTL_S
        ]
        for sid in stale:
            self._sessions.pop(sid, None)
