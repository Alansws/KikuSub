"""双语字幕的两种排版（无 UI / 无网络依赖）。

这里有两个函数，用途必须分清（开发文档 D-4）：

- :func:`bilingual_cues`：**一条 cue 两行**（原文上、译文下）。给烧录/画面叠加层用：
  ffmpeg 的字幕精灵按 cue 取块，一条两行才能让两种语言在同一块里排版。
- :func:`bilingual_entries`：**每个语种一条独立 cue**，共享同一时间轴。给交付文件用：
  官方双语 SRT（如「诸神字幕组」）就是这种写法，播放器里自然叠成两行；
  重新导入核对台时每条都是单行，不会被挤成「日文 中文」一行。

导出字幕文件与烧录成片必须各自调用对应的函数，不允许两处各写一遍。
"""

from __future__ import annotations

from .subtitles import SubtitleCue


def _text_at(texts: list[str], index: int) -> str:
    if 0 <= index < len(texts):
        return str(texts[index] or "").strip()
    return ""


def bilingual_cues(cues: list[SubtitleCue], texts: list[str]) -> list[SubtitleCue]:
    """原文在上、译文在下；译文缺失的条目退化成单行，不产出空行。

    只给「一块画面里排两行」的场景用（烧录硬字幕、画面叠加层）。
    **字幕文件导出请用 :func:`bilingual_entries`。**
    """
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


def bilingual_entries(cues: list[SubtitleCue], texts: list[str]) -> list[SubtitleCue]:
    """交付文件用的双语排版：每个语种一条独立 cue，共享同一时间轴。

    与 :func:`bilingual_cues` 的区别见模块头。原文在前、译文在后；译文缺失的条目
    只写原文，绝不产出空行。重新导入时每条都是单行，核对台按 ``(start, end)``
    聚合回同一块，两种语言各占一行——和官方双语 SRT 的行为一致。
    """
    out: list[SubtitleCue] = []
    for index, cue in enumerate(cues):
        source = cue.text.strip()
        target = _text_at(texts, index)
        if source:
            out.append(SubtitleCue(start=cue.start, end=cue.end, text=source))
        if target:
            out.append(SubtitleCue(start=cue.start, end=cue.end, text=target))
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
