"""ASR 引擎的空闲卸载（P1-1）。

为什么需要它：换引擎复核要先把当前引擎卸掉再装另一个（两个日语引擎同时常驻在
16GB 机器上会换页）。但核对台里连续单条复核时，如果每跑完一句就 `unload()`，
用户会每句都等 20–40s 冷加载。所以：

- **空闲超过 `idle_seconds` 才卸载**（默认 180s，`KIKUSUB_ASR_IDLE_SECONDS` 可覆盖）；
- 每次真正跑片都 `touch()`，连续复核期间不会被卸；
- 整片任务开始时 `release_others(keep=本轮引擎)` 立即把**另一个**引擎让出去，
  但不碰本轮要用的那个。

与 TTS 的 `TTSManager` 是同一种策略（它的默认空闲是 5 分钟），区别是这里只管
ASR 引擎、而且卸载动作委托给 `core.pipeline.release_engine`（唯一出口）。
"""

from __future__ import annotations

import logging
import os
import threading
import time

log = logging.getLogger(__name__)

DEFAULT_IDLE_SECONDS = 180.0
DEFAULT_POLL_SECONDS = 5.0
ENV_IDLE = "KIKUSUB_ASR_IDLE_SECONDS"


def _default_release(engine_key: str) -> bool:
    from .pipeline import release_engine

    return release_engine(engine_key)


class EngineIdleReleaser:
    """记录「哪个引擎最近被用过」，空闲到点就卸载。线程安全。"""

    def __init__(
        self,
        *,
        idle_seconds: float | None = None,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        clock=time.monotonic,
        release=None,
        autostart: bool = True,
    ) -> None:
        raw = idle_seconds
        if raw is None:
            try:
                raw = float(os.environ.get(ENV_IDLE) or DEFAULT_IDLE_SECONDS)
            except ValueError:
                raw = DEFAULT_IDLE_SECONDS
        # 下限 10s：再短就不是"空闲卸载"，而是给每次点击加一次冷启动。
        self.idle_seconds = max(10.0, float(raw))
        self.poll_seconds = max(0.1, float(poll_seconds))
        self._clock = clock
        self._release = release or _default_release
        self._last_used: dict[str, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._autostart = autostart

    # -- 使用记录 ----------------------------------------------------------

    def touch(self, engine_key: str) -> None:
        """标记引擎刚被用过；顺带把「要不要起后台线程」解决掉。"""
        with self._lock:
            self._last_used[engine_key] = self._clock()
        if self._autostart:
            self._ensure_thread()

    def touched(self) -> list[str]:
        with self._lock:
            return sorted(self._last_used)

    # -- 卸载 --------------------------------------------------------------

    def sweep(self) -> list[str]:
        """卸载所有空闲超时的引擎，返回被卸载的键（测试直接调它，不用等线程）。"""
        now = self._clock()
        with self._lock:
            expired = [
                (key, used)
                for key, used in self._last_used.items()
                if now - used >= self.idle_seconds
            ]
            for key, _used in expired:
                self._last_used.pop(key, None)
        released: list[str] = []
        for key, used in expired:
            try:
                if self._release(key):
                    released.append(key)
                    log.info("ASR 引擎空闲卸载 | %s | 空闲 %.0fs", key, now - used)
            except Exception:  # noqa: BLE001 - 卸载失败不能拖垮后台线程
                log.warning("空闲卸载失败 | %s", key, exc_info=True)
        return released

    def release_now(self, reason: str = "") -> list[str]:
        with self._lock:
            keys = list(self._last_used)
            self._last_used.clear()
        released = []
        for key in keys:
            try:
                if self._release(key):
                    released.append(key)
                    log.info("ASR 引擎主动卸载 | %s | %s", key, reason or "无原因")
            except Exception:  # noqa: BLE001
                log.warning("主动卸载失败 | %s", key, exc_info=True)
        return released

    def release_others(self, keep: str, reason: str = "") -> list[str]:
        """整片任务开始前，把「不是本轮引擎」的引擎让出去（不碰 keep）。"""
        with self._lock:
            keys = [key for key in self._last_used if key != keep]
            for key in keys:
                self._last_used.pop(key, None)
        released = []
        for key in keys:
            try:
                if self._release(key):
                    released.append(key)
                    log.info("ASR 引擎让路 | %s | 保留 %s ｜ %s", key, keep, reason or "")
            except Exception:  # noqa: BLE001
                log.warning("让路卸载失败 | %s", key, exc_info=True)
        return released

    # -- 后台线程 ----------------------------------------------------------

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, name="kikusub-asr-idle", daemon=True
            )
            self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                self.sweep()
            except Exception:  # noqa: BLE001
                log.warning("空闲卸载巡检失败", exc_info=True)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None
