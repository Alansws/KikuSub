"""字幕条目列表的纯函数工具：类型归一化、排序去重、表格化。

从 `app.py` 原样搬出。这些是「数据结构 → 数据结构」的转换，既被旧界面用来渲染
`gr.Dataframe`，也被服务层用来拼 JSON，放 core 里两边共用一份。

两条不能改的行为约束（见 AGENTS.md §3）：

1. `_unique_sorted_cues` 对**时间区间完全相同**的条目（中日双语 SRT 的日/中两行）
   必须保留导入时的原始先后顺序，用原始下标做末位 tiebreak；否则双语行序会随
   字符编码随机翻转。
2. `_coerce_cues` 要能吃三种输入：`SubtitleCue`、`dict`、`list/tuple`（含
   `gr.Dataframe` 回传的「带行号列」四元组）。
"""

from __future__ import annotations

from .transcribe import SubtitleCue, format_srt_timestamp, parse_time_str


def _coerce_cues(raw_cues) -> list[SubtitleCue]:
    result: list[SubtitleCue] = []
    for cue in raw_cues or []:
        if isinstance(cue, SubtitleCue):
            result.append(cue)
        elif isinstance(cue, dict):
            try:
                result.append(SubtitleCue(float(cue["start"]), float(cue["end"]), str(cue.get("text", ""))))
            except (KeyError, TypeError, ValueError):
                continue
        elif isinstance(cue, (list, tuple)) and len(cue) >= 3:
            try:
                if len(cue) == 3:
                    s, e, t = cue
                elif len(cue) >= 4:
                    s, e, t = cue[1], cue[2], cue[-1]
                else:
                    continue
                s_val = parse_time_str(str(s)) if isinstance(s, str) else float(s)
                e_val = parse_time_str(str(e)) if isinstance(e, str) else float(e)
                if s_val is not None and e_val is not None:
                    result.append(SubtitleCue(s_val, e_val, str(t)))
            except (ValueError, TypeError):
                continue
    return result


def _unique_sorted_cues(raw_cues) -> list[SubtitleCue]:
    """按时间排序去重，同区间条目保持原始行序（双语字幕依赖这条）。"""
    seen: set[tuple[int, int, str]] = set()
    result: list[SubtitleCue] = []
    ordered = list(enumerate(_coerce_cues(raw_cues)))
    ordered.sort(key=lambda pair: (float(pair[1].start), float(pair[1].end), pair[0]))
    for _, cue in ordered:
        start = max(0.0, float(cue.start))
        end = max(start + 0.001, float(cue.end))
        text = cue.text.strip()
        if not text:
            continue
        key = (round(start * 1000), round(end * 1000), text)
        if key not in seen:
            seen.add(key)
            result.append(SubtitleCue(round(start, 3), round(end, 3), text))
    return result


def cues_to_table(cues: list[SubtitleCue]) -> list[list]:
    """转写结果表格：行号 / 起 / 止 / 文本。"""
    rows = []
    for i, c in enumerate(cues, start=1):
        rows.append([
            i,
            format_srt_timestamp(c.start),
            format_srt_timestamp(c.end),
            c.text.strip(),
        ])
    return rows


def review_cues_to_table(cues) -> list[list]:
    """核对台表格：行号 / 起 / 止 / 时长 / 文本（比转写结果多一列时长）。"""
    return [
        [i, format_srt_timestamp(cue.start), format_srt_timestamp(cue.end), f"{cue.end - cue.start:.2f}s", cue.text]
        for i, cue in enumerate(_unique_sorted_cues(cues), start=1)
    ]


def _cues_to_dicts(cues) -> list[dict]:
    return [{"start": c.start, "end": c.end, "text": c.text} for c in _unique_sorted_cues(cues)]
