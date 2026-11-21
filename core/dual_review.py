"""双引擎复核的对齐与逐字 diff（纯函数，无 IO / 无模型）。

两个引擎对同一段音频的断句与时间轴不会逐条相同：同一句可能被拆成两条、
整体偏移 0.1–0.5 s、或者一边多/少几句。这里按**纯 1:1 逐条**配对：

- ``same``：时间对得上、文本也一致（``=``）；
- ``diff``：时间对得上、文本不同（``~``，带 ``char_ops`` 逐字 diff）；
- ``only_a``：只有主稿有（``−``，B 漏句）；
- ``only_b``：只有第二版有（``+``，A 漏句）。

关键设计（2026-11 修订）：

- **绝不把多条 A/B 合并成一行**。合并会在视觉上把对方多出来的行藏起来，
  83 条 A 与 89 条 B 看起来会像行数一样；逐条配对后必然满足
  ``a_count = paired + only_a``、``b_count = paired + only_b``。
- 一句被对方拆成两句时，只配其中一句，另一句以独立 ``+`` / ``−`` 行出现。
  这是刻意的：两个模型的断句本来就不同，复核页的任务是把差异如实摆出来，
  不是替用户合并句子。
- **每次都由当前两份字幕现算**，不持久化下标映射。

2026-11-21（界面重构 Step 2）起另有 ``ignore_punct``（默认 ``True``）：
只有标点 / 空白不同的行判为 ``same`` 并打 ``punct_only`` 标记，不再计入
``stats.diff`` 与徽标 ``stats.badge``——两个引擎的句读取舍不是听写分歧，
不滤掉会把真正要人听的分歧淹在几百条假阳性里。传 ``False`` 回到逐字严格比对。
"""

from __future__ import annotations

import difflib
import re

from .subtitles import SubtitleCue

#: 两个时间区间相隔多少秒以内仍视为「同一位置」（覆盖整体偏移 0.2s）。
GAP_TOLERANCE = 0.35
#: 时间几乎不重叠（只是相邻）时，文本相似度至少这么高才配对。
NEAR_SIMILARITY = 0.80
#: 有重叠但覆盖率很低时，文本相似度至少这么高才配对；否则按漏句处理。
LOW_OVERLAP_COVERAGE = 0.12
LOW_OVERLAP_SIMILARITY = 0.35

_WS_RE = re.compile(r"\s+")

#: ``ignore_punct=True``（默认）时**不计入文本差异**的字符：常见中日标点 + 空白。
#: 2026-11-21 起默认忽略：两个引擎对同一句话的标点取舍常常不同（句读、引号、省略号），
#: 那是排版分歧，不是听写分歧——不滤掉会把真正要人听的分歧淹在几百条假阳性里。
#:
#: 故意**不包含** ASCII 的 ``.`` / ``,`` / ``-`` / ``'``：它们会出现在数字、版本号与
#: 英文缩写里（``1.5`` vs ``15``、``1,000`` vs ``1000``），去掉等于把真差异藏起来。
IGNORED_PUNCT_CHARS = "、。，．…‥！？!?「」『』（）()【】〔〕：:；;·・“”‘’"
_IGNORED_PUNCT_RE = re.compile("[" + re.escape(IGNORED_PUNCT_CHARS) + "]")


def normalize_text(text: str) -> str:
    """相似度比较用：去掉所有空白，转小写。不改原始文本。"""
    return _WS_RE.sub("", str(text or "")).lower()


def compare_key(text: str, *, ignore_punct: bool = True) -> str:
    """「算不算同一句话」用的归一化。

    ``ignore_punct`` 为真（默认）时在 :func:`normalize_text` 之上再去掉
    :data:`IGNORED_PUNCT_CHARS` 里的标点；假时与 ``normalize_text`` 等价。
    只影响 ``same`` / ``diff`` 的判定，**不改**配对（时间对齐）与逐字 diff 的文本。
    """
    key = normalize_text(text)
    return _IGNORED_PUNCT_RE.sub("", key) if ignore_punct else key



def text_similarity(a: str, b: str) -> float:
    left, right = normalize_text(a), normalize_text(b)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return difflib.SequenceMatcher(None, left, right, autojunk=False).ratio()


def char_ops(a: str, b: str) -> list[dict]:
    """逐字 diff：``eq`` 相同 / ``del`` 只在 A / ``ins`` 只在 B。

    ``replace`` 会被拆成一段 ``del`` + 一段 ``ins``，前端据此分别标红/标绿。
    """
    left, right = str(a or ""), str(b or "")
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
    ops: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            if i2 > i1:
                ops.append({"op": "eq", "text": left[i1:i2]})
            continue
        if tag in ("replace", "delete") and i2 > i1:
            ops.append({"op": "del", "text": left[i1:i2]})
        if tag in ("replace", "insert") and j2 > j1:
            ops.append({"op": "ins", "text": right[j1:j2]})
    return ops


