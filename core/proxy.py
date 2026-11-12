"""480p 监看代理压制（无 UI 依赖）。

Chromium 解不开 MKV / HEVC，所以导入后要么让用户看原片（黑屏），要么压一份 480p
H.264 代理。这份代理是「拖动进度条流畅秒开」的前提。

从 `app.py` 的 `manual_transcode_proxy_generator` 抽出编排，保留全部工程约束：

- **标准路径失败要回退**：VideoToolbox 全硬解 → 软解 + VideoToolbox 编码 → libx264 CPU，
  三条命令依次尝试；实时压制失败后再走一次非实时的 `create_proxy`。
- **写 `*.part.mp4` 再原子 rename**：半成品绝不能被下一次「历史代理」当成成品复用。
- **进度只认单调值**：ffmpeg 偶发回退 `out_time_us` 时进度条不许倒走；探不到时长
  就用 `percent=None` 的不确定进度态，不凭空造百分比。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .paths import OUTPUT_DIR
from .procutil import CommandCancelled, CommandTimeout, run_command, tail, terminate_process

log = logging.getLogger(__name__)

PROXIES_DIR = OUTPUT_DIR / "web_proxies"
MIN_PROXY_BYTES = 50 * 1024
PROGRESS_INTERVAL_S = 0.3

ProgressCb = "callable"


@dataclass(slots=True)
class ProxyResult:
    path: Path
    reused: bool = False
    fallback: bool = False
    duration: float = 0.0
    elapsed: float = 0.0
    size: int = 0

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "name": self.path.name,
            "reused": self.reused,
            "fallback": self.fallback,
            "duration": self.duration,
            "elapsed": self.elapsed,
            "size": self.size,
        }


def proxies_dir(output_dir: Path | None = None) -> Path:
    base = Path(output_dir) if output_dir else OUTPUT_DIR
    return base / "web_proxies"


def proxy_paths(media_path: Path, output_dir: Path | None = None) -> tuple[Path, Path]:
    """返回 `(正式代理, 半成品)`。文件名带片源体积，片源被替换后旧代理自动失效。"""
    media_path = Path(media_path)
    size = media_path.stat().st_size if media_path.exists() else 0
    folder = proxies_dir(output_dir)
    stem = f"{media_path.stem}_{size}_preview"
    return folder / f"{stem}.mp4", folder / f"{stem}.part.mp4"


def drop_broken_proxy(path: Path) -> None:
    """压制失败时删掉半成品，否则下一次点击会把它当成「历史代理」秒级复用。"""
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def get_existing_proxy(media_path: Path, output_dir: Path | None = None) -> Path | None:
    """检查是否已经存在压制好的轻量监看代理成片。"""
    media_path = Path(media_path)
    folder = proxies_dir(output_dir)
    standard, _ = proxy_paths(media_path, output_dir)

    if standard.exists() and standard.stat().st_size > MIN_PROXY_BYTES:
        return standard

    # 历史命名（旧版本没有体积字段）不能无条件复用：同名片源被替换后，
    # 旧代理的画面和当前字幕会错位。只接受文件名中体积与当前片源一致的后缀。
    file_size = media_path.stat().st_size if media_path.exists() else 0
    legacy: list[Path] = []
    for cand in folder.glob("*_preview.mp4"):
        if not cand.name.startswith(f"{media_path.stem}_"):
            continue
        match = re.search(r"_(\d+)_preview\.mp4$", cand.name)
        if match is None or int(match.group(1)) != file_size:
            continue
        try:
            if cand.stat().st_size > MIN_PROXY_BYTES:
                legacy.append(cand)
        except OSError:
            continue
    legacy.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return legacy[0] if legacy else None


def install_existing_proxy(
    media_path: Path,
    source_path: Path,
    output_dir: Path | None = None,
) -> Path:
    """把用户已有的代理文件挂到当前片源的代理路径上，避免再压一遍。

    优先硬链接（同盘、零拷贝），跨盘时用符号链接；两者都不可用时才退回复制。
    正式文件由临时名原子 rename，半成品不会被 ``get_existing_proxy()`` 当成成片。
    目标路径已存在且大小正常时直接复用，不覆盖用户已有的代理。
    """
    media_path = Path(media_path)
    source = Path(source_path).expanduser()
    try:
        source = source.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"代理文件不存在：{source_path}") from exc
    if not source.is_file():
        raise ValueError(f"不是普通文件：{source}")

    standard, _ = proxy_paths(media_path, output_dir)
    if standard.exists() and standard.stat().st_size > MIN_PROXY_BYTES:
        return standard
    if source == standard:
        if standard.exists() and standard.stat().st_size > 1024:
            return standard
        raise ValueError("代理文件为空或过小，无法作为监看画面")

    standard.parent.mkdir(parents=True, exist_ok=True)
    temp = standard.with_name(f"{standard.stem}.importing{standard.suffix}")
    drop_broken_proxy(temp)
    try:
        try:
            os.link(source, temp)
        except OSError:
            try:
                os.symlink(source, temp)
            except OSError:
                shutil.copyfile(source, temp)
        os.replace(temp, standard)
    finally:
        drop_broken_proxy(temp)

    if standard.stat().st_size <= 1024:
        drop_broken_proxy(standard)
        raise ValueError("代理文件为空或过小，无法作为监看画面")
    return standard


def build_streaming_cmd(media_path: Path, dest: Path) -> tuple[list[str], str, str]:
    """实时压制命令：返回 `(命令, 阶段文案, 备注)`。macOS 优先 VideoToolbox。"""
    if sys.platform == "darwin":
        return (
            [
                "ffmpeg", "-y", "-nostdin",
                "-hwaccel", "videotoolbox",
                "-i", str(media_path),
                "-vf", "scale=-2:480,format=yuv420p",
                "-c:v", "h264_videotoolbox",
                "-b:v", "2200k",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                "-progress", "pipe:1",
                str(dest),
            ],
            "正在启动 VideoToolbox 硬件压制…",
            "VideoToolbox 硬件加速中",
        )
    return (
        [
            "ffmpeg", "-y", "-nostdin", "-threads", "0",
            "-i", str(media_path),
            "-vf", "scale=-2:480,format=yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            str(dest),
        ],
        "正在启动 libx264 CPU 压制…",
        "libx264 CPU 编码中",
    )


def create_proxy(media_path: Path, dest: Path | None = None, cancel_event=None) -> Path | None:
    """非实时回退压制（三条命令依次尝试）。失败会删除半成品。"""
    media_path = Path(media_path)
    if dest is None:
        dest, _ = proxy_paths(media_path)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    base = ["ffmpeg", "-y", "-nostdin", "-threads", "0", "-i", str(media_path)]
    video_filter = "scale=-2:480,format=yuv420p"
    audio_args = ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]
    attempts: list[tuple[str, list[str], float]] = []

    if sys.platform == "darwin":
        attempts.append((
            "VideoToolbox 全硬件",
            ["ffmpeg", "-y", "-nostdin", "-hwaccel", "videotoolbox", "-i", str(media_path),
             "-vf", video_filter, "-c:v", "h264_videotoolbox", "-b:v", "2200k",
             *audio_args, str(dest)],
            1200.0,
        ))
        attempts.append((
            "软解 + VideoToolbox 编码",
            [*base, "-vf", video_filter, "-c:v", "h264_videotoolbox", "-b:v", "2200k",
             *audio_args, str(dest)],
            1200.0,
        ))

    attempts.append((
        "libx264 CPU",
        [*base, "-vf", "scale=-2:480", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-preset", "ultrafast", "-crf", "28", *audio_args, str(dest)],
        1800.0,
    ))

    for label, cmd, timeout in attempts:
        log.info("代理压制方案 | %s | dest=%s", label, dest.name)
        try:
            result = run_command(cmd, timeout=timeout, cancel_event=cancel_event)
        except CommandCancelled:
            drop_broken_proxy(dest)
            raise
        except CommandTimeout as exc:
            log.warning("代理压制超时 | %s | %s", label, tail(exc.stderr, 800))
            drop_broken_proxy(dest)
            continue
        except Exception as exc:
            log.warning("代理压制启动失败 | %s | %s", label, exc)
            drop_broken_proxy(dest)
            continue

        if result.returncode == 0 and dest.exists() and dest.stat().st_size > 1024:
            log.info("代理压制成功 | %s | %s", label, dest.name)
            return dest
        log.warning(
            "代理压制失败 | %s | rc=%s | %s", label, result.returncode, tail(result.stderr, 800)
        )
        drop_broken_proxy(dest)

    return None


def probe_duration(media_path: Path) -> float:
    """探不到时长就返回 0（前端据此走不确定进度，不要瞎猜）。"""
    try:
        proc = run_command(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(media_path)],
            timeout=20,
        )
        return max(0.0, float(proc.stdout.strip()))
    except Exception:
        return 0.0


def run_proxy_job(
    media_path: Path,
    *,
    on_progress=None,
    cancel_event=None,
    output_dir: Path | None = None,
) -> ProxyResult:
    """压制 480p 监看代理。阻塞调用；进度通过 `on_progress(event)` 抛出。

    `event` 形如::

        {"percent": 42, "out_s": 123.4, "duration": 293.0,
         "speed": "3.2x", "stage": "正在压制 480p 流畅监看代理…", "note": "…"}

    `percent` 可能是 `None`：时长未知或回退压制时走「不确定进度」。
    """
    media_path = Path(media_path)
    started = time.perf_counter()

    existing = get_existing_proxy(media_path, output_dir)
    if existing is not None:
        return ProxyResult(
            path=existing,
            reused=True,
            duration=probe_duration(media_path),
            elapsed=time.perf_counter() - started,
            size=existing.stat().st_size,
        )

    standard, partial = proxy_paths(media_path, output_dir)
    partial.parent.mkdir(parents=True, exist_ok=True)
    drop_broken_proxy(partial)

    duration = probe_duration(media_path)
    cmd, stage_text, note = build_streaming_cmd(media_path, partial)

    def emit(percent, out_s, speed, stage=None, note_text=None):
        if on_progress is None:
            return
        on_progress(
            {
                "percent": percent,
                "out_s": round(out_s, 2),
                "duration": round(duration, 2),
                "speed": speed,
                "stage": stage or "正在压制 480p 流畅监看代理…",
                "note": note_text or note,
            }
        )

    emit(None, 0.0, "1.0x", stage_text, "初始化编码器")

    proc = None
    ok = False
    max_out_s = 0.0
    speed = "1.0x"
    err_tail = ""
    err_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=err_file, text=True, bufsize=1
        )
        last_emit = time.time()
        last_pct: int | None = -1
        cancelled = False

        while True:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                terminate_process(proc)
                break

            line = proc.stdout.readline() if proc.stdout else ""
            if not line and proc.poll() is not None:
                break
            line_str = line.strip()
            if "=" in line_str:
                key, value = line_str.split("=", 1)
                key, value = key.strip(), value.strip()
                if key == "out_time_us":
                    try:
                        # 只认单调值：ffmpeg 偶发回退/重置时进度条绝不倒走
                        max_out_s = max(max_out_s, float(value) / 1_000_000.0)
                    except ValueError:
                        pass
                elif key == "speed" and value.endswith("x"):
                    speed = value

            now = time.time()
            if now - last_emit < PROGRESS_INTERVAL_S:
                continue
            percent = (
                int(min(99.0, max(0.0, (max_out_s / duration) * 100)))
                if duration > 0
                else None
            )
            # 百分比没变就不刷新（只偶尔补一次速度），避免无意义重绘造成闪烁
            if percent == last_pct and now - last_emit < 1.5:
                continue
            last_pct = percent
            last_emit = now
            emit(percent, max_out_s, speed)

        if cancelled:
            raise CommandCancelled("代理压制已取消")

        proc.wait(timeout=10)
        ok = proc.returncode == 0
    except CommandCancelled:
        raise
    except Exception:
        log.exception("代理实时压制异常 | media=%s", media_path.name)
    finally:
        if proc is not None and proc.poll() is None:
            log.warning("终止代理 ffmpeg | pid=%s", proc.pid)
            terminate_process(proc)
        try:
            err_file.seek(0)
            err_tail = tail(err_file.read(), 1500)
        except Exception:
            err_tail = ""
        try:
            err_file.close()
        except Exception:
            pass

    if ok:
        try:
            if partial.exists() and partial.stat().st_size > MIN_PROXY_BYTES:
                os.replace(partial, standard)
            else:
                ok = False
        except OSError:
            log.exception("代理成片 rename 失败 | %s", partial.name)
            ok = False

    if ok:
        emit(100 if duration > 0 else None, duration or max_out_s, speed,
             "压制完成，正在载入监看画面…", "收尾：生成波形峰值")
        log.info("代理压制完成 | %s", standard.name)
        return ProxyResult(
            path=standard,
            duration=duration,
            elapsed=time.perf_counter() - started,
            size=standard.stat().st_size,
        )

    drop_broken_proxy(partial)
    log.warning("标准代理压制失败 | stderr=%s", err_tail)
    emit(None, 0.0, "回退模式", "标准压制失败，正在切换回退压制…", "软解编码（不确定进度）")

    try:
        fallback = create_proxy(media_path, dest=partial, cancel_event=cancel_event)
    except CommandCancelled:
        raise

    if fallback and fallback.exists() and fallback.stat().st_size > MIN_PROXY_BYTES:
        try:
            os.replace(partial, standard)
        except OSError:
            log.exception("回退代理 rename 失败 | %s", partial.name)
            drop_broken_proxy(partial)
            raise RuntimeError("代理压制未能成功（回退方案 rename 失败）")
        log.info("代理回退压制完成 | %s", standard.name)
        return ProxyResult(
            path=standard,
            fallback=True,
            duration=duration,
            elapsed=time.perf_counter() - started,
            size=standard.stat().st_size,
        )

    drop_broken_proxy(partial)
    raise RuntimeError("代理压制未能成功")
