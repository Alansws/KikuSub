"""源码树不许被 `.gitignore` 吞掉（2026-11-15 起）。

CI 在干净 checkout 上跑 `npm run build`，本地却因为「文件还躺在磁盘上」一路绿灯——
这是最隐蔽的一类红。2026-11-15 实际踩过：`.gitignore` 里 Python 虚拟环境那条 `env/`
没有前导 `/`，匹配了 `desktop/renderer/src/components/settings/env/`，3 个 Svelte
组件从未入库，Desktop job 在 `npm run build` 报
`Could not resolve "../../components/settings/env/HardwareMetrics.svelte"`。

守卫边界：
- 只看**代码树**（`CODE_ROOTS`）——这些目录里的文件应该都在仓库里，而不是靠本机残留；
- `docs/` 与 `tools/` 故意放本地私有素材（`docs/images/shots/current/`、
  `tools/eval/private/`、`tools/eval/*.srt`），不在此列，否则会误报；
- 代码树里允许被忽略的只有生成物（字节码、编辑器/系统垃圾、构建产物）。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# 会被 CI 构建 / 导入的代码树。任何人把这里的文件写进 .gitignore，CI 就会比本地少东西。
CODE_ROOTS = (
    "core/",
    "server/",
    "tests/",
    ".github/",
    "desktop/main/",
    "desktop/renderer/src/",
    "desktop/resources/",
)

# 代码树里允许被忽略的生成物
ALLOWED_SUFFIXES = (".pyc", ".pyo", ".swp", ".swo")
ALLOWED_NAMES = {".DS_Store", "Thumbs.db", ".coverage"}
ALLOWED_PARTS = {"__pycache__", "node_modules", "dist", "build", ".pytest_cache", ".ruff_cache"}


def _ignored_files() -> list[str]:
    """`git ls-files -o -i --exclude-standard`：被忽略且未入库的文件。"""
    if shutil.which("git") is None:
        pytest.skip("没有 git，跳过 gitignore 守卫")
    proc = subprocess.run(
        ["git", "ls-files", "-o", "-i", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip("不是 git 工作区，跳过 gitignore 守卫")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def test_no_code_file_is_gitignored():
    offenders: list[str] = []
    for rel in _ignored_files():
        posix = rel.replace("\\", "/")
        if not posix.startswith(CODE_ROOTS):
            continue
        parts = posix.split("/")
        name = parts[-1]
        if name in ALLOWED_NAMES or name.endswith(ALLOWED_SUFFIXES):
            continue
        if any(part in ALLOWED_PARTS for part in parts):
            continue
        offenders.append(posix)

    assert offenders == [], (
        "这些代码树里的文件被 .gitignore 忽略了：CI 的干净 checkout 拿不到它们，"
        "本地却因为文件还在磁盘而一切正常。\n  "
        + "\n  ".join(sorted(offenders))
        + "\n\n改 .gitignore 时目录规则要加前导 `/` 锚定到仓库根（`env/` 曾把 "
        "desktop/renderer/src/components/settings/env/ 吞掉）；确属产物的路径加进 ALLOWED_PARTS。"
    )
