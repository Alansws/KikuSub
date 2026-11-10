"""KikuSub 算法内核包。

这里只放与 UI 无关的东西：转录引擎、CTC 对齐、音频缓存、任务注册表、
子进程工具、预设存储、日志与路径。

**硬约束**：本包内任何模块都不得 import gradio / fastapi / electron 相关的东西。
这条约束由 `python -m core.smoke` 与 `tests/test_core_boundary.py` 共同看守。
"""

from __future__ import annotations

__all__ = ["paths"]
