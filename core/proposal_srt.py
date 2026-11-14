"""把模型回吐的 SRT 对齐成提案 items —— 手工粘贴通道的共用层。

`core.ai_translate.proposal_from_srt` 与 `core.ai_polish.proposal_from_srt` 原本是两份
近乎逐行相同的实现，差异只有三处：kind、`note` 文案、"漏翻/漏改"这个措辞。
解析、条数校验、按顺序对齐、时间戳漂移告警这些**必须只有一份实现**，否则改一处就分叉
（见 docs/contracts/engineering-practice.md「重复实现」）。

契约（两条通道共用，改之前先读）：
- 条数必须与当前字幕一致，否则整批拒绝（模型合并/漏翻都会在这里被抓住）；
- 只按**顺序**取文本，丢弃它给的序号与时间戳；时间轴永远来自 `cues`（D-1 不破）；
- 时间戳偏差 > 1s 的条数超过 0 时给一条 warning（多半是模型改写了时间轴）。
"""

from __future__ import annotations

from . import ai_client as client
from .subtitles import srt_to_cues

#: 时间戳偏差超过这个秒数就计入 warning（模型改写时间轴的典型征兆）。
DRIFT_TOLERANCE = 1.0


def align_model_srt(
    srt_text: str,
    cues,
    *,
    reject_hint: str = "漏翻",
    scope_label: str = "",
) -> tuple[list[tuple[str, str]], list[str]]:
    """把模型回吐的 SRT 对齐成 ``[(before, after)]``。

    ``reject_hint`` 只影响条数不一致时的错误文案（"漏翻" / "漏改"）。
    解析失败或条数不符一律抛 :class:`ai_client.AiError`，调用方不做兜底。
    """
    parsed = srt_to_cues(srt_text or "")
    if not parsed:
        raise client.AiError("没有从粘贴内容里解析到字幕：确认贴的是完整 SRT（含序号与时间戳）")
    if len(parsed) != len(cues):
        scope = f"{scope_label}，" if scope_label else ""
        raise client.AiError(
            f"{scope}条数对不上：解析到 {len(parsed)} 条，期望 {len(cues)} 条。"
            f"常见原因是模型合并/拆分了句子或{reject_hint}——请让它按原序号逐条输出"
        )

    pairs: list[tuple[str, str]] = []
    drift = 0
    for cue, got in zip(cues, parsed):
        if abs(got.start - cue.start) > DRIFT_TOLERANCE:
            drift += 1
        pairs.append((cue.text, got.text.strip()))

    warnings: list[str] = []
    if drift:
        warnings.append(f"{drift} 条的时间戳与原文对不上（已按顺序采用文本，时间轴仍用原文）")
    return pairs, warnings
