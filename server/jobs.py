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


def _range_replaces_cue(cue, start_s: float, limit: float) -> bool:
    """判断旧字幕是否真的被这次区间重转“覆盖”，而不是只在边缘被切到。

    旧逻辑是 ``cue.end <= start + 0.02 or cue.start >= limit - 0.02``，
    只要区间跨过句子的第一个字，整句就会被删掉。QA「补录」的区间末通常只比
    下一句开头多 0.2–0.3s 的 padding；这会把下一句整条误删。

    这里沿用 ``_audit_cue_overlaps`` 的口径：覆盖超过该句一半，或这句话的
    中点落在区间内，才算替换；只在边缘被切到的小比例重叠必须保留。
    """
    overlap = min(float(cue.end), limit) - max(float(cue.start), start_s)
    if overlap <= 0:
        return False
    cue_dur = max(0.001, float(cue.end) - float(cue.start))
    midpoint = (float(cue.start) + float(cue.end)) / 2.0
    return overlap / cue_dur >= 0.5 or (start_s <= midpoint <= limit)


def merge_replace_range(review_cues, fresh, start_s: float, end_s: float | None):
    """``replace_range`` 的纯函数版本：只替换真正被区间覆盖的旧字幕。"""
    from core.cues import _unique_sorted_cues

    limit = end_s if end_s is not None else float("inf")
    kept = [cue for cue in review_cues if not _range_replaces_cue(cue, start_s, limit)]
    return _unique_sorted_cues([*kept, *fresh])


def first_cue_in_range(cues, start_s: float, end_s: float | None) -> int | None:
    """时间轴里第一条与区间真正重叠的字幕（0 基）。

    区间起点带 padding，可能落在新句之前；如果前端只按 ``start_s`` 跳转，
    ``play.time`` 不在任何 cue 里，表格与检查器就不会同步。
    """
    limit = end_s if end_s is not None else float("inf")
    for index, cue in enumerate(cues):
        if float(cue.end) > start_s and float(cue.start) < limit:
            return index
    return None


