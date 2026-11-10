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

@dataclass
class SubtitleCue:
    start: float
    end: float
    text: str


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
