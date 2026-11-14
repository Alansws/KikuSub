"""把「润色」拆成可重试的分块调用，并产出符合契约的提案。

**这个模块不认识 HTTP，也不认识 UI**：它只拿到文本列表 + `AiConfig`，返回
`proposal.json` 的 dict。真正的网络在 `core.ai_client`，落盘与任务进度在服务层。

三条硬约束（开发文档 §5.3）：

1. 送给模型的载荷里**没有时间码**，只有 `{i, text}`（D-1）。
2. 每块必须**列满本块全部条目**；少一条就整块失败重问，绝不拼一份缺条提案（D-6）。
3. 任何一块最终失败 → **整份提案不产出**，避免"半份提案"被误应用。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from . import ai_client as client
from . import ai_proposal as proposals

log = logging.getLogger(__name__)

# 单次任务最多打多少个请求。防止参数填错（比如块大小 20）时把额度跑光。
MAX_CHUNKS = 20

SYSTEM_PROMPT_DUAL = """你是日语影视字幕校对员。用户会给出同一段音频的两个引擎转写稿：
- A 是主稿（带序号与时间戳），也是**输出骨架**；
- B 是参考稿（带序号与时间戳），只用来核对 A 的错听、漏字与断句。

只修正 A 里「明显的识别错误」：同音字/近音字、助词、活用、断词、人名与术语、标点。
严禁：改写风格、增删/拆分/合并 A 的条目、把 B 的句子拼接或追加到 A、翻译、加解释。
必须为 A 的每一条都返回一条结果（没改也原样返回），i 使用 A 的全局序号。
只输出 JSON：{"items":[{"i":1,"text":"…","note":"…"}]}"""

SYSTEM_PROMPT = """你是日语影视字幕校对员。输入是一段已由 ASR 生成的日语字幕，按条给出。

只修正「明显的识别错误」：
- 同音字/近音字误识（例：きおう→気圧 属误识，需按上下文改回）
- 助词、活用、断词错误
- 人名、专有名词、作品内术语的一致性
- 标点与全角半角

严禁：
- 改写风格、润色措辞、替换更"自然"的说法
- 增删句子、合并或拆分条目
- 翻译、注释、加括号说明
- 改动条数

对每一条都必须返回一条结果（即使没改，原样返回），i 必须与输入一致。
note 用不超过 6 个字说明理由；未改动时 note 为空字符串。

只输出 JSON：{"items":[{"i":1,"text":"…","note":"…"}]}"""

# 第一次结构不合规时追加的提醒（只重问一次，不做更长的"哄模型"）
STRICT_HINT = """

