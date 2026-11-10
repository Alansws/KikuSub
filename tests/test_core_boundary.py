"""守住 `core/` 的边界：内核包必须能在没有 UI 依赖的干净解释器里独立导入。

这条测试是整个 macOS 改造的前提——只要它还绿，`python -m core.smoke` 和打包后的
sidecar 就一定能起来；一旦有人往 core 里塞了 `import gradio`，这里会立刻红。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_MODULES = ["gradio", "fastapi", "uvicorn", "starlette"]

CORE_MODULES = [
    "core.paths",
    "core.procutil",
    "core.jobs",
    "core.presets",
    "core.logging_setup",
    "core.audio_cache",
    "core.transcribe",
    "core.qwen_ctc",
    "core.report",
    "core.audit",
    "core.cues",
    "core.textio",
    "core.pipeline",
]


def test_core_imports_without_ui_dependencies() -> None:
    code = (
        "import sys\n"
        f"import {', '.join(CORE_MODULES)}\n"
        f"leak = [m for m in {UI_MODULES!r} if m in sys.modules]\n"
        "print(','.join(leak))\n"
        "sys.exit(1 if leak else 0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, (
        "core 包泄漏了 UI 依赖：" + proc.stdout.strip() + proc.stderr
    )


def test_paths_are_anchored_at_app_root() -> None:
    """路径中枢必须指向应用根，而不是 core/ 自己（否则打包后模型目录全错）。"""
    from core import paths

    assert paths.ROOT == REPO_ROOT
    assert paths.ROOT.name != "core"
    assert paths.MODELS_DIR.parent == paths.ROOT
    assert paths.PRESETS_PATH.name == "presets.json"


def test_paths_can_be_relocated_by_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """打包后靠环境变量把可写目录挪到 Application Support，这里验证覆盖生效。"""
    monkeypatch.setenv("KIKUSUB_OUTPUT_DIR", str(tmp_path / "out"))
    import importlib

    from core import paths

    reloaded = importlib.reload(paths)
    try:
        assert reloaded.OUTPUT_DIR == (tmp_path / "out").resolve()
    finally:
        monkeypatch.delenv("KIKUSUB_OUTPUT_DIR", raising=False)
        importlib.reload(paths)
