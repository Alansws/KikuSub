"""应用级设置（JSON 落盘，原子写）。

只放「跨会话需要记住、且后端要知道」的偏好；纯界面状态（主题、波形高度）
留在渲染进程的 localStorage。这样服务层不用关心 UI 细节。

当前字段：

- `enabled_engines`：工具栏与转写页允许使用的引擎；引擎配置页的开关写这里。
- `auto_proxy`：导入 MKV/HEVC 时是否自动压制 480p 监看代理。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from . import engines
from .paths import SETTINGS_PATH
from .textio import write_text_atomic

log = logging.getLogger(__name__)

DEFAULTS: dict = {
    "enabled_engines": list(engines.DEFAULT_ENABLED),
    "auto_proxy": True,
}


def _normalize(raw: dict | None) -> dict:
    data = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return data

    enabled = raw.get("enabled_engines")
    if isinstance(enabled, list):
        picked = {str(item) for item in enabled}
        # 保持注册表顺序，前端/DOM 不会因为勾选顺序跳来跳去
        data["enabled_engines"] = [key for key in engines.KEYS if key in picked]
    if isinstance(raw.get("auto_proxy"), bool):
        data["auto_proxy"] = raw["auto_proxy"]
    return data


def load_settings(path: Path | None = None) -> dict:
    target = Path(path or SETTINGS_PATH)
    if not target.exists():
        return dict(DEFAULTS)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("设置文件读取失败，使用默认值 | %s", target, exc_info=True)
        return dict(DEFAULTS)
    return _normalize(raw)


def save_settings(patch: dict, path: Path | None = None) -> dict:
    """合并式更新：只覆盖 patch 里出现的字段。"""
    target = Path(path or SETTINGS_PATH)
    current = load_settings(target)
    merged = dict(current)
    if "enabled_engines" in patch:
        merged["enabled_engines"] = patch.get("enabled_engines")
    if "auto_proxy" in patch:
        merged["auto_proxy"] = bool(patch.get("auto_proxy"))
    normalized = _normalize(merged)
    try:
        write_text_atomic(target, json.dumps(normalized, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        log.exception("设置文件写入失败 | %s", target)
        raise
    log.info(
        "设置已更新 | enabled_engines=%s | auto_proxy=%s | path=%s",
        ",".join(normalized["enabled_engines"]) or "(无)",
        normalized["auto_proxy"],
        target,
    )
    return normalized
