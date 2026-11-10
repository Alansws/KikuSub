"""双语字幕的构造（无 UI / 无网络依赖）。

为什么双语是**一条 cue 两行**而不是"同区间两条 cue"（开发文档 D-4）：

- 播放器兼容性最好，`srt_to_cues()` 也能原样读回成一条带 ``\\n`` 的 cue；
- 核对台的画面字幕叠加层本来就按 ``(start, end)`` 聚合多行，喂两行即可，不用新增机制。

导出与显示**必须共用这里**的实现，不允许两处各写一遍。
"""

from __future__ import annotations

from .subtitles import SubtitleCue


def _text_at(texts: list[str], index: int) -> str:
    if 0 <= index < len(texts):
        return str(texts[index] or "").strip()
    return ""


def bilingual_cues(cues: list[SubtitleCue], texts: list[str]) -> list[SubtitleCue]:
    """原文在上、译文在下；译文缺失的条目退化成单行，不产出空行。"""
    out: list[SubtitleCue] = []
    for index, cue in enumerate(cues):
        source = cue.text.strip()
        target = _text_at(texts, index)
        out.append(
            SubtitleCue(
                start=cue.start,
                end=cue.end,
                text=f"{source}\n{target}" if target else source,
            )
        )
    return out


def target_cues(cues: list[SubtitleCue], texts: list[str]) -> tuple[list[SubtitleCue], int]:
    """只要译文。返回 ``(cues, 被跳过的空条目数)``。

    空译文**直接跳过**而不是回退成原文：混着两种语言的交付文件比少几条更难发现。
    """
    out: list[SubtitleCue] = []
    skipped = 0
    for index, cue in enumerate(cues):
        target = _text_at(texts, index)
        if not target:
            skipped += 1
            continue
        out.append(SubtitleCue(start=cue.start, end=cue.end, text=target))
    return out, skipped


def stale_indices(cues: list[SubtitleCue], base: list[str]) -> list[int]:
    """哪些下标的译文已经不能信了（原文变了 / 条目被删掉）。

    ``base`` 是生成译文时的原文快照。删一条会让它后面的下标整体错位，
    于是后面的条目全部变 stale——这是**如实反映**，不是 bug：译文确实对不上了。
    """
    stale: list[int] = []
    for index, cue in enumerate(cues):
        if index >= len(base) or base[index] != cue.text:
            stale.append(index)
    return stale
