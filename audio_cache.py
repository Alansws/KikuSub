"""16kHz 单声道 wav 解码缓存：同一文件全链路只解码一次。

转写（可选响度归一化档位）与核对台波形共用这里产出的 wav，避免同一次使用里
ffmpeg 反复全片解码。缓存键由「绝对路径 + 体积 + mtime_ns + 响度档位 + 起止时间」
共同决定，任一变化即视为不同文件重新解码。

开关：环境变量 KIKUSUB_AUDIO_CACHE=0 完全退回「每次现解码」的旧行为。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import Callable

import numpy as np

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "outputs" / ".cache" / "audio"

SAMPLE_RATE = 16000
ENV_FLAG = "KIKUSUB_AUDIO_CACHE"
DEFAULT_MAX_BYTES = 4 << 30  # 4GB ≈ 35 小时 16k mono s16
PRUNE_GRACE_S = 600.0

Extractor = Callable[..., None]


def enabled() -> bool:
    raw = os.environ.get(ENV_FLAG, "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _fmt_bound(value: float | None) -> str:
    return "" if value is None else f"{float(value):.3f}"


def cache_key(
    media: str | Path,
    *,
    loudnorm: bool,
    start: float | None = None,
    end: float | None = None,
) -> str:
    path = Path(media).expanduser().resolve()
    try:
        stat = path.stat()
        size, mtime_ns = stat.st_size, stat.st_mtime_ns
    except OSError:
        size, mtime_ns = 0, 0
    raw = f"{path.as_posix()}|{size}|{mtime_ns}|{int(bool(loudnorm))}|{_fmt_bound(start)}|{_fmt_bound(end)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def wav_path(
    media: str | Path,
    *,
    loudnorm: bool,
    start: float | None = None,
    end: float | None = None,
) -> Path:
    key = cache_key(media, loudnorm=loudnorm, start=start, end=end)
    return CACHE_DIR / f"{key}.wav"


def _default_extractor() -> Extractor:
    from transcribe import decode_wav_16k

    return decode_wav_16k


def ensure_wav(
    media: str | Path,
    *,
    loudnorm: bool,
    start: float | None = None,
    end: float | None = None,
    extractor: Extractor | None = None,
) -> Path:
    """返回可用的 16k mono wav 路径；未命中时解码并原子落盘。"""
    target = wav_path(media, loudnorm=loudnorm, start=start, end=end)
    if target.exists() and target.stat().st_size > 44:
        return target

    media_path = Path(media).expanduser()
    if not media_path.exists():
        raise FileNotFoundError(f"媒体文件不存在: {media_path}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # 必须保留 .wav 扩展名，否则 ffmpeg 无法推断输出容器格式
    partial = target.with_name(f"{target.stem}.{os.getpid()}.part.wav")
    decode = extractor or _default_extractor()
    try:
        decode(
            media_path,
            partial,
            enable_loudnorm=loudnorm,
            start_time_s=start,
            end_time_s=end,
        )
        if not partial.exists() or partial.stat().st_size <= 44:
            raise RuntimeError(f"解码产出为空: {partial.name}")
        try:
            os.replace(partial, target)
        except OSError:
            # 少数受限文件系统禁止 rename，退回「复制 + 清理」保证缓存可用
            shutil.copyfile(partial, target)
            try:
                partial.unlink()
            except OSError:
                pass
    finally:
        if partial.exists():
            try:
                partial.unlink()
            except OSError:
                pass

    try:
        prune()
    except Exception:
        pass
    return target


def peaks(wav_path: Path, bins: int) -> tuple[float, list[float]]:
    """从 16k wav 计算归一化波形包络：按 bins 等分，每段取 max|abs| 后除以全局峰值。

    与旧的 1kHz 直读实现同构，只是换成缓存里的 16k 原始样本，因此更锐利且结果稳定。
    """
    import soundfile as sf

    info = sf.info(str(wav_path))
    sr = int(info.samplerate) or SAMPLE_RATE
    frames = int(info.frames)
    duration = frames / sr if sr else 0.0
    if frames <= 0:
        return duration, []

    if bins is None or bins <= 0:
        bins = int(duration * 4) if duration > 0 else 3200
        bins = max(2400, min(8000, bins))
    bins = max(1, min(int(bins), frames))

    data, _ = sf.read(str(wav_path), dtype="float32", always_2d=True)
    if data.size == 0:
        return duration, []
    mono = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]

    edges = np.linspace(0, mono.size, bins + 1, dtype=int)
    values = [
        float(np.abs(mono[edges[i] : edges[i + 1]]).max()) if edges[i] < edges[i + 1] else 0.0
        for i in range(bins)
    ]
    maximum = max(values, default=0.0)
    norm = [round(min(1.0, v / maximum), 2) if maximum else 0.0 for v in values]
    return duration, norm


def prune(max_bytes: int = DEFAULT_MAX_BYTES) -> None:
    """按 mtime 淘汰旧 wav；最近 PRUNE_GRACE_S 内被访问/修改的文件一律跳过。"""
    if not CACHE_DIR.exists():
        return

    now = time.time()
    entries: list[tuple[float, int, Path]] = []
    total = 0
    for path in CACHE_DIR.glob("*.wav*"):
        try:
            stat = path.stat()
        except OSError:
            continue
        total += stat.st_size
        entries.append((stat.st_mtime, stat.st_size, path))

    if total <= max_bytes:
        return

    entries.sort(key=lambda item: item[0])
    for mtime, size, path in entries:
        if total <= max_bytes:
            break
        try:
            last_seen = max(mtime, path.stat().st_atime)
        except OSError:
            continue
        if now - last_seen < PRUNE_GRACE_S:
            continue
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
