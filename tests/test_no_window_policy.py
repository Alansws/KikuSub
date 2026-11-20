"""无窗口铁律的机械守卫（`AGENTS.md` §0.5，2026-11-16 用户红线）。

用户的报障是「每次改个功能都反复弹 Electron 窗口，干扰这台电脑上别的事」。规则写进
AGENTS.md 只是第一级（人会读到）；这里把它升级成会红的检查，防止后来的改动把默认值
改回「开发模式直接 show」。真正的行为判定在 `desktop/test/window-mode.test.cjs`，这里
守的是「接线还在、文档没被删、验证表没再要求裸跑 `npx electron .`」。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS = REPO_ROOT / "AGENTS.md"
MAIN = REPO_ROOT / "desktop" / "main" / "main.cjs"
WINDOWMODE = REPO_ROOT / "desktop" / "main" / "windowmode.cjs"
WINDOWMODE_TEST = REPO_ROOT / "desktop" / "test" / "window-mode.test.cjs"
REBUILD = REPO_ROOT / "tools" / "pack" / "rebuild.sh"


def test_windowmode_module_and_its_test_exist():
    """判定必须是独立纯函数，且有单测——否则又会散回 main.cjs 的 if/else 里。"""
    assert WINDOWMODE.exists(), "缺少 desktop/main/windowmode.cjs（窗口可见性判定）"
    text = WINDOWMODE.read_text(encoding="utf-8")
    assert "resolveWindowMode" in text
    assert "KIKUSUB_ALLOW_WINDOW" in text
    assert "KIKUSUB_NO_WINDOW" in text
    assert WINDOWMODE_TEST.exists(), "缺少 desktop/test/window-mode.test.cjs"


def test_main_process_wires_the_decision_instead_of_guessing():
    """主进程必须调用判定，并在截图时把窗口做成透明（不再 showInactive 直接见人）。"""
    src = MAIN.read_text(encoding="utf-8")
    assert "require('./windowmode.cjs')" in src
    assert "windowmode.resolveWindowMode(" in src
    assert "win.setOpacity(0)" in src, "截图路径必须把窗口设成全透明，否则桌面上会亮几秒"
    assert "win.showInactive()" in src, "透明窗口仍需参与合成，应为 setOpacity(0) + showInactive()"


def test_agents_md_keeps_the_no_window_rule():
    text = AGENTS.read_text(encoding="utf-8")
    assert "## 0.5 无窗口铁律" in text
    for token in ("KIKUSUB_ALLOW_WINDOW", "KIKUSUB_NO_WINDOW", "npx electron . --screenshot"):
        assert token in text, f"AGENTS.md 的无窗口铁律里丢了 `{token}`"


def test_verification_table_does_not_ask_for_a_visible_launch():
    """验证时机表里出现的 `npx electron .` 必须带 --screenshot，否则等于要求开窗验证。"""
    offenders = [
        line
        for line in AGENTS.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("|") and "npx electron ." in line and "--screenshot" not in line
    ]
    assert offenders == [], "验证时机表要求了可见窗口：\n" + "\n".join(offenders)


def test_rebuild_script_is_build_only_by_default():
    src = REBUILD.read_text(encoding="utf-8")
    assert "OPEN_APP=0" in src, "rebuild.sh 默认必须不打开应用"
    assert "--open)" in src and "--no-open)" in src
