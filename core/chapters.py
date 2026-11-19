"""章节 / 时刻点标记：数据结构、归一化、持久化与 FFMETADATA 生成。

## 两种形态

- **场景区间**（`end` 有值）：`00:00 → 23:30 场景1`；
- **关键时刻点**（`end` 为 None）：`23:30 倒计时开始`、`25:10 发射点`。

时刻点在写进容器前必须变成区间：结束时间取**下一个标记的起点或片尾**。播放器
（IINA / QuickTime / VLC）只认「有起点和终点的章节列表」，把时刻点原样丢进去
会被直接忽略，用户点了也跳不过去。

## 归一化规则

1. 按 `start` 升序（稳定排序，同一时刻保留输入顺序）；
2. `start` 夹进 `[0, duration]`，`end` 夹进 `[start, duration]`；
3. 区间不超过下一个标记的起点（防重叠：后一个标记一旦开始，前一个必须结束）；
4. 归一化后长度 < 1ms 的条目丢弃（重复起点 / 片尾之后的标记），
   `FFMETADATA1` 不允许空章节；
5. 最后一个标记的终点 = 片尾（`duration`），没有片长信息时用起点 + 1 秒兜底。

**这里不写「必须从 0 开始」**：用户把第一个标记放在 23:30 是合法的，0–23:30
本来就没有章节。播放器会把它显示成第一个可跳转点。

## FFMETADATA

`;FFMETADATA1` + 每个章节一段 `[CHAPTER]` / `TIMEBASE=1/1000` / `START` / `END`
（整数毫秒）/ `title=…`。值里的 `\\`、`;`、`#`、`=` 与换行必须转义（换行写成
反斜杠 + 真实换行，ffmetadata 解析器会把它并回一行）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CHAPTERS_VERSION = 1
# 一次最多多少条标记：够长片分场景，也不至于把 ffmetadata 撑爆。
MAX_MARKS = 500
MAX_TITLE = 120
# 章节最短长度（秒）：更短的区间在播放器里点不中，直接丢弃。
MIN_CHAPTER_S = 0.001

FFMETADATA_HEADER = ";FFMETADATA1"
# 与 ffmpeg 的 ffmetaenc 一致：这些字符出现在值里必须反斜杠转义
_ESCAPE_CHARS = set("\\;=#")


@dataclass
class ChapterMark:
    """一条标记。`end is None` = 时刻点。"""

    id: str
    start: float
    end: float | None = None
    title: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "start": self.start, "end": self.end, "title": self.title}

    @classmethod
    def from_mapping(cls, raw: dict) -> "ChapterMark":
        """宽松读取（前端 / 旧文件 / 手改的 JSON 都可能缺字段）。"""
        raw = raw or {}
        end_value = raw.get("end")
        try:
            end = None if end_value is None or end_value == "" else float(end_value)
        except (TypeError, ValueError):
            end = None
        return cls(
            id=str(raw.get("id") or "").strip(),
            start=_safe_float(raw.get("start")),
            end=end,
            title=str(raw.get("title") or "").strip()[:MAX_TITLE],
        )


@dataclass
class Chapter:
    """写进容器的最终区间（秒）。"""

    start: float
    end: float
    title: str

    @property
    def start_ms(self) -> int:
        return int(round(self.start * 1000))

    @property
    def end_ms(self) -> int:
        return int(round(self.end * 1000))

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "title": self.title,
        }


def _safe_float(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number == number else 0.0  # NaN → 0


def _identity(media_path: str | Path) -> str:
    path = Path(str(media_path or "")).expanduser()
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    try:
        stat = resolved.stat()
        fingerprint = f"{resolved}|{stat.st_size}|{int(stat.st_mtime_ns)}"
    except OSError:
        fingerprint = str(resolved)
    return hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16]


def store_path(output_dir: str | Path, media_path: str | Path) -> Path:
    """标记边车文件：`{output_dir}/chapters/{stem}.{key}.chapters.json`。

    按「路径 + 大小 + mtime」分段：同一部片换版本（重新压制）时不会把旧章节
    套到新片上，也不会因为另一个同名文件而互相覆盖。
    """
    stem = Path(str(media_path or "")).stem or "media"
    return Path(output_dir) / "chapters" / f"{stem}.{_identity(media_path)}.chapters.json"


def load_marks(output_dir: str | Path, media_path: str | Path) -> list[ChapterMark]:
    """读标记；文件不存在 / 损坏都返回空列表（章节是可选增强）。"""
    path = store_path(output_dir, media_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("marks") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    marks: list[ChapterMark] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        mark = ChapterMark.from_mapping(item)
        if not mark.id:
            mark.id = f"m{len(marks) + 1}"
        marks.append(mark)
    return normalize_marks(marks)


def save_marks(
    output_dir: str | Path, media_path: str | Path, marks: Iterable[ChapterMark]
) -> Path:
    """原子写入标记文件（先写临时文件再 rename）。返回落盘路径。"""
    path = store_path(output_dir, media_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CHAPTERS_VERSION,
        "marks": [mark.to_dict() for mark in normalize_marks(list(marks))],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp = path.with_name(f".{path.name}.{id(payload)}.part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def normalize_marks(
    marks: Iterable[ChapterMark], duration: float = 0.0
) -> list[ChapterMark]:
    """按起点排序、夹紧、去重（id）、截断标题。不处理衔接（`layout_chapters` 做）。"""
    d = max(0.0, _safe_float(duration))
    result: list[ChapterMark] = []
    seen_ids: set[str] = set()
    for raw in marks:
        mark = ChapterMark.from_mapping(raw.to_dict() if isinstance(raw, ChapterMark) else raw)
        start = max(0.0, mark.start)
        if d > 0:
            start = min(start, d)
        end = mark.end
        if end is not None:
            end = max(start, end)
            if d > 0:
                end = min(end, d)
            if end - start < MIN_CHAPTER_S:
                end = None  # 退化成时刻点，交给衔接规则
        # id 必须唯一且可寻址：前端按 id 做重命名 / 删除
        base = mark.id or "mark"
        mark_id = base
        n = 2
        while mark_id in seen_ids:
            mark_id = f"{base}-{n}"
            n += 1
        seen_ids.add(mark_id)
        result.append(
            ChapterMark(id=mark_id, start=round(start, 3), end=None if end is None else round(end, 3), title=mark.title)
        )
        if len(result) >= MAX_MARKS:
            break
    result.sort(key=lambda item: item.start)
    return result


def layout_chapters(
    marks: Iterable[ChapterMark],
    duration: float = 0.0,
    *,
    pad_start: bool = True,
) -> list[Chapter]:
    """归一化 + 衔接：时刻点结束于下一个标记起点（或片尾），区间不重叠。

    返回的列表已经满足 ffmetadata 的要求：按时间升序、每段
    `0 <= start < end`、段与段不重叠。

    ``pad_start``（默认开）在第一个标记晚于 0 时补一个「开场」章节。原因不是
    审美：**MP4 的章节是一条文本轨，ffmpeg 会把首章强制拉回 0**——不补的话
    「12s 的时刻点」在 MP4 里会变成从 0s 开始的章节，用户点它跳到片头而不是
    12s。补一段 0→首个起点既保住真实起点，也让 MKV / MP4 的章节表一致。
    传 ``pad_start=False`` 可得到「忠实于标记」的布局（测试与 API 预览各取所需）。
    """
    d = max(0.0, _safe_float(duration))
    ordered = normalize_marks(marks, d)
    chapters: list[Chapter] = []
    last_end = 0.0
    for index, mark in enumerate(ordered):
        start = max(mark.start, last_end)
        if d > 0 and start >= d - MIN_CHAPTER_S:
            # 起点已经贴到片尾：再生成就是 0 长度章节，播放器会数错章节
            break
        next_start = None
        for later in ordered[index + 1 :]:
            if later.start > start:
                next_start = later.start
                break
        if next_start is None:
            next_start = d if d > 0 else start + 1.0
        end = mark.end if mark.end is not None else next_start
        # 防重叠：后一个标记开始之前必须结束
        end = min(end, next_start)
        # 结束时间在最后一条之后：跟片尾对齐（没有片长也不越过下一个起点）
        if index == len(ordered) - 1 and d > 0:
            end = min(max(end, start), d)
        if end - start < MIN_CHAPTER_S:
            if next_start - start >= MIN_CHAPTER_S:
                end = next_start
            else:
                continue
        title = (mark.title or f"章节 {len(chapters) + 1}").strip()[:MAX_TITLE]
        chapters.append(Chapter(start=round(start, 3), end=round(end, 3), title=title))
        last_end = end
    if pad_start and chapters and chapters[0].start > MIN_CHAPTER_S:
        chapters.insert(0, Chapter(start=0.0, end=chapters[0].start, title="开场"))
    return chapters


def escape_ffmetadata(value: str) -> str:
    """按 ffmetadata 的转义规则处理值。

    `\\`、`;`、`#`、`=` 前缀反斜杠；换行写成反斜杠 + 真实换行（行继续）。
    """
    text = str(value or "")
    escaped: list[str] = []
    for char in text:
        if char in _ESCAPE_CHARS:
            escaped.append("\\")
            escaped.append(char)
        elif char == "\n":
            escaped.append("\\\n")
        elif char == "\r":
            continue
        else:
            escaped.append(char)
    return "".join(escaped)


def ffmetadata_text(marks: Iterable[ChapterMark], duration: float = 0.0) -> str:
    """生成 `-map_chapters` 用的 FFMETADATA 文件内容（TIMEBASE=1/1000）。"""
    chapters = layout_chapters(marks, duration)
    lines = [FFMETADATA_HEADER]
    for chapter in chapters:
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={chapter.start_ms}")
        lines.append(f"END={chapter.end_ms}")
        lines.append(f"title={escape_ffmetadata(chapter.title)}")
    lines.append("")
    return "\n".join(lines)


def write_ffmetadata(
    path: str | Path, marks: Iterable[ChapterMark], duration: float = 0.0
) -> Path:
    """把 FFMETADATA 写到 `path`（UTF-8，无 BOM）。返回路径。"""
    target = Path(path)
    target.write_text(ffmetadata_text(marks, duration), encoding="utf-8")
    return target


def has_chapters(marks: Iterable[ChapterMark], duration: float = 0.0) -> bool:
    return bool(layout_chapters(marks, duration))
