"""断句重排：把外部模型返回的**一整份新 SRT** 收进核对台。

这是第三条车道（前两条是「润色提案」1:1 与「结构建议」ops）：
- 润色提案：条目数与时间轴都不许变，只换文本（``apply_polish()``）；
- 结构建议：只改模型点名的几处，逐项校验、逐项可拒（``ai_structure``）；
- 断句重排：模型自由重切，条数与时间码都可能变，整段换掉。

契约（改之前先读 ``docs/contracts/ai-proposal.md`` 的「断句重排」一节）：

- **只收标准 SRT**（序号 + ``-->`` 时间码 + 文本）。不收纯文本，也不做
  「按原稿重算时间轴」——时间码就是模型给的那些，本模块只做体检、不替模型改数。
- **应用锚点是原稿的条目索引区间** ``(from_index, to_index)``，不是模型吐出来的
  时间边界：分段时两段的交界由原稿的切法决定，模型的时间漂移不该误删邻段。
- **应用前必须校验 digest**：解析之后原稿被改过，旧索引已经不可信，宁可让用户
  重新粘一次，也不能按错位的下标把别的段覆盖掉。

体检阈值刻意宽松（``MAX_CHARS = 24`` / ``MAX_DURATION = 9``）：中文影视字幕
16–18 字很常见，卡 14 字会把正常稿子全标成问题；这里只抓真的会让人读不完或
对不上口型的情况。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Iterable

from . import ai_proposal as proposals
from .subtitles import SubtitleCue, srt_to_cues

#: 单条正文超过这个字数就提示（建议值在提示词里写 18 字，这里只抓明显超长）。
MAX_CHARS = 24
#: 单条时长超过这个秒数就提示。
MAX_DURATION = 9.0
#: 单条短于这个秒数就提示（一闪而过，来不及读）。
MIN_DURATION = 0.5
#: 相邻两条重叠超过这个秒数才算问题（舍入误差不算）。
OVERLAP_EPS = 0.05
#: 分段应用时，新块的时间允许超出本段边界多少秒（模型微调边界是正常的）。
RANGE_TOLERANCE = 1.0
#: 一次粘贴的条数上限：防止粘进来一整部合集把界面拖死。
MAX_CUES = 5000

#: 时间轴行：只用来判断「这份粘贴里到底有没有时间码」。
_TIME_LINE_RE = re.compile(
    r"\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}"
)
_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*$", re.MULTILINE)


class ReshapeError(ValueError):
    """粘贴内容不可用；调用方把 ``str(exc)`` 直接给用户看。"""


def digest_of(cues: Iterable[SubtitleCue]) -> str:
    """源指纹：与润色/结构建议同一套实现，只取文本。"""
    return proposals.source_digest([cue.text for cue in cues])


def _clean(text: str) -> str:
    """去掉模型爱加的 markdown 围栏与首尾空白。"""
    return _FENCE_RE.sub("", str(text or "")).strip()


def has_timecode(text: str) -> bool:
    return bool(_TIME_LINE_RE.search(text or ""))


def parse_draft(text: str) -> list[SubtitleCue]:
    """把粘贴内容解析成一份新字幕；不接受纯文本。

    「缺少时间码」与「有时间码但格式坏了」要给不同的提示：前者是用户贴错了
    东西（或模型没按 SRT 输出），后者是 SRT 本身被写坏了。
    """
    raw = _clean(text)
    if not raw:
        raise ReshapeError("先把模型返回的字幕粘进来")
    if not has_timecode(raw):
        raise ReshapeError(
            "缺少时间码：断句重排只收标准 SRT（序号 + 时间码 + 文本）。"
            "让模型重新输出带时间码的 SRT，或改用「只改几处」的 ops JSON"
        )
    cues = [cue for cue in srt_to_cues(raw) if str(cue.text or "").strip()]
    if not cues:
        raise ReshapeError("这份 SRT 里没有解析到字幕：检查是否漏了时间码行或正文行")
    for cue in cues:
        cue.text = str(cue.text).strip()
    validate_block(cues)
    return cues


def validate_block(block: list[SubtitleCue]) -> None:
    """应用前的结构校验。

    只拦「这不是一份能进核对台的字幕」（空、负数、结束早于开始、超过上限），
    不替用户改风格问题——重叠、偏长、越界都只在体检里标注，由人决定改不改。
    """
    if not block:
        raise ReshapeError("这份新稿没有任何条目")
    if len(block) > MAX_CUES:
        raise ReshapeError(f"一次最多收 {MAX_CUES} 条，这份有 {len(block)} 条；请先分片")
    for index, cue in enumerate(block, start=1):
        if not (math.isfinite(cue.start) and math.isfinite(cue.end)):
            raise ReshapeError(f"第 {index} 条的时间码不是有效数字")
        if cue.start < 0:
            raise ReshapeError(f"第 {index} 条的时间码是负数")
        if cue.end < cue.start:
            raise ReshapeError(f"第 {index} 条的结束时间早于开始时间")


# --------------------------------------------------------------------------- 体检


@dataclass
class Issue:
    """一条行内提示；``index`` 是新块里的 1-based 行号。"""

    index: int
    kind: str
    label: str

    def to_dict(self) -> dict:
        return {"index": self.index, "kind": self.kind, "label": self.label}


@dataclass
class Diagnostics:
    count: int = 0
    count_before: int = 0
    chars: int = 0
    span: tuple[float, float] = (0.0, 0.0)
    issues: list[Issue] = field(default_factory=list)
    totals: dict[str, int] = field(default_factory=dict)
    identical: bool = False

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "count_before": self.count_before,
            "chars": self.chars,
            "span": {"start": self.span[0], "end": self.span[1]},
            "issues": [issue.to_dict() for issue in self.issues],
            "totals": dict(self.totals),
            "identical": self.identical,
        }


def _tc(seconds: float) -> str:
    total = max(0.0, float(seconds or 0.0))
    minutes, rest = divmod(total, 60.0)
    hours, minutes = divmod(int(minutes), 60)
    prefix = f"{hours:02d}:" if hours else ""
    return f"{prefix}{minutes:02d}:{rest:05.2f}"


def diagnose(
    block: list[SubtitleCue],
    *,
    before_texts: list[str] | None = None,
    range_start: float | None = None,
    range_end: float | None = None,
) -> Diagnostics:
    """体检：只标问题，不改数据。

    ``range_start`` / ``range_end`` 是本段在原稿里的时间范围（整片时传 None）。
    """
    result = Diagnostics(
        count=len(block),
        count_before=len(before_texts or []),
        chars=sum(len(str(cue.text or "")) for cue in block),
        totals={
            "overlap": 0,
            "out_of_order": 0,
            "too_long": 0,
            "too_short": 0,
            "out_of_range": 0,
            "empty_text": 0,
        },
    )
    if block:
        result.span = (block[0].start, max(cue.end for cue in block))

    for index, cue in enumerate(block, start=1):
        text = str(cue.text or "")
        if not text.strip():
            result.totals["empty_text"] += 1
            result.issues.append(Issue(index, "empty_text", "正文是空的"))
        duration = cue.end - cue.start
        # 同一条的字数与时长问题合并成一条提示：计数是「条数」不是「问题数」，
        # 否则顶部会写「2 条偏长」而实际只有 1 条。
        reasons: list[str] = []
        if duration > MAX_DURATION:
            reasons.append(f"{duration:.1f}s")
        if len(text) > MAX_CHARS:
            reasons.append(f"{len(text)} 字")
        if reasons:
            result.totals["too_long"] += 1
            result.issues.append(Issue(index, "too_long", f"偏长（{'，'.join(reasons)}）"))
        elif duration < MIN_DURATION:
            result.totals["too_short"] += 1
            result.issues.append(Issue(index, "too_short", f"只有 {duration:.1f}s"))
        if range_start is not None and range_end is not None:
            if cue.start < range_start - RANGE_TOLERANCE or cue.end > range_end + RANGE_TOLERANCE:
                result.totals["out_of_range"] += 1
                result.issues.append(Issue(index, "out_of_range", "超出本段的时间范围"))
        if index > 1:
            prev = block[index - 2]
            if cue.start < prev.start - OVERLAP_EPS:
                result.totals["out_of_order"] += 1
                result.issues.append(Issue(index, "out_of_order", "开始时间早于上一条"))
            elif cue.start < prev.end - OVERLAP_EPS:
                overlap = prev.end - cue.start
                result.totals["overlap"] += 1
                result.issues.append(Issue(index, "overlap", f"与上一条重叠 {overlap:.1f}s"))

    if before_texts is not None and before_texts:
        joined = "".join(str(cue.text or "").strip() for cue in block)
        original = "".join(str(text or "").strip() for text in before_texts)
        # 只有「条数与文字都没变」才算模型没动手。纯合并稿的文字拼起来本来就等于原稿，
        # 只看文字会把它误报成「模型没改」。
        result.identical = (
            bool(joined) and joined == original and len(block) == len(before_texts)
        )
    return result


def summary_notes(diag: Diagnostics, *, range_label: str = "") -> list[dict]:
    """预览顶部那一行摘要；每条 ``{text, level}``，界面按顺序渲染成胶囊。"""
    notes: list[dict] = []
    count_text = f"{diag.count} 条"
    if diag.count_before and diag.count != diag.count_before:
        delta = diag.count - diag.count_before
        count_text += f"（原 {diag.count_before} 条，{'+' if delta > 0 else ''}{delta}）"
    notes.append({"text": count_text, "level": "plain"})
    if diag.count:
        notes.append({"text": f"{_tc(diag.span[0])}–{_tc(diag.span[1])}", "level": "plain"})
    if range_label:
        notes.append({"text": range_label, "level": "plain"})
    for kind, label in (
        ("overlap", "处重叠"),
        ("out_of_order", "处倒序"),
        ("too_long", "条偏长"),
        ("too_short", "条偏短"),
        ("out_of_range", "条越界"),
        ("empty_text", "条空白"),
    ):
        value = diag.totals.get(kind, 0)
        if value:
            notes.append({"text": f"{value} {label.strip()}", "level": "warn"})
    if diag.identical:
        notes.append({"text": "和原稿几乎一样（模型没改）", "level": "warn"})
    return notes
