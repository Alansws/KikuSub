"""发版闸门的"看守测试"（2026-11-13 起）。

背景：发版规范（`docs/release.md`）里能自动化的部分，落成了三处程序化约束——
本地 `tools/release/preflight.sh`、可选的 `tools/git-hooks/pre-push`、CI 的 `release-tag` job。
它们全是**配置与脚本**，不像业务代码那样天天被改动，所以很容易在某次清理里被"顺手简化"掉，
而删掉之后不会立刻报错——直到某次发版翻车。

这里把四条不变量冻住（对应 `docs/release.md` §7 的对照表）：

1. 规范文档必须指向真实存在的工具（文档与脚本不许各走各的）；
2. `preflight.sh` 必须从 `desktop/package.json` 取版本，不许再写死一份（版本双写是发版
   翻车的头号来源，`tests/test_pack_version.py` 守的是装配脚本那一份）；
3. 本地钩子只许拦发版 tag，且必须复用 preflight（不许偷偷实现第二套检查）；
4. CI 必须保留 `release-tag` job 的两个断言：tag == version、tag 提交在 main 上。

图标只做尺寸与透明底断言：`build_app.sh` 每次都从 `docs/app-icon.png` 重渲染 icns，
所以真正会坏的是"源图被换成非 1024 或丢了 alpha"，而不是 icns 本身漂移。
"""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_DOC = REPO_ROOT / "docs" / "release.md"
PREFLIGHT = REPO_ROOT / "tools" / "release" / "preflight.sh"
HOOK = REPO_ROOT / "tools" / "git-hooks" / "pre-push"
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PACKAGE_JSON = REPO_ROOT / "desktop" / "package.json"
APP_ICON = REPO_ROOT / "docs" / "app-icon.png"


def _is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & stat.S_IXUSR)


def test_release_doc_points_at_real_tool():
    assert RELEASE_DOC.exists(), "缺少 docs/release.md（发版规范是四步流程的唯一依据）"
    text = RELEASE_DOC.read_text(encoding="utf-8")

    assert "tools/release/preflight.sh" in text, "发版规范必须写出前置检查脚本的真实路径"
    assert "app/macos" in text and "main" in text, "发版规范必须写明分支模型（main 主线 / app/macos 开发）"
    assert "回滚" in text, "发版规范必须写清回滚口径（本项目没有云端更新配置）"


def test_preflight_takes_version_from_package_json():
    assert PREFLIGHT.exists(), "缺少 tools/release/preflight.sh"
    assert _is_executable(PREFLIGHT), "preflight.sh 必须可执行"

    script = PREFLIGHT.read_text(encoding="utf-8")
    assert "desktop/package.json" in script, "preflight.sh 必须从 desktop/package.json 读版本"

    version = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["version"]
    # 脚本里出现当前版本号的字面量，说明又有人在某处写死了一份
    assert f'"{version}"' not in script and f"={version}" not in script, (
        f"preflight.sh 里出现了写死的版本号 {version}，版本必须从 package.json 读"
    )


def test_shell_scripts_have_no_unbraced_multibyte_expansion():
    """bash 在含全角字符的行里会把 `$VAR（` 解析成 `$VAR` + 半个多字节字符。

    2026-11-13 连炸两次：`pass "version = $VERSION（tag 应为 ...)"` 报
    `VERSION<乱码>: unbound variable`；`tools/check/svelte-check.sh` 又踩了一遍。
    规则：脚本里的变量展开一律写成 `${VAR}`。这里扫全仓的 shell 脚本，不只 preflight。
    """
    scripts = sorted(
        list((REPO_ROOT / "tools").rglob("*.sh"))
        + [REPO_ROOT / "tools" / "git-hooks" / "pre-push"]
    )
    assert scripts, "没找到任何 shell 脚本，检查路径"

    bad: list[str] = []
    for path in scripts:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*[（）：，。；、—]", line):
                bad.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert bad == [], "存在未加花括号的变量展开（后接全角字符）：\n" + "\n".join(bad)


def test_desktop_check_scripts_are_wired():
    """`npm run check`（tsc）与 `check:svelte`（基线守卫）必须都在，且 svelte-check 版本钉死。

    版本漂移会让 svelte-check 的报错口径变化、基线数字变假红，所以这里要求精确版本。
    """
    pkg = json.loads((REPO_ROOT / "desktop" / "package.json").read_text(encoding="utf-8"))
    scripts = pkg.get("scripts", {})

    assert scripts.get("check") == "tsc --noEmit", "npm run check 必须是 tsc --noEmit（CI 的硬闸门）"
    assert "svelte-check" in scripts.get("check:svelte", ""), "npm run check:svelte 必须调用基线守卫脚本"
    version = pkg["devDependencies"].get("svelte-check", "")
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"svelte-check 必须钉死精确版本（当前 {version!r}），否则基线数字会随版本漂移"
    )

    baseline = json.loads(
        (REPO_ROOT / "desktop" / "test" / "svelte-check-baseline.json").read_text(encoding="utf-8")
    )
    assert baseline["svelteCheck"] == version, "基线与 devDependencies 的 svelte-check 版本必须一致"
    assert isinstance(baseline["errors"], int) and baseline["errors"] >= 0


def test_pre_push_hook_only_intercepts_release_tags():
    assert HOOK.exists(), "缺少 tools/git-hooks/pre-push"
    assert _is_executable(HOOK), "pre-push 必须可执行"

    script = HOOK.read_text(encoding="utf-8")
    assert "refs/tags/v*" in script, "钩子必须只拦 v* 发版 tag，普通分支推送要放行"
    assert "tools/release/preflight.sh" in script, "钩子必须复用 preflight.sh，不许实现第二套检查"
    assert "git config core.hooksPath tools/git-hooks" in script, "钩子里要写清启用方式（每个 clone 一次）"


def test_ci_keeps_release_tag_gate():
    """CI 配置没有任何东西看守，删掉 job 不会报错——所以在这里冻住两个断言。"""
    text = CI.read_text(encoding="utf-8")

    assert "release-tag:" in text, "CI 的 release-tag job 被删了（发版闸门失效）"
    assert "startsWith(github.ref, 'refs/tags/v')" in text, "release-tag 必须在推 v* tag 时才跑"
    assert "desktop/package.json" in text, "release-tag 必须校验 tag 与 package.json 版本一致"
    assert "merge-base --is-ancestor" in text, "release-tag 必须校验 tag 的提交在 main 上"
    assert "fetch-depth: 0" in text, "祖先判断需要完整历史，release-tag 必须 fetch-depth: 0"


def test_app_icon_is_1024_rgba():
    """图标源被换成非 1024 或丢了 alpha，iconutil 会生成模糊/白角的 icns。"""
    pytest.importorskip("PIL")
    from PIL import Image

    with Image.open(APP_ICON) as im:
        assert (im.width, im.height) == (1024, 1024), f"图标必须是 1024×1024，实际 {im.size}"
        assert im.mode == "RGBA", f"图标必须带 alpha（RGBA），实际 {im.mode}"
