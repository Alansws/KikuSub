"""把模型回吐的 SRT 对齐成提案 items —— 手工粘贴通道的共用层。

`core.ai_translate.proposal_from_srt` 与 `core.ai_polish.proposal_from_srt` 原本是两份
近乎逐行相同的实现，差异只有三处：kind、`note` 文案、"漏翻/漏改"这个措辞。
解析、条数校验、按顺序对齐、时间戳漂移告警这些**必须只有一份实现**，否则改一处就分叉
（见 docs/contracts/engineering-practice.md「重复实现」）。

契约（两条通道共用，改之前先读）：

- 润色（1:1）条数必须与当前字幕一致，否则整批拒绝（模型合并/漏翻都会在这里被抓住）；
- 只按**顺序**取文本，丢弃它给的序号与时间戳；时间轴永远来自 `cues`（D-1 不破）；
- 时间戳偏差 > 1s 的条数超过 0 时给一条 warning（多半是模型改写了时间轴）。

## 译文的时间轴对齐（2026-11-20 新增）

翻译允许模型把相邻两句合并成一条，所以条数可以比原批少。严格模式关闭时走
`align_translation_cues()`：按**时间戳区间交集**把粘贴的每条译文映射到原批次槽位。

- 一条译文覆盖原句 #5、#6 → 译文写入 #5，#6 置空并标 `merged`（合并覆盖）；
- 之后的译文从 #7 起继续严格对齐（游标只前进，不会回头补空位造成错行）；
- 起止任一端与原文偏差 > `TRANSLATION_DRIFT_TOLERANCE` 时标 `drift`；
- 粘贴条目整条落在本批时间窗之外 → 不写入，计入 `out_of_range` 并高亮提示；
- 没有匹配到译文的原句 → 槽位留空并标 `missing`。

这条通道**只适用于带时间轴的 SRT**。纯文本没有时间轴，仍然整批拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import ai_client as client
from .subtitles import srt_to_cues

#: 时间戳偏差超过这个秒数就计入 warning（模型改写时间轴的典型征兆）。
DRIFT_TOLERANCE = 1.0
#: 译文时间轴对齐的阈值：起止任一端的偏差超过它就高亮「时间戳对不上」。
TRANSLATION_DRIFT_TOLERANCE = 0.5
#: 一条译文最多能吞掉多少条原句；超出部分不合并（防止整段译文覆盖半批）。
MAX_MERGE_SPAN = 8


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


# --------------------------------------------------------------------------- 译文对齐


@dataclass
class TranslationAlignment:
    """一次时间轴对齐的结果：每个原句槽位的译文 + 状态。"""

    #: 与原批次 cues 等长；未匹配 / 被合并覆盖的槽位是空串。
    texts: list[str] = field(default_factory=list)
    #: 每行状态（1 基是**本段内**序号，调用方再加全片偏移）。
    rows: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict = field(default_factory=dict)

    def shifted_rows(self, offset: int) -> list[dict]:
        """把本段内 1 基序号平移到全片序号（提案 items 的坐标系）。"""
        out: list[dict] = []
        for row in self.rows:
            item = dict(row)
            item["i"] = int(row["i"]) + int(offset)
            if item.get("merged_into") is not None:
                item["merged_into"] = int(item["merged_into"]) + int(offset)
            if item.get("merged_to") is not None:
                item["merged_to"] = int(item["merged_to"]) + int(offset)
            out.append(item)
        return out


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return min(a_end, b_end) - max(a_start, b_start)


def align_translation_cues(parsed, cues) -> TranslationAlignment:
    """按时间戳区间交集把粘贴的译文映射到原批次槽位（纯函数）。

    ``parsed`` 是贴回来的 SRT 条目（保留模型给的时间轴），``cues`` 是原批次。
    算法只有一条主循环、一个只前进的游标：

    1. 整条落在本批时间窗之外的译文跳过，计入 ``out_of_range``；
    2. 与游标之后若干条原句有交集 → 写入第一条，其后的交集条目置空并标合并，
       游标移到最后一个交集条目之后；
    3. 没有交集但仍在时间窗内 → 按游标顺序挂到下一条未占用原句，标 drift；
    4. 循环结束后仍未占用的原句 → 空槽 + ``missing``。
    """
    n = len(cues)
    texts = ["" for _ in range(n)]
    states = ["missing" for _ in range(n)]
    drift = [0.0 for _ in range(n)]
    merged_into: list[int | None] = [None for _ in range(n)]
    merged_to: list[int | None] = [None for _ in range(n)]
    cursor = 0
    out_of_range = 0
    ambiguous = 0

    if n:
        batch_start = cues[0].start
        batch_end = cues[-1].end
    else:
        batch_start = batch_end = 0.0

    for got in parsed:
        text = got.text.strip()
        # 明显在批次时间窗之外（允许半个阈值以内的贴边）：不写入。
        if n and (
            got.end < batch_start - TRANSLATION_DRIFT_TOLERANCE
            or got.start > batch_end + TRANSLATION_DRIFT_TOLERANCE
        ):
            out_of_range += 1
            continue

        overlaps = [
            index
            for index in range(cursor, n)
            if _overlap(got.start, got.end, cues[index].start, cues[index].end) > 0
        ]
        if overlaps:
            first, last = overlaps[0], overlaps[-1]
            if last - first + 1 > MAX_MERGE_SPAN:
                last = first + MAX_MERGE_SPAN - 1
                ambiguous += 1
            texts[first] = text
            states[first] = "merged" if last > first else "ok"
            merged_to[first] = last if last > first else None
            drift[first] = max(
                abs(got.start - cues[first].start), abs(got.end - cues[last].end)
            )
            for index in range(first + 1, last + 1):
                states[index] = "merged"
                merged_into[index] = first
                drift[index] = drift[first]
            cursor = last + 1
            continue

        # 没有交集：仍在时间窗内（模型轻微挪了时间码），按顺序挂到下一个槽位。
        if cursor >= n:
            out_of_range += 1
            continue
        index = cursor
        for probe in range(cursor, n):
            if cues[probe].end > got.start - 0.001:
                index = probe
                break
        else:
            index = n - 1
        texts[index] = text
        states[index] = "ok"
        drift[index] = max(abs(got.start - cues[index].start), abs(got.end - cues[index].end))
        cursor = index + 1

    rows: list[dict] = []
    drift_rows = 0
    missing_rows = 0
    merged_rows = 0
    for index in range(n):
        state = states[index]
        row_drift = round(drift[index], 3)
        if row_drift > TRANSLATION_DRIFT_TOLERANCE:
            drift_rows += 1
        if state == "merged":
            merged_rows += 1
            if merged_into[index] is not None:
                label = f"并入第 {merged_into[index] + 1} 条的译文（本槽位置空）"
            else:
                last = merged_to[index]
                label = (
                    f"一条译文合并覆盖第 {index + 1}–{last + 1} 条"
                    if last is not None and last > index
                    else "已按时间轴对齐"
                )
        elif state == "missing":
            missing_rows += 1
            label = "没有匹配到译文（保持空位）"
        else:
            label = "已按时间轴对齐"
        if row_drift > TRANSLATION_DRIFT_TOLERANCE:
            label = f"{label}；时间戳偏差 {row_drift:.1f}s"
        rows.append(
            {
                "i": index + 1,
                "state": state,
                "text": texts[index],
                "drift": row_drift,
                "label": label,
                "merged_into": merged_into[index] + 1 if merged_into[index] is not None else None,
                "merged_to": merged_to[index] + 1 if merged_to[index] is not None else None,
            }
        )

    counts = {
        "ok": sum(1 for state in states if state == "ok"),
        "merged": merged_rows,
        "missing": missing_rows,
        "drift": drift_rows,
        "out_of_range": out_of_range,
    }
    warnings: list[str] = []
    if out_of_range:
        warnings.append(
            f"有 {out_of_range} 条粘贴内容落在本批次时间范围外，未写入；"
            "如果整段都贴错，请检查复制提示词时的范围"
        )
    if missing_rows:
        warnings.append(f"{missing_rows} 条原句没有匹配到译文，槽位保持空位（不写原文占位）")
    if merged_rows:
        warnings.append(
            f"{merged_rows} 个槽位涉及合并覆盖：一条译文跨多句时只写第一条，其余置空"
        )
    if drift_rows:
        warnings.append(
            f"{drift_rows} 条译文的时间戳与原文偏差超过 {TRANSLATION_DRIFT_TOLERANCE:.1f}s"
            "（已按时间轴对齐，时间轴仍用原文）"
        )
    if ambiguous:
        warnings.append(
            f"{ambiguous} 条译文覆盖的原句超过 {MAX_MERGE_SPAN} 条，已截断到上限"
        )
    return TranslationAlignment(texts=texts, rows=rows, warnings=warnings, counts=counts)


def align_translation_srt(srt_text: str, cues) -> TranslationAlignment:
    """``align_translation_cues`` 的 SRT 入口；解析失败整批拒绝。"""
    parsed = srt_to_cues(srt_text or "")
    if not parsed:
        raise client.AiError(
            "没有从粘贴内容里解析到带时间轴的字幕：确认贴的是完整 SRT（含序号与时间戳）"
        )
    return align_translation_cues(parsed, cues)
