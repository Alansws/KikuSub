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


def build_user_prompt(
    texts: list[str],
    chunk: Chunk,
    context_cues: int,
    lang: str = "ja",
    total_chunks: int = 1,
) -> str:
    """组一块的 user 消息。上下文只读，不参与输出（`i` 用全局绝对序号）。"""
    ctx = max(0, int(context_cues))
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
) -> dict[int, dict]:
    """跑一块：结构不合规重问一次，仍不行就抛错（调用方整份放弃）。"""
    prompt = build_user_prompt(texts, chunk, context_cues, lang, total_chunks)
    last: Exception | None = None
    for attempt in range(2):
        data = client.chat_json(
            cfg,
            SYSTEM_PROMPT,
            prompt if attempt == 0 else prompt + STRICT_HINT,
            cancel=cancel,
        )
        try:
            return collect_chunk(data, chunk)
        except client.AiError as exc:
            last = exc
            log.warning("第 %d 块结构不合规（第 %d 次）：%s", chunk.index, attempt + 1, exc)
    raise last or client.AiError(f"第 {chunk.index} 块失败")


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
    cancel=None,
    on_progress=None,
) -> tuple[dict, list[str]]:
    """逐块润色，返回 ``(提案 dict, 校验警告)``。

    失败语义：任何一块最终失败都抛异常，**不产出半份提案**。
    取消语义：分块之间检查令牌，抛 `AiPolishCancelled`，同样不产出。
    """
    if not texts:
        raise client.AiError("没有可润色的字幕")

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
        merged.update(
            _run_chunk(cfg, chunk, texts, context_cues, lang, cancel, len(chunks))
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
    )

    check = proposals.validate_proposal(proposal, texts)
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


def build_manual_prompt(srt_text: str) -> str:
    """组润色手写通道的提示词。``srt_text`` 用与导出同一份 ``cues_to_srt``。"""
    return MANUAL_PROMPT.replace("__SRT__", (srt_text or "").strip())


def proposal_from_srt(
    srt_text: str,
    cues,
    *,
    entry: str = "manual",
) -> tuple[dict, list[str]]:
    """把模型回吐的修正版 SRT 变成 polish 提案。

    与翻译通道同样只按**顺序**取文本，序号和时间戳一律丢弃；条数不一致整批拒绝。
    时间轴仍由 ``cues`` 提供（D-1 不破）。
    """
    from .proposal_srt import align_model_srt

    pairs, warnings = align_model_srt(srt_text, cues, reject_hint="漏改")
    items = [
        {
            "i": idx,
            "before": before,
            "after": after,
            "note": "手动粘贴" if after != before else "",
        }
        for idx, (before, after) in enumerate(pairs, start=1)
    ]

    proposal = proposals.build_proposal(
        kind="polish",
        src_lang="ja",
        texts=[c.text for c in cues],
        items=items,
        model="manual-paste",
        entry=entry,
        chunks=1,
    )
    check = proposals.validate_proposal(proposal, [c.text for c in cues])
    if not check.ok:
        raise client.AiError("；".join(check.errors[:3]))
    return proposal, warnings + check.warnings