上一轮输出不符合要求。注意：
- 必须为本次 items 里的每一条都返回一条结果，i 必须与输入完全一致
- 不要输出解释、不要用 markdown 围栏，只输出 JSON"""


class AiPolishCancelled(RuntimeError):
    """用户在分块之间取消了任务。"""


@dataclass
class Chunk:
    index: int  # 1 起
    start: int  # 0 起、含
    end: int    # 0 起、不含


def plan_chunks(total: int, chunk_cues: int) -> list[Chunk]:
    size = max(1, int(chunk_cues))
    chunks = [
        Chunk(index=i // size + 1, start=i, end=min(total, i + size))
        for i in range(0, total, size)
    ]
    return chunks


def srt_block(cues, indices: list[int] | None = None) -> str:
    """把一组 cue 渲染成带**全局序号**的 SRT（双源提示词用）。

    这里刻意保留原序号/时间戳：双源润色要求模型以 A 的序号与时间轴为骨架，
    序号被本地重排会直接导致回填错位。输出仍只取文本，时间轴永远来自我们的 cue。
    """
    from .subtitles import format_srt_timestamp

    picked = list(indices) if indices is not None else list(range(len(cues)))
    lines: list[str] = []
    for pos in picked:
        if not 0 <= pos < len(cues):
            continue
        cue = cues[pos]
        lines.append(
            f"{pos + 1}\n{format_srt_timestamp(cue.start)} --> {format_srt_timestamp(cue.end)}\n{cue.text}"
        )
    return "\n\n".join(lines)


def build_user_prompt(
    texts: list[str],
    chunk: Chunk,
    context_cues: int,
    lang: str = "ja",
    total_chunks: int = 1,
    *,
    srt_a: str = "",
    srt_b: str = "",
    range_hint: str = "",
    texts_b: list[str] | None = None,
) -> str:
    """组一块的 user 消息。上下文只读，不参与输出（`i` 用全局绝对序号）。

    单源路径的 JSON 形状保持不变（没有时间戳，见 D-1）。双源路径额外带
    ``subtitle_a`` / ``subtitle_b`` 两段**带时间戳**的参考稿——这是 Q9 的
    明确要求：模型需要时间对时间地看才能判断「B 的哪一句对应 A 的哪一句」。
    输出仍然只收文本，应用时间轴永远取自 A。
    """
    ctx = max(0, int(context_cues))
    if texts_b is not None or srt_a or srt_b:
        payload = {
            "chunk": chunk.index,
            "total": total_chunks,
            "lang": lang,
            "range": range_hint or f"第 {chunk.start + 1}–{chunk.end} 条",
            "subtitle_a": srt_a,
            "subtitle_b": srt_b,
            "items": [
                {"i": i + 1, "text": texts[i]} for i in range(chunk.start, chunk.end)
            ],
        }
        return json.dumps(payload, ensure_ascii=False)
    before = texts[max(0, chunk.start - ctx) : chunk.start]
    after = texts[chunk.end : chunk.end + ctx]
    payload = {
        "chunk": chunk.index,
        "total": total_chunks,
        "lang": lang,
        "context_before": before,
        "context_after": after,
        "items": [{"i": i + 1, "text": texts[i]} for i in range(chunk.start, chunk.end)],
    }
    return json.dumps(payload, ensure_ascii=False)


def collect_chunk(data: dict, chunk: Chunk) -> dict[int, dict]:
    """从一块的响应里取出 `i -> {text, note}`，并保证覆盖本块全部序号。"""
    items = data.get("items")
    if not isinstance(items, list):
        raise client.AiError(f"第 {chunk.index} 块：模型没有返回 items 数组")

    got: dict[int, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        idx = item.get("i")
        text = item.get("text")
        if isinstance(idx, int) and not isinstance(idx, bool) and isinstance(text, str):
            got[idx] = {
                "text": text,
                "note": str(item.get("note") or "")[:24],
            }

    expected = set(range(chunk.start + 1, chunk.end + 1))
    missing = sorted(expected - set(got))
    if missing:
        raise client.AiError(
            f"第 {chunk.index} 块缺少 {len(missing)} 条（如 #{missing[0]}）"
        )
    return {idx: got[idx] for idx in expected}


def _run_chunk(
    cfg: client.AiConfig,
    chunk: Chunk,
    texts: list[str],
    context_cues: int,
    lang: str,
    cancel,
    total_chunks: int = 1,
    *,
    dual: bool = False,
    srt_a: str = "",
    srt_b: str = "",
    range_hint: str = "",
) -> dict[int, dict]:
    """跑一块：结构不合规重问一次，仍不行就抛错（调用方整份放弃）。"""
    prompt = build_user_prompt(
        texts,
        chunk,
        context_cues,
        lang,
        total_chunks,
        srt_a=srt_a,
        srt_b=srt_b,
        range_hint=range_hint,
        texts_b=[] if dual else None,
    )
    system = SYSTEM_PROMPT_DUAL if dual else SYSTEM_PROMPT
    last: Exception | None = None
    for attempt in range(2):
        data = client.chat_json(
            cfg,
            system,
            prompt if attempt == 0 else prompt + STRICT_HINT,
            cancel=cancel,
        )
        try:
            return collect_chunk(data, chunk)
        except client.AiError as exc:
            last = exc
            log.warning("第 %d 块结构不合规（第 %d 次）：%s", chunk.index, attempt + 1, exc)
    raise last or client.AiError(f"第 {chunk.index} 块失败")


def dual_context_cues(cues_b, start_s: float, end_s: float, pad: float = 2.0) -> list[int]:
    """取 B 在 A 块时间窗 ``[start-pad, end+pad]`` 内的下标（Q9 的上下文口径）。"""
    if not cues_b:
        return []
    lo, hi = float(start_s) - float(pad), float(end_s) + float(pad)
    return [
        index
        for index, cue in enumerate(cues_b)
        if cue.end >= lo and cue.start <= hi
    ]


def run_polish(
    texts: list[str],
    cfg: client.AiConfig,
    *,
    chunk_cues: int = 200,
    context_cues: int = 5,
    lang: str = "ja",
    model: str = "",
    entry: str = "in-app",
    source_path: str = "",
    texts_b: list[str] | None = None,
    cues_a=None,
    cues_b=None,
    cancel=None,
    on_progress=None,
) -> tuple[dict, list[str]]:
    """逐块润色，返回 ``(提案 dict, 校验警告)``。

    双源（``texts_b`` 非空）时：每块仍以 A 的 **全局序号** 为骨架，``subtitle_b``
    只放 B 在 ``[t0-2s, t1+2s]`` 内的上下文；输出与单源完全同构
    （``{i, text}``），时间轴仍取自 A（D-1 不破）。

    失败语义：任何一块最终失败都抛异常，**不产出半份提案**。
    取消语义：分块之间检查令牌，抛 `AiPolishCancelled`，同样不产出。
    """
    if not texts:
        raise client.AiError("没有可润色的字幕")
    # B 的条数**不要求**与 A 相同：两个引擎的断句本来就不一样。A 决定输出
    # 序号与时间轴；B 只按时间窗提供参考上下文，可以多几句或少几句。
    dual = texts_b is not None
    chunks = plan_chunks(len(texts), chunk_cues)
    if len(chunks) > MAX_CHUNKS:
        raise client.AiError(
            f"分块太多（{len(chunks)} 块，上限 {MAX_CHUNKS}）：请把每块条数调大"
        )

    merged: dict[int, dict] = {}
    for pos, chunk in enumerate(chunks):
        if cancel is not None and cancel.is_set():
            raise AiPolishCancelled()
        if on_progress:
            on_progress(pos / len(chunks), f"第 {chunk.index}/{len(chunks)} 块")
        srt_a = srt_b = ""
        range_hint = ""
        if dual:
            a_slice = list(range(chunk.start, chunk.end))
            srt_a = srt_block(cues_a, a_slice) if cues_a is not None else ""
            b_indices: list[int] = []
            if cues_b:
                if cues_a is not None and len(cues_a) == len(texts):
                    t0 = cues_a[chunk.start].start
                    t1 = cues_a[chunk.end - 1].end
                    b_indices = dual_context_cues(cues_b, t0, t1)
                else:
                    b_indices = a_slice
                srt_b = srt_block(cues_b, b_indices)
            range_hint = (
                f"只处理第 {chunk.start + 1}–{chunk.end} 条（共 {len(texts)} 条），"
                "输出必须与这些序号逐条对应。"
            )
        merged.update(
            _run_chunk(
                cfg,
                chunk,
                texts,
                context_cues,
                lang,
                cancel,
                len(chunks),
                dual=dual,
                srt_a=srt_a,
                srt_b=srt_b,
                range_hint=range_hint,
            )
        )

    if on_progress:
        on_progress(1.0, "校验提案")

    items = [
        {
            "i": idx,
            "before": texts[idx - 1],
            "after": merged[idx]["text"],
            "note": merged[idx]["note"],
        }
        for idx in range(1, len(texts) + 1)
    ]

    proposal = proposals.build_proposal(
        kind="polish",
        src_lang=lang,
        texts=texts,
        items=items,
        model=model or cfg.model,
        entry=entry,
        chunks=len(chunks),
        source_path=source_path,
        texts_b=texts_b,
    )

    check = proposals.validate_proposal(proposal, texts, texts_b)
    if not check.ok:
        raise client.AiError("模型输出未通过校验：" + "；".join(check.errors[:3]))
    return proposal, check.warnings


# --------------------------------------------------------------------------- 手动通道
#
# 与翻译一样，没有 API Key / 想用网页版模型时：
#   「复制提示词」→ 粘到任意聊天窗 → 把模型回的 SRT 粘回来 → 解析成提案 → 同一套 diff。
# 差别只在提示词与校验类型：润色输出的是 corrected SRT，不是译文。


MANUAL_PROMPT = """你是日语影视字幕校对员。下面是带序号和时间戳的 SRT 字幕。

