"""把「翻译」拆成两遍：先抽术语表，再逐块翻译。

与 `core.ai_polish` 同构（同样的分块、校验、取消语义），差别只有三点：

1. **必须先统一术语**：分块最大的坑是同一人名/称呼在不同块里译法不同。所以先拿全文
   抽一份 glossary，再注入每一块（开发文档 §6.2.1）。
2. **目标语种**写进 system prompt 与提案的 `dst_lang`。
3. 译文**不回写 review_cues**：调用方拿到提案后走 `/api/translations` 落成平行轨（D-3）。

同样不认识的：HTTP、UI。网络在 `core.ai_client`，落盘在服务层。
"""

from __future__ import annotations

import json
import logging

from . import ai_client as client
from . import ai_proposal as proposals
from .ai_polish import MAX_CHUNKS, STRICT_HINT, collect_chunk, plan_chunks

log = logging.getLogger(__name__)

# 语种代码 → 给模型看的中文名。没收录的直接把代码丢给模型（也能work，只是可能问一句）。
LANG_NAMES = {
    "zh-Hans": "简体中文",
    "zh-Hant": "繁體中文",
    "en": "English",
    "ko": "한국어",
    "ja": "日本語",
}

# 抽术语表时最多喂这么多字符：超了只取开头（人名通常出现在前半段）。
GLOSSARY_CHAR_LIMIT = 24000
GLOSSARY_LIMIT = 80

SYSTEM_PROMPT = """你是日语影视字幕翻译。把给定的日语字幕逐条译成__LANG__。

要求：
- 一条原文对应一条译文，条数必须相同，i 必须与输入一致
- 译文要能在单行内显示：中文不超过 18 个全角字，超长时压缩措辞，绝不拆条
- 保留人物称呼与敬语层级；人名按术语表统一
- 不加解释、不加括号补充、不音译外来语原文
- 参考 context_before / context_after 理解语境，但只为 items 输出译文

只输出 JSON：{"items":[{"i":1,"text":"…","note":""}]}"""

GLOSSARY_PROMPT = """你是日语影视字幕的术语整理员。下面是一部片子的全部日语字幕。

请找出需要**全片统一译法**的专有名词：人名、称呼、地名、机构、作品内术语。
只收真正会导致前后不一致的词，不要收普通名词和语气词。

每条给出来源写法与建议译法；最多 __LIMIT__ 条，没有就给空数组。
只输出 JSON：{"glossary":[{"src":"千尋","dst":"千寻"}]}"""


def lang_name(dst_lang: str) -> str:
    return LANG_NAMES.get(dst_lang, dst_lang or "目标语言")


def extract_glossary(
    texts: list[str],
    cfg: client.AiConfig,
    *,
    dst_lang: str,
    cancel=None,
) -> list[dict]:
    """一遍全文抽取术语表。失败由调用方决定是否降级（这里只抛 AiError）。"""
    joined = "\n".join(t.strip() for t in texts if t.strip())
    if not joined:
        return []
    if len(joined) > GLOSSARY_CHAR_LIMIT:
        joined = joined[:GLOSSARY_CHAR_LIMIT]

    # 不用 str.format：提示词里大量 { } 会被当成占位符
    system = GLOSSARY_PROMPT.replace("__LIMIT__", str(GLOSSARY_LIMIT))
    user = json.dumps(
        {"dst_lang": lang_name(dst_lang), "subtitles": joined},
        ensure_ascii=False,
    )
    data = client.chat_json(cfg, system, user, cancel=cancel)
    raw = data.get("glossary")
    if not isinstance(raw, list):
        return []

    out: list[dict] = []
    for item in raw:
        # 模型偶尔会把 {"src":..., "dst":...} 写成 ["src","dst"]
        if isinstance(item, dict):
            src = str(item.get("src") or item.get("source") or "").strip()
            dst = str(item.get("dst") or item.get("target") or "").strip()
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            src, dst = str(item[0]).strip(), str(item[1]).strip()
        else:
            continue
        if src and dst and src != dst:
            out.append({"src": src[:40], "dst": dst[:40]})
        if len(out) >= GLOSSARY_LIMIT:
            break
    return out


def build_user_prompt(
    texts: list[str],
    chunk,
    context_cues: int,
    glossary: list[dict],
    dst_lang: str,
    total_chunks: int = 1,
) -> str:
    """一块的 user 消息。和润色一样：**没有时间码**，`i` 用全局绝对序号。"""
    ctx = max(0, int(context_cues))
    payload = {
        "chunk": chunk.index,
        "total": total_chunks,
        "dst_lang": lang_name(dst_lang),
        "glossary": glossary,
        "context_before": texts[max(0, chunk.start - ctx) : chunk.start],
        "context_after": texts[chunk.end : chunk.end + ctx],
        "items": [{"i": i + 1, "text": texts[i]} for i in range(chunk.start, chunk.end)],
    }
    return json.dumps(payload, ensure_ascii=False)


def _run_chunk(
    cfg: client.AiConfig,
    chunk,
    texts: list[str],
    context_cues: int,
    glossary: list[dict],
    dst_lang: str,
    cancel,
    total_chunks: int,
) -> dict[int, dict]:
    prompt = build_user_prompt(texts, chunk, context_cues, glossary, dst_lang, total_chunks)
    system = SYSTEM_PROMPT.replace("__LANG__", lang_name(dst_lang))
    last: Exception | None = None
    for attempt in range(2):
        data = client.chat_json(
            cfg, system, prompt if attempt == 0 else prompt + STRICT_HINT, cancel=cancel
        )
        try:
            return collect_chunk(data, chunk)
        except client.AiError as exc:
            last = exc
            log.warning("翻译第 %d 块结构不合规（第 %d 次）：%s", chunk.index, attempt + 1, exc)
    raise last or client.AiError(f"第 {chunk.index} 块失败")


