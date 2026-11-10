"""sidecar 入口：`python -m server [--port 0] [--legacy]`

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
import socket
import sys

import uvicorn

from .app import API_VERSION, create_app
from .config import ServerConfig, new_token


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m server", description="KikuSub 本地服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认只监听回环）")
    parser.add_argument("--port", type=int, default=0, help="端口；0 表示交给 OS 分配")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="把旧 Gradio 界面挂到 /legacy（阶段 2–6 的回退通道，会多花 3–5 s 启动时间）",
    )
    parser.add_argument("--token", default="", help="指定访问 token；不传则随机生成")
    parser.add_argument("--log-level", default="info", choices=["critical", "error", "warning", "info", "debug"])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    config = ServerConfig(
        host=args.host,
        port=args.port,
        token=args.token or new_token(),
        legacy=args.legacy,
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
                "legacy": config.legacy,
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
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
