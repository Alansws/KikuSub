"""FastAPI 应用装配。

职责边界：这里只做「把路由拼起来 + 错误翻译」，不含任何业务逻辑。
业务逻辑要么在 `core/`，要么在 `server/routes_*.py`。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.paths import MODELS_DIR
from core.presets import PresetStore

from . import API_VERSION
from .config import ServerConfig
from .jobs import JobManager
from .media import MediaError, MediaStore
from .routes_ai import router as ai_router
from .routes_cues import router as cues_router
from .routes_jobs import router as jobs_router
from .routes_media import router as media_router
from .routes_presets import router as presets_router
from .routes_qa import router as qa_router
from .routes_report import router as report_router
from .routes_session import router as session_router
from .routes_settings import router as settings_router
from .routes_translations import router as translations_router
from .security import require_token
from .sessions import SessionStore

log = logging.getLogger("kikusub.server")

def _warmup(app: FastAPI) -> None:
    """后台预热推理内核。

    为什么要单独起线程：`import core.pipeline` 会拉起 torch / transformers，
    耗时约 7 秒。如果放在请求里做，用户点「开始转写」后会**干等 7 秒没反应**。
    放在启动后的后台线程里，这 7 秒和「用户挑文件、看界面」重叠掉了。

    握手仍然在 0.5 秒内完成，所以窗口该多快就多快（规划 §5 指标 5）。
    """
    try:
        from core.transcribe import detect_device

        import core.pipeline  # noqa: F401  —— 真正把 torch 拉起来的就是这一行

        app.state.device = detect_device()
        log.info("内核预热完成 | device=%s", app.state.device)
    except Exception:
        app.state.device = "unavailable"
        log.exception("内核预热失败（不影响启动，首次转写会慢一些）")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    threading.Thread(target=_warmup, args=(app,), daemon=True, name="kikusub-warmup").start()
    yield


def create_app(config: ServerConfig | None = None) -> FastAPI:
    config = config or ServerConfig()

    app = FastAPI(
        title="KikuSub Local API",
        version=API_VERSION,
        # 本地自用服务，文档端点没有意义，还多两条攻击面
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
    )
    app.state.config = config
    app.state.token = config.token
    app.state.settings_path = config.settings_path
    # 由后台预热线程写入；设置页/底部状态栏在预热完成前显示“检测中”。
    app.state.device = "unknown"
    app.state.media = MediaStore(output_dir=config.output_dir)
    app.state.sessions = SessionStore()
    app.state.presets = PresetStore()
    app.state.jobs = JobManager(config.output_dir)

    # 渲染进程可能以 file:// 或 vite dev server 为 origin 发请求；真正的门是 token，
    # 这里放开 origin 只是为了不被浏览器预检拦住。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def _log_requests(request: Request, call_next):
        """把每个 API 请求写进日志。

        排查用户问题时最缺的往往不是 traceback，而是「他到底点了什么、服务回了几
        几毫秒、哪个会话」。`/media/*` 与波形轮询量太大，降为 DEBUG；写操作、
        错误、任务/质检/报告接口保留 INFO。token 永远不写进日志。
        """
        req_id = uuid.uuid4().hex[:8]
        request.state.req_id = req_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # 统一由下面的 exception_handler 记录堆栈，这里只把 req id 带过去，
            # 避免同一个异常打两遍。
            raise
        elapsed = (time.perf_counter() - started) * 1000
        response.headers["X-Request-Id"] = req_id
        path = request.url.path
        if path.startswith(("/api", "/media")):
            noisy = path.endswith("/peaks") or path.startswith("/media/")
            important = (
                request.method != "GET"
                or response.status_code >= 400
                or path in {"/api/jobs", "/api/qa", "/api/report", "/api/diagnostics"}
            )
            # 客户端日志自己会写一行，不必再让中间件重复一条
            if path == "/api/log":
                important = False
            level = logging.INFO if (important and not noisy) or response.status_code >= 400 else logging.DEBUG
            session_id = (
                request.headers.get("x-kikusub-session", "")
                or request.cookies.get("kikusub_sid", "")
            )[:8]
            log.log(
                level,
                "%s %s -> %s | %.0fms | req=%s | sid=%s",
                request.method,
                path,
                response.status_code,
                elapsed,
                req_id,
                session_id or "-",
            )
        return response

    @app.exception_handler(MediaError)
    async def _media_error(_: Request, exc: MediaError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """兜底：任何未捕获异常都回 JSON。

        否则 Starlette 会回纯文本 `Internal Server Error`，
        前端 `JSON.parse` 直接炸成「Unexpected token 'I'」——用户看不懂，
        我们也定位不到。日志里仍然有完整堆栈。
        """
        log.exception(
            "未处理异常 | %s %s | req=%s",
            request.method,
            request.url.path,
            getattr(request.state, "req_id", "-"),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": f"{type(exc).__name__}: {exc}"},
        )

    app.include_router(media_router)
    app.include_router(cues_router)
    app.include_router(presets_router)
    app.include_router(jobs_router)
    app.include_router(report_router)
    app.include_router(qa_router)
    app.include_router(session_router)
    app.include_router(settings_router)
    app.include_router(ai_router)
    app.include_router(translations_router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": API_VERSION}

    @app.get("/api/config", dependencies=[Depends(require_token)])
    def runtime_config() -> dict:
        """前端启动时拉一次的运行期信息（对应旧界面的 `device_banner`）。

        引擎列表来自 `core.engines` 注册表，带上 installed/enabled，工具栏据此
        只显示用户启用的引擎；`size` 字段特意不算（目录遍历留给设置页）。
        """
        from core import engines as engine_registry
        from core import settings as settings_store

        current = settings_store.load_settings(config.settings_path)
        return {
            "version": API_VERSION,
            "device": getattr(app.state, "device", "unknown"),
            "models_dir": str(MODELS_DIR),
            "output_dir": str(config.output_dir),
            # 字幕实际落盘目录（设置页可改）；output_dir 仍存放日志/质检/代理。
            "export_dir": str(
                settings_store.resolve_export_dir(current, Path(config.output_dir))
            ),
            "settings_path": str(config.settings_path),
            "formats": ["SRT", "VTT", "TXT"],
            "engines": [
                {**item, "desc": item["description"]}
                for item in engine_registry.describe(
                    enabled_keys=current.get("enabled_engines") or [],
                    include_size=False,
                )
            ],
            "settings": current,
        }

    return app


def media_paths_for_import(raw: str) -> Path:
    """导入路径的轻量规范化，供 CLI / Electron 复用。"""
    return Path(raw).expanduser().resolve()
