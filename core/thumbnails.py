"""最近打开列表用的视频缩略图。

设计目标只有一个：**便宜且不拿黑场当封面**。

- 只解开头 60 秒，按 1fps 抽帧后用 FFmpeg 的 ``thumbnail`` 滤镜挑一张
  「最有代表性」的帧。该滤镜按直方图方差打分，开头由黑场淡入的视频不会
  选中纯黑帧；整段黑场才会退化成黑图，这是可接受的边界。
- 生成一次后按「路径 + mtime + 大小」缓存成 JPG，下次列表直接读文件。
- 同一时间最多跑 2 个 ffmpeg：导入页一次可能展示 6 条最近打开，全部并行会
  把 CPU 瞬间吃满；缩略图不值得。
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path

from .procutil import CommandCancelled, CommandTimeout, run_command, tail

log = logging.getLogger(__name__)

# 只取前 60 秒参与挑选：覆盖常见的「黑场 → 片头 logo → 正片」过渡，又不会
# 为了封面解码整部电影。实测 1080p/3.3GB 的素材约 1.4 秒。
SAMPLE_SECONDS = 60.0
SAMPLE_FPS = 1
SAMPLE_FRAMES = int(SAMPLE_SECONDS * SAMPLE_FPS)
THUMB_WIDTH = 480
FFMPEG_TIMEOUT_S = 30.0
CONCURRENCY = 2

_SEMAPHORE = threading.BoundedSemaphore(CONCURRENCY)
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


class ThumbnailError(RuntimeError):
    """缩略图生成失败（文件不可读 / 没有视频轨 / ffmpeg 报错）。"""


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def cache_key(source: Path, width: int = THUMB_WIDTH) -> str:
    stat = source.stat()
    payload = f"{source.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{width}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:24]


def _run(cmd: list[str]) -> None:
    try:
        with _SEMAPHORE:
            proc = run_command(cmd, timeout=FFMPEG_TIMEOUT_S)
    except FileNotFoundError as exc:
        raise ThumbnailError("找不到 ffmpeg，无法生成视频缩略图") from exc
    except CommandTimeout as exc:
        raise ThumbnailError("生成缩略图超时") from exc
    except CommandCancelled as exc:
        raise ThumbnailError("应用正在退出，缩略图任务已取消") from exc
    if proc.returncode != 0:
        raise ThumbnailError(tail(proc.stderr or proc.stdout) or "ffmpeg 生成缩略图失败")


def _frame_has_signal(path: Path) -> bool:
    """判断一帧是否“有画面”，而不是纯黑 / 接近纯黑。

    只看亮部占比与平均亮度：黑场淡入的第一帧通常平均亮度极低且几乎没有
    高亮像素；片头 logo 虽然是黑底，但有明确的亮部，应该保留。
    Pillow 不可用时按“有内容”处理——静态构建里 Pillow 是硬依赖，缺它时
    宁可返回首帧，也不要为了缩略图把接口打挂。
    """
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return True
    try:
        with Image.open(path) as image:
            gray = image.convert("L")
            gray.thumbnail((64, 36))
            values = list(gray.tobytes())
    except Exception:  # noqa: BLE001
        return True
    if not values:
        return False
    total = len(values)
    mean = sum(values) / total
    bright = sum(1 for value in values if value >= 24) / total
    return mean >= 6 or bright >= 0.01


def thumbnail_for(
    source: Path | str,
    cache_dir: Path | str,
    *,
    width: int = THUMB_WIDTH,
) -> Path:
    """返回缩略图路径；不存在时生成并原子落盘。

    失败抛 :class:`ThumbnailError`，调用方（路由）转成 404/422，前端退回占位图标。
    """
    path = Path(source).expanduser()
    try:
        if not path.is_file():
            raise ThumbnailError("视频文件不存在")
    except OSError as exc:
        raise ThumbnailError(f"无法读取视频文件：{exc}") from exc

    directory = Path(cache_dir).expanduser()
    key = cache_key(path, width)
    target = directory / f"{key}.jpg"
    if target.is_file() and target.stat().st_size > 0:
        return target

    with _lock_for(key):
        # 双检：等锁期间可能已被另一个请求生成。
        if target.is_file() and target.stat().st_size > 0:
            return target
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ThumbnailError(f"无法创建缩略图缓存目录：{exc}") from exc

        temp = directory / f".{key}.{os.getpid()}.{time.time_ns()}.jpg"
        first = directory / f".{key}.{os.getpid()}.{time.time_ns()}.first.jpg"
        common = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
        scaled = f"scale={width}:-2:flags=fast_bilinear"

        def single_frame(at: float, target: Path) -> None:
            _run(
                common
                + [
                    "-ss", f"{max(0.0, at):.3f}",
                    "-i", str(path),
                    "-map", "0:v:0",
                    "-an",
                    "-sn",
                    "-vf", scaled,
                    "-frames:v", "1",
                    "-q:v", "4",
                    str(target),
                ]
            )

        try:
            # 第一优先：真正的首帧。多数视频的首帧就是用户想看的画面。
            try:
                single_frame(0.0, first)
            except ThumbnailError as exc:
                log.info("读取视频首帧失败，改用代表帧 | %s | %s", path, exc)
            if first.is_file() and first.stat().st_size > 0 and _frame_has_signal(first):
                os.replace(first, target)
                return target

            # 首帧是纯黑/接近黑场：用 thumbnail 在前 60 秒里挑一张有画面内容的。
            # 先缩放再抽帧：thumbnail 会把整批帧留在内存里，1080p×60 帧能吃掉
            # 过半 GB；480p 之后只有二十多 MB。
            try:
                _run(
                    common
                    + [
                        "-ss", "0",
                        "-t", f"{SAMPLE_SECONDS:.0f}",
                        "-i", str(path),
                        "-map", "0:v:0",
                        "-an",
                        "-sn",
                        "-vf", f"{scaled},fps={SAMPLE_FPS},thumbnail={SAMPLE_FRAMES}",
                        "-frames:v", "1",
                        "-q:v", "4",
                        str(temp),
                    ]
                )
            except ThumbnailError as exc:
                # thumbnail 滤镜不可用：退回第 1 秒的单帧。可能仍是黑场，
                # 但总比在最近打开里显示破图好。
                log.info("thumbnail 滤镜失败，回退单帧 | %s | %s", path, exc)
                single_frame(1.0, temp)
            if not temp.is_file() or temp.stat().st_size <= 0:
                raise ThumbnailError("ffmpeg 没有输出缩略图")
            os.replace(temp, target)
            return target
        except OSError as exc:
            raise ThumbnailError(f"保存缩略图失败：{exc}") from exc
        finally:
            for leftover in (temp, first):
                try:
                    leftover.unlink(missing_ok=True)
                except OSError:
                    pass