def _overlap(a: SubtitleCue, b: SubtitleCue) -> float:
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def _row(
    a_cue: SubtitleCue | None,
    b_cue: SubtitleCue | None,
    kind: str,
    ratio: float,
    *,
    a_index: int | None = None,
    b_index: int | None = None,
) -> dict:
    a_text = a_cue.text if a_cue is not None else ""
    b_text = b_cue.text if b_cue is not None else ""
    if a_cue is not None and b_cue is not None:
        start, end = a_cue.start, a_cue.end
    elif a_cue is not None:
        start, end = a_cue.start, a_cue.end
    else:
        assert b_cue is not None
        start, end = b_cue.start, b_cue.end
    row = {
        "kind": kind,
        "a_indices": [] if a_index is None else [a_index],
        "b_indices": [] if b_index is None else [b_index],
        "a_text": a_text,
        "b_text": b_text,
        "start": round(start, 3),
        "end": round(end, 3),
        "a_start": round(a_cue.start, 3) if a_cue is not None else None,
        "a_end": round(a_cue.end, 3) if a_cue is not None else None,
        "b_start": round(b_cue.start, 3) if b_cue is not None else None,
        "b_end": round(b_cue.end, 3) if b_cue is not None else None,
        "ratio": round(float(ratio), 4),
    }
    if kind == "diff":
        row["char_ops"] = char_ops(a_text, b_text)
    return row


def _pair_ok(a: SubtitleCue, b: SubtitleCue, gap: float) -> bool:
    """判断这一对 A/B 是否真的应该配成一行。

    - 有明显时间重叠：默认配对（同一位置的稿子，即使识别得完全不同）；
      只有「几乎只是擦边」且文本又完全不像时，才判为两条独立句子。
    - 不重叠：只有在 ``gap`` 容差内且文本几乎一致时才配对（覆盖整体偏移）。
    """
    overlap = _overlap(a, b)
    similarity = text_similarity(a.text, b.text)
    if overlap > 0:
        shorter = max(0.001, min(a.end - a.start, b.end - b.start))
        coverage = min(1.0, overlap / shorter)
        return coverage >= LOW_OVERLAP_COVERAGE or similarity >= LOW_OVERLAP_SIMILARITY
    if a.end <= b.start:
        return (b.start - a.end) <= gap and similarity >= NEAR_SIMILARITY
    return (a.start - b.end) <= gap and similarity >= NEAR_SIMILARITY


def build_review(
    a_cues: list[SubtitleCue],
    b_cues: list[SubtitleCue],
    *,
    gap: float = GAP_TOLERANCE,
    ignore_punct: bool = True,
) -> dict:
    """逐条对齐两份字幕，返回 ``{"rows": [...], "stats": {...}}``。

    ``rows`` 里的 ``a_indices`` / ``b_indices`` 是 0 基、指向传入列表的下标；
    每条 row 最多一个 A 下标和一个 B 下标。

    ``ignore_punct=True``（默认）时，**只有标点 / 空白不同**的一对判为 ``same``，
    并在该行打 ``punct_only: True``：它们不计入 ``stats.diff``，也不计入徽标
    ``stats.badge``；``stats.punct_only`` 单独记下被忽略的行数，供界面说明
    「已忽略 N 处仅标点差异」。传 ``False`` 时回到逐字严格比对（标点也算差异）。
    """
    a = list(a_cues or [])
    b = list(b_cues or [])
    rows: list[dict] = []

    i = j = 0
    while i < len(a) or j < len(b):
        if i >= len(a):
            rows.append(_row(None, b[j], "only_b", 0.0, b_index=j))
            j += 1
            continue
        if j >= len(b):
            rows.append(_row(a[i], None, "only_a", 0.0, a_index=i))
            i += 1
            continue

        cur_a, cur_b = a[i], b[j]
        if _pair_ok(cur_a, cur_b, gap):
            ratio = text_similarity(cur_a.text, cur_b.text)
            same = compare_key(cur_a.text, ignore_punct=ignore_punct) == compare_key(
                cur_b.text, ignore_punct=ignore_punct
            )
            # 文本「真的不一样」，但去掉标点后一致 → 记 punct_only，界面可解释。
            punct_only = same and normalize_text(cur_a.text) != normalize_text(cur_b.text)
            row = _row(
                cur_a,
                cur_b,
                "same" if same else "diff",
                ratio,
                a_index=i,
                b_index=j,
            )
            if punct_only:
                row["punct_only"] = True
            rows.append(row)
            i += 1
            j += 1
            continue

        # 不配对：先输出时间更早的那一条，保证接下来还能继续尝试后面的组合。
        if cur_a.end <= cur_b.end:
            rows.append(_row(cur_a, None, "only_a", 0.0, a_index=i))
            i += 1
        else:
            rows.append(_row(None, cur_b, "only_b", 0.0, b_index=j))
            j += 1

    # 正常走法已经按时间顺序；按开始时间稳排一次，避免 only 行交错时乱序。
    rows.sort(key=lambda row: (row["start"], row["kind"]))

    paired = sum(1 for row in rows if row["kind"] in ("same", "diff"))
    only_a = sum(1 for row in rows if row["kind"] == "only_a")
    only_b = sum(1 for row in rows if row["kind"] == "only_b")
    diff = sum(1 for row in rows if row["kind"] == "diff")
    stats = {
        "total": len(rows),
        "paired": paired,
        "same": sum(1 for row in rows if row["kind"] == "same"),
        "diff": diff,
        "only_a": only_a,
        "only_b": only_b,
        "a_count": len(a),
        "b_count": len(b),
        # ``ignore_punct`` 滤掉的那部分：界面写「已忽略 N 处仅标点差异」用。
        "punct_only": sum(1 for row in rows if row.get("punct_only")),
        # 徽标只统计文本差异行（Q8）；+ / − 在页内单独展示。
        # 2026-11-21 起 ``diff`` 已排除「仅标点不同」，徽标跟着降。
        "badge": diff,
    }
    # 不变量：每一条 A/B 都必须落在「配对」或自己的独有行里，绝不被合并隐藏。
    assert stats["a_count"] == paired + only_a
    assert stats["b_count"] == paired + only_b
    return {"rows": rows, "stats": stats}
