"""补译批次（gap fill）：只翻译 / 回填「待译」的那几条。

## 为什么不是提案

整轨翻译（``core/ai_translate``）是「把一段连续区间重翻一遍」：抽术语表、分块、
生成 digest、写提案文件，再由用户整版应用。补译要解决的场景完全不同（2026-11-25
用户工作流）：逐句核对完一章后只剩十几条没有译文（局部转写新加的行、或者人工删掉
的坏译文）。为了这十几条重翻整章，会把已经核对过的译文一起覆盖。

所以补译通道刻意**不走提案**：

- 输入是显式条号集合（``indices``），不是连续区间；
- 提示词只包含这些条目 + 每条前后若干条原文与邻居已有译文（仅参考）；
- 回填解析严格 1:1：按**序号**落位，条数兜底；不做时间轴对齐（那会猜错槽位）；
- 应用由 ``POST /api/translations/gap`` 只写显式下标，其余条目一个字节不动；
- 不落盘、不生成 ``proposal.json``、不改 CLI / 技能的提案契约。

## 两条解析顺序

1. 回复里的序号集合与请求**完全一致** → 按序号落位（最稳，模型按模板保留序号）；
2. 否则条数一致 → 按顺序落位并给一条 warning（模型把序号改写成 1~N 了）；
3. 条数不一致 → 整批拒绝，错误里指出缺了哪几条，绝不猜。

复制出去的 SRT 用**全片条号**当序号（不是 1~N），这样第 1 条规则能生效。
"""

from __future__ import annotations

import re

from .ai_proposal import source_digest
from .subtitles import SubtitleCue, format_srt_timestamp, parse_srt_entries

#: 一次补译最多多少条。超过它提示词会大到没有意义，也让「复制哪一章」失去焦点。
MAX_INDICES = 500
#: 上下文：每条待译句前后各取几条原文（与单句补译 ``ai_translate_cue`` 同一口径）。
NEIGHBOR = 4
#: 上下文总行数上限（几百条待译时不能让提示词爆炸）。
MAX_CONTEXT_LINES = 120
#: 单条译文的长度上限：超过它一定是模型把解释也写进来了。
MAX_OUT_CHARS = 300


