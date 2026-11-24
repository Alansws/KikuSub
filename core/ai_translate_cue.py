"""单句补译：让本地大模型只翻核对台里「待译」的这一条。

## 为什么不是提案

整轨翻译（``core.ai_translate``）要先抽术语表、分块、生成 digest，再走
`/api/ai/apply` 的校验与提案文件；那是「把整片重翻一遍」的流程。这里要解决的
场景完全不同：局部转写**新加了一条**原文，整片译文都在、只缺这一句
（2026-11-25 用户报障）。为了补一句重翻全片既慢又容易把已核对的稿子冲掉。

所以这条车道刻意**不落盘、不进历史、不改字幕**：

- 只带这一句的日语原文 + 前后各几行的原文 + 这些行**已有的译文**当语气 / 术语参考；
- 不发时间轴、音频、界面状态；
- 返回一段草稿文本，用户在检查器里看一眼（可改）点「采纳」才走既有
  ``updateTranslation()``（一步历史，可 ⌘Z）。

## 上下文预算

默认走本机 LM Studio（2048 context）。system 约 300 字，输出只有一句，所以
user 消息压到 :data:`MAX_PROMPT_CHARS` 以内，上下文按「离当前句近的优先」裁。
"""

from __future__ import annotations

import json
import re

from . import ai_client as client
from .ai_translate import lang_name

MAX_CONTEXT_CUES = 4
MAX_TEXT_CHARS = 300
# 一句字幕的译文上限：中文 60 字已经远超单行字幕，超过它一定是模型在解释。
MAX_OUT_CHARS = 120
MAX_NOTE_CHARS = 60
# user 消息总预算（字符）。本地 2048 context + 中日文分词差异留足余量。
MAX_PROMPT_CHARS = 1200

_WS_RE = re.compile(r"\s+")
_TIME_RE = re.compile(r"\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?")
_ARROW_RE = re.compile(r"-->")


class CueTranslateError(ValueError):
    """模型输出不能当作一句字幕译文使用。"""


SYSTEM_PROMPT = """你是日本影视字幕译者。把「target」这一条日语字幕译成__LANG__。

要求：
- 只输出 JSON：{"text": "译文", "note": ""}
- 单行；中文尽量不超过 18 个全角字，宁短勿长，绝不拆成两条
- 保留人物称呼与敬语层级；context_before / context_after 与 references 里的
  称呼、语气词、专有名词译法要与已有译文一致
- 不加解释、不加括号补充、不音译外来语音
- target 常常是半句（被断句切开的），按上下文译出语义完整的一句，不要硬凑长句"""

STRICT_HINT = "\n\n只输出 JSON：{\"text\": \"译文\", \"note\": \"\"}，不要任何解释。"


def _clean(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return _WS_RE.sub(" ", value).strip()[:limit].strip()


def _clean_list(items: object, *, keep_nearest: bool) -> list[str]:
    if not isinstance(items, (list, tuple)):
        return []
    cleaned = [_clean(item, MAX_TEXT_CHARS) for item in items]
    cleaned = [text for text in cleaned if text]
    return cleaned[-MAX_CONTEXT_CUES:] if keep_nearest else cleaned[:MAX_CONTEXT_CUES]


def _clean_refs(items: object) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(items, (list, tuple)):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        src = _clean(item.get("src"), MAX_TEXT_CHARS)
        dst = _clean(item.get("dst"), MAX_OUT_CHARS)
        if src and dst:
            out.append({"src": src, "dst": dst})
    return out[: MAX_CONTEXT_CUES * 2]


def build_prompt(
    text: str,
    *,
    before: object = (),
    after: object = (),
    refs: object = (),
    dst_lang: str = "zh-Hans",
) -> str:
    """拼 user 消息。没有时间码；只放离当前句最近的几条上下文。"""
    payload = {
        "dst_lang": lang_name(dst_lang),
        "context_before": _clean_list(before, keep_nearest=True),
        "context_after": _clean_list(after, keep_nearest=False),
        "references": _clean_refs(refs),
        "target": {"text": _clean(text, MAX_TEXT_CHARS)},
    }
    prompt = json.dumps(payload, ensure_ascii=False)
    if len(prompt) > MAX_PROMPT_CHARS:
        # 超预算就只留目标句：宁可少参考，也不把超长 prompt 塞给 2048 context。
        payload["context_before"] = []
        payload["context_after"] = []
        payload["references"] = []
        prompt = json.dumps(payload, ensure_ascii=False)[:MAX_PROMPT_CHARS]
    return prompt


def parse_result(data: object) -> dict:
    """校验模型结果，返回 ``{"text": ..., "note": ...}``。"""
    if not isinstance(data, dict):
        raise CueTranslateError("模型应返回一个 JSON 对象")
    raw = data.get("text")
    if not isinstance(raw, str):
        raise CueTranslateError("模型结果缺少 text")
    text = _clean(raw, MAX_OUT_CHARS + 1)
    if not text:
        raise CueTranslateError("模型返回的译文为空")
    if len(text) > MAX_OUT_CHARS:
        raise CueTranslateError("模型返回的译文太长（像是解释而不是一句字幕）")
    if _ARROW_RE.search(text) or _TIME_RE.search(text):
        raise CueTranslateError("模型返回的译文里带了时间码")
    note = _clean(data.get("note"), MAX_NOTE_CHARS)
    return {"text": text, "note": note}


def translate_cue(
    text: str,
    cfg: client.AiConfig,
    *,
    dst_lang: str = "zh-Hans",
    before: object = (),
    after: object = (),
    refs: object = (),
    no_think: bool = False,
    cancel=None,
) -> dict:
    """翻一条。失败抛 :class:`CueTranslateError` / ``ai_client.AiError``。

    ``no_think`` 与单句判定同一条策略：Qwen3 系推理模型默认把答案写进
    ``reasoning_content``、``content`` 为空；``/no_think`` 是它认识的软开关。
    """
    target = _clean(text, MAX_TEXT_CHARS)
    if not target:
        raise CueTranslateError("这一句原文是空的，没有可翻译的内容")
    if not (dst_lang or "").strip():
        raise CueTranslateError("必须指定目标语种")

    system = SYSTEM_PROMPT.replace("__LANG__", lang_name(dst_lang))
    if no_think:
        system += "\n\n/no_think"
    prompt = build_prompt(target, before=before, after=after, refs=refs, dst_lang=dst_lang)
    # 本地推理模型（Qwen3 系）会用 assistant 前缀把输出钉成 JSON；云端模型走正常模式。
    prefill = '{"text": "' if client.is_local_url(cfg.base_url) else ""
    last: Exception | None = None
    for attempt in range(2):
        data = client.chat_json(
            cfg,
            system,
            prompt if attempt == 0 else prompt + STRICT_HINT,
            cancel=cancel,
            temperature=0.1,
            assistant_prefill=prefill,
        )
        try:
            return parse_result(data)
        except CueTranslateError as exc:
            last = exc
    raise last or CueTranslateError("模型没有返回可用的译文")
