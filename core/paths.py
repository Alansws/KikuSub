"""运行期路径中枢。

`core/` 会被原样搬进 `KikuSub.app/Contents/Resources/python/`，所以任何模块都不能
再用 `Path(__file__).resolve().parent` 去猜仓库根——那个值在打包后会指向 `core/`。
所有需要落盘的位置统一从这里派生，并允许用环境变量覆盖（打包后指向
`~/Library/Application Support/KikuSub/`）。
"""

from __future__ import annotations

import os
from pathlib import Path

# core/paths.py -> core/ -> 应用根（开发期是仓库根，打包后是 Resources/python）
APP_ROOT = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: Path) -> Path:
    raw = (os.environ.get(name) or "").strip()
    return Path(raw).expanduser().resolve() if raw else default


ROOT = APP_ROOT
MODELS_DIR = _env_path("KIKUSUB_MODELS_DIR", ROOT / "models")
OUTPUT_DIR = _env_path("KIKUSUB_OUTPUT_DIR", ROOT / "outputs")
PRESETS_PATH = _env_path("KIKUSUB_PRESETS_PATH", ROOT / "presets.json")
STATIC_DIR = _env_path("KIKUSUB_STATIC_DIR", ROOT / "static")
