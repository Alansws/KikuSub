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


def stale_indices(
    cues: list[SubtitleCue],
    base: list[str],
    texts: list[str] | None = None,
) -> list[int]:
    """哪些下标的译文已经不能信了（原文变了 / 条目被删掉）。

    ``base`` 是生成译文时的原文快照。删一条会让它后面的下标整体错位，
    于是后面的条目全部变 stale——这是**如实反映**，不是 bug：译文确实对不上了。

    传了 ``texts`` 时，**空译文算「待译」不算「过期」**（2026-11-25）：局部转写
    新增的那一条还没有译文，不该被算进「原文改过」的同一堆提示里。
    只动句读的改动已经在写 base 时就对齐了（:func:`rebase_punctuation_base`）。
    """
    stale: list[int] = []
    for index, cue in enumerate(cues):
        if texts is not None:
            text = str(texts[index]) if index < len(texts) else ""
            if not text.strip():
                continue
        if index >= len(base) or base[index] != cue.text:
            stale.append(index)
    return stale


def pending_indices(cues: list[SubtitleCue], texts: list[str] | None) -> list[int]:
    """还没有译文的条目（「待译」）。与 stale 分开计数，界面给不同提示。"""
    if not texts:
        return list(range(len(cues)))
    return [
        index
        for index in range(len(cues))
        if not str(texts[index] if index < len(texts) else "").strip()
    ]


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


def merge_translation_texts(
    source_texts: list[str],
    texts: list[str] | None,
    base: list[str] | None,
    updates: dict[int, str],
    *,
    skip_empty: bool = True,
    sync_unchanged_base: bool = True,
) -> tuple[list[str], list[str], list[int], int]:
    """把若干条新译文合并进一条整片轨（**纯函数**，不读会话）。

    为什么需要：整轨替换会把不在本次范围内的槽位一起写掉。补译（只回填几条）、
    局部应用（只写本段）、批量替换（只写改过的）都需要「其余条目原样保留」，
    所以合并口径必须只有一份实现。

    参数：

    - ``source_texts``：当前原文（逐条）；``texts`` / ``base`` 是现有轨，``None``
      或条数对不上时按「整轨重建」处理（范围外为空位）；
    - ``updates``：本次要写的 ``{下标(0 基): 文本}``；
    - ``skip_empty``：空文本是否算「本次没有提供译文」。**提案应用 / 补译**为
      ``True``——模型把两条合并成一条时，被合并槽位的 ``after`` 是空串，绝不能
      用它清掉用户已经核对过的译文；**整轨替换**为 ``False``（每一格都是用户给的
      最终值，允许清空）；
    - ``sync_unchanged_base``：文本没变时是否也把 ``base`` 对齐到当前原文。
      模型 / 用户明确写入了这一条，就该算「已同步」；批量替换只改文本、不该借机
      把整条轨的「原文已改」标记抹掉，所以那条路传 ``False``。

    返回 ``(新 texts, 新 base, 文本真正变化的 0 基下标, 因空值被保留的条数)``。
    """
    total = len(source_texts)
    aligned = texts is not None and len(texts) == total
    if aligned:
        out_texts = [str(item or "") for item in texts]
        out_base = [str(item or "") for item in (base or [])]
        if len(out_base) < total:
            out_base.extend(source_texts[len(out_base) :])
        out_base = out_base[:total]
    else:
        out_texts = [""] * total
        out_base = list(source_texts)

    changed: list[int] = []
    kept = 0
    for index, raw in sorted(updates.items()):
        if not isinstance(index, int) or not 0 <= index < total:
            continue
        value = str(raw or "")
        if skip_empty and not value.strip():
            if out_texts[index].strip():
                kept += 1
            continue
        previous = out_texts[index]
        out_texts[index] = value
        if value != previous:
            changed.append(index)
        if value and (sync_unchanged_base or value != previous):
            out_base[index] = source_texts[index]
    return out_texts, out_base, changed, kept


def remap_track(
    old_cues: list[SubtitleCue],
    new_cues: list[SubtitleCue],
    texts: list[str],
    base: list[str],
) -> tuple[list[str], list[str], dict[str, int]]:
    """把一条译文轨从旧字幕表映射到新字幕表（局部转写后不丢译文）。

    为什么需要：``转写选区`` / ``重转此句`` 会换掉区间内的旧字幕。条数一变，
    "逐条对齐"的旧轨就整体作废；直接丢弃等于一次局部修正把整片译文删光
    （2026-11-25 用户实测：219 条译文被 1 条新句顶掉）。

    匹配顺序（宁可标成「原文已改」，也不把 A 句的译文塞给 B 句）：

    1. **整条相同**（起止 + 文本都一致）：原样搬走译文与 base，最常见；
    2. 剩下的按时间重叠 1:1 配对：搬走译文、**保留旧 base**——原文变了但译文还在，
       界面会如实标成「原文已改」，用户自己决定要不要改；
    3. 其余新条目留空（empty text）→ 界面显示「待译」；
    4. 没配上的旧条目直接丢弃。

    返回 ``(新 texts, 新 base, 统计)``；统计键：``kept`` / ``moved`` / ``blank`` /
    ``dropped``。纯函数，不读会话。
    """
    from collections import deque

    out_texts = ["" for _ in new_cues]
    out_base = [cue.text for cue in new_cues]

    def key(cue: SubtitleCue) -> tuple[float, float, str]:
        return (round(float(cue.start), 3), round(float(cue.end), 3), cue.text)

    by_key: dict[tuple[float, float, str], deque[int]] = {}
    for index, cue in enumerate(old_cues):
        by_key.setdefault(key(cue), deque()).append(index)

    matched_old: set[int] = set()
    matched_new: set[int] = set()
    stats = {"kept": 0, "moved": 0, "blank": 0, "dropped": 0}

    for new_index, cue in enumerate(new_cues):
        bucket = by_key.get(key(cue))
        if not bucket:
            continue
        old_index = bucket.popleft()
        matched_old.add(old_index)
        matched_new.add(new_index)
        out_texts[new_index] = str(texts[old_index]) if old_index < len(texts) else ""
        out_base[new_index] = str(base[old_index]) if old_index < len(base) else cue.text
        stats["kept"] += 1

    # 第二步：时间重叠配对（文本 / 边界被重转改写的那几条）
    for new_index, cue in enumerate(new_cues):
        if new_index in matched_new:
            continue
        best_old = -1
        best_overlap = 0.0
        for old_index, old in enumerate(old_cues):
            if old_index in matched_old:
                continue
            overlap = min(float(cue.end), float(old.end)) - max(
                float(cue.start), float(old.start)
            )
            if overlap > best_overlap:
                best_overlap = overlap
                best_old = old_index
        if best_old < 0 or best_overlap <= 0.0:
            stats["blank"] += 1
            continue
        matched_old.add(best_old)
        matched_new.add(new_index)
        out_texts[new_index] = str(texts[best_old]) if best_old < len(texts) else ""
        out_base[new_index] = str(base[best_old]) if best_old < len(base) else cue.text
        stats["moved"] += 1

    stats["dropped"] = len(old_cues) - len(matched_old)
    return out_texts, out_base, stats
