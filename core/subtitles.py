"""字幕数据结构与格式转换（**不依赖 torch**）。

这些是纯函数：`SubtitleCue`、时间解析/格式化、SRT/VTT/TXT 互转。
单独成模块是为了让服务层能在 ~1 秒内启动——只要 import 了 `core.transcribe`
就会把 torch / transformers / torchaudio 一起拉起来（实测 8.3 s），
而 API 层根本不需要模型。

`core.transcribe` 会把这些名字原样再导出，所以旧的 `from core.transcribe import
SubtitleCue` 依然有效。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

@dataclass
class SubtitleCue:
    start: float
    end: float
    text: str
    # 置信度特征（P0-3 诊断用；只有 Qwen 的对齐路径会填，其余引擎恒为 None）。
    # 挂在这条字幕上而不是平行列表里：`_dedupe` / `_heal_broken_cues` 会重建并合并
    # 字幕对象，平行列表一旦被删条/合并就永久错位（2026-11-14 实测 89 vs 88）。
    confidence: dict | None = None


ELLIPSIS_ONLY_RE = re.compile(r"^[.…。]+$")
SRT_TIME_LINE_RE = re.compile(
    r"^\s*(?P<start>\d{1,}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,}:\d{2}:\d{2}[,.]\d{1,3})(?:\s+.*)?\s*$"
)


def parse_time_str(val: str | None) -> float | None:
    if not val:
        return None
    s = val.strip().replace(",", ".")
    if not s:
        return None
    try:
        if ":" in s:
            parts = s.split(":")
            if len(parts) == 3:
                h, m, sec = parts
                return int(h) * 3600 + int(m) * 60 + float(sec)
            if len(parts) == 2:
                m, sec = parts
                return int(m) * 60 + float(sec)
        return float(s)
    except (ValueError, TypeError):
        return None


def format_time_tag(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}h{m:02d}m{s:02d}s"
    return f"{m:02d}m{s:02d}s"


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f} 秒"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes} 分 {secs:.2f} 秒 ({seconds:.2f} 秒)"


def is_ellipsis_only(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return bool(compact) and bool(ELLIPSIS_ONLY_RE.fullmatch(compact))


def remove_ellipsis_only_cues(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    return [cue for cue in cues if not is_ellipsis_only(cue.text)]


def parse_srt_timestamp(value: str) -> float:
    time_part, millis_part = re.split(r"[,.]", value.strip(), maxsplit=1)
    hours, minutes, seconds = (int(part) for part in time_part.split(":"))
    millis = int((millis_part + "000")[:3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def srt_to_cues(srt_text: str) -> list[SubtitleCue]:
    """健壮的 SRT 解析器：精准前瞻识别序号行，彻底杜绝序号渗入字幕正文。"""
    normalized = srt_text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    # 过滤纯空白行，仅保留有内容的文本行
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    
    cues: list[SubtitleCue] = []
    curr_start: float | None = None
    curr_end: float | None = None
    curr_text_lines: list[str] = []

    total_lines = len(lines)
    for i, line in enumerate(lines):
        match = SRT_TIME_LINE_RE.match(line)
        if match:
            # 遇到新的时间轴行，先把上一条字幕保存入库
            if curr_start is not None and curr_end is not None:
                text_content = "\n".join(curr_text_lines).strip()
                if text_content:
                    cues.append(SubtitleCue(curr_start, curr_end, text_content))
            curr_start = parse_srt_timestamp(match.group("start"))
            curr_end = parse_srt_timestamp(match.group("end"))
            curr_text_lines = []
            continue

        # 核心修复：当前行是纯数字，且下一行紧接着是时间轴时，才判定为序号行跳过
        if line.isdigit() and i + 1 < total_lines and SRT_TIME_LINE_RE.match(lines[i + 1]):
            continue

        # 收集真正的字幕文本
        if curr_start is not None:
            curr_text_lines.append(line)

    # 收尾保存最后一条字幕
    if curr_start is not None and curr_end is not None:
        text_content = "\n".join(curr_text_lines).strip()
        if text_content:
            cues.append(SubtitleCue(curr_start, curr_end, text_content))

    return cues


def strip_webvtt(text: str) -> str:
    """去掉 WEBVTT 头与 NOTE / STYLE / REGION 块，只留 cue 正文。

    VTT 的时间戳格式与 SRT 兼容（解析器同时认 `.` 和 `,`），所以去掉元数据后
    可以直接复用 ``srt_to_cues()``。这些块都是「块头一行 + 可选正文 + 空行」，
    遇到空行就结束跳过，不能整段吞掉后面的字幕。
    """
    body: list[str] = []
    skipping = False
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if stripped.upper().startswith("WEBVTT"):
            continue
        if stripped.upper().startswith(("NOTE", "STYLE", "REGION")):
            skipping = True
            continue
        if skipping:
            if not stripped:
                skipping = False
            continue
        body.append(line)
    return "\n".join(body)


def cues_from_subtitle_file(path: str | Path) -> list[SubtitleCue]:
    """读取本地 .srt / .vtt 并解析成 cue；文件读失败会抛 ``OSError``。

    原文轨与译文轨导入共用这一个解析入口，避免两个接口的 VTT 处理悄悄分叉。
    """
    file = Path(path)
    text = file.read_text(encoding="utf-8-sig", errors="replace")
    if file.suffix.lower() == ".vtt":
        text = strip_webvtt(text)
    return srt_to_cues(text)


def align_translation_texts(
    base_cues: list[SubtitleCue],
    incoming: list[SubtitleCue],
) -> list[str] | None:
    """把译文 cue 逐条对到原文时间轴上，返回与原文等长的文本数组。

    - 条数相同时直接按顺序对齐（机器翻译常见：只换文本，时间轴不动）。
    - 条数不同时按时间重叠匹配：导出的「仅译文」SRT 会跳过空译文，
      条数天然少于原文；按区间挂回去，空条保留空串，不丢中间位置。
    - 有任何一条挂不上、或两条译文抢同一原文时返回 ``None``（整批拒绝）。
    """
    if len(base_cues) == len(incoming):
        return [cue.text.strip() for cue in incoming]
    if not incoming:
        return None

    out = [""] * len(base_cues)
    used: set[int] = set()
    for cue in incoming:
        best = -1
        best_key: tuple[float, float] | None = None
        for index, base in enumerate(base_cues):
            if index in used:
                continue
            overlap = min(cue.end, base.end) - max(cue.start, base.start)
            if overlap <= 0:
                continue
            key = (overlap, -abs(cue.start - base.start))
            if best_key is None or key > best_key:
                best = index
                best_key = key
        if best < 0:
            return None
        used.add(best)
        out[best] = cue.text.strip()
    return out


def split_multiline_cues(cues: list[SubtitleCue]) -> tuple[list[SubtitleCue], int]:
    """把「一条 cue 多行」拆成「每个非空行一条」，时间轴完全相同。

    用于导入**旧版双语交付文件**：旧导出把原文/译文塞进同一条 cue（两行），
    ``srt_to_cues()`` 读回来是一段带 ``\\n`` 的文本，核对台会把它挤成一行。
    拆开后每条都是单行，与官方双语 SRT（同时间轴日/中两条）的表现一致。

    返回 ``(cues, 被拆分的条数)``；单行 cue 原样保留（含首尾空白的清理）。
    """
    out: list[SubtitleCue] = []
    exploded = 0
    for cue in cues:
        lines = [line.strip() for line in str(cue.text or "").splitlines()]
        lines = [line for line in lines if line]
        if len(lines) <= 1:
            out.append(SubtitleCue(cue.start, cue.end, lines[0] if lines else ""))
            continue
        exploded += 1
        out.extend(SubtitleCue(cue.start, cue.end, line) for line in lines)
    return out, exploded


def format_srt_timestamp(seconds: float) -> str:
    """秒 → SRT 时间戳。

    先把整段换算成毫秒再分解，避免 `59.9996` 这类值被四舍五入成
    `00:00:60,000`（旧实现只给秒 +1，没有处理分/时进位）。
    """
    total_ms = int(round(max(0.0, float(seconds)) * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_vtt_timestamp(seconds: float) -> str:
    return format_srt_timestamp(seconds).replace(",", ".")


def cues_to_srt(cues: list[SubtitleCue]) -> str:
    lines: list[str] = []
    for i, cue in enumerate(cues, start=1):
        lines.append(str(i))
        lines.append(f"{format_srt_timestamp(cue.start)} --> {format_srt_timestamp(cue.end)}")
        lines.append(cue.text.strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def cues_to_vtt(cues: list[SubtitleCue]) -> str:
    lines = ["WEBVTT", ""]
    for cue in cues:
        lines.append(f"{format_vtt_timestamp(cue.start)} --> {format_vtt_timestamp(cue.end)}")
        lines.append(cue.text.strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def cues_to_txt(cues: list[SubtitleCue]) -> str:
    return "\n".join(cue.text.strip() for cue in cues if cue.text.strip()) + "\n"
