"""sidecar 入口：`python -m server [--port 0]`

握手协议（Electron 主进程读 stdout 首行）：

```json
{"event": "ready", "port": 51234, "token": "…", "pid": 12345, "version": "0.1.0"}
```

端口由 OS 分配（`--port 0`），因此必须自己 bind 再把 socket 交给 uvicorn——
uvicorn 自己监听时拿不到「最终端口」，而主进程需要它来拼 URL。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from core.logging_setup import prune_logs, setup_logging
from core.paths import MODELS_DIR, PRESETS_PATH

from .app import API_VERSION, create_app
from .config import ServerConfig, new_token


def _start_log_maintenance(log_dir: Path, interval_s: float = 6 * 3600) -> None:
    """长驻进程也要定期清日志；用户可能开着应用好几天。"""

    def loop() -> None:
        while True:
            time.sleep(interval_s)
            try:
                prune_logs(log_dir)
            except Exception:  # noqa: BLE001 - 维护失败不能影响服务
                pass

    threading.Thread(target=loop, daemon=True, name="kikusub-log-maintenance").start()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m server", description="KikuSub 本地服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认只监听回环）")
    parser.add_argument("--port", type=int, default=0, help="端口；0 表示交给 OS 分配")
    parser.add_argument("--token", default="", help="指定访问 token；不传则随机生成")
    parser.add_argument("--log-level", default="info", choices=["critical", "error", "warning", "info", "debug"])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    config = ServerConfig(
        host=args.host,
        port=args.port,
        token=args.token or new_token(),
    )

    # 日志必须最先落地：之后任何启动失败（模型目录、ffmpeg、端口）都要能在
    # ~/Library/Application Support/KikuSub/outputs/logs/kikusub.log 里查到。
    log_path = setup_logging(
        Path(config.output_dir) / "logs",
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        force=True,
    )
    log = logging.getLogger("kikusub.server")
    _start_log_maintenance(Path(config.output_dir) / "logs")
    log.info("=" * 68)
    log.info(
        "KikuSub sidecar 启动 | version=%s | pid=%s | frozen=%s | python=%s",
        API_VERSION,
        os.getpid(),
        bool(getattr(sys, "frozen", False)),
        sys.version.split()[0],
    )
    log.info(
        "运行环境 | %s %s | ffmpeg=%s | ffprobe=%s",
        platform.platform(),
        platform.machine(),
        shutil.which("ffmpeg") or "(未找到)",
        shutil.which("ffprobe") or "(未找到)",
    )
    log.info(
        "运行期目录 | output=%s | models=%s | presets=%s | log=%s",
        config.output_dir,
        MODELS_DIR,
        PRESETS_PATH,
        log_path,
    )

    app = create_app(config)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((config.host, config.port))
    sock.listen(2048)
    actual_port = sock.getsockname()[1]

    # 首行握手：必须是 stdout 的第一行，主进程按行读取。
    print(
        json.dumps(
            {
                "event": "ready",
                "port": actual_port,
                "token": config.token,
                "pid": os.getpid(),
                "version": API_VERSION,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            log_level=args.log_level,
            access_log=False,
            # 我们自己的 logger 已经在 core.logging_setup 里配好；
            # 让 uvicorn 不要覆盖 root handler，否则会丢文件日志。
            log_config=None,
        )
    )
    try:
        server.run(sockets=[sock])
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
