"""发版脚本的版本号一致性（2026-11 起）。

背景：`tools/pack/build_app.sh` 曾经把 `"version": "0.2.0"` 硬编码在装配出来的
`package.json` 里，与 `desktop/package.json` 双写。发版时只改一处，`About` 里显示的
版本、DMG 文件名和 Git 标签就会互相打架——这类"两处维护同一个事实"的问题必须由测试守，
而不是靠发版 checklist（见 docs/contracts/engineering-practice.md）。
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_JSON = REPO_ROOT / "desktop" / "package.json"
PACKAGE_LOCK = REPO_ROOT / "desktop" / "package-lock.json"
BUILD_APP = REPO_ROOT / "tools" / "pack" / "build_app.sh"


def _version(path: Path) -> str:
    return json.loads(path.read_text(encoding="utf-8"))["version"]


def test_build_app_reads_version_from_package_json():
    script = BUILD_APP.read_text(encoding="utf-8")

    assert "desktop/package.json" in script, "build_app.sh 必须从 desktop/package.json 取版本"
    # 装配时写入的 package.json 里不允许再出现字面量版本号
    assert '"version": "0.' not in script, "build_app.sh 又写回了硬编码版本号"
    assert '"version": "$APP_VERSION"' in script, "装配产物应使用 $APP_VERSION 变量"


def test_package_lock_matches_package_json():
    """package-lock 根版本落后会导致 `npm ci` 报错，是发版翻车的常见来源。"""
    assert PACKAGE_LOCK.exists(), "缺少 desktop/package-lock.json"
    lock = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))

    assert lock["version"] == _version(PACKAGE_JSON)
    root = lock.get("packages", {}).get("", {})
    if "version" in root:
        assert root["version"] == _version(PACKAGE_JSON)
