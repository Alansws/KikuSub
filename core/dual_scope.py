"""双引擎复核的**对照范围**（focus scope）纯函数。

## 为什么需要它（2026-11-26 真机报障）

逐章跑「两版一起」/「第二版」时，核对台 A 是**累积**的（第 1–3 章 636 条、
00:13–55:36），而第二版 B 只包含这一趟的区间（第 3 章 220 条、35:58–55:36）。
复核页若按整片对齐，前两章 430 条会全部变成红色的「仅 A」：

- 真正要核对的章节三被埋在 400 多行假差异下面；
- 「~ 文本不同」与侧栏徽标失真（用户看到 430 个不存在的差异）；
- 最危险的是那次「整列覆盖」会把前两章一起丢掉。

所以复核页需要一个**可切换的对照范围**，并且默认要能自己认出「B 只覆盖了一段」，
把对齐、列表、统计、写回全部收进这一段。本模块只做纯计算（无 IO / 无模型，
可被 ``node`` 以外的一切直接单测），服务端与渲染层共用同一套口径。

## 三个范围

- ``all``：整片对齐（B 是完整第二版时的正常口径）；
- ``b``：B 自己覆盖的区间（``[min(start), max(end)]``）；
- ``ch:<id>``：工程里已有的**区间章节**（时刻点不算，它没有跨度）。

三者都用**原片绝对时间**表示，和核对台、章节、导出同一条时间轴。

## 「B 只覆盖了一部分」的判据

:func:`is_partial_b`：B 的跨度没有盖住 A 的跨度（任一端差超过
:data:`EDGE_TOLERANCE` 秒）。局部转录、逐章转录都会命中；B 是整片第二版时不会。
命中时 :func:`default_focus` 默认聚焦 B 的区间，并优先套上覆盖它的章节名。
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .subtitles import SubtitleCue

#: A / B 跨度差多少秒以内仍视为「覆盖了整片」。转写首尾各留 0.3–0.5s 静音，
#: 取 1.0s 既不会把「差一句」误判成整片，也不会把整片第二版误判成局部稿。
EDGE_TOLERANCE = 1.0
#: B 的跨度有多大比例落在某个章节里，才把这一章当成「B 所在章节」。
CHAPTER_FIT_RATIO = 0.85
#: 章节跨度可以比 B 的跨度短多少秒（转写会比章节首尾多留一点 padding）。
CHAPTER_PAD = 2.0

ALL_KEY = "all"
B_KEY = "b"
CHAPTER_PREFIX = "ch:"


def format_clock(seconds: float) -> str:
    """``2133.4`` → ``35:33``；超过一小时用 ``1:02:03``。"""
    total = max(0, int(float(seconds or 0.0)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def cue_span(cues: Iterable[SubtitleCue]) -> tuple[float, float] | None:
    """一组字幕的时间跨度；空列表返回 ``None``。"""
    first: float | None = None
    last: float | None = None
    for cue in cues or []:
        start = float(cue.start)
        end = float(cue.end)
        first = start if first is None else min(first, start)
        last = end if last is None else max(last, end)
    if first is None or last is None:
        return None
    return (first, max(last, first))


def cues_in_window(
    cues: Sequence[SubtitleCue], start: float, end: float
) -> tuple[list[SubtitleCue], list[int]]:
    """时间窗内**有任何重叠**的字幕，以及它们在原列表里的 0 基下标。

    与 :func:`core.clip_range.select_cues_in_range` 的「首尾蹭边」不同：复核页
    要的是「这一段的对照」，句子的边界由引擎决定，不能被窗口切掉半句——
    只要有一点点重叠就保留整条，否则窗口边界上的句子会在两列之间凭空消失。
    """
    lo = float(start)
    hi = float(end)
    if hi <= lo:
        return ([], [])
    picked: list[SubtitleCue] = []
    indices: list[int] = []
    for index, cue in enumerate(cues or []):
        if float(cue.end) > lo and float(cue.start) < hi:
            picked.append(cue)
            indices.append(index)
    return (picked, indices)


def is_partial_b(
    a_cues: Sequence[SubtitleCue],
    b_cues: Sequence[SubtitleCue],
    *,
    tolerance: float = EDGE_TOLERANCE,
) -> bool:
    """B 是不是「只覆盖了一段」的第二版（局部转录 / 逐章转录的产物）。"""
    span_a = cue_span(a_cues)
    span_b = cue_span(b_cues)
    if span_a is None or span_b is None:
        return False
    return (
        span_b[0] > span_a[0] + tolerance
        or span_b[1] < span_a[1] - tolerance
    )


def interval_chapters(chapters: Iterable) -> list[dict]:
    """只留**区间章节**（``end`` 有值），归一成 ``{id,title,start,end}``。

    时刻点没有跨度，不能当对照范围；章节按起点升序，去掉零长度条目。
    接受 ``ChapterMark`` 数据类、dict 或任何带同名属性的对象（接口层喂进来的是
    dict，``Session.chapters`` 里是 dataclass，两边都要能用）。
    """
    out: list[dict] = []
    for index, mark in enumerate(chapters or []):
        if isinstance(mark, dict):
            raw_end = mark.get("end")
            raw_start = mark.get("start", 0.0)
            title = mark.get("title", "")
            ident = mark.get("id", "")
        else:
            raw_end = getattr(mark, "end", None)
            raw_start = getattr(mark, "start", 0.0)
            title = getattr(mark, "title", "")
            ident = getattr(mark, "id", "")
        if raw_end is None or raw_end == "":
            continue
        try:
            start = float(raw_start or 0.0)
            end = float(raw_end)
        except (TypeError, ValueError):
            continue
        if end - start <= 0.001:
            continue
        out.append(
            {
                "id": str(ident or f"mark-{index + 1}"),
                "title": str(title or "").strip(),
                "start": round(start, 3),
                "end": round(end, 3),
            }
        )
    out.sort(key=lambda item: (item["start"], item["end"]))
    return out


def _fit_ratio(window: tuple[float, float], chapter: dict) -> float:
    """B 的窗口有多大比例落在这一章里（0–1）。"""
    lo, hi = window
    length = hi - lo
    if length <= 0:
        return 0.0
    overlap = min(hi, float(chapter["end"])) - max(lo, float(chapter["start"]))
    return max(0.0, overlap) / length


def match_chapter(
    window: tuple[float, float] | None,
    chapters: Iterable[dict],
    *,
    ratio: float = CHAPTER_FIT_RATIO,
    pad: float = CHAPTER_PAD,
) -> dict | None:
    """找「B 所在的那一章」：重叠占比够高、且两端都没有跑到章外太远。"""
    if window is None:
        return None
    lo, hi = window
    best: tuple[float, dict] | None = None
    for chapter in chapters or []:
        start = float(chapter["start"])
        end = float(chapter["end"])
        if lo < start - pad or hi > end + pad:
            continue
        fit = _fit_ratio(window, chapter)
        if fit < ratio:
            continue
        score = fit - abs((start + end) / 2 - (lo + hi) / 2) / 1_000_000
        if best is None or score > best[0]:
            best = (score, chapter)
    return best[1] if best else None


def _window_union(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (min(a[0], b[0]), max(a[1], b[1]))


def _focus(
    *,
    kind: str,
    key: str,
    start: float,
    end: float,
    label: str,
    chapter: dict | None = None,
) -> dict:
    start = round(max(0.0, float(start)), 3)
    end = round(max(start + 0.001, float(end)), 3)
    return {
        "kind": kind,
        "key": key,
        "start": start,
        "end": end,
        "label": label,
        "range_label": f"{format_clock(start)}–{format_clock(end)}",
        "chapter_id": (chapter or {}).get("id", ""),
        "chapter_title": (chapter or {}).get("title", ""),
    }


def all_focus(
    a_cues: Sequence[SubtitleCue],
    b_cues: Sequence[SubtitleCue] | None = None,
    duration: float = 0.0,
) -> dict:
    """整片范围：A 与 B 跨度的**并集**。

    只取 A 的跨度会把 B 多出来的尾部句子切掉（A 2 条 / B 3 条时统计会假变成 2），
    而「全片」的语义是「这份工程涉及的全部时间」。两列都空时退回片长。
    """
    span_a = cue_span(a_cues)
    span_b = cue_span(b_cues or [])
    spans = [span for span in (span_a, span_b) if span is not None]
    if spans:
        start = min(span[0] for span in spans)
        end = max(span[1] for span in spans)
        return _focus(kind="all", key=ALL_KEY, start=start, end=end, label="全片")
    total = max(0.0, float(duration or 0.0))
    return _focus(kind="all", key=ALL_KEY, start=0.0, end=total or 1.0, label="全片")


def b_focus(b_cues: Sequence[SubtitleCue], chapters: Iterable[dict] | None = None) -> dict | None:
    """B 所在区间；能匹配到章节时用章节名（并扩到章 + B 的并集，不丢 B 的句子）。"""
    span = cue_span(b_cues)
    if span is None:
        return None
    chapters = list(chapters or [])
    chapter = match_chapter(span, chapters)
    window = _window_union(span, (chapter["start"], chapter["end"])) if chapter else span
    if chapter:
        label = chapter["title"] or "B 所在章节"
        return _focus(
            kind="chapter",
            key=f"{CHAPTER_PREFIX}{chapter['id']}",
            start=window[0],
            end=window[1],
            label=label,
            chapter=chapter,
        )
    return _focus(kind="range", key=B_KEY, start=window[0], end=window[1], label="B 所在区间")


def chapter_focus(chapter: dict) -> dict:
    """某一段区间章节。"""
    start = float(chapter["start"])
    end = float(chapter["end"])
    return _focus(
        kind="chapter",
        key=f"{CHAPTER_PREFIX}{chapter['id']}",
        start=start,
        end=end,
        label=chapter.get("title") or "章节",
        chapter=chapter,
    )


def default_focus(
    a_cues: Sequence[SubtitleCue],
    b_cues: Sequence[SubtitleCue],
    chapters: Iterable | None = None,
    duration: float = 0.0,
) -> dict:
    """进入复核页时的默认范围：B 只覆盖一段就聚焦那一段，否则整片。

    这是修复「636 vs 220」的核心：默认口径不再拿前两章凑假差异。
    """
    marks = interval_chapters(chapters or [])
    if is_partial_b(a_cues, b_cues):
        focus = b_focus(b_cues, marks)
        if focus is not None:
            return focus
    return all_focus(a_cues, b_cues, duration)


def scope_options(
    a_cues: Sequence[SubtitleCue],
    b_cues: Sequence[SubtitleCue],
    chapters: Iterable | None = None,
    duration: float = 0.0,
) -> list[dict]:
    """给界面用的范围清单（含每项条数，切范围不必再发请求）。

    顺序：B 所在区间 → 各章节 → 全片。B 覆盖整片时不重复给「B 所在区间」
    （它和全片是同一件事），章节多于 :data:`MAX_SCOPE_CHAPTERS` 时全部照给——
    章节本来就该由用户在工具栏里直接点选。
    """
    marks = interval_chapters(chapters or [])
    options: list[dict] = []
    seen_keys: set[str] = set()

    if is_partial_b(a_cues, b_cues):
        focus = b_focus(b_cues, marks)
        if focus is not None:
            options.append(_option(focus, a_cues, b_cues))
            seen_keys.add(focus["key"])

    for chapter in marks:
        focus = chapter_focus(chapter)
        if focus["key"] in seen_keys:
            continue
        options.append(_option(focus, a_cues, b_cues))

    options.append(_option(all_focus(a_cues, b_cues, duration), a_cues, b_cues))
    return options


def _option(focus: dict, a_cues, b_cues) -> dict:
    a_hits, _ = cues_in_window(a_cues or [], focus["start"], focus["end"])
    b_hits, _ = cues_in_window(b_cues or [], focus["start"], focus["end"])
    return {**focus, "a_count": len(a_hits), "b_count": len(b_hits)}


def resolve_focus(
    key: str,
    a_cues: Sequence[SubtitleCue],
    b_cues: Sequence[SubtitleCue],
    chapters: Iterable | None = None,
    duration: float = 0.0,
) -> dict:
    """把界面传来的范围 key 解析成 focus；未知 key 退回默认范围。

    ``auto`` / 空串 = 智能默认（:func:`default_focus`）。
    """
    marks = interval_chapters(chapters or [])
    raw = str(key or "").strip()
    if not raw or raw == "auto":
        return default_focus(a_cues, b_cues, chapters or [], duration)
    if raw == ALL_KEY:
        return all_focus(a_cues, b_cues, duration)
    if raw == B_KEY:
        focus = b_focus(b_cues, marks)
        return focus if focus is not None else all_focus(a_cues, b_cues, duration)
    if raw.startswith(CHAPTER_PREFIX):
        wanted = raw[len(CHAPTER_PREFIX) :]
        for chapter in marks:
            if chapter["id"] == wanted:
                return chapter_focus(chapter)
        return default_focus(a_cues, b_cues, chapters or [], duration)
    return default_focus(a_cues, b_cues, chapters or [], duration)


def hidden_counts(
    a_cues: Sequence[SubtitleCue], b_cues: Sequence[SubtitleCue], focus: dict
) -> tuple[int, int]:
    """范围外被隐去的 A / B 条数（页头「已隐去 N 条」与徽标解释用）。"""
    a_in, _ = cues_in_window(a_cues or [], focus["start"], focus["end"])
    b_in, _ = cues_in_window(b_cues or [], focus["start"], focus["end"])
    return (max(0, len(list(a_cues or [])) - len(a_in)), max(0, len(list(b_cues or [])) - len(b_in)))


def replace_window(
    a_cues: Sequence[SubtitleCue],
    b_cues: Sequence[SubtitleCue],
    start: float,
    end: float,
) -> tuple[list[SubtitleCue], int, int]:
    """「用 B 替换当前范围」：只换窗口内的 A，窗口外一条不动。

    返回 ``(merged, removed, inserted)``：

    - ``removed``：被换掉的 A 条数（与窗口有重叠的那些）；
    - ``inserted``：写进来的 B 条数（与窗口有重叠的那些）。

    窗口外的 A 原样保留、顺序不变——这正是「绝不误删第 1、2 章」的保证。
    """
    lo = float(start)
    hi = float(end)
    kept = [
        cue for cue in (a_cues or []) if not (float(cue.end) > lo and float(cue.start) < hi)
    ]
    incoming, _ = cues_in_window(b_cues or [], lo, hi)
    merged = [*kept, *incoming]
    merged.sort(key=lambda cue: (float(cue.start), float(cue.end)))
    return (merged, len(list(a_cues or [])) - len(kept), len(incoming))


def would_trim(
    a_cues: Sequence[SubtitleCue],
    b_cues: Sequence[SubtitleCue],
    *,
    tolerance: float = EDGE_TOLERANCE,
) -> int:
    """整列覆盖会**丢掉**多少条 A（B 覆盖不到的时间段里的 A 条数）。

    整列覆盖前用它做最后一道闸：>0 且用户没显式确认时服务端直接拒绝。
    返回 0 表示 B 盖住了 A 的全部跨度，整列覆盖是安全的。
    """
    span_b = cue_span(b_cues)
    if span_b is None:
        return len(list(a_cues or []))
    span_a = cue_span(a_cues)
    if span_a is None:
        return 0
    if span_b[0] <= span_a[0] + tolerance and span_b[1] >= span_a[1] - tolerance:
        return 0
    outside = [
        cue
        for cue in (a_cues or [])
        if float(cue.end) <= span_b[0] + 0.001 or float(cue.start) >= span_b[1] - 0.001
    ]
    return len(outside)
