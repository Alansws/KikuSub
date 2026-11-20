"""单句 AI 判定（两版引擎转写 → 第三版建议，也支持无识别时按线索还原）。

这条车道刻意**不是提案**：

- 没有 digest、没有提案文件、不经过 ``apply_polish()``；
- 只把这一句的材料（A/B 文本、可选听音线索、最近几轮追问）与前后各 3 句上下文
  发给模型；
- 不发送时间轴、音频或界面截图；
- 结果只是检查器里的第三张卡，采用时走既有 ``updateCue()``（一步历史）。

材料组合决定提示词：双版对照 / 单版纠偏 / 无识别（只能靠上下文 + 听音线索还原）/
多轮追问。本地 2048 context 是硬约束：``hint`` 与最近 6 轮都有上限，同时按总字符
预算从最旧的记录开始裁，绝不把超长 prompt 塞给模型。

模型输出按语言分开提示：日语素材不要被中文校对规则改写，中文素材也不要被
日语语法（助词/活用）带偏。解析失败只允许上层重问一次，绝不产出半份结果。
"""

from __future__ import annotations

import re

MAX_CONTEXT_CUES = 3
MAX_TEXT_CHARS = 300
MAX_NOTE_CHARS = 80
MAX_CONTEXT_CHARS = 200

# 追问材料的上限；真正的约束见 ``MAX_USER_CHARS``（本地 2048 context）。
MAX_HINT_CHARS = 400
MAX_HISTORY_ROUNDS = 6
MAX_HISTORY_MESSAGE_CHARS = 260
MAX_HISTORY_CHARS = 400
MAX_CONTEXT_TOTAL_CHARS = 450
# 整个 user 消息（含标题、分隔）的字符预算。system 约 400 字，输出 JSON 约 100 字；
# 1300 + 444 + 100 仍留在 2048 context 内，且给中日文的分词差异留了余量。
MAX_USER_CHARS = 1300

_WS_RE = re.compile(r"\s+")
_SRT_TIME_RE = re.compile(r"\d{1,2}:\d{2}:\d{2}(?:[,.]\d{1,3})?|\d{1,2}:\d{2}[,.]\d{3}")
_ARROW_RE = re.compile(r"-->")

Message = dict[str, str]


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


def _item_field(item: object, name: str) -> object:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _history_chars(messages: list[Message]) -> int:
    # 标签（「用户：」/「AI：」）与换行也占预算，按每条 4 字估算。
    return sum(len(item["text"]) + 4 for item in messages)


def _clean_history(items: object) -> list[Message]:
    """把追问记录收成 ``[{role, text}]``：最多 6 轮、单条有上限，保留最近的尾部。"""
    if not isinstance(items, (list, tuple)):
        return []
    messages: list[Message] = []
    for item in items:
        role = str(_item_field(item, "role") or "").strip().lower()
        if role not in ("user", "assistant"):
            continue
        text = _clean_text(_item_field(item, "text"))[:MAX_HISTORY_MESSAGE_CHARS]
        if text:
            messages.append({"role": role, "text": text})
    # 先限轮次（一轮 = 用户 + AI 两条），畸形输入多留几条，后面再整理。
    # 不强行丢掉开头的 AI 消息：首轮判定可能没有用户线索，那条 AI 结论仍是
    # 后续追问的重要上下文。
    return messages[-MAX_HISTORY_ROUNDS * 2 :]


def _fit_history(messages: list[Message], budget: int) -> list[Message]:
    """按字符预算裁剪：从最旧的一条开始丢，仍超才截断最旧的一条。"""
    if budget <= 0:
        return []
    kept = [dict(item) for item in messages]
    # 从最旧的一条开始丢，保留最近的连续对话；开头落在 AI 行也允许。
    while kept and _history_chars(kept) > budget:
        kept.pop(0)
    if kept and _history_chars(kept) > budget:
        overflow = _history_chars(kept) - budget
        first = kept[0]
        keep = max(0, len(first["text"]) - overflow)
        first["text"] = first["text"][:keep].rstrip()
        if not first["text"]:
            kept.pop(0)
    return kept


