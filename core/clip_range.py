"""片段范围（clip）的纯函数裁剪：字幕、译文、章节 / 时刻点。

## 为什么单独一个模块

长片里用户常常只精修一段（例如只核对第 1–291 条），打上章节（`0:10 → 24:22`）
与内部时刻点（`22:55 发射点`），然后只导出这一段。润色、翻译、成片导出、字幕导出
都要做同一件事：**把整片的坐标搬到片段坐标**（时间减 `start`，夹到
`[0, end - start]`），章节和时刻点也要一起搬。四处各写一遍必然漂移，所以集中在这里，
`core/` 内零依赖（不 import UI / 网络 / torch）。

## 三条口径

1. **首尾蹭边不算命中**：与区间重叠不足 :data:`MIN_EDGE_OVERLAP_S`（0.1s）且
   **不是整条落在区间内**的句子，是相邻场景的尾巴/开头，必须忽略。否则导出时
   片头会多出一句属于上一场景的字幕。
2. **平移后必须夹紧**：`t - start` 可能为负（跨界句）或超过片段长度（尾部跨界句），
   一律夹到 `[0, duration]`，再丢掉夹成 0 长度的条目。
3. **章节不拆碎**：区间标记（`end` 有值）按原样保留并夹紧，**不被内部时刻点切成
   两段**——那就是用户在核对台里画的章，导出后播放器里必须还是同一个章。

示例（用户原话）：`0:10 章节1` + `22:55 发射点`，裁剪成 `[10s, 1462s]` 后
得到 `0:00 章节1` 与 `22:45 发射点`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .chapters import ChapterMark, MIN_CHAPTER_S, normalize_marks
from .subtitles import SubtitleCue

# 首尾「蹭边」的判定阈值：更短的重叠来自相邻场景，不属于本片段。
MIN_EDGE_OVERLAP_S = 0.1
# 片段最短长度：再短就不是「一段」而是误触，规划阶段直接拒绝。
MIN_CLIP_S = 0.2
# 文件名标签长度上限（章节标题可能很长）。
MAX_CLIP_LABEL = 48

_UNSAFE = re.compile(r'[\s\\/:*?"<>|;#$\u0000-\u001f]+')


@dataclass(frozen=True)
class ClipWindow:
    """一个已归一化的片段窗口（秒）。`end` 是**原片**时间，不是长度。"""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def clamp(self, seconds: float) -> float:
        """原片时间 → 片段内时间（相对 `start`，夹紧）。"""
        return min(self.duration, max(0.0, float(seconds) - self.start))

    def contains(self, seconds: float) -> bool:
        return self.start <= float(seconds) <= self.end

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
        }


def clip_window(start: float | None, end: float | None, duration: float = 0.0) -> ClipWindow | None:
    """把用户给的 `[start, end]` 归一化成 :class:`ClipWindow`；`None` = 全片。

    - `end` 缺失 / ≤0 表示「全片」，返回 None（调用方不需要分支处理 0 长度片段）；
    - `start` 夹进 `[0, duration]`，`end` 夹进 `[start, duration]`；
    - 归一化后短于 :data:`MIN_CLIP_S` 抛 ``ValueError``（由服务层转成可读错误）。
    """
    try:
        raw_end = 0.0 if end is None else float(end)
    except (TypeError, ValueError):
        raw_end = 0.0
    if raw_end <= 0:
        return None
    try:
        raw_start = 0.0 if start is None else float(start)
    except (TypeError, ValueError):
        raw_start = 0.0
    total = max(0.0, float(duration or 0.0))
    lo = min(max(0.0, raw_start), total) if total > 0 else max(0.0, raw_start)
    hi = raw_end if total <= 0 else min(raw_end, total)
    if hi - lo < MIN_CLIP_S:
        raise ValueError(
            f"片段范围太短或超出片尾：{_clock(lo)} → {_clock(hi)}（至少 {MIN_CLIP_S:g} 秒）"
        )
    return ClipWindow(start=round(lo, 3), end=round(hi, 3))


@dataclass
class CueSelection:
    """`select_cues_in_range()` 的结果：命中的字幕、它们在原片的 0 基下标与范围。"""

    cues: list[SubtitleCue]
    indices: list[int]
    start: float
    end: float

    @property
    def count(self) -> int:
        return len(self.cues)

    @property
    def from_index(self) -> int:
        """1 基、含（接口 / 界面都用这个口径）。空选区返回 0。"""
        return self.indices[0] + 1 if self.indices else 0

    @property
    def to_index(self) -> int:
        return self.indices[-1] + 1 if self.indices else 0

    @property
    def contiguous(self) -> bool:
        """命中的下标是否连续（提案按区间切片时需要）。"""
        return all(b == a + 1 for a, b in zip(self.indices, self.indices[1:]))

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "from_index": self.from_index,
            "to_index": self.to_index,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "contiguous": self.contiguous,
        }


def select_cues_in_range(
    cues: list[SubtitleCue],
    start: float,
    end: float,
    *,
    min_overlap: float = MIN_EDGE_OVERLAP_S,
) -> CueSelection:
    """筛出与 `[start, end]` 有效相交的字幕，并记录它们在原片的 0 基下标。

    命中规则：重叠 > 0 且（重叠 ≥ `min_overlap` **或**整条都落在区间内）。
    第二条是给很短的句子留的：0.06 秒的「はい」整条都在片段里，不能因为短就丢。
    """
    lo = float(start)
    hi = float(end)
    picked: list[SubtitleCue] = []
    indices: list[int] = []
    if hi <= lo:
        return CueSelection(cues=picked, indices=indices, start=lo, end=hi)
    for index, cue in enumerate(cues):
        overlap = min(float(cue.end), hi) - max(float(cue.start), lo)
        if overlap <= 0:
            continue
        inside = float(cue.start) >= lo and float(cue.end) <= hi
        if not inside and overlap < min_overlap:
            continue
        picked.append(cue)
        indices.append(index)
    return CueSelection(cues=picked, indices=indices, start=lo, end=hi)


def shift_cues_to_clip(
    cues: list[SubtitleCue],
    translations: list[str] | None,
    start: float,
    end: float,
) -> tuple[list[SubtitleCue], list[str]]:
    """把字幕与译文搬到片段坐标：`t - start`，夹进 `[0, end - start]`。

    `translations` 与 `cues` 逐条对齐；为空 / 偏短时补空串。返回的是**副本**，
    调用方可以直接交给导出器，不会改到核对台的字幕。
    """
    lo = float(start)
    hi = float(end)
    duration = max(0.0, hi - lo)
    texts = list(translations or [])
    out_cues: list[SubtitleCue] = []
    out_texts: list[str] = []
    for index, cue in enumerate(cues):
        new_start = min(duration, max(0.0, float(cue.start) - lo))
        new_end = min(duration, max(0.0, float(cue.end) - lo))
        if new_end - new_start <= 0:
            # 整条都在片段外（起点夹到片尾后仍是 0 长度）：不产出空字幕。
            continue
        out_cues.append(SubtitleCue(start=round(new_start, 3), end=round(new_end, 3), text=cue.text))
        out_texts.append(str(texts[index]) if index < len(texts) else "")
    return out_cues, out_texts


def shift_chapters_to_clip(
    chapters: list[ChapterMark],
    start: float,
    end: float,
) -> list[ChapterMark]:
    """保留与 `[start, end]` 相交的标记（区间 + 内部时刻点），时间平移到片段坐标。

    区间标记按原样夹紧、**不在内部时刻点处切开**；时刻点按点平移。
    平移后长度不足 :data:`core.chapters.MIN_CHAPTER_S` 的条目丢弃
    （ffmetadata 不允许空章节）。
    """
    lo = float(start)
    hi = float(end)
    duration = max(0.0, hi - lo)
    if duration <= 0:
        return []
    shifted: list[ChapterMark] = []
    for mark in normalize_marks(chapters):
        if mark.end is None:
            if not lo <= float(mark.start) <= hi:
                continue
            at = float(mark.start) - lo
            if at < 0 or at >= duration - MIN_CHAPTER_S:
                # 落在片段终点上的时刻点没有可跳转的空间。
                continue
            shifted.append(
                ChapterMark(id=mark.id, start=round(at, 3), end=None, title=mark.title)
            )
            continue
        overlap = min(float(mark.end), hi) - max(float(mark.start), lo)
        if overlap < MIN_CHAPTER_S:
            continue
        new_start = max(0.0, float(mark.start) - lo)
        new_end = min(duration, float(mark.end) - lo)
        if new_end - new_start < MIN_CHAPTER_S:
            continue
        shifted.append(
            ChapterMark(
                id=mark.id,
                start=round(new_start, 3),
                end=round(new_end, 3),
                title=mark.title,
            )
        )
    return shifted


# --------------------------------------------------------------------------- 文件名标签


def clock_label(seconds: float) -> str:
    """`10` → `00m10s`，`1462` → `24m22s`，`3723` → `1h02m03s`。文件名安全。"""
    total = max(0, int(round(float(seconds))))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    return f"{minutes:02d}m{secs:02d}s"


def safe_label(text: str, *, max_len: int = MAX_CLIP_LABEL) -> str:
    """把章节标题变成文件名安全片段：去掉路径分隔符与控制字符，折叠空白。"""
    cleaned = _UNSAFE.sub("-", str(text or "").strip()).strip("-._")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned[:max_len].strip("-._")


def clip_tag(start: float, end: float, title: str = "") -> str:
    """片段导出文件名里的范围标签，例如 `场景1-00m10s-24m22s`。"""
    window = f"{clock_label(start)}-{clock_label(end)}"
    label = safe_label(title)
    return f"{label}-{window}" if label else window


def _clock(seconds: float) -> str:
    total = max(0.0, float(seconds))
    return f"{int(total // 60):02d}:{total % 60:06.3f}"
