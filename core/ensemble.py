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
#: 只在候选句前后这个邻域里比对主稿相似句：长片里「はい」这类短句会重复出现，
#: 全片比对会把后面真正的新漏句误杀。
LOCAL_DEDUPE_S = 5.0
#: 与主稿任何字幕的时间交集达到「候选时长的 20%」或「0.15s」就绝不作为补漏：
#: 否则采纳后会在核对台产生重叠双字幕，应该留在 DualView 里当断句差异看。
PRIMARY_OVERLAP_RATIO = 0.20
PRIMARY_OVERLAP_MIN_S = 0.15
#: 纯发声碎片（喘息/笑声/拟声）不进补漏队列：它们属于 nonverbal 质检，
#: 作为台词插回核对台只会制造噪声。保守地只识别「ん/ふ/っ/ー/…」这类无实义音。
_VOCALIZATION_CHARS = set("んふっッー〜~…、。！？!? 　")
#: 动漫/ASMR 里常见的拟声词标记；只有全假名（无汉字）时才据此判纯发声。
_NONVERBAL_MARKERS = (
    "ぺろ",
    "はむ",
    "んふ",
    "んっ",
    "ふぅ",
    "はぁ",
    "すぅ",
    "ちゅ",
    "ぱく",
    "ごく",
    "くちゅ",
    "ずぷ",
    "ぷちゅ",
    "ぬちゅ",
)


def _content_chars(text: str) -> int:
    """只数字母/数字/假名/汉字；标点、省略号、空白不算「有台词」。"""
    return sum(1 for ch in str(text or "") if unicodedata.category(ch)[0] in {"L", "N"})


def _has_kanji(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _is_vocalization_only(text: str) -> bool:
    compact = "".join(ch for ch in str(text or "") if not ch.isspace())
    if not compact:
        return True
    if len(compact) <= 4 and all(ch in _VOCALIZATION_CHARS for ch in compact):
        return True
    # 「ぺろっ」「はむぅ…」「んっ…んんっ…」这类全假名拟声不是台词；
    # 一旦带汉字（「必要だね」）就交回正常文本判断，避免误杀。
    return not _has_kanji(compact) and any(mark in compact for mark in _NONVERBAL_MARKERS)


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


def _overlaps_primary(cue: SubtitleCue, primary: list[SubtitleCue]) -> bool:
    """候选是否与主稿字幕有明显时间交集。

    这类候选多半只是两边断句点不同；一旦作为补漏插回，就会和主稿那条叠在一起。
    """
    duration = max(0.0, float(cue.end) - float(cue.start))
    if duration <= 0:
        return False
    for other in primary:
        overlap = min(float(cue.end), float(other.end)) - max(
            float(cue.start), float(other.start)
        )
        if overlap <= 0:
            continue
        if overlap / duration >= PRIMARY_OVERLAP_RATIO or overlap >= PRIMARY_OVERLAP_MIN_S:
            return True
    return False


def _similar_nearby_in_primary(
    text: str,
    cue: SubtitleCue,
    primary: list[SubtitleCue],
    *,
    window_s: float = LOCAL_DEDUPE_S,
) -> bool:
    """只在候选句 ±window_s 内找主稿相似句，避免全片比对误杀重复短句。"""
    target = normalize_text(text)
    if not target:
        return True
    for other in primary:
        if float(other.end) < float(cue.start) - window_s:
            continue
        if float(other.start) > float(cue.end) + window_s:
            continue
        if text_similarity(target, other.text) >= DUPLICATE_SIMILARITY:
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
    recent: list[tuple[float, str]] = []
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
        if (
            _content_chars(text) < MIN_TEXT_CHARS
            or duration < MIN_DURATION_S
            or _is_vocalization_only(text)
        ):
            continue
        if _overlaps_primary(cue, primary):
            continue
        if _similar_nearby_in_primary(text, cue, primary):
            continue
        # 副稿自身只在 ±LOCAL_DEDUPE_S 内去重：远距离同文重复是正常台词。
        if any(
            abs(float(cue.start) - start) <= LOCAL_DEDUPE_S and normalized == seen_text
            for start, seen_text in recent
        ):
            continue
        recent.append((float(cue.start), normalized))
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