def _context_within(
    before: object, after: object, budget: int
) -> tuple[list[str], list[str]]:
    """在字符预算内取上下文，前后交替、由近及远；放不下的条目截断或丢弃。"""
    before_texts = _clean_context(before, keep_nearest=True)
    after_texts = _clean_context(after, keep_nearest=False)
    before_keep: list[str] = []
    after_keep: list[str] = []
    remaining = max(0, budget)
    step = 0
    while step < max(len(before_texts), len(after_texts)):
        if step < len(after_texts):
            text = after_texts[step]
            cost = len(text) + 1
            if cost <= remaining:
                after_keep.append(text)
                remaining -= cost
            elif remaining >= 8:
                after_keep.append(text[: remaining - 1].rstrip())
                remaining = 0
                break
            else:
                break
        if step < len(before_texts):
            text = before_texts[-1 - step]
            cost = len(text) + 1
            if cost <= remaining:
                before_keep.append(text)
                remaining -= cost
            elif remaining >= 8:
                before_keep.append(text[: remaining - 1].rstrip())
                remaining = 0
                break
            else:
                break
        step += 1
    before_keep.reverse()
    return before_keep, after_keep


def _materials_mode(text_a: str, text_b: str) -> str:
    if text_a and text_b:
        return "same" if text_a == text_b else "dual"
    if text_a or text_b:
        return "single"
    return "blind"


def _system_prompt(
    lang: str, *, mode: str, has_hint: bool, has_history: bool
) -> str:
    """按语种与材料组合组织 system prompt；输出契约始终是同一份 JSON。"""
    if lang == "ja":
        base = (
            "你是日语字幕校对员。用户正在核对一段日语音频，ASR 引擎没有完整听清，"
            "需要你还原这一句里最可能的日语。"
        )
        rules = """注意：
- ASR 常见错误是同音词、助词、长音/促音、断词和口语省略；
- 不要因为某一版更通顺就选它，以日语口语的实际发音和上下文为准；
- 不要按中文语序重写，也不要翻译成中文。"""
        target = "日语"
    elif lang == "zh":
        base = (
            "你是中文字幕校对员。用户正在核对一段中文音频，ASR 引擎没有完整听清，"
            "需要你还原这一句里最可能的中文。"
        )
        rules = """注意：
- ASR 常见错误是同音字、前后鼻音、儿化、断词、语气词和口语省略；
- 不要按日语语法或日语语序改中文，也不要把口语改写成书面语；
- 以中文口语的实际发音和上下文为准。"""
        target = "中文"
    else:
        base = (
            "你是字幕校对员。用户正在核对一段音频，ASR 引擎没有完整听清，"
            "需要你还原这一句里最可能的文本。"
        )
        rules = """注意：
- ASR 常见错误是同音词、断词、口语省略和发音相近的词；
- 以实际发音和上下文为准，不要为了通顺补写没有依据的内容。"""
        target = "与材料相同语言"

    mode_line = {
        "dual": "两个 ASR 引擎给出了 A 和 B 两个不一致的版本。",
        "same": "两个 ASR 引擎给出了一致的文本；用户仍想请你复核这一句。",
        "single": "只有一个 ASR 引擎识别出了文本，另一版为空；请结合上下文补齐或纠错。",
        "blind": "两个 ASR 引擎都没有识别到内容；只能根据上下文和用户提供的线索还原。",
    }[mode]

    mode_guard = {
        "dual": "两版各有对错时可以合并成一句最自然的{target}；没有把握时选更符合上下文与口语的一版。",
        "same": "两版一致时优先保留原文；只有上下文或线索明确指向另一句时才改。",
        "single": "以已识别到的一版为骨架，只改有明显发音依据的错误，不要整句重写成无关内容。",
        "blind": "线索与上下文不足时，给出最可能的还原，并在 note 里写明不确定。",
    }[mode].format(target=target)

    guidance: list[str] = []
    if has_hint:
        guidance.append(
            "用户提供了听音线索（可能是中文音译、罗马音、空耳或不完整描述）；"
            "线索只用来定位发音，不是最终文本，不要照抄线索里的中文。"
        )
    if has_history:
        guidance.append(
            "这是多轮追问：结合之前的问答，保留已经确认的信息，不要重复提问，"
            "也不要忽略用户最新的补充。"
        )
    if mode != "blind":
        guidance.append("有前后文时，保持人物称呼、口吻与话题连贯。")
    guidance_text = "\n".join(f"- {line}" for line in guidance)

    return f"""{base}

{mode_line}

{rules}
{mode_guard}
{guidance_text}
- 文本可能很短（一个词或一句口头禅）；不要为了通顺补写没有依据的内容。
- 只输出这一句的{target}文本：不要时间码、不要解释、不要翻译、不要补句号、不要输出前后文。
严格输出 JSON，不要 markdown 代码块：{{"text": "...", "note": "不超过 40 字的判断理由"}}"""


