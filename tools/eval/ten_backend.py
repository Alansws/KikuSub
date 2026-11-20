#!/usr/bin/env python3
"""TEN-VAD 对照实现（只给评测台用，不进产品内核）。

P1 结论：TEN-VAD 在负样本（BGM / 环境音）上把 85–98% 的窗口判成语音，整片 CER
从 10.7% 升到 61%、插入从 64 升到 505。它不是「更灵敏的 VAD」，而是「把人声之外
也当人声」，所以适配代码留在 `tools/eval/`，`core/vad.py` 只保留 Silero / WhisperSeg。

依赖只在真正调用时导入；`ten-vad` 不在 requirements.txt，也不随 sidecar 打包。
"""

from __future__ import annotations

import importlib

import numpy as np

SAMPLE_RATE = 16000
TEN_HOP = 256  # 16ms @16k


def _flag_runs_to_stamps(
    flags: np.ndarray,
    *,
    frame_samples: int,
    total_samples: int,
    min_speech_ms: int,
    min_silence_ms: int,
    speech_pad_ms: int,
) -> list[dict]:
    """把逐帧 0/1 判决转成统一 stamps。

    TEN 的 C 层已经做迟滞，输出 flag 就是最终判决；这里只做最短语音、最短静音与留白。
    """
    flags = np.asarray(flags, dtype=bool).reshape(-1)
    if flags.size == 0:
        return []
    frame_ms = frame_samples * 1000.0 / SAMPLE_RATE
    min_speech_frames = max(1, int(round(min_speech_ms / frame_ms)))
    min_silence_frames = max(1, int(round(min_silence_ms / frame_ms)))

    runs: list[list[int]] = []
    start = None
    for i, on in enumerate(flags):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append([start, i])
            start = None
    if start is not None:
        runs.append([start, len(flags)])

    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] < min_silence_frames:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    merged = [r for r in merged if r[1] - r[0] >= min_speech_frames]

    pad = max(0, int(round(speech_pad_ms / frame_ms)))
    starts = [max(0, s - pad) for s, _ in merged]
    ends = [min(len(flags), e + pad) for _, e in merged]
    for i in range(1, len(starts)):
        starts[i] = max(starts[i], ends[i - 1])
    for i in range(len(ends) - 1):
        ends[i] = min(ends[i], starts[i + 1])

    out: list[dict] = []
    for s, e in zip(starts, ends):
        a = max(0, min(total_samples, s * frame_samples))
        b = max(0, min(total_samples, e * frame_samples))
        if b > a:
            out.append({"start": int(a), "end": int(b)})
    return out


def detect(
    audio: np.ndarray,
    *,
    threshold: float = 0.5,
    min_speech_ms: int = 80,
    min_silence_ms: int = 200,
    speech_pad_ms: int = 250,
) -> list[dict]:
    """TEN-VAD 推理；缺依赖时抛 RuntimeError（评测脚本会把它记进表格）。"""
    try:
        TenVad = importlib.import_module("ten_vad").TenVad
    except Exception as exc:  # pragma: no cover - 依赖缺失
        raise RuntimeError(
            "TEN-VAD 不可用：需要 ten-vad（uv pip install ten-vad）"
        ) from exc

    audio = np.asarray(audio, dtype=np.float32)
    if audio.size == 0:
        return []
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    n = (len(pcm) // TEN_HOP) * TEN_HOP
    if n <= 0:
        return []
    vad = TenVad(hop_size=TEN_HOP, threshold=float(threshold))
    flags = np.empty(n // TEN_HOP, dtype=bool)
    for idx, i in enumerate(range(0, n, TEN_HOP)):
        _prob, flag = vad.process(pcm[i : i + TEN_HOP])
        flags[idx] = bool(flag)
    return _flag_runs_to_stamps(
        flags,
        frame_samples=TEN_HOP,
        total_samples=len(audio),
        min_speech_ms=min_speech_ms,
        min_silence_ms=min_silence_ms,
        speech_pad_ms=speech_pad_ms,
    )
