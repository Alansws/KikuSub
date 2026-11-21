"""ffmpeg / ffprobe 的解析顺序（2026-11-21 界面重构 Step 7）。

用户报障的根因：**macOS 不自带 ffmpeg，而从访达启动的 .app 只拿到
`/usr/bin:/bin:/usr/sbin:/sbin`**——Homebrew 的 `/opt/homebrew/bin` 不在里面，
于是「下载 .app、双击、导入视频」对没装过 Homebrew 的普通用户是直接失败。
主进程早就在补 PATH（`main.cjs`），但那只在「用户自己装过 Homebrew」时有效。

Step 7 改为**随 .app 分发静态 ffmpeg/ffprobe**，所以这里锁四件事：

1. 解析顺序：显式文件 → 显式目录 → 包内 bin → 系统 PATH → 裸名字兜底；
2. 包内目录的位置：`core/` 在 `Contents/Resources/python/core/`，
   所以包内 bin 就是 `APP_ROOT.parent / "bin"`，不能靠猜 `sys._MEIPASS`；
3. 不允许再出现「裸 `"ffmpeg"` 当命令头」——漏一处就等于在无 Homebrew 的机器上
   漏一条功能，而且是运行到那一步才炸；
4. 打包脚本真的把二进制、许可全文与来源 NOTICE 放进 `.app`，并且钉死 sha256。
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

from core import paths

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_APP = REPO_ROOT / "tools" / "pack" / "build_app.sh"
FETCH_FFMPEG = REPO_ROOT / "tools" / "pack" / "fetch_ffmpeg.sh"
GPL_TEXT = REPO_ROOT / "tools" / "pack" / "ffmpeg-COPYING.GPLv3.txt"

TOOL_ENV = (
    paths.FFMPEG_ENV_FILE,
    paths.FFPROBE_ENV_FILE,
    paths.FFMPEG_ENV_DIR,
    "KIKUSUB_BUNDLE_BIN",
)


@pytest.fixture(autouse=True)
def _clean_tool_env(monkeypatch):
    """每个用例都从「什么都没配」开始：本机真实的 Homebrew 不能参与断言。"""
    for name in TOOL_ENV:
        monkeypatch.delenv(name, raising=False)
    paths._WARNED.clear()
    yield
    paths._WARNED.clear()


def _fake_tool(directory: Path, name: str) -> Path:
    """在目录里放一个可执行的假工具（只需要能 stat 到 +x，不会被真的执行）。"""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    target.chmod(0o755)
    return target


def test_bundled_bin_beats_system_path(monkeypatch, tmp_path):
    """包内自带的那份必须优先于系统 PATH 里另一份（版本可能不一致）。"""
    bundled = tmp_path / "Resources" / "bin"
    _fake_tool(bundled, "ffmpeg")
    _fake_tool(bundled, "ffprobe")
    system = tmp_path / "system-bin"
    _fake_tool(system, "ffmpeg")

    monkeypatch.setenv("KIKUSUB_BUNDLE_BIN", str(bundled))
    monkeypatch.setenv("PATH", str(system))

    assert paths.ffmpeg_bin() == str(bundled / "ffmpeg")
    assert paths.ffprobe_bin() == str(bundled / "ffprobe")


def test_explicit_env_wins_over_bundled(monkeypatch, tmp_path):
    """用户显式指定就该赢：这是「我把 ffmpeg 装在奇怪位置」的最终手段。"""
    bundled = tmp_path / "bundle"
    _fake_tool(bundled, "ffmpeg")
    custom = tmp_path / "custom"
    custom_tool = _fake_tool(custom, "ffmpeg")

    monkeypatch.setenv("KIKUSUB_BUNDLE_BIN", str(bundled))
    monkeypatch.setenv("KIKUSUB_FFMPEG_DIR", str(custom))
    assert paths.ffmpeg_bin() == str(custom_tool)

    # 文件级变量优先级更高，且允许与目录变量同时存在
    monkeypatch.setenv(paths.FFMPEG_ENV_FILE, str(bundled / "ffmpeg"))
    assert paths.ffmpeg_bin() == str(bundled / "ffmpeg")


def test_invalid_env_falls_through(monkeypatch, tmp_path, caplog):
    """配错的环境变量只告警一次，然后继续往下找——不能让 app 起不来。"""
    bundled = tmp_path / "bundle"
    _fake_tool(bundled, "ffmpeg")
    monkeypatch.setenv("KIKUSUB_BUNDLE_BIN", str(bundled))
    monkeypatch.setenv(paths.FFMPEG_ENV_FILE, str(tmp_path / "nope" / "ffmpeg"))
    monkeypatch.setenv("KIKUSUB_FFMPEG_DIR", str(tmp_path / "nope-dir"))

    with caplog.at_level("WARNING"):
        for _ in range(3):
            assert paths.ffmpeg_bin() == str(bundled / "ffmpeg")

    warnings = [r for r in caplog.records if "忽略" in r.getMessage()]
    assert len(warnings) == 2, "两个坏变量各告警一次；重复调用不该刷屏"


def test_falls_back_to_path_when_no_bundle(monkeypatch, tmp_path):
    """开发机（仓库根旁边没有 bin/）照旧用 Homebrew。"""
    system = tmp_path / "system-bin"
    tool = _fake_tool(system, "ffmpeg")
    monkeypatch.setenv("KIKUSUB_BUNDLE_BIN", str(tmp_path / "absent"))
    monkeypatch.setenv("PATH", str(system))

    assert paths.ffmpeg_bin() == str(tool)


def test_returns_bare_name_when_nothing_found(monkeypatch, tmp_path):
    """找不到时返回裸名字：上层靠它触发 FileNotFoundError →「请安装 ffmpeg」。

    返回空串会让 subprocess 报 `[Errno 13] Permission denied: ''`，完全没法排查。
    """
    monkeypatch.setenv("KIKUSUB_BUNDLE_BIN", str(tmp_path / "absent"))
    monkeypatch.setenv("PATH", str(tmp_path / "also-absent"))

    assert paths.ffmpeg_bin() == "ffmpeg"
    assert paths.ffprobe_bin() == "ffprobe"


def test_bundled_bin_dir_is_resources_bin_in_packaged_layout(monkeypatch, tmp_path):
    """打包后 core/ 在 Resources/python/core/，包内 bin 必须是 Resources/bin。

    这里用假的「打包后 APP_ROOT」反推：不依赖本机装没装 .app，也不联网。
    """
    packaged_python = tmp_path / "KikuSub.app" / "Contents" / "Resources" / "python"
    packaged_python.mkdir(parents=True)
    monkeypatch.setattr(paths, "APP_ROOT", packaged_python)

    resolved = paths.bundled_bin_dir()
    assert resolved == tmp_path / "KikuSub.app" / "Contents" / "Resources" / "bin"
    assert resolved.name == "bin"


def test_install_bundled_bin_path_prepends_once(monkeypatch, tmp_path):
    """sidecar 启动时把包内 bin 前置进 PATH，重复调用幂等。"""
    bundled = tmp_path / "Resources" / "bin"
    bundled.mkdir(parents=True)
    monkeypatch.setenv("KIKUSUB_BUNDLE_BIN", str(bundled))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    added = paths.install_bundled_bin_path()
    assert added == [str(bundled)]
    assert os.environ["PATH"].split(os.pathsep)[0] == str(bundled)

    assert paths.install_bundled_bin_path() == []
    assert os.environ["PATH"].split(os.pathsep).count(str(bundled)) == 1


def _command_heads(tree: ast.AST) -> list[tuple[int, str]]:
    """找出「列表字面量的第一个元素是裸工具名」的地方（= 真会被 spawn 的命令）。"""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
            continue
        head = node.elts[0]
        if isinstance(head, ast.Constant) and head.value in {"ffmpeg", "ffprobe"}:
            hits.append((getattr(node, "lineno", 0), str(head.value)))
    return hits


def test_no_module_spawns_bare_ffmpeg():
    """命令头必须是 ``core.paths.ffmpeg_bin()`` / ``ffprobe_bin()``。

    这条守的是「静默退化」：漏改一处不会让测试变红，只会在没装 Homebrew 的机器上
    让某个具体功能（导出 / 缩略图 / TTS 归一化 / 人声分离）单独失败。
    """
    offenders: list[str] = []
    for directory in ("core", "server"):
        for path in sorted((REPO_ROOT / directory).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for lineno, name in _command_heads(tree):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno} 用了裸 {name!r}")

    assert offenders == [], (
        "这些地方没走 core.paths 的解析，打包后（没有 Homebrew）会找不到 ffmpeg：\n"
        + "\n".join(offenders)
    )


def test_build_app_embeds_binaries_license_and_notice():
    script = BUILD_APP.read_text(encoding="utf-8")

    assert "build/pack/vendor/ffmpeg" in script, "build_app.sh 要从 vendor 目录取二进制"
    assert 'Contents/Resources/bin' in script, "core/paths.py 按 Contents/Resources/bin 找"
    assert "LICENSE-ffmpeg-GPLv3.txt" in script, "分发 GPLv3 二进制必须带许可全文"
    assert "NOTICE-ffmpeg.txt" in script, "来源与 sha256 要随包（GPL 的来源要求）"
    assert 'codesign --force --sign - "$BUNDLED_DST/ffmpeg"' in script, "嵌套二进制要单独签名"
    assert "KIKUSUB_REQUIRE_BUNDLED_FFMPEG" in script, "发版时缺内置 ffmpeg 必须能变成硬失败"


def test_fetch_script_pins_version_and_checksums():
    """二进制不入库，所以「钉死版本 + 校验 sha256」是唯一的来源保证。"""
    script = FETCH_FFMPEG.read_text(encoding="utf-8")

    assert re.search(r'FFMPEG_VERSION="\d', script), "版本必须钉死在脚本里"
    checksums = re.findall(r'_[A-Z_]*SHA256="([0-9a-f]{64})"', script)
    assert len(checksums) == 2, "ffmpeg.zip / ffprobe.zip 各需要一个 sha256"
    assert "shasum -a 256" in script, "下载后必须自己算一遍 sha256"
    assert "ffmpeg.martin-riedl.de" in script, "来源要写清楚（构建者 + 站点）"
    assert "arm64" in script, "随包的必须是 Apple Silicon 静态构建"

    # GPLv3 全文要能在仓库里找到（fetch 后装配时拷进 .app）
    assert GPL_TEXT.is_file(), "缺少 tools/pack/ffmpeg-COPYING.GPLv3.txt"
    assert "GNU GENERAL PUBLIC LICENSE" in GPL_TEXT.read_text(encoding="utf-8")


def test_ffmpeg_info_reports_bundled_source(monkeypatch, tmp_path):
    """设置页诊断要能说清楚「用的是包内那份还是系统那份」。"""
    from server import routes_settings

    bundled = tmp_path / "Resources" / "bin"
    _fake_tool(bundled, "ffmpeg")
    monkeypatch.setenv("KIKUSUB_BUNDLE_BIN", str(bundled))

    assert routes_settings._ffmpeg_source(str(bundled / "ffmpeg")) == "bundled"
    monkeypatch.setenv("KIKUSUB_FFMPEG_DIR", str(tmp_path))
    assert routes_settings._ffmpeg_source("/somewhere/else/ffmpeg") == "explicit"
