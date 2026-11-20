"""运行期路径中枢。

`core/` 会被原样搬进 `KikuSub.app/Contents/Resources/python/`，所以任何模块都不能
再用 `Path(__file__).resolve().parent` 去猜仓库根——那个值在打包后会指向 `core/`。
所有需要落盘的位置统一从这里派生，并允许用环境变量覆盖（打包后指向
`~/Library/Application Support/KikuSub/`）。
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

# core/paths.py -> core/ -> 应用根（开发期是仓库根，打包后是 Resources/python）
APP_ROOT = Path(__file__).resolve().parent.parent

log = logging.getLogger(__name__)


def _env_path(name: str, default: Path) -> Path:
    raw = (os.environ.get(name) or "").strip()
    return Path(raw).expanduser().resolve() if raw else default


ROOT = APP_ROOT
MODELS_DIR = _env_path("KIKUSUB_MODELS_DIR", ROOT / "models")
OUTPUT_DIR = _env_path("KIKUSUB_OUTPUT_DIR", ROOT / "outputs")
PRESETS_PATH = _env_path("KIKUSUB_PRESETS_PATH", ROOT / "presets.json")
# 应用级设置（启用的引擎、AI 参数等）。和 presets.json 同级，打包后落在
# ~/Library/Application Support/KikuSub/settings.json。
SETTINGS_PATH = _env_path("KIKUSUB_SETTINGS_PATH", OUTPUT_DIR.parent / "settings.json")
STATIC_DIR = _env_path("KIKUSUB_STATIC_DIR", ROOT / "static")


def ensure_usable_cwd() -> str | None:
    """cwd 已被删掉时切到一个真实存在的目录；没动过则返回 None。

    打包脚本是 `rm -rf KikuSub.app` 后重新装配，而 sidecar 是 detached 的（父进程
    退出它也不跟着死）。装配那一刻它的 cwd 就变成一个已删除的 inode，之后每次
    `os.getcwd()` 都抛 `OSError(ENOENT)`：torch 在 import 期就会踩
    （`torch/_dynamo/config.py: default_debug_dir_root`），一次 Whisper/Qwen 转写
    就这样在 1 秒内失败，界面上只留一句 `[Errno 2] No such file or directory`，
    跟视频、模型都无关，极难反推。

    代价只有一次系统调用，所以启动时查一次、每次重任务前再查一次。
    """
    try:
        os.getcwd()
        return None
    except OSError:
        pass

    for candidate in (OUTPUT_DIR, Path.home(), Path(tempfile.gettempdir())):
        try:
            os.chdir(candidate)
        except OSError:
            continue
        log.warning(
            "进程工作目录已失效（典型原因：打包脚本覆盖了正在运行的 .app），已切换到 %s",
            candidate,
        )
        return str(candidate)
    return None
