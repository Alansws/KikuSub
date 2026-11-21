"""TTS 响度统一：让不同引擎、不同参考音频的输出听起来一样响。

为什么需要这一层（2026-11 用户报障）：

- OmniVoice 是**零样本克隆**，输出幅度会跟着参考音频走。从影视里切出来的参考
  音频本身常常很轻（实测 −27 ～ −40 LUFS），克隆出来的整句也跟着轻 10 ～ 20 dB；
- macOS ``say`` 的输出大约在 −24 ～ −26 LUFS，视频对白则是另一个量级。
  三者没有共同基准，用户预览视频和单独听朗读时就得反复调系统音量。

所以这里做两件事，都走 ffmpeg 的 EBU R128：

1. :func:`normalize_reference`：建音色时把参考音频对齐到 ``−20 LUFS``，
   让模型「听到」的输入保持同一水平（实测输出幅度与参考幅度高度相关）；
2. :func:`normalize_file`：合成出来的每一句再对齐到 ``−18 LUFS / −1.5 dBTP``。
   这是两遍 ``loudnorm``（先测后放），线性增益优先，不会给短句加压缩泵感。

失败策略：没有 ffmpeg、量不出响度（极短/全静音）都只记录日志并保持原文件，
绝不因为「统一音量」这个增强功能让朗读整体失败。
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from core.paths import ffmpeg_bin
from core.procutil import CommandTimeout, run_command, tail

log = logging.getLogger(__name__)

# 播放基准：−18 LUFS 介于影视对白（约 −24 LUFS）和网络视频混音（约 −14 LUFS）
# 之间，也比系统 say 的 −25 LUFS 更容易听清，同时不把峰值顶到 0 dB。
TARGET_LUFS = -18.0
TRUE_PEAK_DB = -1.5
# 参考音频比播放目标再留一点余量：模型输出通常比参考略轻 1–2 dB。
REFERENCE_LUFS = -20.0
REFERENCE_TRUE_PEAK_DB = -2.0

# 缓存键里带上这个标签：算法/目标一变，旧缓存必须自然失效，不能继续播旧音量。
CACHE_TAG = "lufs-v1:-18"

SAMPLE_RATE = 24000
# 低于这个响度基本等于静音（短于一帧的音频 loudnorm 会返回 -inf）。
SILENCE_LUFS = -70.0
FFMPEG_TIMEOUT_S = 60.0

_JSON_BLOCK_RE = re.compile(r'\{\s*"input_i"[\s\S]*?\}')


class LoudnessError(RuntimeError):
    """响度测量/归一化失败；调用方通常只记日志，不阻断合成。"""


def _loudnorm_params(
    target: float = TARGET_LUFS, true_peak: float = TRUE_PEAK_DB
) -> str:
    return f"loudnorm=I={target:g}:TP={true_peak:g}:LRA=11"


def _run(args: list[str], timeout: float = FFMPEG_TIMEOUT_S):
    try:
        return run_command(args, timeout=timeout)
    except FileNotFoundError as exc:
        raise LoudnessError("找不到 ffmpeg，无法统一朗读音量") from exc
    except CommandTimeout as exc:
        raise LoudnessError("测量朗读音量超时") from exc


def measure(path: Path | str, *, target: float = TARGET_LUFS) -> dict:
    """用 loudnorm 的测量档位量一遍，返回 input_i / input_tp / input_lra / thresh。

    量不出有效值（纯静音、极短音频）时返回 ``input_i = "-inf"``，由调用方决定
    走峰值兜底还是原样返回。
    """
    proc = _run(
        [
            ffmpeg_bin(),
            "-hide_banner",
            "-nostdin",
            "-i",
            str(path),
            "-af",
            f"{_loudnorm_params(target)}:print_format=json",
            "-f",
            "null",
            "-",
        ]
    )
    stderr = proc.stderr or ""
    blocks = _JSON_BLOCK_RE.findall(stderr)
    if not blocks:
        raise LoudnessError(tail(stderr) or "ffmpeg 没有返回响度数据")
    try:
        stats = json.loads(blocks[-1])
    except ValueError as exc:
        raise LoudnessError("无法解析 ffmpeg 的响度数据") from exc
    required = {"input_i", "input_tp", "input_lra", "input_thresh", "target_offset"}
    if not required.issubset(stats):
        raise LoudnessError("ffmpeg 返回的响度字段不完整")
    return stats


def _integrated_lufs(stats: dict) -> float | None:
    raw = str(stats.get("input_i") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    if value <= SILENCE_LUFS:
        return None
    return value


def measure_integrated(path: Path | str, *, target: float = TARGET_LUFS) -> float | None:
    """量一段音频的积分响度（LUFS）；静音/极短到量不出时返回 None。"""
    return _integrated_lufs(measure(path, target=target))


def _fallback_peak_normalize(
    path: Path, *, target_peak_db: float = TRUE_PEAK_DB
) -> bool:
    """极短音频（<0.4s，loudnorm 量不出 I）的兜底：按 RMS 抬到大约 −18 dBFS。

    只用于一句话里的半个词这种长度；不追求精确 LUFS，只保证不会轻到听不见。
    峰值同时压在目标以下，避免 PCM16 削波。
    """
    import numpy as np
    import soundfile as sf

    data, samplerate = sf.read(str(path), dtype="float32", always_2d=True)
    if data.size == 0 or samplerate <= 0:
        return False
    mono = data.mean(axis=1)
    rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(mono)))
    if rms <= 1e-6 or peak <= 0:
        return False
    target_rms = 10 ** (-18.0 / 20.0)
    gain = min(
        target_rms / rms,
        (10 ** (target_peak_db / 20.0)) / peak,
    )
    if gain <= 1.02:
        return False
    out = np.clip(mono * gain, -1.0, 1.0)
    sf.write(str(path), out, samplerate, subtype="PCM_16")
    return True


def normalize_file(
    path: Path | str,
    *,
    target: float = TARGET_LUFS,
    true_peak: float = TRUE_PEAK_DB,
    sample_rate: int = SAMPLE_RATE,
) -> dict:
    """把 WAV 原地对齐到目标响度，返回测量/结果信息。

    两遍 loudnorm：第一遍只测，第二遍用测得的 ``measured_*`` 做线性增益。
    峰值装不下时 loudnorm 自动退回动态模式，至少保证不削波。
    """
    source = Path(path)
    if not source.is_file():
        raise LoudnessError("音频文件不存在")

    stats = measure(source, target=target)
    before = _integrated_lufs(stats)
    if before is None:
        changed = _fallback_peak_normalize(source, target_peak_db=true_peak)
        return {
            "before_lufs": None,
            "after_lufs": None,
            "fallback": True,
            "changed": changed,
        }

    filter_spec = (
        f"{_loudnorm_params(target, true_peak)}"
        f":measured_I={stats['input_i']}"
        f":measured_LRA={stats['input_lra']}"
        f":measured_TP={stats['input_tp']}"
        f":measured_thresh={stats['input_thresh']}"
        f":offset={stats['target_offset']}"
        ":linear=true"
    )
    temp = source.with_name(f".{source.stem}.loudness{source.suffix}")
    try:
        proc = _run(
            [
                ffmpeg_bin(),
                "-hide_banner",
                "-nostdin",
                "-y",
                "-i",
                str(source),
                "-af",
                filter_spec,
                "-ar",
                str(sample_rate),
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(temp),
            ]
        )
        if proc.returncode != 0 or not temp.is_file() or temp.stat().st_size <= 44:
            raise LoudnessError(tail(proc.stderr or proc.stdout) or "ffmpeg 没有输出音频")
        os.replace(temp, source)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass

    try:
        after_stats = measure(source, target=target)
        after = _integrated_lufs(after_stats)
    except LoudnessError:
        after = None
    log.debug(
        "TTS 响度归一 | %s %.1f → %s LUFS (target %.1f)",
        source.name,
        before,
        f"{after:.1f}" if after is not None else "?",
        target,
    )
    return {
        "before_lufs": round(before, 2),
        "after_lufs": round(after, 2) if after is not None else None,
        "fallback": False,
        "changed": True,
    }


def normalize_reference(path: Path | str) -> dict:
    """建音色时的参考音频：对齐到 −20 LUFS，让克隆输出不再跟着素材忽大忽小。"""
    return normalize_file(
        path,
        target=REFERENCE_LUFS,
        true_peak=REFERENCE_TRUE_PEAK_DB,
    )
