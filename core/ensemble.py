"""双引擎顺序协同：把副稿里「主稿没有、且可信」的补漏候选筛出来。

P2 的顺序协同不是把两稿直接混在一起，而是：

1. Pass A（主引擎）写主稿；
2. Pass B（副引擎）写只读第二列；
3. 只把 B 的 ``only_b`` 行里**时间对不上主稿、文本也不与主稿任何一句重复**的
   条目，作为 ``ensemble`` 建议送进质检队列，由用户逐条采纳。

这个模块只做第 3 步的纯函数部分（无 IO / 无模型 / 无 UI），对齐复用
``core.dual_review.build_review``——复核页与补漏建议必须看到同一份差异，
不允许再写一套「哪句算漏」的判断。
"""

from __future__ import annotations

import unicodedata

from .dual_review import build_review, normalize_text, text_similarity
from .subtitles import SubtitleCue

#: 少于两个字或短于这个时长的候选，多半是呼吸/切分碎片，不进队列。
MIN_TEXT_CHARS = 2
MIN_DURATION_S = 0.35
#: 单次任务最多送这么多条建议，避免长片把质检队列刷爆。
MAX_SUGGESTIONS = 50
#: 副稿文本在主稿里已有高度相似句时，视为断句差异而非漏句。
DUPLICATE_SIMILARITY = 0.85


def _content_chars(text: str) -> int:
    """只数字母/数字/假名/汉字；标点、省略号、空白不算「有台词」。"""
    return sum(1 for ch in str(text or "") if unicodedata.category(ch)[0] in {"L", "N"})


def _nearest_text(cue: SubtitleCue, cues: list[SubtitleCue]) -> str:
    """找时间上最近的主稿句子，只用于队列里给用户一个对照。"""
    if not cues:
        return ""
    centre = (cue.start + cue.end) / 2.0
    nearest = min(
        cues,
        key=lambda item: abs((item.start + item.end) / 2.0 - centre),
    )
    return nearest.text


def _already_in_primary(text: str, cues: list[SubtitleCue]) -> bool:
    """副稿这句是否只是主稿某句的断句/时间差异。"""
    target = normalize_text(text)
    if not target:
        return True
    for cue in cues:
        if text_similarity(target, cue.text) >= DUPLICATE_SIMILARITY:
            return True
    return False


def build_ensemble_suggestions(
    primary: list[SubtitleCue],
    secondary: list[SubtitleCue],
    *,
    engine: str = "",
    limit: int = MAX_SUGGESTIONS,
) -> list[dict]:
    """返回可直接当作 ``ensemble`` 质检项的补漏候选（按时间排序）。

    每个 item 的字段与 ``core.audit`` 的 item 对齐：
    ``start / end / text / engine / reason / nearest_a / duration``。
    """
    primary = list(primary or [])
    secondary = list(secondary or [])
    if not secondary or limit <= 0:
        return []

    review = build_review(primary, secondary)
    out: list[dict] = []
    seen: set[str] = set()
    for row in review["rows"]:
        if row["kind"] != "only_b":
            continue
        indices = row.get("b_indices") or []
        if not indices:
            continue
        cue = secondary[int(indices[0])]
        text = str(cue.text or "").strip()
        normalized = normalize_text(text)
        duration = max(0.0, float(cue.end) - float(cue.start))
        if _content_chars(text) < MIN_TEXT_CHARS or duration < MIN_DURATION_S:
            continue
        if normalized in seen or _already_in_primary(text, primary):
            continue
        seen.add(normalized)
        out.append({
            "start": round(float(cue.start), 3),
            "end": round(float(cue.end), 3),
            "duration": round(duration, 2),
            "text": text,
            "engine": str(engine or ""),
            "reason": "only_b",
            "nearest_a": _nearest_text(cue, primary),
        })

    out.sort(key=lambda item: (item["start"], item["end"]))
    return out[:limit]
