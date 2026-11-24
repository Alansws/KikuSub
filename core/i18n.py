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


# ---------------------------------------------------------------------------
# 「只动了句读」的原文改动
#
# 批量清理标点只删 / 换 句读与空白，不碰任何字。如果拿这种改动去算 stale，整条
# 译文轨会一夜之间全是「原文已改」——用户看着几十条其实没问题的提示，只会不再
# 相信这个提示（2026-11-25 用户报障）。所以「标点等价」必须单独识别。
#
# 字符集与桌面端 `lib/punctuation.ts` 的清理集合保持一致：只有这里列出的符号
# 与空白不算语义；加字、删字、改假名 / 汉字 / 数字一定会判定成「原文改过」。
# ---------------------------------------------------------------------------

PUNCT_NOISE = "、，。．｡､,.…⋯‥"


def punctuation_signature(text: str) -> str:
    """去掉句读与空白后的字符序列；两条文本相等 = 只动了标点。"""
    return "".join(
        ch for ch in str(text or "") if ch not in PUNCT_NOISE and not ch.isspace()
    )


def is_punctuation_only_change(old: str, new: str) -> bool:
    """``old`` → ``new`` 是否只是标点 / 空白的变化（内容一字未动）。"""
    if old == new:
        return False
    return punctuation_signature(old) == punctuation_signature(new)


def rebase_punctuation_base(cues: list[SubtitleCue], base: list[str]) -> tuple[list[str], list[int]]:
    """把「只动句读」的新原文同步进译文 base。

    返回 ``(新 base, 被对齐的下标)``。**纯函数**：调用方决定写回哪条轨。
    用途是让「清理标点」之后的译文保持「全部同步」，而不是整片标红。
    """
    out = list(base)
    rebased: list[int] = []
    for index, cue in enumerate(cues):
        if index >= len(out):
            break
        if is_punctuation_only_change(out[index], cue.text):
            out[index] = cue.text
            rebased.append(index)
    return out, rebased
