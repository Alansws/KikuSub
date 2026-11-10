"""任务路由：创建 / 查询 / 取消，以及 WebSocket 进度流。

WS 鉴权同样走 `?token=`：浏览器的 `WebSocket` 构造函数不接受自定义请求头，
这是唯一可行的方式（和 `/media/*` 同理）。

事件帧格式：

```json
{"type": "snapshot",  "job": {...}}                       // 连上先发
{"type": "progress",  "ratio": 0.42, "percent": 42, "stage": "正在识别第 154/283 段"}
{"type": "done",      "job": {...}}                       // job.result 里是完整结果
{"type": "error",     "message": "…", "job": {...}}
{"type": "cancelled", "message": "…", "job": {...}}
```
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .jobs import TERMINAL_EVENTS, JobConflict, JobManager, JobNotFound
from .security import require_token, token_ok

router = APIRouter(tags=["jobs"])


class TranscribeJobRequest(BaseModel):
    media_id: str
    # transcribe=转写；proxy=压制 480p 监看代理（Chromium 解不开 MKV/HEVC 时用）
    kind: str = Field(default="transcribe", pattern="^(transcribe|proxy)$")
    # transcribe=转写；proxy=压制 480p 监看代理（Chromium 解不开 MKV/HEVC 时用）
    kind: str = Field(default="transcribe", pattern="^(transcribe|proxy)$")
    engine: str = Field(default="whisper", pattern="^(whisper|qwen)$")
    output_format: str = Field(default="SRT", pattern="^(SRT|VTT|TXT)$")
    save_beside: bool = False
    start: float | None = None
    end: float | None = None
    keep_absolute_timeline: bool = True
    # 引擎参数直接透传给 dataclass；字段名以 WhisperVadConfig / QwenCtcConfig 为准
    params: dict = Field(default_factory=dict)


def _manager(request: Request) -> JobManager:
    return request.app.state.jobs


def _build_request(request: Request, payload: TranscribeJobRequest):
    # 延迟导入：core.pipeline 会拉起 torch（约 7 s），只有真的要转写时才付这个代价
    from core import params as param_specs
    from core import pipeline
    from core.qwen_ctc import QwenCtcConfig
    from core.transcribe import WhisperVadConfig, build_whisper_config

    try:
        info = request.app.state.media.get(payload.media_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if payload.start is not None and payload.start < 0:
        raise HTTPException(status_code=422, detail="起始时间不能为负")
    if payload.start is not None and payload.end is not None and payload.end <= payload.start:
        raise HTTPException(status_code=422, detail="结束时间必须大于起始时间")

    # 参数键用 core.params 的规格键（whisper.vad_threshold 这种），
    # 与预设文件里的键天然一致；缺失补默认、越界夹紧都由 normalize 负责。
    values = dict(payload.params or {})
    whisper_config: WhisperVadConfig | None = None
    qwen_config: QwenCtcConfig | None = None
    try:
        if payload.engine == "qwen":
            qwen_config = QwenCtcConfig(**param_specs.config_kwargs("qwen", values))
        else:
            whisper_config = build_whisper_config(**param_specs.config_kwargs("whisper", values))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"引擎参数不合法：{exc}") from exc

    extra = param_specs.passthrough_kwargs(payload.engine, values)

    return pipeline.TranscribeRequest(
        media_path=info.path,
        media_id=payload.media_id,
        engine_key=payload.engine,
        output_format=payload.output_format,
        save_beside=payload.save_beside,
        start_s=payload.start,
        end_s=payload.end,
        keep_absolute_timeline=payload.keep_absolute_timeline,
        whisper_config=whisper_config,
        qwen_config=qwen_config,
        no_repeat_ngram_size=int(extra.get("no_repeat_ngram_size", 5)),
        repetition_penalty=float(extra.get("repetition_penalty", 1.15)),
        use_alignment=bool(extra.get("use_alignment", True)),
    )


@router.post("/api/jobs", dependencies=[Depends(require_token)], status_code=201)
async def create_job(payload: TranscribeJobRequest, request: Request) -> dict:
    manager = _manager(request)
    session_id = request.cookies.get("kikusub_sid", "")
    loop = asyncio.get_running_loop()

    try:
        if payload.kind == "proxy":
            try:
                info = request.app.state.media.get(payload.media_id)
            except Exception as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            job = manager.start_proxy(
                info.path, media_id=info.id, session_id=session_id, loop=loop
            )
        else:
            job = manager.start_transcribe(
                _build_request(request, payload), session_id=session_id, loop=loop
            )
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # 会话绑定到该媒体：质检队列按媒体落盘，后续 /api/qa 需要知道为谁服务
    from .deps import SESSION_COOKIE

    session = request.app.state.sessions.get(request.cookies.get(SESSION_COOKIE))
    session.media_id = payload.media_id
    return job.snapshot()


@router.get("/api/params", dependencies=[Depends(require_token)])
def get_params() -> dict:
    """可调参数规格（含分组、范围、默认值）。前端据此渲染控件，预设也用同一套键。"""
    from core import params as param_specs

    return param_specs.schema()


@router.get("/api/jobs", dependencies=[Depends(require_token)])
def list_jobs(request: Request) -> dict:
    manager = _manager(request)
    active = manager.active()
    return {"active": active.snapshot() if active else None}


@router.get("/api/jobs/{job_id}", dependencies=[Depends(require_token)])
def get_job(job_id: str, request: Request) -> dict:
    try:
        return _manager(request).get(job_id).snapshot()
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@router.delete("/api/jobs/{job_id}", dependencies=[Depends(require_token)])
def cancel_job(job_id: str, request: Request) -> dict:
    try:
        cancelled = _manager(request).cancel(job_id)
    except JobNotFound as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return {"cancelled": cancelled}


@router.websocket("/ws/jobs/{job_id}")
async def job_stream(websocket: WebSocket, job_id: str) -> None:
    if not token_ok(websocket):
        await websocket.close(code=4401)
        return

    manager: JobManager = websocket.app.state.jobs
    try:
        manager.get(job_id)
    except JobNotFound:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    queue = manager.subscribe(job_id, asyncio.get_running_loop())
    try:
        # 已结束的任务直接把终态发完就关，不必等
        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event["type"] in TERMINAL_EVENTS:
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(job_id, queue)
        try:
            await websocket.close()
        except RuntimeError:
            pass