def _user_prefix(mode: str) -> str:
    return {
        "dual": "以下是同一句音频的两个转写版本与它的上下文。请按系统要求只判定这一句。",
        "same": "以下是同一句音频目前一致的转写版本与它的上下文。请按系统要求复核这一句。",
        "single": "以下是同一句音频目前唯一识别到的文本与它的上下文。请按系统要求补全或纠错这一句。",
        "blind": "两个引擎都没有识别到这一句的文本。请根据上下文与听音线索，只还原这一句。",
    }[mode]


def build_prompt(
    *,
    lang: str,
    text_a: str,
    text_b: str,
    before: object = (),
    after: object = (),
    hint: str = "",
    history: object = (),
    no_think: bool = False,
) -> tuple[str, str]:
    """构造 (system, user)。user 里只有文本，**绝不**出现时间码。

    ``no_think=True`` 会在 user 末尾追加 Qwen3 的 ``/no_think`` 软开关。本地
    Qwen 推理模型（如 LM Studio 里的 Qwen3.8）默认只把推理写进
    ``reasoning_content``、content 为空；关掉思考后才会稳定输出最终 JSON。
    """
    code = normalize_lang(lang)
    a = _clean_text(text_a)[:MAX_TEXT_CHARS]
    b = _clean_text(text_b)[:MAX_TEXT_CHARS]
    clue = _clean_text(hint)[:MAX_HINT_CHARS]
    mode = _materials_mode(a, b)
    before_texts = _clean_context(before, keep_nearest=True)
    after_texts = _clean_context(after, keep_nearest=False)
    has_context = bool(before_texts or after_texts)
    messages = _clean_history(history)

    # 先扣掉当前材料与标题开销，再把剩余预算分给追问记录和上下文：有上下文时
    # 历史最多拿一半，剩下给前后文；没有上下文时历史可拿满，避免多轮对话被截空。
    fixed = len(a) + len(b) + len(clue)
    available = max(0, MAX_USER_CHARS - fixed - 140)
    history_budget = min(MAX_HISTORY_CHARS, available // 2 if has_context else available)
    messages = _fit_history(messages, history_budget)
    remaining = max(0, available - _history_chars(messages))
    before_texts, after_texts = _context_within(
        before_texts, after_texts, min(MAX_CONTEXT_TOTAL_CHARS, remaining)
    )

    sections: list[str] = []
    if before_texts:
        sections.append("【前文】\n" + "\n".join(before_texts))
    if a and b:
        sections.append("【A 版】\n" + a)
        sections.append("【B 版】\n" + b)
    elif a or b:
        label = "A 版" if a else "B 版"
        sections.append(f"【识别结果（{label}）】\n{a or b}")
        sections.append("【另一版】\n（空：这个引擎没有识别到内容）")
    else:
        sections.append("【识别结果】\n两个引擎都没有识别到内容。")
    if messages:
        lines = ["【之前的追问（越靠后越新）】"]
        for item in messages:
            label = "用户：" if item["role"] == "user" else "AI："
            lines.append(label + item["text"])
        sections.append("\n".join(lines))
    if clue:
        sections.append("【听音线索（用户最新补充）】\n" + clue)
    if after_texts:
        sections.append("【后文】\n" + "\n".join(after_texts))

    user = _user_prefix(mode) + "\n\n" + "\n\n".join(sections)
    if no_think:
        user += "\n\n/no_think"
    system = _system_prompt(
        code,
        mode=mode,
        has_hint=bool(clue),
        has_history=bool(messages),
    )
    return system, user


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
