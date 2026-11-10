"""统一的日志落盘配置。

目标不是“多打日志”，而是让用户报障时有一个可复制、可轮转、包含 traceback 的
本地文件：``outputs/logs/kikusub.log``。控制台仍保留一份，方便开发时直接看。

本模块只依赖标准库，便于在轻量 CI 中直接测试。
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
_NOISY_LOGGERS = (
    "httpx",
    "httpx2",
    "httpcore",
    "gradio",
    "urllib3",
    "huggingface_hub",
    "filelock",
    "matplotlib",
    "PIL",
    "asyncio",
)
_thread_hook_installed = False


def _install_thread_excepthook() -> None:
    """后台线程里未被捕获的异常也要进日志，否则守护线程会静默死掉。"""
    global _thread_hook_installed
    if _thread_hook_installed:
        return
    original = threading.excepthook

    def hook(args) -> None:  # noqa: ANN001 - 与标准库签名保持一致
        logging.getLogger("kikusub.thread").critical(
            "后台线程未捕获异常: %s",
            args.exc_value,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        try:
            original(args)
        except Exception:
            pass

    threading.excepthook = hook
    _thread_hook_installed = True


def setup_logging(
    log_dir: str | Path,
    *,
    level: int = logging.INFO,
    filename: str = "kikusub.log",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
    force: bool = False,
) -> Path:
    """配置根 logger 并返回日志文件路径；重复调用不会叠加 handler。"""
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename

    root = logging.getLogger()
    if force:
        for handler in list(root.handlers):
            if getattr(handler, "_kikusub_handler", False):
                root.removeHandler(handler)
                # 不立即 close：其他线程可能正好在 emit，关闭流会产生
                # "I/O operation on closed file" 的 logging 噪音。移除引用后
                # 交给 GC/解释器退出时回收即可。
                try:
                    handler.flush()
                except Exception:
                    pass

    if not any(getattr(h, "_kikusub_handler", False) for h in root.handlers):
        formatter = logging.Formatter(_LOG_FORMAT)

        file_handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        file_handler._kikusub_handler = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)

        if sys.stderr is not None:
            console = logging.StreamHandler(sys.stderr)
            console.setFormatter(formatter)
            console.setLevel(level)
            console._kikusub_handler = True  # type: ignore[attr-defined]
            root.addHandler(console)

    root.setLevel(min(root.level, level) if root.level else level)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(logging.WARNING, level))
    _install_thread_excepthook()
    return path
