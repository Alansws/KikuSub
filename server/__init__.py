"""KikuSub 本地服务层（FastAPI）。

设计要点（对应改造规划 §2、§4）：

- 只监听 `127.0.0.1`，端口由 OS 分配（`--port 0`），启动后把真实端口与一次性 token
  写到 stdout 首行，Electron 主进程读取后注入渲染进程。
- 所有 `/api/*` 请求校验 token，防止本机其他进程调用；`/media/*` 因为是 `<video src>`
  直接请求（浏览器发不了自定义头），改走 `?token=` 查询参数。
- 这里**不 import 任何 UI**：桌面端渲染层只通过 `/api` 与 `/media` 访问，
  旧 Gradio 界面已从本仓库移除（归档于 `v0.9-gradio` 标签与本地独立目录）。
"""

from __future__ import annotations

API_VERSION = "0.1.0"

__all__: list[str] = ["API_VERSION"]
