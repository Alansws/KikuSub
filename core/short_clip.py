"""核对台短选区的「轻声兜底」——只服务人工框选 / 单句重转。

## 为什么需要它

整片转写里 VAD 没有切出语音段时返回空结果**是对的**：静音、雨声、纯音乐会被
Whisper 幻觉成「すぅう…」。但人工框选是另一个语义——用户听着某处有人在说话，
框出 1–5 秒点「转写选区」，句首是气声、音量低，Silero 在默认阈值 0.30 下切不出
一段语音，于是落到「未检测到有效语音」。用户听到的和界面报的正好相反。

所以这里只给**核对台的人工短选区**加一条降级链，且不改任何全局默认值：

1. 仍按当前参数（含用户自己调过的 VAD）正常跑一次；
2. 结果为空且选区 ≤ 20s：把阈值降到 :data:`LOW_VAD_THRESHOLD`（0.05）**静默**重试一次；
3. 仍为空且选区 ≤ 12s：跳过 VAD 切分，整段音频（保留 dynaudnorm）直接送引擎识别一次；
4. 再没有文字才让上层报「未检测到有效语音」。

整片转写、区间追加（`apply=append`）、质检门控都不走这里：`pipeline` 只在
`TranscribeRequest.short_clip_fallback` 为真时调用，而服务层只对核对台的
`replace_range`（转写选区 / 重转此句 / 质检补录）置真。VAD 的默认值
（0.30 / 0.25）与 `tools/eval/` 的评测基线因此完全不受影响。

## 为什么整段送模是安全的

只在「人工明确指定、≤12 秒、且前两次都切不出语音」时才发生。这个长度下模型
没有时间编出一整段幻觉对白，`_retry_gain`/非台词边缘剔除仍然生效；而且结果只
替换这一个区间，用户立刻能看到并撤销。
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable

from .procutil import CommandCancelled
from .subtitles import SubtitleCue

# 极低阈值：Silero 在 0.05 上几乎只过滤纯数字静音，轻声/气声也能切出来。
LOW_VAD_THRESHOLD = 0.05
# 只在「短句」范围做极低阈值重试；再长就该走正常参数，免得整段变成一条。
LOW_THRESHOLD_MAX_S = 20.0
# 连 VAD 切分都跳过、整段送模的上限。超过这个长度，幻觉风险大于收益。
WHOLE_CLIP_MAX_S = 12.0

STEP_LOW_THRESHOLD = "low_threshold"
STEP_WHOLE_CLIP = "whole_clip"


def selection_seconds(
    start_s: float | None,
    end_s: float | None,
    media_duration_s: float = 0.0,
) -> float:
    """选区时长（秒）。只填一端时用片长补另一端；全空 = 0（整片）。"""
    if end_s is None and start_s is None:
        return 0.0
    start = max(0.0, float(start_s or 0.0))
    if end_s is None:
        return max(0.0, float(media_duration_s or 0.0) - start)
    return max(0.0, float(end_s) - start)


def plan_fallbacks(duration: float) -> list[str]:
    """按顺序给出该尝试的降级步骤；空列表 = 不做任何兜底。纯函数。"""
    length = float(duration or 0.0)
    if length <= 0:
        return []
    steps: list[str] = []
    if length <= LOW_THRESHOLD_MAX_S:
        steps.append(STEP_LOW_THRESHOLD)
    if length <= WHOLE_CLIP_MAX_S:
        steps.append(STEP_WHOLE_CLIP)
    return steps


def lower_threshold(config: Any, family: str) -> Any | None:
    """复制一份只把 VAD 阈值降到 0.05 的配置。

    字段名在三个引擎族里不一致（whisper 用 ``threshold``，qwen / sherpa 用
    ``vad_threshold``），这是它们各自的真实 schema，不在这里另造映射。
    配置不是 dataclass / 没有该字段时返回 None（调用方跳过这一步）。
    """
    field = "threshold" if family == "whisper" else "vad_threshold"
    if config is None or not dataclasses.is_dataclass(config):
        return None
    if not hasattr(config, field):
        return None
    current = float(getattr(config, field) or 0.0)
    # 用户已经调得比兜底阈值还低：重试没有意义，别白跑一次模型。
    if current <= LOW_VAD_THRESHOLD:
        return None
    return dataclasses.replace(config, **{field: LOW_VAD_THRESHOLD})


def whole_clip_cue(text: str, start_s: float | None, end_s: float | None) -> SubtitleCue:
    """整段识别结果 → 恰好一条覆盖整个选区的字幕。"""
    start = max(0.0, float(start_s or 0.0))
    end = max(start, float(end_s if end_s is not None else start))
    return SubtitleCue(start=round(start, 3), end=round(end, 3), text=(text or "").strip())


def read_whole_clip(
    engine: Any,
    family: str,
    config: Any,
    *,
    media_path: str | Any,
    start_time_s: float | None,
    end_time_s: float | None,
    cancel_event: Any = None,
    **window_kwargs: Any,
) -> str:
    """跳过 VAD，把整段选区（保留 dynaudnorm）送引擎识别一次，返回文本。

    与整片转写共用 ``load_audio_for_transcription``（同一个 16k + 响度归一化缓存），
    所以这里拿到的是用户调过「动态响度归一化」之后真正会送模的那份音频。
    ``engine.transcribe_window`` 是「另一引擎复核」用的同一条无 VAD 入口。
    """
    from .transcribe import load_audio_for_transcription  # 延迟导入：模块顶层不拉 torch

    enable_loudnorm = bool(getattr(config, "enable_loudnorm", True))
    audio = load_audio_for_transcription(
        media_path,
        enable_loudnorm=enable_loudnorm,
        start_time_s=start_time_s,
        end_time_s=end_time_s,
        tmp_prefix="kikusub-short-clip-",
        cancel_event=cancel_event,
    )
    if audio.size == 0:
        return ""
    window = getattr(engine, "transcribe_window", None)
    if not callable(window):
        return ""
    text = window(audio, config=config, **window_kwargs)
    return str(text or "").strip()


def run_fallbacks(
    *,
    engine: Any,
    family: str,
    config: Any,
    media_path: str | Any,
    start_s: float | None,
    end_s: float | None,
    duration: float,
    retry: Callable[[Any], list[SubtitleCue]],
    cancelled: Callable[[], bool] = lambda: False,
    cancel_event: Any = None,
    decode_start: float | None = None,
    decode_end: float | None = None,
    window_kwargs: dict | None = None,
) -> list[SubtitleCue]:
    """执行降级链；返回第一条非空结果（都没有就是空列表）。

    ``retry(config)`` 由调用方提供：它必须用传入的配置重跑一次**同一个引擎**
    （参数里的阈值只在这一步被改写）。取消在任何一步之间都立刻生效。

    ``decode_start`` / ``decode_end`` 是**解码**区间（人声分离时为 None：传入的
    wav 本身就已经是选区），``start_s`` / ``end_s`` 是**字幕**时间。两者分开，
    是因为分离后的音频没有原片时间轴，混用会把整条人声轨当成选区送模。
    """
    if cancelled():
        return []
    for step in plan_fallbacks(duration):
        if step == STEP_LOW_THRESHOLD:
            lowered = lower_threshold(config, family)
            if lowered is None:
                continue
            cues = retry(lowered)
            if cues:
                return cues
        elif step == STEP_WHOLE_CLIP:
            try:
                text = read_whole_clip(
                    engine,
                    family,
                    config,
                    media_path=media_path,
                    start_time_s=decode_start,
                    end_time_s=decode_end,
                    cancel_event=cancel_event,
                    **(window_kwargs or {}),
                )
            except CommandCancelled:
                # 用户在整段送模前按了取消：当作「没有结果」，让上层走取消分支，
                # 不要把取消报成导出/转写失败。
                return []
            if text:
                return [whole_clip_cue(text, start_s, end_s)]
        if cancelled():
            return []
    return []
