"""第二引擎复核（P1-1）：把字幕条的时间窗直接送另一个引擎，1:1 拿回文本。

为什么是**逐条窗口**而不是「按区间重跑」：区间重跑会重新跑 VAD 与断句，第二引擎切出来的
条数和原条对不上，映射回原条只能靠时间重叠猜，而「猜错一条」就等于给用户看一句别人的话。
逐条窗口没有这个问题——一条进、一条出，结果直接挂在原条上。

窗口与边界：

```text
lo = clamp(start - pad, 0, prev_end)   # 左不越过上一条的终点
hi = clamp(end + pad, next_start, …)   # 右不越过下一条的起点
```

±0.25s 是路线文档 P0-1 的 probe 用的扩窗量：太窄句首会被切，太宽会吃进邻句。
夹住之后若 `lo >= hi`（字幕首尾相接、邻句贴死），退回原条区间——宁可少听 0.25s，
也不要把上一句的尾音塞给第二引擎（它会复读上一句，看起来像"另一引擎更差"）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .procutil import CommandCancelled

# 与路线文档 P0-1 的 probe 一致；改这里等于改「另一引擎听到多宽」，属于产品口径。
SECOND_OPINION_PAD_S = 0.25
# 一次最多复核多少条：40 条是一屏能扫完的量，也是「一次模型加载」摊得动的上限。
MAX_WINDOWS = 40


def clamp_window(
    start: float,
    end: float,
    *,
    prev_end: float | None = None,
    next_start: float | None = None,
    pad: float = SECOND_OPINION_PAD_S,
) -> tuple[float, float]:
    """算一条字幕的复核窗口（秒），受相邻字幕约束。纯函数。"""
    start = float(start)
    end = float(max(start, end))
    pad = max(0.0, float(pad))
    lo = max(0.0, start - pad)
    if prev_end is not None:
        # 邻句重叠（脏数据）时不要把窗口起点推到本条之后。
        lo = max(lo, min(float(prev_end), start))
    hi = end + pad
    if next_start is not None:
        hi = min(hi, max(float(next_start), end))
    if hi <= lo:
        return start, end
    return lo, hi


def transcribe_windows(
    engine,
    windows: list[dict],
    *,
    audio: np.ndarray | None = None,
    media_path: str | Path | None = None,
    config=None,
    progress_cb=None,
    cancel_event=None,
) -> list[dict]:
    """把每条的窗口送 `engine.transcribe_window()`，返回与入参一一对应的结果。

    `windows` 每项至少含 `start`/`end`（秒）；`audio` 可直接给（测试用），否则按
    `media_path` 解码一次（响度归一化跟随引擎配置），所有窗口共用这一次解码。

    取消只能落在窗口之间：单条窗口只有一两秒音频，不值得再切一刀。
    """
    if not windows:
        return []
    if len(windows) > MAX_WINDOWS:
        raise ValueError(f"一次最多复核 {MAX_WINDOWS} 条（收到 {len(windows)} 条）")
    if audio is None:
        if media_path is None:
            raise ValueError("transcribe_windows 需要 audio 或 media_path 之一")
        # 延迟导入：本模块的窗口计算是纯函数，测试不该为了它拉起 torch。
        from .transcribe import load_audio_for_transcription

        loudnorm = bool(getattr(config, "enable_loudnorm", True))
        audio = load_audio_for_transcription(Path(media_path), enable_loudnorm=loudnorm)

    from .transcribe import SAMPLE_RATE

    total = len(windows)
    results: list[dict] = []
    for index, window in enumerate(windows):
        if cancel_event is not None and cancel_event.is_set():
            raise CommandCancelled("复核已取消")
        start = float(window["start"])
        end = float(window["end"])
        lo = max(0, int(round(start * SAMPLE_RATE)))
        hi = min(audio.size, int(round(end * SAMPLE_RATE)))
        chunk = np.ascontiguousarray(audio[lo:hi], dtype=np.float32)
        if chunk.size == 0:
            text = ""
        else:
            text = engine.transcribe_window(chunk, config=config)
        results.append(
            {
                "index": int(window.get("index", index)),
                "start": round(start, 3),
                "end": round(end, 3),
                "text": (text or "").strip(),
            }
        )
        if progress_cb is not None:
            progress_cb(index + 1, total)
    return results
