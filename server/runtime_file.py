"""运行期握手文件：让外部 CLI 在 `~/.local/bin/kikusub` 找到正在运行的 App。

为什么需要：端口由 OS 分配（`--port 0`），token 每次启动随机生成。CLI 不能在
磁盘上猜这两个值，主进程也只把握手交给渲染层。sidecar 自己写一份 `runtime.json`
是唯一稳定的发现通道。

安全口径：

- **0600**：token 等于本机 API 的全部权限，同机其他用户不能读；
- 只写 `<output_dir>/runtime.json`，不写 `$TMPDIR`（临时目录可能是共享的）；
- 原子替换：先写同目录 0600 临时文件再 `os.replace`，CLI 永远读不到半截 JSON；
- 优雅退出时删掉；崩溃/强杀留下的文件由 CLI 用 pid 探活识别，不当作可用实例。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

RUNTIME_VERSION = 1
FILE_NAME = "runtime.json"


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # 显式 chmod：umask 与既有文件都可能让 0600 落空
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


class RuntimeFile:
    """一个进程一份的运行期握手文件；`note_session` 只在会话变化时落盘。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._payload: dict = {}
        self._session_id = ""

    def write(self, *, port: int, token: str, version: str, output_dir: Path | str) -> None:
        with self._lock:
            self._payload = {
                "app": "KikuSub",
                "runtime_version": RUNTIME_VERSION,
                "api_version": str(version),
                "port": int(port),
                "token": str(token),
                "pid": os.getpid(),
                "started_at": round(time.time(), 3),
                "output_dir": str(output_dir),
                "session_id": self._session_id,
            }
            _atomic_write(self.path, self._payload)

    def note_session(self, session_id: str) -> None:
        """记住渲染层正在用的会话 id。

        **只应由「客户端带着已有 id 进来」的请求调用**：CLI 自己会新建一个空会话，
        如果那个 id 也被记下来，下一次 CLI 就会读到空会话而不是 App 里正在编辑的字幕。
        """
        sid = str(session_id or "").strip()
        if not sid or not self._payload:
            return
        with self._lock:
            if sid == self._session_id:
                return
            self._session_id = sid
            self._payload["session_id"] = sid
            _atomic_write(self.path, self._payload)

    def clear(self) -> None:
        """只删自己写的文件：sidecar 被替换/重启时不能误删新实例的握手。"""
        with self._lock:
            try:
                data = json.loads(self.path.read_text("utf-8"))
            except (OSError, ValueError):
                data = {}
            if int(data.get("pid") or 0) not in (0, os.getpid()):
                return
            try:
                self.path.unlink()
            except OSError:
                pass
            self._payload = {}


def read_runtime(path: Path | str) -> dict | None:
    """CLI 侧共用的解析（也用于测试）：文件缺失或 JSON 坏了都返回 None。"""
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
