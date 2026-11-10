"""FastAPI 应用装配。

职责边界：这里只做「把路由拼起来 + 错误翻译 + 按需挂载旧界面」，不含任何业务逻辑。
业务逻辑要么在 `core/`，要么在 `server/routes_*.py`。
"""

from __future__ import annotations

import importlib
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.paths import MODELS_DIR, OUTPUT_DIR
from core.presets import PresetStore

from .config import ServerConfig
from .jobs import JobManager
from .media import MediaError, MediaStore
from .routes_cues import router as cues_router
from .routes_jobs import router as jobs_router
from .routes_media import router as media_router
from .routes_presets import router as presets_router
from .routes_qa import router as qa_router
from .routes_report import router as report_router
from .routes_session import router as session_router
from .security import require_token
from .sessions import SessionStore

log = logging.getLogger("kikusub.server")

API_VERSION = "0.1.0"


def _warmup() -> None:
    """后台预热推理内核。

    为什么要单独起线程：`import core.pipeline` 会拉起 torch / transformers，
    耗时约 7 秒。如果放在请求里做，用户点「开始转写」后会**干等 7 秒没反应**。
    放在启动后的后台线程里，这 7 秒和「用户挑文件、看界面」重叠掉了。

    握手仍然在 0.5 秒内完成，所以窗口该多快就多快（规划 §5 指标 5）。
    """
    try:
        from core.transcribe import detect_device

        import core.pipeline  # noqa: F401  —— 真正把 torch 拉起来的就是这一行

        log.info("内核预热完成 | device=%s", detect_device())
    except Exception:
        log.exception("内核预热失败（不影响启动，首次转写会慢一些）")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    threading.Thread(target=_warmup, daemon=True, name="kikusub-warmup").start()
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
        log.exception("未处理异常 | %s %s", request.method, request.url.path)
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

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": API_VERSION}

    @app.get("/api/config", dependencies=[Depends(require_token)])
    def runtime_config() -> dict:
        """前端启动时拉一次的运行期信息（对应旧界面的 `device_banner`）。"""
        from core.transcribe import detect_device

        return {
            "version": API_VERSION,
            "device": detect_device(),
            "models_dir": str(MODELS_DIR),
            "output_dir": str(OUTPUT_DIR),
            "formats": ["SRT", "VTT", "TXT"],
            "engines": [
                {"key": "whisper", "label": "Anime Whisper", "desc": "自然连贯的日语对话转写"},
                {"key": "qwen", "label": "Qwen3-ASR + CTC", "desc": "逐字发声时间对齐"},
            ],
            "legacy_ui": bool(config.legacy),
        }

    if config.legacy:
        _mount_legacy(app)

    return app


def _mount_legacy(app: FastAPI) -> None:
    """把旧 Gradio 界面挂到 `/legacy`。

    阶段 2–6 期间它是完整功能的回退通道；阶段 7 删除 Gradio 依赖后一并移除。
    导入 `app` 模块会构建整个 Blocks（约 3–5 s），所以只在显式开启时做。
    """
    import gradio as gr

    legacy = importlib.import_module("app")
    demo = getattr(legacy, "demo", None)
    if demo is None:
        log.warning("旧界面没有 demo 对象，跳过 /legacy 挂载")
        return
    gr.mount_gradio_app(app, demo, path="/legacy")
    log.info("旧 Gradio 界面已挂载到 /legacy")


def media_paths_for_import(raw: str) -> Path:
    """导入路径的轻量规范化，供 CLI / Electron 复用。"""
    return Path(raw).expanduser().resolve()