只修正明显的识别错误：
- 同音字/近音字误识
- 助词、活用、断词错误
- 人名、专有名词、作品内术语的一致性
- 标点与全角半角

严禁改写风格、润色措辞、增删句子、合并或拆分条目。
严格保留原 SRT 的序号和时间戳，只输出修正后的 SRT；不要解释、不要 markdown 代码块。
内容如下：
<subtitles>
__SRT__
</subtitles>"""


def build_manual_prompt(
    srt_text: str,
    *,
    srt_b: str = "",
    range_hint: str = "",
    dual: bool = False,
) -> str:
    """组润色手写通道的兜底提示词（提示词库不可用时才走这里）。

    ``srt_text`` 用与导出同一份 ``cues_to_srt``。双源时把 A/B 两段都带上，
    并明确「以 A 为骨架」。
    """
    if not dual:
        body = MANUAL_PROMPT.replace("__SRT__", (srt_text or "").strip())
        if range_hint:
            body = range_hint + "\n\n" + body
        return body
    hint = range_hint or "只输出与 A 逐条对应的修订后 SRT。"
    return (
        "你是日语影视字幕校对员。下面是同一段音频的两个引擎转写稿。\n"
        "请以 A 为主稿、参考 B 修正 A 的明显识别错误；不得增删、拆分、合并 A 的条目，"
        "禁止把 B 的句子拼接或追加到 A。\n"
        f"{hint}\n只输出修订后的 A SRT（序号沿用 A），不要解释、不要 markdown 代码块。\n\n"
        f"【A（主稿）】\n{srt_text or ''}\n\n【B（参考稿）】\n{srt_b or ''}"
    )


def proposal_from_srt(
    srt_text: str,
    cues,
    *,
    entry: str = "manual",
    from_index: int = 1,
    to_index: int | None = None,
    texts_b: list[str] | None = None,
) -> tuple[dict, list[str]]:
    """把模型回吐的修正版 SRT 变成 polish 提案。

    ``from_index`` / ``to_index`` 用于长片分段粘贴：只解析本段（1 基、含两端），
    其余条目原样保留，这样多段粘贴回来能合并成一份完整提案。

    与翻译通道同样只按**顺序**取文本，序号和时间戳一律丢弃；条数不一致整批拒绝。
    时间轴仍由 ``cues`` 提供（D-1 不破）。

    序号容错：外部模型可能输出全局序号（k..m）或本段相对序号（1..X）。这里
    只按顺序取文本，所以两种写法都能安全映射回 k..m；只要**条数**对得上。
    """
    from .proposal_srt import align_model_srt

    source_texts = [c.text for c in cues]
    total = len(source_texts)
    start = max(1, int(from_index or 1))
    end = total if to_index is None else min(total, int(to_index))
    if start > end:
        raise client.AiError(f"片段范围不合法：第 {start}–{end} 条")
    expected = end - start + 1
    slice_cues = list(cues[start - 1 : end])
    scope = f"本段期望第 {start}–{end} 条（共 {expected} 条）"
    pairs, warnings = align_model_srt(
        srt_text,
        slice_cues,
        reject_hint="漏改",
        scope_label=scope,
    )
    after_texts = list(source_texts)
    for offset, (_before, after) in enumerate(pairs):
        after_texts[start - 1 + offset] = after
    items = [
        {
            "i": idx,
            "before": source_texts[idx - 1],
            "after": after_texts[idx - 1],
            "note": "手动粘贴" if after_texts[idx - 1] != source_texts[idx - 1] else "",
        }
        for idx in range(1, total + 1)
    ]

    proposal = proposals.build_proposal(
        kind="polish",
        src_lang="ja",
        texts=source_texts,
        texts_b=texts_b,
        items=items,
        model="manual-paste",
        entry=entry,
        chunks=1,
    )
    check = proposals.validate_proposal(proposal, source_texts, texts_b)
    if not check.ok:
        raise client.AiError("；".join(check.errors[:3]))
    span = f"{start}–{end}" if (start, end) != (1, total) else ""
    if span:
        warnings = [f"已按第 {span} 条回填"] + warnings
    return proposal, warnings + check.warnings
