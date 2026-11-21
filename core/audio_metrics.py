"""片段电平指标：给 CLI 的 `cues` / `cue` 提供绝对响度证据。

为什么不用 `load_wav_mono()`：它在音频很轻时会做峰值归一化（把 -85 dBFS 的
底噪抬到 -5），看「这一段到底有没有人声」必须看**未归一化**的真实电平。这里
直接读 wav 采样算 RMS，不碰任何增益。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

try:  # soundfile 是运行期依赖；单元测试在轻量环境里可以只测 rms_dbfs
    import soundfile as sf
except Exception:  # pragma: no cover - 依赖缺失时由调用方处理
    sf = None  # type: ignore[assignment]


def rms_dbfs(samples) -> float | None:
    """一段采样的 RMS 电平（dBFS）；空的/非有限值返回 None。"""
    data = np.asarray(samples, dtype=np.float64)
    if data.size == 0:
        return None
    if data.ndim > 1:
        data = data.mean(axis=1)
    rms = float(np.sqrt(np.mean(data * data)))
    if not np.isfinite(rms):
        return None
    return round(20.0 * float(np.log10(max(rms, 1e-9))), 1)


def segment_dbfs(
    wav_path: str | Path,
    start: float,
    end: float,
    *,
    channel_mean: bool = True,
) -> float | None:
    """只读 wav 的一段采样算 RMS（不整份载入，长片也便宜）。

    ``channel_mean=True`` 时先把多声道平均成单声道——人声分离产物是 44.1k
    立体声，直接对两声道一起算 RMS 与取均值再算在能量接近时等价，但遇到
    单边相位差时更稳。
    """
    if sf is None:
        return None
    path = Path(wav_path)
    if not path.exists() or path.stat().st_size <= 44:
        return None
    try:
        with sf.SoundFile(str(path)) as handle:
            rate = int(handle.samplerate or 0)
            if rate <= 0:
                return None
            total = int(handle.frames)
            lo = max(0, int(round(float(start) * rate)))
            hi = min(total, int(round(float(end) * rate)))
            if hi <= lo:
                return None
            handle.seek(lo)
            chunk = handle.read(hi - lo, dtype="float32", always_2d=True)
    except (OSError, RuntimeError):
        return None
    if chunk.size == 0:
        return None
    return rms_dbfs(chunk.mean(axis=1) if channel_mean else chunk)


def wav_duration(wav_path: str | Path) -> float:
    """wav 时长（秒）；读不到返回 0。"""
    if sf is None:
        return 0.0
    try:
        info = sf.info(str(wav_path))
    except (OSError, RuntimeError):
        return 0.0
    if not info.samplerate:
        return 0.0
    return float(info.frames) / float(info.samplerate)
