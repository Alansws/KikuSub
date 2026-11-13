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
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator

from .deps import get_session
from .jobs import TERMINAL_EVENTS, JobConflict, JobManager, JobNotFound
from .security import require_token, token_ok
from .sessions import Session

router = APIRouter(tags=["jobs"])


class CompareRange(BaseModel):
    """一条要复核的字幕：时间窗 + 两侧邻句边界（服务端据此夹窗口）。"""

    index: int | None = None
    start: float
    end: float
    prev_end: float | None = None
    next_start: float | None = None


class TranscribeJobRequest(BaseModel):
    media_id: str
    # transcribe=转写；proxy=压制 480p 监看代理；compare=用另一个引擎把窗口重听一遍
    kind: str = Field(default="transcribe", pattern="^(transcribe|proxy|compare)$")
    # 合法值来自 `core.engines` 注册表（见下方 validator）：不要在这里写死引擎名，
    # 否则新增引擎会在请求层被 422 掉，而 pipeline/设置页都是正常的。
    engine: str = "whisper"
    output_format: str = Field(default="SRT", pattern="^(SRT|VTT|TXT)$")
    save_beside: bool = False
    start: float | None = None
    end: float | None = None
    keep_absolute_timeline: bool = True
    # 结果如何进入核对台：整片覆盖 / 合并追加 / 只替换该区间（局部重转）
    apply: str = Field(default="replace", pattern="^(replace|append|replace_range)$")
    # 引擎参数直接透传给 dataclass；字段名以 WhisperVadConfig / QwenCtcConfig 为准
    params: dict = Field(default_factory=dict)
    # kind=compare 时用它；每条一个字幕窗口，最多 core.second_opinion.MAX_WINDOWS 条
    ranges: list[CompareRange] = Field(default_factory=list)

    @field_validator("engine")
    @classmethod
    def _known_engine(cls, value: str) -> str:
        from core import engines

        if value not in engines.KEYS:
            raise ValueError(
                f"未知的识别引擎：{value}（可选：{', '.join(engines.KEYS)}）"
            )
        return value


def _manager(request: Request) -> JobManager:
    return request.app.state.jobs


def _engine_config(engine_key: str, family: str, values: dict):
    """按引擎族构造配置 dataclass。转写与复核共用这一份，避免两处默认值分裂。"""
    # 延迟导入：core.pipeline 会拉起 torch（约 7 s），只有真的要跑片时才付这个代价
    from core import params as param_specs
    from core.qwen_ctc import QwenCtcConfig
    from core.sherpa_asr import SherpaAsrConfig
    from core.transcribe import build_whisper_config

    try:
        if family == "qwen":
            return QwenCtcConfig(**param_specs.config_kwargs("qwen", values))
        if family == "sherpa":
            return SherpaAsrConfig(**param_specs.config_kwargs(engine_key, values))
        return build_whisper_config(**param_specs.config_kwargs("whisper", values))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"引擎参数不合法：{exc}") from exc


def _compare_windows(payload: TranscribeJobRequest) -> list[dict]:
    from core.second_opinion import MAX_WINDOWS, clamp_window

    if not payload.ranges:
        raise HTTPException(status_code=422, detail="复核需要至少一条字幕区间")
    if len(payload.ranges) > MAX_WINDOWS:
        raise HTTPException(
            status_code=422, detail=f"一次最多复核 {MAX_WINDOWS} 条（收到 {len(payload.ranges)} 条）"
        )
    windows: list[dict] = []
    for item in payload.ranges:
        if item.end <= item.start:
            raise HTTPException(status_code=422, detail="字幕区间的结束必须大于开始")
        lo, hi = clamp_window(
            item.start, item.end, prev_end=item.prev_end, next_start=item.next_start
        )
        windows.append(
            {
                "index": item.index if item.index is not None else len(windows),
                "start": lo,
                "end": hi,
            }
        )
    return windows


def _build_request(request: Request, payload: TranscribeJobRequest):
    # 延迟导入：core.pipeline 会拉起 torch（约 7 s），只有真的要转写时才付这个代价
    from core import engines as engine_registry
    from core import params as param_specs
    from core import pipeline
    from core import settings as settings_store

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
    try:
        family = engine_registry.family_of(payload.engine)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    config = _engine_config(payload.engine, family, values)
    if family == "qwen":
        whisper_config, qwen_config, sherpa_config = None, config, None
    elif family == "sherpa":
        whisper_config, qwen_config, sherpa_config = None, None, config
    else:
        whisper_config, qwen_config, sherpa_config = config, None, None

    extra = param_specs.passthrough_kwargs(payload.engine, values)

    # 设置里的「导出文件夹」在每次任务开始时读取：用户在设置页改完之后，
    # 下一次点「开始转写」立即生效，不需要重启 sidecar。
    current_settings = settings_store.load_settings(
        Path(getattr(request.app.state, "settings_path", settings_store.SETTINGS_PATH))
    )
    export_dir = settings_store.resolve_export_dir(
        current_settings,
        Path(request.app.state.config.output_dir),
    )

    return pipeline.TranscribeRequest(
        media_path=info.path,
        media_id=payload.media_id,
        engine_key=payload.engine,
        output_format=payload.output_format,
        save_beside=payload.save_beside,
        export_dir=export_dir,
        start_s=payload.start,
        end_s=payload.end,
        keep_absolute_timeline=payload.keep_absolute_timeline,
        whisper_config=whisper_config,
        qwen_config=qwen_config,
        sherpa_config=sherpa_config,
        no_repeat_ngram_size=int(extra.get("no_repeat_ngram_size", 5)),
        repetition_penalty=float(extra.get("repetition_penalty", 1.15)),
        use_alignment=bool(extra.get("use_alignment", True)),
        # 只有核对台里的「单句/选区修正」保留原队列；转写页的整片或区间任务
        # 都是一次新的转写，报告里会出现质检统计，队列必须同步落盘——否则
        # 报告显示「漏句 1、短句 4」而质检面板是 0 条。
        write_audit=payload.apply != "replace_range",
    )


@router.post("/api/jobs", dependencies=[Depends(require_token)], status_code=201)
async def create_job(
    payload: TranscribeJobRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    manager = _manager(request)
    loop = asyncio.get_running_loop()

    # 会话与媒体显式绑定：`/api/qa` 按媒体落盘，抢在转写前绑好，
    # 任务完成时才能把结果写回同一个会话。
    if payload.kind != "compare":
        # 复核不改会话里的字幕，也就不应该把会话的「当前媒体」绑到这次请求上。
        session.media_id = payload.media_id

    try:
        if payload.kind == "compare":
            from core import engines as engine_registry

            try:
                info = request.app.state.media.get(payload.media_id)
            except Exception as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            family = engine_registry.family_of(payload.engine)
            if family not in {"whisper", "qwen"}:
                raise HTTPException(
                    status_code=422,
                    detail=f"复核只支持 whisper / qwen；{payload.engine} 的权重是按需下载的",
                )
            values = dict(payload.params or {})
            config = _engine_config(payload.engine, family, values)
            job = manager.start_compare(
                info.path,
                payload.engine,
                config,
                _compare_windows(payload),
                media_id=info.id,
                session_id=session.id,
                loop=loop,
            )
        elif payload.kind == "proxy":
            try:
                info = request.app.state.media.get(payload.media_id)
            except Exception as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            job = manager.start_proxy(
                info.path,
                media_id=info.id,
                session_id=session.id,
                loop=loop,
            )
        else:
            job = manager.start_transcribe(
                _build_request(request, payload),
                session=session,
                apply=payload.apply,
                session_id=session.id,
                loop=loop,
            )
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

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
