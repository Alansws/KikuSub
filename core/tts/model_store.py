"""OmniVoice 权重下载：后台线程 + 目录大小进度。

为什么不用 ``JobManager`` 的 download 槽：TTS 模型下载和转写不是同一类资源
（它只吃网络/磁盘，且秒级可取消），塞进单槽会让用户为了下载模型而排队等转写。
这里用一个独立的守护线程，状态只存在内存里；重启后靠 ``installed()`` 重新判断。
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from .clone_engine import REPO_ID, missing_model_files, model_installed

log = logging.getLogger(__name__)

# 拿不到远端文件清单时的兜底期望值（model 2.45GB + tokenizer 0.8GB）。
FALLBACK_BYTES = int(3.3 * 1024**3)
POLL_SECONDS = 1.0


def _dir_size(root: Path) -> int:
    total = 0
    try:
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
    except OSError:
        return total
    return total


class ModelDownloader:
    def __init__(self, model_dir: Path | str, *, repo_id: str = REPO_ID) -> None:
        self.model_dir = Path(model_dir).expanduser()
        self.repo_id = repo_id
        # RLock：``start()`` 在锁内会回读 ``status()``（同样加锁），普通 Lock 会死锁。
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._status: dict = {
            "status": "idle",
            "percent": 0,
            "stage": "",
            "error": "",
            "bytes": 0,
            "total": 0,
        }
        if self.installed():
            self._status.update(status="done", percent=100, stage="模型已就绪")

    def installed(self) -> bool:
        return not self.missing_files()

    def missing_files(self) -> list[str]:
        return missing_model_files(self.model_dir)

    def verify(self) -> dict:
        """只读校验：不下载、不占任务槽，给设置页「校验 / 补齐」用。"""
        missing = self.missing_files()
        return {
            "installed": not missing,
            "missing": missing,
            "model_dir": str(self.model_dir),
            "repo": self.repo_id,
            "bytes": _dir_size(self.model_dir),
        }

    def status(self) -> dict:
        with self._lock:
            payload = dict(self._status)
        payload["installed"] = self.installed()
        payload["missing"] = self.missing_files()
        payload["model_dir"] = str(self.model_dir)
        payload["repo"] = self.repo_id
        if payload["installed"]:
            payload["status"] = "done"
            payload["percent"] = 100
        return payload

    def start(self) -> dict:
        with self._lock:
            if self.installed():
                self._status.update(status="done", percent=100, stage="模型已就绪")
                return self.status()
            if self._thread is not None and self._thread.is_alive():
                return self.status()
            self._status.update(
                status="running", percent=0, stage="连接 Hugging Face…", error=""
            )
            self._thread = threading.Thread(
                target=self._run, name="kikusub-tts-download", daemon=True
            )
            self._thread.start()
        return self.status()

    # -- 内部 ---------------------------------------------------------------

    def _set(self, **fields) -> None:
        with self._lock:
            self._status.update(fields)

    def _remote_total(self) -> int:
        try:
            from huggingface_hub import HfApi

            info = HfApi().model_info(self.repo_id, files_metadata=True)
            total = sum(int(item.size or 0) for item in info.siblings or [])
            return total or FALLBACK_BYTES
        except Exception:  # noqa: BLE001 —— 进度兜底，不影响下载本身
            return FALLBACK_BYTES

    def _poll(self, stop: threading.Event, total: int) -> None:
        while not stop.wait(POLL_SECONDS):
            size = _dir_size(self.model_dir)
            percent = min(99, int(size * 100 / max(1, total)))
            with self._lock:
                if self._status["status"] != "running":
                    return
                self._status["bytes"] = size
                self._status["total"] = total
                self._status["percent"] = max(self._status["percent"], percent)
                self._status["stage"] = "正在下载 OmniVoice 权重…"

    def _run(self) -> None:
        total = self._remote_total()
        self._set(total=total, stage="正在下载 OmniVoice 权重…")
        stop = threading.Event()
        poller = threading.Thread(
            target=self._poll, args=(stop, total), name="kikusub-tts-download-poll", daemon=True
        )
        poller.start()
        try:
            from huggingface_hub import snapshot_download

            self.model_dir.mkdir(parents=True, exist_ok=True)
            snapshot_download(
                repo_id=self.repo_id,
                local_dir=str(self.model_dir),
                ignore_patterns=["*.md", ".gitattributes"],
                max_workers=2,
            )
            if not self.installed():
                missing = self.missing_files()
                raise RuntimeError("下载完成但缺少文件：" + "、".join(missing))
            self._set(status="done", percent=100, stage="模型已就绪", bytes=_dir_size(self.model_dir))
            log.info("OmniVoice 模型下载完成 | %s", self.model_dir)
        except Exception as exc:  # noqa: BLE001
            self._set(status="error", stage="下载失败", error=f"{type(exc).__name__}: {exc}")
            log.warning("OmniVoice 模型下载失败：%s", exc)
        finally:
            stop.set()
            with self._lock:
                self._status["total"] = total


def download_status(model_dir: Path | str) -> dict:
    """无状态查询：给还没创建 downloader 的调用方用。"""
    root = Path(model_dir).expanduser()
    installed = model_installed(root)
    return {
        "status": "done" if installed else "idle",
        "percent": 100 if installed else 0,
        "installed": installed,
        "model_dir": str(root),
        "repo": REPO_ID,
        "time": time.time(),
    }