def target_cue_index(merged, fresh, start_s: float, end_s: float | None) -> int | None:
    """这次局部转写完成后，核对台应该选中的那一条在合并时间轴里的下标。

    优先认 ``fresh``（这次模型真正转出来的）里的第一条：区间边缘可能留着上一句
    的尾巴，直接扫 ``merged`` 会选中邻句，而不是用户期待的新句。
    """
    fresh_hit = first_cue_in_range(fresh, start_s, end_s)
    if fresh_hit is not None:
        wanted = fresh[fresh_hit]
        for index, cue in enumerate(merged):
            if (
                cue.start == wanted.start
                and cue.end == wanted.end
                and cue.text == wanted.text
            ):
                return index
    return first_cue_in_range(merged, start_s, end_s)


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
    def __init__(
        self,
        output_dir: Path | None = None,
        runner=None,
        on_heavy_job=None,
        idle_releaser=None,
        engine_resolver=None,
    ) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, JobRecord] = {}
        self._registry = JobRegistry()
        self._output_dir = Path(output_dir or OUTPUT_DIR)
        # 可注入的编排入口：默认走 core.pipeline（**延迟导入**——它会把 torch 拉进来，
        # 而服务层启动时不该付这 7 秒），测试里换成替身。
        self._runner = runner
        # 重任务开跑前让路：TTS 的克隆模型和 ASR 抢同一块统一内存，转写/导出前
        # 必须先卸载。这里用回调而不是直接 import core.tts，避免服务层耦合。
        self._on_heavy_job = on_heavy_job
        # ASR 引擎的空闲卸载：换引擎复核不该句句冷启动，也不该两个引擎常驻。
        # 默认不自动起线程，第一次 touch 时才起（测试里不会凭空多线程）。
        from core.engine_idle import EngineIdleReleaser

        self._idle = idle_releaser or EngineIdleReleaser()
        # 复核要拿到「另一个引擎」的实例；默认走 core.pipeline 的进程内单例，
        # 测试里换成替身（替身只需实现 transcribe_window）。
        self._engine_resolver = engine_resolver

    @property
    def idle(self):
        return self._idle

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

    def start_compare(
        self,
        media_path: Path,
        engine_key: str,
        engine_config,
        windows: list[dict],
        *,
        media_id: str = "",
        session_id: str = "",
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> JobRecord:
        """用另一个引擎把若干字幕窗口各听一遍；只回文本，不落盘、不写回会话。

        与转写共用单槽：它同样要吃满 GPU。结果不进 `session.cues`——采用哪一份是
        用户在核对台的决定，服务端不替用户改字幕。
        """
        from core import engines as engine_registry

        name = engine_registry.get(engine_key).label
        job = self._launch("compare", f"{name} × {len(windows)} 条", session_id, loop)
        self._spawn(
            self._run_compare, job, Path(media_path), engine_key, engine_config, windows, media_id
        )
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

    def start_download(
        self,
        engine_key: str,
        *,
        session_id: str = "",
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> JobRecord:
        """下载/补齐某个引擎的模型权重。

        与转写共用单槽：下载会持续吃网络与磁盘，和转写并跑只会让两边都变慢。
        """
        job = self._launch("download", engine_key, session_id, loop)
        self._spawn(self._run_download, job, engine_key)
        return job

    # -- 成片导出 ------------------------------------------------------------

    def start_export(
        self,
        *,
        media_path: Path,
        info,
        options,
        cues,
        translation_texts: list[str] | None,
        out_dir: Path,
        session_id: str = "",
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> JobRecord:
        """导出带字幕的成片。与转写共用单槽：编码会吃满 CPU/GPU。"""
        job = self._launch("export", Path(media_path).name, session_id, loop)
        self._spawn(
            self._run_export,
            job,
            Path(media_path),
            info,
            options,
            list(cues),
            list(translation_texts or []),
            Path(out_dir),
        )
        return job

    def _run_export(
        self,
        job: JobRecord,
        media_path: Path,
        info,
        options,
        cues,
        translation_texts: list[str],
        out_dir: Path,
    ) -> None:
        from core import video_export

        job.status = "running"
        job.started_at = time.time()
        self._emit(job, {"type": "start", "job": job.snapshot()})
        try:
            def on_progress(ratio: float, stage: str, extra: dict) -> None:
                ratio = max(job.ratio, max(0.0, min(1.0, float(ratio))))
                job.ratio = ratio
                job.percent = int(ratio * 100)
                job.stage = str(stage or job.stage)
                payload = {
                    "type": "progress",
                    "ratio": round(ratio, 4),
                    "percent": job.percent,
                    "stage": job.stage,
                    "job_percent": job.percent,
                }
                if extra.get("out_s") is not None:
                    payload["out_s"] = round(float(extra["out_s"]), 2)
                if extra.get("speed"):
                    payload["speed"] = str(extra["speed"])
                self._emit(job, payload)

            result = video_export.run_export(
                media_path,
                cues,
                info,
                options,
                out_dir,
                translation_texts=translation_texts,
                on_progress=on_progress,
                cancel_event=job.token,
            )
            job.status = "done"
            job.ratio = 1.0
            job.percent = 100
            job.stage = "成片已导出"
            job.result = result
            job.finished_at = time.time()
            self._emit(job, {"type": "done", "job": job.snapshot()})
            log.info(
                "成片导出完成 | job=%s | %s | %.1f MB | %.1fs",
                job.id,
                result.get("name"),
                float(result.get("size") or 0) / 1024**2,
                float(result.get("elapsed") or 0),
            )
        except CommandCancelled:
            job.status = "cancelled"
            job.error = "任务已取消"
            job.finished_at = time.time()
            self._emit(job, {"type": "cancelled", "message": job.error, "job": job.snapshot()})
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = str(exc) or exc.__class__.__name__
            job.finished_at = time.time()
            log.warning("成片导出失败 | job=%s | %s", job.id, job.error)
            self._emit(job, {"type": "error", "message": job.error, "job": job.snapshot()})
        finally:
            self._registry.finish(job.token)

    # -- AI 生成（润色 / 翻译）----------------------------------------------

    def start_ai_polish(
        self,
        *,
        session,
        config,
        chunk_cues: int,
        context_cues: int,
        lang: str,
        source_path: str,
        out_path: Path,
        session_id: str = "",
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> JobRecord:
        """生成一份润色提案。

        与转写共用单槽：真跑起来也是长时间把机器占住，而且会读写同一个会话。
        ``config`` 里带着 api_key，**只作为线程参数存在**，绝不进 JobRecord。
        """
        job = self._launch("ai-polish", "AI 润色", session_id, loop)
        self._spawn(
            self._run_ai_generation,
            job,
            session,
            config,
            {
                "kind": "polish",
                "lang": lang,
                "chunk_cues": chunk_cues,
                "context_cues": context_cues,
                "source_path": source_path,
            },
            out_path,
        )
        return job

    def start_ai_translate(
        self,
        *,
        session,
        config,
        dst_lang: str,
        chunk_cues: int,
        context_cues: int,
        source_path: str,
        out_path: Path,
        session_id: str = "",
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> JobRecord:
        """生成一份翻译提案（只产提案，落轨由 /api/translations 负责）。"""
        job = self._launch("ai-translate", "AI 翻译", session_id, loop)
        self._spawn(
            self._run_ai_generation,
            job,
            session,
            config,
            {
                "kind": "translate",
                "dst_lang": dst_lang,
                "chunk_cues": chunk_cues,
                "context_cues": context_cues,
                "source_path": source_path,
            },
            out_path,
        )
        return job

    def _run_ai_generation(
        self,
        job: JobRecord,
        session,
        config,
        params: dict,
        out_path: Path,
    ) -> None:
        from core import ai_client, ai_polish, ai_proposal, ai_translate
        from core.textio import write_text_atomic

        kind = str(params.get("kind") or "polish")
        job.status = "running"
        job.started_at = time.time()
        self._emit(job, {"type": "start", "job": job.snapshot()})
        texts = [cue.text for cue in getattr(session, "review_cues", []) or []]
        def progress(ratio: float, stage: str) -> None:
            self._progress(job, ratio, stage)

        # 单槽必须占到最后一步（含写盘）才释放：中途放开会让新任务踩进同一个会话。
        try:
            if kind == "translate":
                proposal, warnings, _glossary = ai_translate.run_translate(
                    texts,
                    config,
                    dst_lang=str(params.get("dst_lang") or ""),
                    chunk_cues=int(params.get("chunk_cues") or 120),
                    context_cues=int(params.get("context_cues") or 0),
                    source_path=str(params.get("source_path") or ""),
                    cancel=job.token,
                    on_progress=progress,
                )
            else:
                proposal, warnings = ai_polish.run_polish(
                    texts,
                    config,
                    chunk_cues=int(params.get("chunk_cues") or 200),
                    context_cues=int(params.get("context_cues") or 0),
                    lang=str(params.get("lang") or "ja"),
                    model=config.model,
                    entry="in-app",
                    source_path=str(params.get("source_path") or ""),
                    cancel=job.token,
                    on_progress=progress,
                )

            changed = sum(1 for item in proposal["items"] if item["after"] != item["before"])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(out_path, ai_proposal.dump_proposal(proposal))

            job.status = "done"
            job.ratio = 1.0
            job.percent = 100
            job.stage = "提案已生成"
            job.result = {
                "proposal_path": str(out_path),
                "kind": kind,
                "count": len(texts),
                "changed": changed,
                "chunks": int(proposal.get("chunks") or 1),
                "warnings": list(warnings or [])[:5],
                "pending_apply": True,
            }
            if kind == "translate":
                job.result["dst_lang"] = str(proposal.get("dst_lang") or "")
                job.result["glossary"] = len(proposal.get("glossary") or [])
            job.finished_at = time.time()
            self._emit(job, {"type": "done", "job": job.snapshot()})
            log.info(
                "AI %s 完成 | job=%s | %d 条 | 改动 %d 处 | 输出=%s",
                kind,
                job.id,
                len(texts),
                changed,
                out_path.name,
            )
        except (ai_polish.AiPolishCancelled, ai_client.AiCancelled):
            job.status = "cancelled"
            job.error = "任务已取消"
            job.finished_at = time.time()
            self._emit(job, {"type": "cancelled", "message": job.error, "job": job.snapshot()})
            log.info("AI 任务已取消 | job=%s", job.id)
        except Exception as exc:  # noqa: BLE001 - 任务失败要变成可读状态，不能抛穿线程
            job.status = "error"
            job.error = str(exc) or exc.__class__.__name__
            job.finished_at = time.time()
            self._emit(job, {"type": "error", "message": job.error, "job": job.snapshot()})
            log.warning("AI 任务失败 | job=%s | %s", job.id, job.error)
        finally:
            self._registry.finish(job.token)

    def _run_download(self, job: JobRecord, engine_key: str) -> None:
        from core import engines

        job.status = "running"
        job.started_at = time.time()
        self._emit(job, {"type": "start", "job": job.snapshot()})
        stop = threading.Event()
        monitor = None
        try:
            spec = engines.get(engine_key)
            directory = engines.model_dir(spec)
            if engines.is_installed(spec):
                job.stage = "模型已就绪"
            else:
                expected = max(1, spec.approx_bytes)

                def monitor_size() -> None:
                    # 下载器不提供可靠进度，靠磁盘增长估算总进度；只报单调值。
                    while not stop.wait(0.8):
                        size = engines.dir_size(directory, ttl_s=0)
                        ratio = min(0.97, 0.02 + size / expected * 0.95)
                        self._progress(
                            job,
                            ratio,
                            f"正在下载模型 {size / 1024**3:.2f} / {spec.approx_bytes / 1024**3:.1f} GB",
                        )

                monitor = threading.Thread(
                    target=monitor_size, daemon=True, name=f"kikusub-dl-{job.id}"
                )
                monitor.start()

                def on_progress(ratio: float, stage: str) -> None:
                    # 下载器只在开始时给一帧「正在连接镜像」，不要用它覆盖磁盘估算
                    if stage:
                        job.stage = stage
                        self._emit(
                            job,
                            {
                                "type": "progress",
                                "ratio": round(job.ratio, 4),
                                "percent": job.percent,
                                "stage": stage,
                            },
                        )

                engines.ensure_model(engine_key, progress_cb=on_progress)

            installed = engines.is_installed(spec)
            if not installed:
                raise RuntimeError(
                    "下载结束后仍没有找到完整权重，请检查网络或代理后重试。"
                )
            stop.set()
            if monitor is not None:
                monitor.join(timeout=2)
            size = engines.dir_size(directory, ttl_s=0)
            job.status = "done"
            job.ratio = 1.0
            job.percent = 100
            job.stage = "模型下载完成"
            job.result = {
                "engine": engine_key,
                "installed": True,
                "size_bytes": size,
                "model_dir": str(directory),
            }
            job.finished_at = time.time()
            self._emit(job, {"type": "done", "job": job.snapshot()})
            log.info(
                "模型下载完成 | engine=%s | size=%.2fGB | dir=%s",
                engine_key,
                size / 1024**3,
                directory,
            )
        except Exception as exc:  # noqa: BLE001
            stop.set()
            job.status = "error"
            job.error = str(exc)
            job.finished_at = time.time()
            log.exception("模型下载失败 | engine=%s", engine_key)
            self._emit(job, {"type": "error", "message": job.error, "job": job.snapshot()})
        finally:
            stop.set()
            self._registry.finish(job.token)

    def _launch(
        self,
        kind: str,
        label: str,
        session_id: str,
        loop: asyncio.AbstractEventLoop | None,
    ) -> JobRecord:
        # 先释放 TTS 再占单槽：即使后面 JobBusy 失败，提前卸载也不会有副作用。
        if self._on_heavy_job is not None and kind in {"transcribe", "proxy", "export", "compare"}:
            try:
                self._on_heavy_job(f"{kind} 启动")
            except Exception:  # noqa: BLE001 —— 释放失败不能挡住真正的任务
                log.warning("释放 TTS 模型失败", exc_info=True)
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

    def _run_compare(
        self,
        job: JobRecord,
        media_path: Path,
        engine_key: str,
        engine_config,
        windows: list[dict],
        media_id: str = "",
    ) -> None:
        from core import engines as engine_registry
        from core.second_opinion import transcribe_windows

        job.status = "running"
        job.started_at = time.time()
        name = engine_registry.get(engine_key).label
        self._emit(job, {"type": "start", "job": job.snapshot()})
        started = time.time()
        try:
            # 复核要装另一个引擎：先把别的引擎让出去（本次要用的那个若已常驻则保留）。
            self._idle.release_others(engine_key, reason="另一引擎复核")
            self._progress(job, 0.02, f"正在加载 {name}（换引擎约 20–40 秒）…")

            def on_window(done: int, total: int) -> None:
                ratio = 0.05 + 0.93 * (done / max(1, total))
                self._progress(job, ratio, f"正在用 {name} 复核第 {done}/{total} 条…")

            texts = transcribe_windows(
                self._resolve_engine(engine_key),
                windows,
                media_path=media_path,
                config=engine_config,
                progress_cb=on_window,
                cancel_event=job.token,
            )
            job.status = "done"
            job.ratio = 1.0
            job.percent = 100
            job.stage = f"{name} 复核完成"
            job.result = {
                "kind": "compare",
                "engine": engine_key,
                "engine_name": name,
                "media_id": media_id,
                "elapsed": round(time.time() - started, 2),
                "texts": texts,
            }
            job.finished_at = time.time()
            self._emit(job, {"type": "done", "job": job.snapshot()})
            log.info("复核完成 | job=%s | engine=%s | 条数=%s", job.id, engine_key, len(texts))
        except CommandCancelled:
            job.status = "cancelled"
            job.error = "复核已取消"
            job.finished_at = time.time()
            self._emit(job, {"type": "cancelled", "message": job.error, "job": job.snapshot()})
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = str(exc)
            job.finished_at = time.time()
            log.exception("复核失败 | job=%s", job.id)
            self._emit(job, {"type": "error", "message": job.error, "job": job.snapshot()})
        finally:
            # 留着别立刻卸：用户很可能接着复核下一条。空闲超时由 EngineIdleReleaser 负责。
            self._idle.touch(engine_key)
            self._registry.finish(job.token)

    def _resolve_engine(self, engine_key: str):
        if self._engine_resolver is not None:
            return self._engine_resolver(engine_key)
        from core.pipeline import resolve_engine

        return resolve_engine(engine_key)

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
            # 整片任务开始前把另一个引擎让出去（本轮要用的这个保留，避免自削一刀）。
            engine_key = str(getattr(request, "engine_key", "") or "")
            if engine_key:
                self._idle.release_others(engine_key, reason="整片任务开始")
            # 字幕的落盘目录由设置里的「导出文件夹」决定；漏句清单 / 质检队列 /
            # 代理缓存仍然留在 output_dir（运行数据与用户交付物分开）。
            out_dir = Path(getattr(request, "export_dir", None) or self._output_dir)
            result = runner(
                request,
                on_progress=lambda ratio, stage: self._progress(job, ratio, stage),
                cancel_event=job.token,
                output_dir=out_dir,
            )
            job.status = "done"
            job.ratio = 1.0
            job.percent = 100
            job.result = result.to_dict()
            job.result["media_id"] = request.media_id
            job.result["export_dir"] = str(out_dir)
            # 会话是服务端唯一真源：任务跑完必须把字幕写回去，否则前端
            # `/api/cues` 永远是空的（表现为「转写完成但核对台没有字幕」）。
            if session is not None:
                job.result.update(self._apply_cues(session, request, result.cues, apply, job))
            job.finished_at = time.time()
            self._emit(job, {"type": "done", "job": job.snapshot()})
            if engine_key:
                self._idle.touch(engine_key)
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

    def _apply_cues(self, session, request, cues, apply: str, job=None) -> dict:
        """把一次转写的结果合并进会话。返回给前端的状态摘要。

        三种语义（对应转写页的「结果处理」与核对台的局部重转）：

        - `replace`：整片覆盖核对台；
        - `append`：与现有时间轴合并去重，用于「局部转写后添加」；
        - `replace_range`：只替换该区间内的旧字幕，其余原样保留——单句/选区重转
          走这条，用户不会因为重转一句而丢掉整张表。

        `review_source` 只在整片/追加这类「产生新一版转写」时改写；单句/选区
        修正保留原来的来源，右侧报告才能继续对应整片那次任务。
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
                merged = merge_replace_range(session.review_cues, fresh, start_s, end_s)
            else:
                merged = fresh
            if apply == "replace_range" and start_s is not None:
                limit = end_s if end_s is not None else float("inf")
                label = f"局部转写 {start_s:.1f}s–{limit:.1f}s" if end_s is not None else f"局部转写 {start_s:.1f}s 起"
            elif apply == "append":
                label = f"追加转写（{len(fresh)} 条）"
            else:
                label = f"整片转写（{len(merged)} 条）"
            job_result = getattr(job, "result", None) or {}
            # 整片 / 追加转写会写一份新的质检队列；在压历史之前先把新 payload
            # 放进会话，重做这一步时才能把「同一份待核清单」一起恢复。
            # 局部修正（replace_range）刻意保留原队列，不能覆盖。
            if apply != "replace_range" and getattr(request, "write_audit", False):
                audit_payload = str(job_result.get("audit_payload") or "")
                if audit_payload:
                    session.set_qa_payload(audit_payload)
            source = None
            if apply != "replace_range" and job is not None:
                source = {
                    "kind": "transcription",
                    "name": Path(str(job_result.get("out_filename") or "")).name,
                    "path": str(job_result.get("out_path") or ""),
                    "job_id": job.id,
                    "at": time.time(),
                    "apply": apply,
                }
            session.replace_review(merged, label=label, source=source)
            session.updated_at = time.time()
            # 前端据此把底部表格 / 右侧检查器直接定位到**这次新转出的第一句**。
            # 只给时间区间不够：padding 会让区间起点落在新句之前，play.time 不在
            # 任何 cue 里，cueIndex 为 -1，界面就不会同步（用户报过这个 bug）。
            target_index = None
            if apply == "replace_range" and start_s is not None:
                target_index = target_cue_index(merged, fresh, start_s, end_s)
            return {
                "applied": apply,
                "cue_count": len(merged),
                "added": max(0, len(merged) - before),
                # 被本区间替换掉的旧条数：前端据此区分「新增」与「更新」
                "removed": max(0, before + len(fresh) - len(merged)),
                # 这次应在核对台选中的第一条新字幕（0 基）；无结果时 None
                "target_index": target_index,
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

    def cancel_all(self, reason: str = "应用正在退出") -> int:
        """退出/父进程消失时向所有在跑的任务发取消信号。

        真正的进程终止由 ``core.procutil.terminate_all_processes()`` 完成：
        这里只把令牌置位，让 worker 线程走了 ``terminate`` 分支，把
        ``.part.mp4`` 清掉，不留下半成品。
        """
        count = 0
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if job.token is None or job.finished_at:
                continue
            job.token.cancel()
            job.status = "cancelling"
            count += 1
            self._emit(job, {"type": "cancelling", "message": reason})
        return count

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