def run_translate(
    texts: list[str],
    cfg: client.AiConfig,
    *,
    dst_lang: str,
    chunk_cues: int = 120,
    context_cues: int = 5,
    source_path: str = "",
    entry: str = "in-app",
    cancel=None,
    on_progress=None,
) -> tuple[dict, list[str], list[dict]]:
    """逐块翻译，返回 ``(提案, 校验警告, 术语表)``。

    失败语义与润色一致：任何一块最终失败都抛异常，**不产出半份提案**。
    """
    from .ai_polish import AiPolishCancelled

    if not texts:
        raise client.AiError("没有可翻译的字幕")
    if not (dst_lang or "").strip():
        raise client.AiError("必须指定目标语种")

    chunks = plan_chunks(len(texts), chunk_cues)
    if len(chunks) > MAX_CHUNKS:
        raise client.AiError(
            f"分块太多（{len(chunks)} 块，上限 {MAX_CHUNKS}）：请把每块条数调大"
        )

    def report(ratio: float, stage: str) -> None:
        if on_progress:
            on_progress(max(0.0, min(1.0, ratio)), stage)

    # 第一遍：术语表（只有分块时才做——单片一次调用时模型自己就能保持全文一致）
    glossary: list[dict] = []
    if len(chunks) > 1:
        report(0.0, "整理术语表")
        try:
            glossary = extract_glossary(texts, cfg, dst_lang=dst_lang, cancel=cancel)
        except client.AiError as exc:
            # 术语表是增强项：失败不该让翻译整个挂掉
            log.warning("术语表抽取失败，降级为无术语表：%s", exc)
            glossary = []

    merged: dict[int, dict] = {}
    for pos, chunk in enumerate(chunks):
        if cancel is not None and cancel.is_set():
            raise AiPolishCancelled()
        report(0.1 + 0.9 * pos / len(chunks), f"第 {chunk.index}/{len(chunks)} 块")
        merged.update(
            _run_chunk(cfg, chunk, texts, context_cues, glossary, dst_lang, cancel, len(chunks))
        )

    report(1.0, "校验译文")

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
        kind="translate",
        src_lang="ja",
        dst_lang=dst_lang,
        texts=texts,
        items=items,
        model=cfg.model,
        entry=entry,
        glossary=glossary,
        chunks=len(chunks),
        source_path=source_path,
    )

    check = proposals.validate_proposal(proposal, texts)
    if not check.ok:
        raise client.AiError("模型输出未通过校验：" + "；".join(check.errors[:3]))
    return proposal, check.warnings, glossary


# --------------------------------------------------------------------------- 手动通道
#
# 没有 API Key、或想用网页版模型时走这条路：
#   「复制提示词」→ 用户粘到任意聊天窗 → 把模型回的 SRT 粘回来 → 解析成提案 → 同一套 diff。
# 两条硬约束：
#   1. 提示词里**必须带序号和时间戳**（否则模型没法逐条对齐，长片极易错位）；
#   2. 解析回来时**只取文本，时间戳一律丢弃**，用我们自己 cue 的时间码重建（D-1）。

MANUAL_PROMPT = """请将以下 SRT 日语字幕翻译为__LANG__：
风格要求：综合全片先理解整部影片的风格，例如语气是温柔撒娇还是粗俗轻视，然后再结合上下文翻译。
格式要求：严格保留原 SRT 的序号和时间戳不变。
仅输出翻译后的__LANG__内容，不要解释、不要 markdown 代码块。
内容如下：
<subtitles>
__SRT__
</subtitles>"""


def build_manual_prompt(srt_text: str, dst_lang: str) -> str:
    """组「一键复制」的提示词。``srt_text`` 用导出的同一份 ``cues_to_srt`` 结果。"""
    return (
        MANUAL_PROMPT.replace("__LANG__", lang_name(dst_lang))
        .replace("__SRT__", (srt_text or "").strip())
    )


def proposal_from_srt(
    srt_text: str,
    cues,
    dst_lang: str,
    *,
    entry: str = "manual",
) -> tuple[dict, list[str]]:
    """把模型回吐的 SRT 变成 translate 提案。

    - 条数必须与当前字幕一致，否则整批拒绝（合并/漏翻都会在这里被抓住）；
    - 文本按**顺序**对齐，不用它给的序号，也不看它给的时间戳；
    - 时间戳偏差过大时给一条 warning（多半是模型改写了时间轴或整体错位）。
    """
    from .subtitles import srt_to_cues

    parsed = srt_to_cues(srt_text or "")
    if not parsed:
        raise client.AiError("没有从粘贴内容里解析到字幕：确认贴的是完整 SRT（含序号与时间戳）")
    if len(parsed) != len(cues):
        raise client.AiError(
            f"条数对不上：解析到 {len(parsed)} 条，当前字幕 {len(cues)} 条。"
            "常见原因是模型合并/拆分了句子或漏翻——请让它按原序号逐条输出"
        )

    warnings: list[str] = []
    drift = 0
    items = []
    for idx, cue in enumerate(cues, start=1):
        got = parsed[idx - 1]
        if abs(got.start - cue.start) > 1.0:
            drift += 1
        items.append(
            {
                "i": idx,
                "before": cue.text,
                "after": got.text.strip(),
                "note": "",
            }
        )
    if drift:
        warnings.append(
            f"{drift} 条的时间戳与原文对不上（已按顺序采用文本，时间轴仍用原文）"
        )

    proposal = proposals.build_proposal(
        kind="translate",
        src_lang="ja",
        dst_lang=dst_lang,
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
