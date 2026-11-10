"""设置、引擎配置、诊断日志路由。

拆出来的原因：`/api/config` 只回答「这个进程怎么跑」，而设置页需要写操作
（启停引擎、下载权重）和可复制的诊断信息。两者生命周期不同，混在一起会让
`create_app` 越来越长。
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import shutil
import sys
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core import engines
from core import settings as settings_store
from core.paths import MODELS_DIR, OUTPUT_DIR, PRESETS_PATH

from . import API_VERSION
from .deps import get_session
from .jobs import JobConflict, JobManager
from .security import require_token
from .sessions import Session

router = APIRouter(tags=["settings"], dependencies=[Depends(require_token)])

log = logging.getLogger("kikusub.server")
renderer_log = logging.getLogger("kikusub.renderer")

MAX_LOG_LINES = 4000
MAX_MESSAGE = 4000
MAX_DETAIL = 8000
CLIENT_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


class SettingsPatch(BaseModel):
    enabled_engines: list[str] | None = None
    auto_proxy: bool | None = None


class ClientLog(BaseModel):
    level: str = "error"
    event: str = ""
    message: str = ""
    detail: str | int | float | bool | None = None


def _settings_path(request: Request) -> Path:
    return Path(getattr(request.app.state, "settings_path", settings_store.SETTINGS_PATH))


def _log_path(request: Request) -> Path:
    output_dir = Path(getattr(request.app.state.config, "output_dir", OUTPUT_DIR))
    return output_dir / "logs" / "kikusub.log"


def _tail(path: Path, lines: int) -> str:
    if lines <= 0 or not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-min(lines, MAX_LOG_LINES) :])


def _ffmpeg_info() -> dict:
    executable = shutil.which("ffmpeg")
    if not executable:
        return {"path": "", "version": "", "ok": False}
    try:
        import subprocess

        proc = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        first = (proc.stdout or "").splitlines()[0] if proc.stdout else ""
    except Exception:  # noqa: BLE001 - 诊断信息不该反过来把接口打挂
        first = ""
    return {"path": executable, "version": first, "ok": True}


def _runtime(request: Request) -> dict:
    return {
        "version": API_VERSION,
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "device": getattr(request.app.state, "device", "unknown"),
    }


def _paths(request: Request) -> dict:
    return {
        "output_dir": str(getattr(request.app.state.config, "output_dir", OUTPUT_DIR)),
        "models_dir": str(MODELS_DIR),
        "presets_path": str(PRESETS_PATH),
        "settings_path": str(_settings_path(request)),
        "log_path": str(_log_path(request)),
        "log_dir": str(_log_path(request).parent),
    }


def _payload(request: Request, settings: dict) -> dict:
    return {
        "settings": settings,
        "engines": engines.describe(
            enabled_keys=settings.get("enabled_engines") or [],
            include_size=True,
        ),
        "paths": _paths(request),
        "runtime": _runtime(request),
        "ffmpeg": _ffmpeg_info(),
    }


@router.get("/api/settings")
def get_settings(request: Request) -> dict:
    settings = settings_store.load_settings(_settings_path(request))
    return _payload(request, settings)


@router.patch("/api/settings")
def patch_settings(payload: SettingsPatch, request: Request) -> dict:
    patch: dict = {}
    if payload.enabled_engines is not None:
        unknown = [key for key in payload.enabled_engines if key not in engines.KEYS]
        if unknown:
            raise HTTPException(status_code=422, detail=f"未知引擎：{', '.join(unknown)}")
        patch["enabled_engines"] = payload.enabled_engines
    if payload.auto_proxy is not None:
        patch["auto_proxy"] = payload.auto_proxy
    if not patch:
        raise HTTPException(status_code=422, detail="没有需要更新的字段")

    try:
        settings = settings_store.save_settings(patch, _settings_path(request))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"设置写入失败：{exc}") from exc
    log.info("设置接口更新 | %s", json.dumps(patch, ensure_ascii=False))
    return _payload(request, settings)


@router.get("/api/engines")
def list_engines(request: Request) -> dict:
    settings = settings_store.load_settings(_settings_path(request))
    return {
        "engines": engines.describe(
            enabled_keys=settings.get("enabled_engines") or [],
            include_size=True,
        )
    }


@router.post("/api/engines/{engine_key}/download", status_code=201)
async def download_engine(
    engine_key: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    try:
        spec = engines.get(engine_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not spec.downloadable:
        raise HTTPException(status_code=400, detail=f"{spec.label} 不支持自动下载")

    manager: JobManager = request.app.state.jobs

    try:
        job = manager.start_download(
            engine_key,
            session_id=session.id,
            loop=asyncio.get_running_loop(),
        )
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log.info(
        "开始下载模型 | engine=%s | repo=%s | dir=%s | job=%s",
        engine_key,
        spec.hf_repo,
        engines.model_dir(spec),
        job.id,
    )
    return job.snapshot()


@router.post("/api/log")
def client_log(payload: ClientLog, request: Request) -> dict:
    """渲染进程/主进程的客户端日志落盘。

    这是「用户遇到问题 → 把日志发给我」链路的关键：渲染层的异常、API 失败、
    用户关键操作都会进同一个 kikusub.log，不再只存在于 DevTools 里。
    """
    level = CLIENT_LEVELS.get(payload.level.lower(), logging.ERROR)
    message = (payload.message or "")[:MAX_MESSAGE].replace("\n", " ↵ ")
    event = (payload.event or "client")[:120]
    detail = payload.detail
    if detail is not None and not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False)
    detail_text = str(detail or "")[:MAX_DETAIL]
    session_id = request.headers.get("x-kikusub-session", "")[:12] if hasattr(request, "headers") else ""
    renderer_log.log(
        level,
        "renderer | event=%s | session=%s | %s%s",
        event,
        session_id or "-",
        message,
        (f" | detail={detail_text}" if detail_text else ""),
    )
    return {"ok": True}


@router.get("/api/diagnostics")
def diagnostics(request: Request, lines: int = 200) -> dict:
    settings = settings_store.load_settings(_settings_path(request))
    log_path = _log_path(request)
    tail = _tail(log_path, max(1, min(lines, MAX_LOG_LINES)))
    errors = [
        line
        for line in tail.splitlines()
        if " ERROR " in line or " CRITICAL " in line or " WARNING " in line
    ][-30:]
    return {
        "generated_at": time.time(),
        "runtime": _runtime(request),
        "paths": _paths(request),
        "ffmpeg": _ffmpeg_info(),
        "settings": settings,
        "engines": engines.describe(
            enabled_keys=settings.get("enabled_engines") or [],
            include_size=True,
        ),
        "log_path": str(log_path),
        "log_exists": log_path.exists(),
        "log_tail": tail,
        "recent_problems": errors,
    }


@router.get("/api/diagnostics/log")
def diagnostics_log(request: Request, lines: int = 300) -> dict:
    log_path = _log_path(request)
    text = _tail(log_path, max(1, min(lines, MAX_LOG_LINES)))
    return {
        "path": str(log_path),
        "exists": log_path.exists(),
        "lines": len(text.splitlines()) if text else 0,
        "text": text,
    }
