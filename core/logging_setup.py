"""统一的日志落盘配置。

目标不是“多打日志”，而是让用户报障时有一个可复制、可轮转、包含 traceback 的
本地文件：``outputs/logs/kikusub.log``。控制台仍保留一份，方便开发时直接看。

本模块只依赖标准库，便于在轻量 CI 中直接测试。
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
import threading
import time
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
# 日志会被用户复制出来发人，token 绝不能跟着走。uvicorn 的 WebSocket 访问日志
# 会原样打印 `?token=...`，所以统一在格式化出口做一次脱敏。
_SECRET_PATTERNS = (
    (re.compile(r"(token=)[^&\s\"']+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE), r"\1***"),
)


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for pattern, replacement in _SECRET_PATTERNS:
            text = pattern.sub(replacement, text)
        return text


# 保留策略：14 天或整个日志目录 64 MB，先到先删。只删轮转备份，永远不碰
# 正在写入的 kikusub.log / main.log（活动文件由 RotatingFileHandler 轮转）。
LOG_RETENTION_DAYS = 14
LOG_MAX_TOTAL_BYTES = 64 * 1024 * 1024
ACTIVE_LOG_NAMES = frozenset({"kikusub.log", "main.log"})

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


def _is_log_file(name: str) -> bool:
    lower = name.lower()
    return lower.endswith(".log") or ".log." in lower


def prune_logs(
    log_dir: str | Path,
    *,
    max_age_days: int = LOG_RETENTION_DAYS,
    max_total_bytes: int = LOG_MAX_TOTAL_BYTES,
    active_names: frozenset[str] | set[str] = ACTIVE_LOG_NAMES,
) -> dict:
    """清理过期/超量的日志备份，返回可展示的统计（供设置页「清理旧日志」）。

    只处理形如 ``*.log`` / ``*.log.N`` 的文件；活动日志即使过期也不删，
    否则正在写的 handler 会指向一个已删除的 inode。
    """
    directory = Path(log_dir)
    try:
        entries = list(directory.iterdir())
    except OSError:
        return {"removed": 0, "freed": 0, "total_bytes": 0, "kept": 0}

    files: list[tuple[Path, int, float]] = []
    for path in entries:
        try:
            if not path.is_file() or not _is_log_file(path.name):
                continue
            stat = path.stat()
        except OSError:
            continue
        files.append((path, stat.st_size, stat.st_mtime))

    cutoff = time.time() - max(0, max_age_days) * 24 * 60 * 60
    removed = 0
    freed = 0

    def remove(path: Path, size: int) -> bool:
        nonlocal removed, freed
        try:
            path.unlink()
        except OSError:
            return False
        removed += 1
        freed += size
        return True

    for path, size, mtime in files:
        if path.name in active_names:
            continue
        if mtime < cutoff:
            remove(path, size)

    def total_bytes() -> int:
        total = 0
        for path, size, _ in files:
            try:
                if path.exists():
                    total += size
            except OSError:
                continue
        return total

    total = total_bytes()
    backups = sorted(
        (item for item in files if item[0].name not in active_names),
        key=lambda item: item[2],
    )
    for path, size, _ in backups:
        if total <= max_total_bytes:
            break
        try:
            if not path.exists():
                continue
        except OSError:
            continue
        if remove(path, size):
            total -= size

    kept = sum(1 for path, _, _ in files if path.exists())
    return {
        "removed": removed,
        "freed": freed,
        "total_bytes": max(0, total),
        "kept": kept,
        "log_dir": str(directory),
    }


def clear_logs(log_dir: str | Path, *, active_names: frozenset[str] | set[str] = ACTIVE_LOG_NAMES) -> dict:
    """用户主动「清空全部日志」：轮转活动日志，再删掉所有备份。

    与 :func:`prune_logs` 的区别是**一定**会释放空间：prune 只按保留策略删过期
    备份，在「只有一个 5 MB 活动日志、没有轮转备份」时返回 0，用户会以为按钮坏了。
    这里先把活动文件滚成 ``.log.1``（handler 自己关闭/重开，不碰 inode），再把
    备份按 0 天 / 0 字节策略全部删掉。永远不直接 truncate 正在写的 handler 流。
    """
    directory = Path(log_dir)
    rotated = 0
    if directory.exists():
        root = logging.getLogger()
        for handler in list(root.handlers):
            if not getattr(handler, "_kikusub_handler", False):
                continue
            if not isinstance(handler, logging.handlers.RotatingFileHandler):
                continue
            try:
                handler.acquire()
                handler.doRollover()
                rotated += 1
            except Exception:  # noqa: BLE001 - 轮转失败退化为普通清理
                logging.getLogger(__name__).debug("活动日志轮转失败", exc_info=True)
            finally:
                try:
                    handler.release()
                except Exception:
                    pass

    result = prune_logs(
        directory,
        max_age_days=0,
        max_total_bytes=0,
        active_names=active_names,
    )
    result["rotated"] = rotated
    return result


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
        formatter = _RedactingFormatter(_LOG_FORMAT)

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
    # 启动时清一次：旧版本可能留下很多 5 MB 的轮转文件
    try:
        prune_logs(directory)
    except Exception:  # noqa: BLE001 - 日志清理失败不能拖垮启动
        logging.getLogger(__name__).debug("日志清理失败", exc_info=True)
    return path
