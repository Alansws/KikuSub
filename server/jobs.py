"""异步任务：转写任务的注册、进度广播、取消。

替代旧实现里 `manual_transcode_proxy_generator` / `transcribe_media` 那套
「Gradio 流式生成器 + queue.Queue」的写法。职责分工：

- 编排在 `core.pipeline`（与旧界面共用同一份）；
- 这里只管任务生命周期与事件分发：线程里跑 pipeline，进度转成事件推给订阅者；
- 单槽并发沿用 `core.jobs.JobRegistry`（这套并发加固已经是对的，别改）。

**为什么要保留事件历史**：WebSocket 可能在任务开跑之后才连上（前端先发 POST 再开
WS，中间有几十毫秒），新订阅者必须先收到一条快照，否则界面会一直停在 0%。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from core import proxy
from core.jobs import CancelToken, JobBusy, JobRegistry
from core.procutil import CommandCancelled
from core.paths import OUTPUT_DIR

log = logging.getLogger("kikusub.server.jobs")

EVENT_HISTORY = 200
JOB_RETENTION = 64

# 终态事件：订阅者收到这些就可以关掉连接了。
TERMINAL_EVENTS = {"done", "error", "cancelled"}


class JobNotFound(KeyError):
    pass


class JobConflict(RuntimeError):
    """已有重任务在跑（单槽约束）。"""


@dataclass
class JobRecord:
    id: str
    kind: str
    status: str = "queued"
    ratio: float = 0.0
    percent: int = 0
    stage: str = ""
    error: str = ""
    result: dict | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0
    token: CancelToken | None = None
    events: deque = field(default_factory=lambda: deque(maxlen=EVENT_HISTORY))
    # 订阅者 = (队列, 该订阅者所在的事件循环)。必须逐订阅者记录循环：
    # 建任务的请求循环和等 WS 帧的循环不一定是同一个（测试客户端甚至是每请求一个）。
    subscribers: list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = field(default_factory=list)
    loop: asyncio.AbstractEventLoop | None = None

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "ratio": self.ratio,
            "percent": self.percent,
            "stage": self.stage,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 2)
            if self.started_at
            else 0.0,
            "result": self.result,
        }


class JobManager:
    def __init__(self, output_dir: Path | None = None, runner=None) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, JobRecord] = {}
        self._registry = JobRegistry()
        self._output_dir = Path(output_dir or OUTPUT_DIR)
        # 可注入的编排入口：默认走 core.pipeline（**延迟导入**——它会把 torch 拉进来，
        # 而服务层启动时不该付这 7 秒），测试里换成替身。
        self._runner = runner

    # -- 生命周期 -----------------------------------------------------------

    def start_transcribe(
        self,
        request,
        *,
        session=None,
        apply: str = "replace",
        session_id: str = "",
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> JobRecord:
        job = self._launch("transcribe", str(request.media_path.name), session_id, loop)
        self._spawn(self._run_transcribe, job, request, session, apply)
        return job

    def start_proxy(
        self,
        media_path: Path,
        *,
        media_id: str = "",
        session_id: str = "",
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> JobRecord:
        """压制 480p 监看代理。与转写共用单槽：两者都吃满 CPU/GPU，不能并行。"""
        job = self._launch("proxy", Path(media_path).name, session_id, loop)
        self._spawn(self._run_proxy, job, Path(media_path), media_id)
        return job

    def _launch(
        self,
        kind: str,
        label: str,
        session_id: str,
        loop: asyncio.AbstractEventLoop | None,
    ) -> JobRecord:
        try:
            token = self._registry.start(session_id or "api", label=label)
        except JobBusy as exc:
            raise JobConflict(str(exc)) from exc
        job = JobRecord(id=uuid.uuid4().hex[:12], kind=kind, token=token, loop=loop)
        with self._lock:
            self._jobs[job.id] = job
            self._prune_locked()
        return job

    def _spawn(self, target, job: JobRecord, *args) -> None:
        threading.Thread(
            target=target,
            args=(job, *args),
            daemon=True,
            name=f"kikusub-job-{job.id}",
        ).start()

    def _run_proxy(self, job: JobRecord, media_path: Path, media_id: str = "") -> None:
        job.status = "running"
        job.started_at = time.time()
        self._emit(job, {"type": "start", "job": job.snapshot()})
        try:
            result = proxy.run_proxy_job(
                media_path,
                on_progress=lambda event: self._proxy_progress(job, event),
                cancel_event=job.token,
                output_dir=self._output_dir,
            )
            job.status = "done"
            job.ratio = 1.0
            job.percent = 100
            job.stage = "代理已就绪"
            job.result = {"proxy": result.to_dict(), "media_id": media_id}
            job.finished_at = time.time()
            self._emit(job, {"type": "done", "job": job.snapshot()})
            log.info("代理任务完成 | job=%s | %s", job.id, result.path.name)
        except CommandCancelled:
            job.status = "cancelled"
            job.error = "任务已取消"
            job.finished_at = time.time()
            self._emit(job, {"type": "cancelled", "message": job.error, "job": job.snapshot()})
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = str(exc)
            job.finished_at = time.time()
            log.exception("代理任务失败 | job=%s", job.id)
            self._emit(job, {"type": "error", "message": job.error, "job": job.snapshot()})
        finally:
            self._registry.finish(job.token)

    def _proxy_progress(self, job: JobRecord, event: dict) -> None:
        percent = event.get("percent")
        if percent is not None:
            # 与转写一致：只取单调最大值，进度条绝不倒走
            job.ratio = max(job.ratio, max(0.0, min(1.0, percent / 100.0)))
            job.percent = int(job.ratio * 100)
        job.stage = str(event.get("stage") or job.stage)
        self._emit(job, {"type": "progress", **event, "job_percent": job.percent})

    def _run_transcribe(self, job: JobRecord, request, session=None, apply: str = "replace") -> None:
        job.status = "running"
        job.started_at = time.time()
        self._emit(job, {"type": "start", "job": job.snapshot()})
        try:
            runner = self._runner
            if runner is None:
                from core.pipeline import run_transcription

                runner = run_transcription
            result = runner(
                request,
                on_progress=lambda ratio, stage: self._progress(job, ratio, stage),
                cancel_event=job.token,
                output_dir=self._output_dir,
            )
            job.status = "done"
            job.ratio = 1.0
            job.percent = 100
            job.result = result.to_dict()
            job.result["media_id"] = request.media_id
            # 会话是服务端唯一真源：任务跑完必须把字幕写回去，否则前端
            # `/api/cues` 永远是空的（表现为「转写完成但核对台没有字幕」）。
            if session is not None:
                job.result.update(self._apply_cues(session, request, result.cues, apply))
            job.finished_at = time.time()
            self._emit(job, {"type": "done", "job": job.snapshot()})
            log.info(
                "任务完成 | job=%s | cues=%s | apply=%s | session=%s",
                job.id,
                len(result.cues),
                apply,
                getattr(session, "id", "-"),
            )
        except Exception as exc:  # noqa: BLE001 —— 任何失败都要变成事件，不能只留在线程里
            cancelled = bool(job.token is not None and job.token.is_set())
            job.status = "cancelled" if cancelled else "error"
            job.error = "任务已取消" if cancelled else str(exc)
            job.finished_at = time.time()
            if not cancelled:
                log.exception("任务失败 | job=%s", job.id)
            self._emit(
                job,
                {
                    "type": "cancelled" if cancelled else "error",
                    "message": job.error,
                    "job": job.snapshot(),
                },
            )
        finally:
            # 槽位由真正停止工作的 worker 释放（与旧实现同一套语义）
            self._registry.finish(job.token)

    def _apply_cues(self, session, request, cues, apply: str) -> dict:
        """把一次转写的结果合并进会话。返回给前端的状态摘要。

        三种语义（对应转写页的「结果处理」与核对台的局部重转）：

        - `replace`：整片覆盖核对台；
        - `append`：与现有时间轴合并去重，用于「局部转写后添加」；
        - `replace_range`：只替换该区间内的旧字幕，其余原样保留——单句/选区重转
          走这条，用户不会因为重转一句而丢掉整张表。
        """
        from core.cues import _unique_sorted_cues

        fresh = _unique_sorted_cues(cues)
        start_s = getattr(request, "start_s", None)
        end_s = getattr(request, "end_s", None)
        with session.lock:
            session.latest_cues = list(fresh)
            before = len(session.review_cues)
            if apply == "append":
                merged = _unique_sorted_cues([*session.review_cues, *fresh])
            elif apply == "replace_range" and start_s is not None:
                limit = end_s if end_s is not None else float("inf")
                kept = [
                    cue
                    for cue in session.review_cues
                    if cue.end <= start_s + 0.02 or cue.start >= limit - 0.02
                ]
                merged = _unique_sorted_cues([*kept, *fresh])
            else:
                merged = fresh
            session.replace_review(merged)
            session.updated_at = time.time()
            return {
                "applied": apply,
                "cue_count": len(merged),
                "added": max(0, len(merged) - before),
                # 被本区间替换掉的旧条数：前端据此区分「新增」与「更新」
                "removed": max(0, before + len(fresh) - len(merged)),
            }

    def _progress(self, job: JobRecord, ratio: float, stage: str) -> None:
        # 引擎可能先报 2%（抽音频）再报 1%（载模型）；保持单调，避免进度倒退。
        ratio = max(job.ratio, max(0.0, min(1.0, float(ratio))))
        job.ratio = ratio
        job.percent = int(ratio * 100)
        job.stage = stage
        self._emit(
            job,
            {"type": "progress", "ratio": round(ratio, 4), "percent": job.percent, "stage": stage},
        )

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job.token is None or job.finished_at:
            return False
        job.token.cancel()
        job.status = "cancelling"
        self._emit(job, {"type": "cancelling", "message": "已发送取消指令"})
        return True

    # -- 查询 / 订阅 --------------------------------------------------------

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        return job

    def latest_completed(self, kind: str | None = None) -> JobRecord | None:
        """最近一次成功完成的任务，供 /api/report 与前端恢复上次结果。"""
        with self._lock:
            done = [
                job
                for job in self._jobs.values()
                if job.status == "done" and (kind is None or job.kind == kind)
            ]
        if not done:
            return None
        return max(done, key=lambda job: job.finished_at)

    def active(self) -> JobRecord | None:
        with self._lock:
            for job in self._jobs.values():
                if not job.finished_at:
                    return job
        return None

    def subscribe(self, job_id: str, loop: asyncio.AbstractEventLoop | None = None) -> asyncio.Queue:
        """返回一个事件队列，并立刻塞入快照（必要时补一条终态）。

        **竞态**：前端先 POST 建任务、再开 WS，中间那几十毫秒里任务可能已经跑完
        （短片、或者替身引擎）。此时只发快照，订阅者会永远等不到终态事件而挂住。
        所以这里在任务已结束时，把历史里的最后一条终态事件一并补投。
        """
        job = self.get(job_id)
        queue: asyncio.Queue = asyncio.Queue(maxsize=EVENT_HISTORY)
        with self._lock:
            job.subscribers.append((queue, loop or job.loop))
        queue.put_nowait({"type": "snapshot", "job": job.snapshot()})
        if job.finished_at:
            for event in reversed(job.events):
                if event.get("type") in TERMINAL_EVENTS:
                    queue.put_nowait(event)
                    break
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        try:
            job = self.get(job_id)
        except JobNotFound:
            return
        with self._lock:
            job.subscribers = [item for item in job.subscribers if item[0] is not queue]

    # -- 内部 ---------------------------------------------------------------

    def _emit(self, job: JobRecord, event: dict) -> None:
        job.events.append(event)
        with self._lock:
            subscribers = list(job.subscribers)
        for queue, loop in subscribers:
            if loop is not None and loop.is_running():
                try:
                    loop.call_soon_threadsafe(_offer, queue, event)
                except RuntimeError:
                    # 事件循环已关闭（进程收尾），静默丢弃即可
                    pass
            else:
                _offer(queue, event)

    def _prune_locked(self) -> None:
        if len(self._jobs) <= JOB_RETENTION:
            return
        finished = sorted(
            (job for job in self._jobs.values() if job.finished_at),
            key=lambda job: job.finished_at,
        )
        for job in finished[: len(self._jobs) - JOB_RETENTION]:
            self._jobs.pop(job.id, None)


def _offer(queue: asyncio.Queue, event: dict) -> None:
    """非阻塞投递；队列满说明消费端跟不上，丢掉最旧的一条。"""
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
            queue.put_nowait(event)
        except (asyncio.QueueEmpty, asyncio.QueueFull):
            pass
