"""「不管 200% 页面缩放」的机械守卫（`AGENTS.md` 红线 14，2026-11-24 用户决定）。

用户的报障不是「200% 下不好用」，而是「每次查一个界面问题，最后都查到 200% 这种
根本不会发生的场景上」。本应用**没有**缩放菜单，200% 只能靠系统辅助功能或外部注入
到达，1360×838 的有效视口会掉到 680×419——核对台的「侧栏 236 + 检查器 348」就已经
占满 584px，布局塌是必然结果，不是 bug。

规则写进 AGENTS.md 只是第一级（人会读到）。这里把它升级成会红的检查，因为
2026-11-24 那次 `verify_settings_layout.mjs` 真的报了 6 条失败，全部只在 200% 下出现，
排查成本被白烧了一遍。三级升级的落点：

1. 契约：`AGENTS.md` 红线 14 + `desktop-lifecycle.md` §3.7.1 + `review-console.md` §3.4.19；
2. **本文件**：脚本里一旦重新出现 200% 用例就红；
3. 视口清单：验收脚本的 CASES 里不许再出现 200% 条目。

注意：`KIKUSUB_ZOOM` 这个开发取证开关**保留**（`desktop/main/main.cjs`），规则只约束
「不要拿它做验收」，不是「删掉它」。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS = REPO_ROOT / "AGENTS.md"
CONTRACTS = REPO_ROOT / "docs" / "contracts"
SHOTS = REPO_ROOT / "tools" / "shots"

# 验收脚本所在目录。README.md 是文档，会解释「为什么不再测 200%」，不该被抓。
SKIP_NAMES = {"README.md"}


def _acceptance_scripts() -> list[Path]:
    if not SHOTS.exists():
        return []
    return [
        path
        for path in SHOTS.rglob("*")
        if path.is_file() and path.suffix in {".mjs", ".cjs", ".js", ".sh"} and path.name not in SKIP_NAMES
    ]


def test_agents_md_keeps_the_no_zoom200_rule():
    text = AGENTS.read_text(encoding="utf-8")
    assert "不管 200% 页面缩放" in text, "AGENTS.md 丢了「不管 200% 页面缩放」这条红线（红线 14）"
    for token in ("KIKUSUB_ZOOM", "test_no_zoom200_policy"):
        assert token in text, f"AGENTS.md 的红线 14 里丢了 `{token}`"


def test_contracts_record_the_decision():
    """决策必须落在契约里，否则下一个人只会看到「脚本里没有 200% 用例」这个结果。"""
    lifecycle = (CONTRACTS / "desktop-lifecycle.md").read_text(encoding="utf-8")
    assert "3.7.1 200% 页面缩放" in lifecycle, "desktop-lifecycle.md 缺 §3.7.1"

    console = (CONTRACTS / "review-console.md").read_text(encoding="utf-8")
    assert "3.4.19 200% 页面缩放不在支持范围" in console, "review-console.md 缺 §3.4.19"


def test_no_acceptance_script_has_a_zoom200_case():
    """验收脚本里不许再有 200% 用例：它们只会稳定报假红。"""
    offenders: list[str] = []
    pattern = re.compile(r"zoom\s*[:=]\s*2\b|zoom200|KIKUSUB_ZOOM|style\.zoom\s*=|webContents\.setZoomFactor")

    for path in _acceptance_scripts():
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{line_no}: {line.strip()}")

    assert offenders == [], (
        "验收脚本里又出现了 200% 缩放用例（AGENTS.md 红线 14 / desktop-lifecycle §3.7.1）：\n"
        + "\n".join(offenders)
        + "\n\n本应用没有缩放菜单，200% 不是用户可达状态，680×419 下布局必然塌。"
        "\n要验窄窗就用真实小窗口（例如 880x838 / 1000x700），不要用缩放模拟。"
    )


def test_acceptance_viewport_list_excludes_zoom200():
    """视口清单里只该有真实窗口尺寸。"""
    allowed = ("1440x900", "1360x838", "1120x800", "1000x700", "880x838", "680x900")
    names: list[str] = []
    case_re = re.compile(r"size:\s*'(\d+x\d+)'")

    for path in _acceptance_scripts():
        names.extend(case_re.findall(path.read_text(encoding="utf-8")))

    assert names, "没有在验收脚本里找到任何视口清单（CASES / size:），检查规则是否已过时"
    unknown = sorted({name for name in names if name not in allowed})
    assert unknown == [], (
        "验收脚本用了清单外的视口尺寸："
        + ", ".join(unknown)
        + f"\n允许：{', '.join(allowed)}（新增尺寸先更新本清单与 §3.7.1）"
    )
