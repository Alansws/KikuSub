"""运行期路径中枢。

`core/` 会被原样搬进 `KikuSub.app/Contents/Resources/python/`，所以任何模块都不能
再用 `Path(__file__).resolve().parent` 去猜仓库根——那个值在打包后会指向 `core/`。
所有需要落盘的位置统一从这里派生，并允许用环境变量覆盖（打包后指向
`~/Library/Application Support/KikuSub/`）。
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

# core/paths.py -> core/ -> 应用根（开发期是仓库根，打包后是 Resources/python）
APP_ROOT = Path(__file__).resolve().parent.parent

log = logging.getLogger(__name__)

# 单个工具名的解析优先级（改这里之前先读 docs/contracts/desktop-lifecycle.md §3.8）：
#   1. ``KIKUSUB_FFMPEG`` / ``KIKUSUB_FFPROBE``：显式文件路径，排最前（用户把 ffmpeg
#      装在奇怪位置时的最后手段）；
#   2. ``KIKUSUB_FFMPEG_DIR``：一个目录，里面放着 ffmpeg 与 ffprobe（主进程早就
#      支持这个变量，错误文案里也写过，不能改成别的名字）；
#   3. **应用包内的** ``Contents/Resources/bin/``：Step 7 起随 .app 分发的静态
#      ffmpeg / ffprobe。没有 Homebrew 的普通用户靠这一层「双击即用」；
#   4. 系统 PATH（开发机上的 Homebrew 走这一层）；
#   5. 兜底返回裸名字，让 ``subprocess`` 抛 ``FileNotFoundError``——上层那些
#      「找不到 ffmpeg，请先 brew install」的提示就是接这个异常的。
FFMPEG_ENV_FILE = "KIKUSUB_FFMPEG"
FFPROBE_ENV_FILE = "KIKUSUB_FFPROBE"
FFMPEG_ENV_DIR = "KIKUSUB_FFMPEG_DIR"


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


# --------------------------------------------------------------------------- 外部工具


def _bundled_bin_candidates() -> list[Path]:
    """「包内 bin」可能在哪：开发态一层，冻结后要多看两层。

    - 开发态：`core/paths.py` 在 `<repo>/core/`，`APP_ROOT` 是仓库根，
      `APP_ROOT.parent / "bin"` 就是「仓库旁边的 bin」——通常是空的，于是落到
      Homebrew（开发机本来就装了）。
    - 打包态（**实测过的坑**）：PyInstaller onedir 会把 `core` 冻进可执行文件，
      `__file__` 变成 `<onedir>/core/paths.py`，也就是
      `Contents/Resources/python/sidecar/core/paths.py`——`APP_ROOT` 是 **onedir
      目录本身**，`APP_ROOT.parent` 是 `Resources/python`，不是 `Resources`。
      所以必须再往上找两层才能到 `Contents/Resources/bin`。
      （第一版只取了 `APP_ROOT.parent / "bin"`，结果日志里写着
      `bundled_bin=…/Resources/python/bin`、「PATH+=(无)」，包内 ffmpeg 根本没被发现。）
    """
    bases = [APP_ROOT]
    if getattr(sys, "frozen", False):
        bases.append(Path(sys.executable).resolve().parent)
    candidates: list[Path] = []
    for base in bases:
        for up in range(0, 4):
            try:
                candidates.append(base.parents[up] / "bin")
            except IndexError:
                break
    return candidates


def bundled_bin_dir() -> Path:
    """随包静态二进制目录（优先返回真实存在的那个候选）。

    `KIKUSUB_BUNDLE_BIN` 是最高优先级：主进程打包态会显式传
    `<resourcesPath>/bin`，不依赖任何目录层数推断；验收脚本也用它把任意临时目录
    当成「包内 bin」。没有它时才按 :func:`_bundled_bin_candidates` 推。
    """
    raw = (os.environ.get("KIKUSUB_BUNDLE_BIN") or "").strip()
    if raw:
        return Path(raw).expanduser()
    candidates = _bundled_bin_candidates()
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def _executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


# 解析失败的环境变量只在第一次告警：``ffmpeg_bin()`` 是每条命令调一次的，
# 配错一个变量不该在日志里刷出几百行。
_WARNED: set[str] = set()


def _warn_once(key: str, message: str, *args: object) -> None:
    if key in _WARNED:
        return
    _WARNED.add(key)
    log.warning(message, *args)


def _explicit_tool(name: str, env_file: str) -> str | None:
    raw = (os.environ.get(env_file) or "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if _executable(candidate):
        return str(candidate)
    _warn_once(f"{env_file}:{raw}", "%s 指向的文件不可执行，忽略：%s", env_file, candidate)
    return None


def _resolve_tool(name: str, env_file: str) -> str:
    explicit = _explicit_tool(name, env_file)
    if explicit:
        return explicit

    dir_override = (os.environ.get(FFMPEG_ENV_DIR) or "").strip()
    if dir_override:
        candidate = Path(dir_override).expanduser() / name
        if _executable(candidate):
            return str(candidate)
        _warn_once(
            f"{FFMPEG_ENV_DIR}:{dir_override}",
            "%s 里没有可执行的 %s，忽略：%s",
            FFMPEG_ENV_DIR,
            name,
            dir_override,
        )

    bundled = bundled_bin_dir() / name
    if _executable(bundled):
        return str(bundled)

    found = shutil.which(name)
    if found:
        return found

    # 不要返回空字符串：上层拼命令时那会变成「第一个参数是空串」，报错变成
    # 难以理解的 ``[Errno 13] Permission denied: ''``。裸名字能让 ``subprocess``
    # 抛 ``FileNotFoundError``，各模块已经把它翻译成「请安装 ffmpeg」。
    return name


def ffmpeg_bin() -> str:
    """ffmpeg 的绝对路径（找不到时退回裸名字 ``ffmpeg``）。

    每次调用都重新解析、不缓存：验收脚本与单测靠 monkeypatch 环境变量切换
    「有没有内置 ffmpeg」，缓存会让它们互相污染；而这点 ``stat`` 与一次 ffmpeg
    解码相比可以忽略。
    """
    return _resolve_tool("ffmpeg", FFMPEG_ENV_FILE)


def ffprobe_bin() -> str:
    """ffprobe 的绝对路径（同 :func:`ffmpeg_bin`，找不到时退回裸名字）。"""
    return _resolve_tool("ffprobe", FFPROBE_ENV_FILE)


def install_bundled_bin_path() -> list[str]:
    """把内置 bin 与 ``KIKUSUB_FFMPEG_DIR`` 前置进 PATH；返回实际新增的目录。

    只做兜底：核心路径都走 :func:`ffmpeg_bin`，但用户可能自己装了个 Demucs /
    插件、或在诊断里被外部脚本拿 PATH 找 ffmpeg。前置而不是追加，保证「包内
    自带」优先于系统里另一份版本不一致的 ffmpeg。重复调用幂等。
    """
    added: list[str] = []
    wanted: list[str] = []
    dir_override = (os.environ.get(FFMPEG_ENV_DIR) or "").strip()
    if dir_override:
        wanted.append(str(Path(dir_override).expanduser()))
    wanted.append(str(bundled_bin_dir()))

    parts = [p for p in (os.environ.get("PATH") or "").split(os.pathsep) if p]
    for directory in reversed(wanted):
        if not Path(directory).is_dir():
            continue
        if directory in parts:
            continue
        parts.insert(0, directory)
        added.append(directory)
    if added:
        os.environ["PATH"] = os.pathsep.join(parts)
        log.info("PATH 前置内置工具目录 | %s", ", ".join(added))
    return added


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
