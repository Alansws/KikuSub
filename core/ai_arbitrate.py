"""单句 AI 判定（两版引擎转写 → 第三版建议）。

这条车道刻意**不是提案**：

- 没有 digest、没有提案文件、不经过 ``apply_polish()``；
- 只把这一句的 A/B 文本与前后各 3 句上下文发给模型；
- 不发送时间轴、音频或界面截图；
- 结果只是检查器里的第三张卡，采用时走既有 ``updateCue()``（一步历史）。

模型输出按语言分开提示：日语素材不要被中文校对规则改写，中文素材也不要被
日语语法（助词/活用）带偏。解析失败只允许上层重问一次，绝不产出半份结果。
"""

from __future__ import annotations

import re

MAX_CONTEXT_CUES = 3
MAX_TEXT_CHARS = 300
MAX_NOTE_CHARS = 80
MAX_CONTEXT_CHARS = 200

_WS_RE = re.compile(r"\s+")
_SRT_TIME_RE = re.compile(r"\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?|\d{1,2}:\d{2}[,.]\d{3}")
_ARROW_RE = re.compile(r"-->")


class ArbitrationError(ValueError):
    """模型输出不能当作一句字幕使用。"""


def normalize_lang(lang: str) -> str:
    """把引擎语种收成提示词分支；未知语种走通用模板。"""
    value = str(lang or "").strip().lower()
    if value.startswith("ja"):
        return "ja"
    if value.startswith("zh"):
        return "zh"
    return "generic"


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return _WS_RE.sub(" ", value).strip()


def _clean_context(items: object, *, keep_nearest: bool) -> list[str]:
    """清洗上下文并只保留离当前句最近的 3 条。

    ``keep_nearest=True`` 用于前文（调用方可能多传了几条，保留末尾 3 条）；
    后文保留开头 3 条。空字符串直接丢弃——ASR 漏识别的空白句不该占上下文预算。
    """
    if not isinstance(items, (list, tuple)):
        return []
    cleaned = [_clean_text(item) for item in items]
    cleaned = [text[:MAX_CONTEXT_CHARS] for text in cleaned if text]
    return cleaned[-MAX_CONTEXT_CUES:] if keep_nearest else cleaned[:MAX_CONTEXT_CUES]


def _system_prompt(lang: str) -> str:
    if lang == "ja":
        return """你是日语字幕校对员。同一段日语音频被两个 ASR 引擎分别转写为 A 和 B，两个版本不一致。
请根据前后文判断这段音频最可能说的是什么。

注意：
- ASR 常见错误是同音词、助词、长音/促音、断词和口语省略；
- 不要因为某一版更通顺就选它，以日语口语的实际发音和上下文为准；
- 不要按中文语序重写，也不要翻译成中文。

如果两版各有对错，可以合并成一句最自然的日语；没有把握时选更符合上下文与日语语法的一版。
只输出这一句的日语文本：不要时间码、不要解释、不要翻译、不要补句号、不要输出前后文。
严格输出 JSON，不要 markdown 代码块：{"text": "...", "note": "不超过 40 字的判断理由"}"""
    if lang == "zh":
        return """你是中文字幕校对员。同一段中文音频被两个 ASR 引擎分别转写为 A 和 B，两个版本不一致。
请根据前后文判断这段音频最可能说的是什么。

注意：
- ASR 常见错误是同音字、前后鼻音、儿化、断词、语气词和口语省略；
- 不要按日语语法或日语语序改中文，也不要把口语改写成书面语；
- 以中文口语的实际发音和上下文为准。

如果两版各有对错，可以合并成一句最自然的中文；没有把握时选更符合上下文与中文口语的一版。
只输出这一句的中文文本：不要时间码、不要解释、不要翻译、不要补句号、不要输出前后文。
严格输出 JSON，不要 markdown 代码块：{"text": "...", "note": "不超过 40 字的判断理由"}"""
    return """你是字幕校对员。同一段音频被两个 ASR 引擎分别转写为 A 和 B，两个版本不一致。
请根据前后文判断这段音频最可能说的是什么。

如果两版各有对错，可以合并成一句最自然的文本；没有把握时选更符合上下文与口语表达的一版。
只输出这一句与 A/B 相同语言的文本：不要时间码、不要解释、不要翻译、不要补句号、不要输出前后文。
严格输出 JSON，不要 markdown 代码块：{"text": "...", "note": "不超过 40 字的判断理由"}"""


def build_prompt(
    *,
    lang: str,
    text_a: str,
    text_b: str,
    before: object = (),
    after: object = (),
    no_think: bool = False,
) -> tuple[str, str]:
    """构造 (system, user)。user 里只有文本，**绝不**出现时间码。

    ``no_think=True`` 会在 user 末尾追加 Qwen3 的 ``/no_think`` 软开关。本地
    Qwen 推理模型（如 LM Studio 里的 Qwen3.8）默认只把推理写进
    ``reasoning_content``、content 为空；关掉思考后才会稳定输出最终 JSON。
    """
    code = normalize_lang(lang)
    before_texts = _clean_context(before, keep_nearest=True)
    after_texts = _clean_context(after, keep_nearest=False)
    a = _clean_text(text_a) or "（空：这个引擎没有识别到内容）"
    b = _clean_text(text_b) or "（空：这个引擎没有识别到内容）"

    sections: list[str] = []
    if before_texts:
        sections.append("【前文】\n" + "\n".join(before_texts))
    sections.append("【A 版】\n" + a)
    sections.append("【B 版】\n" + b)
    if after_texts:
        sections.append("【后文】\n" + "\n".join(after_texts))
    user = (
        "以下是同一句音频的两个转写版本与它的上下文。请按系统要求只判定这一句。\n\n"
        + "\n\n".join(sections)
    )
    if no_think:
        user += "\n\n/no_think"
    return _system_prompt(code), user


STRICT_HINT = (
    "\n\n上一次输出不符合格式。必须只返回一个 JSON 对象："
    '{"text": "这一句的文本", "note": "不超过 40 字的理由"}；'
    "text 不能为空，不能含时间码，不能输出解释或 markdown 代码块。"
)


def parse_result(data: object) -> dict:
    """校验模型结果，返回 ``{"text": ..., "note": ...}``。"""
    if not isinstance(data, dict):
        raise ArbitrationError("模型应返回一个 JSON 对象")
    raw_text = data.get("text")
    if not isinstance(raw_text, str):
        raise ArbitrationError("模型结果缺少 text")
    text = _clean_text(raw_text)
    if not text:
        raise ArbitrationError("模型返回的文本为空")
    if len(text) > MAX_TEXT_CHARS:
        raise ArbitrationError("模型返回的文本太长")
    if _ARROW_RE.search(text) or _SRT_TIME_RE.search(text):
        raise ArbitrationError("模型返回的文本里带了时间码")

    note = _clean_text(data.get("note"))
    if len(note) > MAX_NOTE_CHARS:
        note = note[:MAX_NOTE_CHARS].rstrip()
    return {"text": text, "note": note}
