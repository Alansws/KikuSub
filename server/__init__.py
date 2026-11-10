"""KikuSub 本地服务层（FastAPI）。

设计要点（对应改造规划 §2、§4）：

- 只监听 `127.0.0.1`，端口由 OS 分配（`--port 0`），启动后把真实端口与一次性 token
  写到 stdout 首行，Electron 主进程读取后注入渲染进程。
- 所有 `/api/*` 请求校验 token，防止本机其他进程调用；`/media/*` 因为是 `<video src>`
  直接请求（浏览器发不了自定义头），改走 `?token=` 查询参数。
- 这里**不 import app.py**：Gradio 旧界面通过 `mount_legacy()` 按需挂载到 `/legacy`，
  新界面走 `/api`，两者共用 `core/` 内核。
"""

from __future__ import annotations

__all__: list[str] = []