class GapError(ValueError):
    """补译通道的用户可见错误；``status`` 直接作为 HTTP 状态码。"""

    def __init__(self, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.status = int(status)


def normalize_indices(raw: str | list[int] | tuple[int, ...] | None, total: int) -> list[int]:
    """把 ``"285,287,290"`` / ``[285, 287]`` 规范成升序、去重的全片 1 基条号。

    越界 / 非法一律 ``GapError``（422）：宁可拒绝，也不要拿一个错位的集合去
    复制或回填——那会把 A 句的译文写进 B 句。
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        parts: list[object] = [part for part in re.split(r"[,，\s]+", raw.strip()) if part]
    else:
        parts = list(raw)
    seen: set[int] = set()
    for part in parts:
        try:
            value = int(str(part).strip())
        except (TypeError, ValueError) as exc:
            raise GapError(f"条号不合法：{part!r}") from exc
        if not 1 <= value <= max(0, int(total)):
            raise GapError(f"条号越界：{value}（当前共 {total} 条）")
        seen.add(value)
    indices = sorted(seen)
    if len(indices) > MAX_INDICES:
        raise GapError(
            f"一次最多补译 {MAX_INDICES} 条（这次 {len(indices)} 条）；"
            "请按章节分批，或改用翻译页整段翻译"
        )
    return indices


def gap_srt(cues: list[SubtitleCue], indices: list[int]) -> str:
    """只含待译条目的 SRT，**序号用全片条号**（回填按它落位）。"""
    lines: list[str] = []
    for index in indices:
        cue = cues[index - 1]
        lines.append(str(index))
        lines.append(
            f"{format_srt_timestamp(cue.start)} --> {format_srt_timestamp(cue.end)}"
        )
        lines.append(cue.text.strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def gap_instructions(total: int, indices: list[int], scope_label: str = "") -> str:
    """提示词前置说明（走模板的 ``{{RANGE}}`` 注入口，用户模板不用改）。"""
    where = f"（{scope_label}）" if scope_label else ""
    return (
        f"【补译批次】本次只处理 {len(indices)} 条{where}：这些条目目前还没有译文。\n"
        f"请只输出下面字幕块里的这 {len(indices)} 条，一条不多、一条不少；\n"
        "序号保持原片条号不变（不要改成 1~N），时间戳原样保留；"
        "不要翻译、也不要重复文末的上下文块。"
    )


def _flat(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def context_block(
    cues: list[SubtitleCue],
    texts: list[str] | None,
    indices: list[int],
    neighbor: int = NEIGHBOR,
) -> str:
    """待译句的前后上下文（原文 + 邻居已有译文），纯文本、明确标注「仅参考」。

    为什么带邻居译文：用户已经逐句核对过的那些句子定义了称呼、语气词与专有名词的
    译法。补译只翻几条时，模型看不到它们就会把「前辈」翻成「学长」。
    """
    wanted = set(indices)
    picked: set[int] = set()
    order: list[int] = []
    for index in indices:
        low = max(1, index - neighbor)
        high = min(len(cues), index + neighbor)
        for cursor in range(low, high + 1):
            if cursor in wanted or cursor in picked:
                continue
            picked.add(cursor)
            order.append(cursor)
            if len(order) >= MAX_CONTEXT_LINES:
                break
        if len(order) >= MAX_CONTEXT_LINES:
            break
    if not order:
        return ""
    lines = ["【上下文（仅参考，不要翻译、不要出现在回答里）】"]
    for cursor in sorted(order):
        source = _flat(cues[cursor - 1].text)
        target = ""
        if texts and cursor - 1 < len(texts):
            target = _flat(texts[cursor - 1])
        lines.append(f"#{cursor}  {source}" + (f"  ｜译：{target}" if target else ""))
    return "\n".join(lines)


_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(.*?)\n```\s*$", re.DOTALL)


def _strip_fence(text: str) -> str:
    body = str(text or "").strip()
    match = _FENCE_RE.match(body)
    return match.group(1) if match else body


def parse_gap_reply(
    text: str, cues: list[SubtitleCue], indices: list[int]
) -> tuple[list[dict], list[str]]:
    """把外部模型返回的 SRT 变成 ``[{i, before, after}]``（严格 1:1）。

    返回的 ``items`` 是**唯一**可以被 ``/api/translations/gap`` 写入的集合；
    解析阶段的任何不确定都直接抛 :class:`GapError`，绝不产出半份回填。
    """
    if not indices:
        raise GapError("补译批次是空的：先点「复制待译」再粘贴回复")
    entries = parse_srt_entries(_strip_fence(text))
    if not entries:
        raise GapError("没有从粘贴内容里解析到字幕：确认贴的是完整 SRT（含序号与时间戳）")

    expected = list(indices)
    numbers = [index for index, _cue in entries]
    all_numbered = all(number is not None for number in numbers)
    got = {int(number) for number in numbers if number is not None}
    warnings: list[str] = []

    if all_numbered and len(numbers) == len(expected) and got == set(expected):
        # 1) 序号完全对得上：按序号落位（最稳）
        mapping = {
            int(number): entry_cue.text
            for number, (_index, entry_cue) in zip(numbers, entries)
        }
    elif len(entries) == len(expected):
        # 2) 条数对得上但序号被改写 / 没给序号：按顺序落位，并提示用户核对
        if all_numbered:
            warnings.append("回复的序号与请求不一致（已按顺序对位），请核对每行是否对得上")
        else:
            warnings.append("回复里没有序号（已按顺序对位），请核对每行是否对得上")
        mapping = {
            expected[position]: entry_cue.text
            for position, (_index, entry_cue) in enumerate(entries)
        }
    else:
        missing = sorted(set(expected) - got) if all_numbered else []
        extra = sorted(got - set(expected)) if all_numbered else []
        detail = []
        if missing:
            detail.append("缺少 " + "、".join(f"#{i}" for i in missing[:8]))
        if extra:
            detail.append("多出 " + "、".join(f"#{i}" for i in extra[:8]))
        hint = f"（{'；'.join(detail)}）" if detail else ""
        raise GapError(
            f"条数不符：期望 {len(expected)} 条，解析到 {len(entries)} 条{hint}。"
            "补译要求一条对一条：请让模型只输出这次要补的条目并保留序号"
        )

    items: list[dict] = []
    for index in expected:
        after = str(mapping.get(index) or "").strip()
        if not after:
            raise GapError(f"第 {index} 条的译文是空的：模型漏翻了这一条，请补上后重新粘贴")
        if len(after) > MAX_OUT_CHARS:
            raise GapError(
                f"第 {index} 条的译文异常长（{len(after)} 字）：像是模型把解释也贴进来了"
            )
        items.append({"i": index, "before": cues[index - 1].text, "after": after})
    return items, warnings


def digest_of(cues: list[SubtitleCue], indices: list[int]) -> str:
    """本次补译批次的源指纹：复制时给前端，回填时校验「原文没被改过」。"""
    return source_digest([cues[index - 1].text for index in indices])


def validate_gap_items(items: list[object], cues: list[SubtitleCue]) -> dict[int, str]:
    """校验回填请求里的每一条，返回 ``{0 基下标: 最终译文}``。

    ``before`` 必须与当前原文一致（复制之后原文改过 → 409）：这是「回填不覆盖
    已核对译文」里唯一能把 A 句译文塞进 B 句的缺口，必须堵死。
    """
    total = len(cues)
    if not items:
        raise GapError("补译批次是空的：先把外部模型返回的结果粘回来")
    if len(items) > total:
        raise GapError("补译条目数超过字幕总数")
    updates: dict[int, str] = {}
    for item in items:
        try:
            index = int(getattr(item, "i"))
        except (TypeError, ValueError) as exc:
            raise GapError("补译条目缺少条号") from exc
        if not 1 <= index <= total:
            raise GapError(f"条号越界：{index}（共 {total} 条）")
        if index - 1 in updates:
            raise GapError(f"条号重复：{index}")
        before = str(getattr(item, "before", "") or "")
        if before and before != cues[index - 1].text:
            raise GapError(
                f"第 {index} 条的原文已经改过，请重新复制提示词再补译", status=409
            )
        after = str(getattr(item, "after", "") or "")
        if not after.strip():
            raise GapError(f"第 {index} 条的译文是空的")
        updates[index - 1] = after
    return updates
