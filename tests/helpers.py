"""测试公用小工具。

放在独立模块而不是 conftest 里，是为了能在需要时显式 import，
不必给每个用例加 fixture 参数。
"""

from __future__ import annotations

from pathlib import Path


def patch_output_dir(monkeypatch, path: Path) -> Path:
    """把所有模块的 `OUTPUT_DIR` 一起重定向到 `path`。

    为什么不能只打 `app.OUTPUT_DIR`：`core.report` / `core.audit` 在 import 时
    各自绑定了一份 `OUTPUT_DIR` 引用，只打 app 的桩不会影响 core 里的读写，
    结果就是「测试以为写进了 tmp_path，实际读写的是仓库里的 outputs/」。
    """
    from core import audit, paths, report

    import app

    for module in (app, paths, audit, report):
        if hasattr(module, "OUTPUT_DIR"):
            monkeypatch.setattr(module, "OUTPUT_DIR", path)
    return path
