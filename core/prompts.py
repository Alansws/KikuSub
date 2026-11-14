"""可编辑的提示词模板库。

「手动粘贴通道」原本把提示词写死在 ``core/ai_translate.MANUAL_PROMPT`` 里。用户
需要在网页版模型和不同翻译风格之间切换，所以模板必须变成可保存、可编辑、可选中
的数据，而不是改一次代码换一次提示词。

2026-11 双引擎重构后模板分成三个**互不混杂**的分类（Q12）：

- ``polish_single``：单源润色，变量 ``{{SRT}}``；
- ``polish_dual``：双源润色，变量 ``{{SRT_A}}`` / ``{{SRT_B}}``（可选 ``{{RANGE}}``）；
- ``translate``：翻译，变量 ``{{SRT}}`` / ``{{LANG}}``。

分类各自记住「当前选中」：``selected`` 仍然是翻译的选中项（向后兼容旧
``prompts.json``），另加 ``selected_polish_single`` / ``selected_polish_dual``。
没有分类字段的历史自定义模板一律归入翻译（旧版只有翻译）。

设计约束：

- 文件是普通 JSON，放在 ``settings.json`` 旁边，原子写；
- 内置模板始终存在；用户对它们的修改会持久化，删掉文件就回到出厂文案；
- 渲染只做字符串替换，不执行任何模板语言。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from .paths import SETTINGS_PATH
from .textio import write_text_atomic

log = logging.getLogger(__name__)

LIBRARY_VERSION = 1
MAX_NAME = 60
MAX_DESCRIPTION = 200
MAX_CONTENT = 60_000

LEGACY_ID = "legacy"
LOCALIZATION_ID = "localization"
POLISH_SINGLE_ID = "polish-single"
POLISH_DUAL_ID = "polish-dual"

CATEGORY_TRANSLATE = "translate"
CATEGORY_POLISH_SINGLE = "polish_single"
CATEGORY_POLISH_DUAL = "polish_dual"
CATEGORIES = (CATEGORY_POLISH_SINGLE, CATEGORY_POLISH_DUAL, CATEGORY_TRANSLATE)
DEFAULT_CATEGORY = CATEGORY_TRANSLATE

#: 每个分类的「当前选中」存在哪个字段。``selected`` 保持翻译，兼容旧文件。
SELECTED_KEYS = {
    CATEGORY_TRANSLATE: "selected",
    CATEGORY_POLISH_SINGLE: "selected_polish_single",
    CATEGORY_POLISH_DUAL: "selected_polish_dual",
}

LEGACY_CONTENT = """请将以下 SRT 日语字幕翻译为{{LANG}}：
风格要求：综合全片先理解整部影片的风格，例如语气是温柔撒娇还是粗俗轻视，然后再结合上下文翻译。
格式要求：严格保留原 SRT 的序号和时间戳不变。
仅输出翻译后的{{LANG}}内容，不要解释、不要 markdown 代码块。
内容如下：
<subtitles>
{{SRT}}
</subtitles>"""

LOCALIZATION_CONTENT = """请将以下 SRT 日语字幕翻译为简体中文：
【场景定位】本作是成人互动作品（ASMR音声 / AV视频）。请以“资深成熟汉化组”的视角进行本地化翻译，追求中文母语听感、沉浸感与性张力。
【翻译准则】
1. 彻底去除翻译腔（母语化）：严禁机翻和二次生硬翻译腔（避免通篇“呐…”、“毕竟…呢”、“……的说”等）。请想象一位真实的中文母语者在耳边低语调情，用最地道、顺畅的中文日常口语重构台词。
2. 性暗示与动作具象化：日语习惯用代词、拟声词或委婉语表达生理状态与身体互动。翻译时请结合视听画面与上下文，将其意译为生动、有画面感的中文生理/性爱动作描写，不要浮于表面字面。
3. 自然补全人称代词：日语音频极常省略主语和宾语。请结合互动视听情境，自然补全“我/你/看我/我的”等代词，强化听众的代入感与视听沉浸感。
4. 跨字幕语流连贯：当一句话被切分在多行时间戳内，或遇到日式倒装时，请在保留原时间戳的前提下，让多行字幕在阅读逻辑上像一句连贯自然的中文，避免碎片感。
5. 准确捕捉人设语气：综合全篇把握角色的微表情与语调（如：是主导挑逗、娇嗔撒娇、还是沉溺享受），用中文地道的虚词（“可”、“倒”、“吧”、“呢”、“行”、“看你…”）还原角色的情绪拉扯感。
【格式要求】严格保留原 SRT 的序号和时间戳不变。仅输出翻译后的简体中文内容，不要解释、不要 markdown 代码块。
内容如下：
{{SRT}}"""

POLISH_SINGLE_CONTENT = """你是日语影视字幕校对员。下面是带序号和时间戳的 SRT 字幕。

只修正明显的识别错误：
- 同音字/近音字误识
- 助词、活用、断词错误
- 人名、专有名词、作品内术语的一致性
- 标点与全角半角

严禁改写风格、润色措辞、增删句子、合并或拆分条目。
严格保留原 SRT 的序号和时间戳，只输出修正后的 SRT；不要解释、不要 markdown 代码块。
{{RANGE_HINT}}
内容如下：
<subtitles>
{{SRT}}
</subtitles>"""

POLISH_DUAL_CONTENT = """你是日语影视字幕校对员。下面提供同一段音频的两个引擎转写稿：
- A 是主稿（核对台当前版本），带序号与时间戳；
- B 是另一引擎的参考稿，也带序号与时间戳。

请以 A 为主稿，参考 B 修正 A 的明显识别错误（同音字/近音字、助词、活用、断词、人名与术语、标点）。
硬性要求：
1. 严格以 A 的序号与时间轴为骨架，逐条输出 A 的修订文本；不得增删、拆分、合并条目。
2. 只能采用 B 中与 A 同一时间段对应的内容；禁止把 B 的句子拼接或追加到 A，导致重复或时间轴错位。
3. 没有把握的地方保留 A 原文；不要改写风格、不要翻译、不要加括号说明。
4. 只输出与 A 逐条对应的修订后 SRT（序号沿用 A），不要解释、不要 markdown 代码块。
{{RANGE_HINT}}

【A（主稿）】
{{SRT_A}}

【B（参考稿）】
{{SRT_B}}"""

DEFAULT_TEMPLATES: list[dict] = [
    {
        "id": LEGACY_ID,
        "category": CATEGORY_TRANSLATE,
        "name": "原有模板",
        "description": "带序号与时间戳的通用翻译提示词，适合大多数网页版模型。",
        "content": LEGACY_CONTENT,
        "builtin": True,
    },
    {
        "id": LOCALIZATION_ID,
        "category": CATEGORY_TRANSLATE,
        "name": "成熟汉化组",
        "description": "去翻译腔、性张力与画面感；面向成人互动作品的口语化本地化。",
        "content": LOCALIZATION_CONTENT,
        "builtin": True,
    },
    {
        "id": POLISH_SINGLE_ID,
        "category": CATEGORY_POLISH_SINGLE,
        "name": "单源润色（默认）",
        "description": "只修正识别错误，不改写风格；严格沿用原序号与时间轴。",
        "content": POLISH_SINGLE_CONTENT,
        "builtin": True,
    },
    {
        "id": POLISH_DUAL_ID,
        "category": CATEGORY_POLISH_DUAL,
        "name": "双源润色（默认）",
        "description": "以 A 为骨架、参考 B 修复错听与漏字；禁止拼接重复。",
        "content": POLISH_DUAL_CONTENT,
        "builtin": True,
    },
]


def default_prompts_path(settings_path: str | Path | None = None) -> Path:
    """模板库默认与 settings.json 同目录；``KIKUSUB_PROMPTS_PATH`` 可覆盖。"""
    override = (os.environ.get("KIKUSUB_PROMPTS_PATH") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    base = Path(settings_path or SETTINGS_PATH).expanduser()
    return base.parent / "prompts.json"


def normalize_category(raw: object, fallback: str = DEFAULT_CATEGORY) -> str:
    category = str(raw or "").strip()
    return category if category in CATEGORIES else fallback


def _clean_text(value: object, limit: int) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _normalize_template(raw: object, fallback_id: str = "") -> dict | None:
    if not isinstance(raw, dict):
        return None
    template_id = _clean_text(raw.get("id") or fallback_id, 64)
    if not template_id:
        return None
    content = str(raw.get("content") or "")[:MAX_CONTENT]
    name = _clean_text(raw.get("name"), MAX_NAME) or template_id
    description = _clean_text(raw.get("description"), MAX_DESCRIPTION)
    # 旧模板没有分类字段 → 翻译（旧版只有翻译，这是唯一的合理默认）。
    category = normalize_category(raw.get("category"), DEFAULT_CATEGORY)
    return {
        "id": template_id,
        "category": category,
        "name": name,
        "description": description,
        "content": content,
        "builtin": bool(raw.get("builtin")),
        "updated_at": float(raw.get("updated_at") or 0.0),
    }


def _defaults() -> list[dict]:
    now = time.time()
    return [
        {
            "id": item["id"],
            "category": item["category"],
            "name": item["name"],
            "description": item["description"],
            "content": item["content"],
            "builtin": True,
            "updated_at": now,
        }
        for item in DEFAULT_TEMPLATES
    ]


def _first_in_category(templates: list[dict], category: str) -> str:
    for item in templates:
        if item.get("category") == category:
            return str(item["id"])
    return ""


def _normalize_library(raw: object) -> dict:
    defaults = _defaults()
    saved = raw if isinstance(raw, dict) else {}
    saved_items = saved.get("templates") if isinstance(saved.get("templates"), list) else []
    by_id: dict[str, dict] = {}
    for item in saved_items:
        template = _normalize_template(item)
        if template is not None:
            by_id[template["id"]] = template

    templates: list[dict] = []
    default_ids = {item["id"] for item in defaults}
    for default in defaults:
        override = by_id.pop(default["id"], None)
        if override is not None:
            templates.append(
                {
                    "id": default["id"],
                    # 内置模板的分类不可被旧文件里的脏字段改掉
                    "category": default["category"],
                    "name": override["name"] or default["name"],
                    "description": override["description"] or default["description"],
                    "content": override["content"] or default["content"],
                    "builtin": True,
                    "updated_at": override["updated_at"] or default["updated_at"],
                }
            )
        else:
            templates.append(default)

    # 用户自建模板按分类 + 名称排序，保证多次读取顺序稳定
    for template in sorted(
        by_id.values(), key=lambda item: (item["category"], item["name"], item["id"])
    ):
        template["builtin"] = False
        if template["id"] in default_ids:
            template["category"] = DEFAULT_CATEGORY
        templates.append(template)

    out: dict = {"version": LIBRARY_VERSION, "templates": templates}
    for category, key in SELECTED_KEYS.items():
        selected = _clean_text(saved.get(key), 64)
        ids = {item["id"] for item in templates if item.get("category") == category}
        if selected not in ids:
            selected = _first_in_category(templates, category)
        out[key] = selected
    return out


def load_library(path: str | Path | None = None, settings_path: str | Path | None = None) -> dict:
    target = Path(path) if path is not None else default_prompts_path(settings_path)
    if not target.exists():
        return _normalize_library({})
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("提示词库读取失败，使用内置模板 | %s", target)
        return _normalize_library({})
    return _normalize_library(raw)


def save_library(
    library: dict, path: str | Path | None = None, settings_path: str | Path | None = None
) -> dict:
    target = Path(path) if path is not None else default_prompts_path(settings_path)
    normalized = _normalize_library(library)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(target, json.dumps(normalized, ensure_ascii=False, indent=2) + "\n")
    return normalized


def find_template(
    library: dict, template_id: str | None = None, category: str = DEFAULT_CATEGORY
) -> dict | None:
    category = normalize_category(category)
    wanted = _clean_text(template_id, 64)
    if not wanted:
        wanted = _clean_text(library.get(SELECTED_KEYS.get(category, "selected")), 64)
    for item in library.get("templates") or []:
        if item.get("id") == wanted:
            return item
    if wanted:
        # 指定了模板 id 却找不到：不要退回别的分类，否则翻译会拿到润色模板。
        return None
    for item in library.get("templates") or []:
        if item.get("category") == category:
            return item
    return None


def _library_payload(
    library: dict, templates: list[dict], selected: dict[str, str] | None = None
) -> dict:
    payload = {
        "version": LIBRARY_VERSION,
        "templates": templates,
        "selected": (selected or {}).get("selected", library.get("selected") or ""),
        "selected_polish_single": (selected or {}).get(
            "selected_polish_single", library.get("selected_polish_single") or ""
        ),
        "selected_polish_dual": (selected or {}).get(
            "selected_polish_dual", library.get("selected_polish_dual") or ""
        ),
    }
    return payload


def update_template(
    library: dict,
    template_id: str,
    patch: dict,
    *,
    path: str | Path | None = None,
    settings_path: str | Path | None = None,
) -> dict:
    template_id = _clean_text(template_id, 64)
    found = False
    updated: list[dict] = []
    for item in library.get("templates") or []:
        if item.get("id") != template_id:
            updated.append(item)
            continue
        found = True
        merged = dict(item)
        if "name" in patch:
            name = _clean_text(patch.get("name"), MAX_NAME)
            if not name:
                raise ValueError("模板名称不能为空")
            merged["name"] = name
        if "description" in patch:
            merged["description"] = _clean_text(patch.get("description"), MAX_DESCRIPTION)
        if "content" in patch:
            content = str(patch.get("content") or "")[:MAX_CONTENT]
            if not content.strip():
                raise ValueError("模板内容不能为空")
            merged["content"] = content
        if "category" in patch and not merged.get("builtin"):
            merged["category"] = normalize_category(patch.get("category"), merged.get("category"))
        merged["updated_at"] = time.time()
        updated.append(merged)
    if not found:
        raise KeyError(template_id)
    return save_library(
        _library_payload(library, updated),
        path=path,
        settings_path=settings_path,
    )


def create_template(
    library: dict,
    name: str,
    content: str,
    description: str = "",
    *,
    category: str = DEFAULT_CATEGORY,
    path: str | Path | None = None,
    settings_path: str | Path | None = None,
) -> tuple[dict, dict]:
    name = _clean_text(name, MAX_NAME) or "新模板"
    content = str(content or "")[:MAX_CONTENT]
    if not content.strip():
        raise ValueError("模板内容不能为空")
    category = normalize_category(category)
    token = f"custom-{int(time.time() * 1000):x}"
    template = {
        "id": token,
        "category": category,
        "name": name,
        "description": _clean_text(description, MAX_DESCRIPTION),
        "content": content,
        "builtin": False,
        "updated_at": time.time(),
    }
    templates = list(library.get("templates") or []) + [template]
    selected = {key: library.get(key) or "" for key in SELECTED_KEYS.values()}
    selected[SELECTED_KEYS[category]] = token
    saved = save_library(
        _library_payload(library, templates, selected),
        path=path,
        settings_path=settings_path,
    )
    return saved, template


def set_selected(
    library: dict,
    template_id: str,
    *,
    category: str = "",
    path: str | Path | None = None,
    settings_path: str | Path | None = None,
) -> dict:
    target = next(
        (item for item in library.get("templates") or [] if item.get("id") == template_id),
        None,
    )
    if target is None:
        raise KeyError(template_id)
    # 分类以模板自身为准；调用方传错分类也不会把模板挂到别人的选中键上。
    target_category = normalize_category(target.get("category"))
    if category and normalize_category(category) != target_category:
        raise ValueError("模板不属于该分类")
    selected = {key: library.get(key) or "" for key in SELECTED_KEYS.values()}
    selected[SELECTED_KEYS[target_category]] = template_id
    return save_library(
        _library_payload(library, library.get("templates") or [], selected),
        path=path,
        settings_path=settings_path,
    )


def delete_template(
    library: dict,
    template_id: str,
    *,
    path: str | Path | None = None,
    settings_path: str | Path | None = None,
) -> dict:
    templates = list(library.get("templates") or [])
    remaining = [item for item in templates if item.get("id") != template_id]
    if len(remaining) == len(templates):
        raise KeyError(template_id)
    selected = {key: library.get(key) or "" for key in SELECTED_KEYS.values()}
    for category, key in SELECTED_KEYS.items():
        if selected.get(key) == template_id:
            selected[key] = _first_in_category(remaining, category)
    return save_library(
        _library_payload(library, remaining, selected),
        path=path,
        settings_path=settings_path,
    )


def render_template(
    content: str,
    srt_text: str,
    lang_name: str,
    *,
    srt_a: str = "",
    srt_b: str = "",
    range_text: str = "",
) -> str:
    """把模板正文渲染成可粘贴的完整提示词。

    支持：``{{SRT}}`` / ``{{SRT_A}}`` / ``{{SRT_B}}`` / ``{{LANG}}`` / ``{{RANGE}}``，
    以及旧版的 ``__SRT__`` / ``__LANG__``。没有 SRT 占位符时把字幕追加到末尾。
    """
    text = str(content or "")
    srt = str(srt_text or "").strip()
    srt_a = str(srt_a or "").strip() or srt
    srt_b = str(srt_b or "").strip()
    lang = str(lang_name or "").strip() or "简体中文"
    # 先替换更长的 token，避免 {{SRT}} 抢先吃掉 {{SRT_A}} 的前缀。
    for token in ("{{SRT_A}}", "__SRT_A__"):
        text = text.replace(token, srt_a)
    for token in ("{{SRT_B}}", "__SRT_B__"):
        text = text.replace(token, srt_b)
    for token in ("{{SRT}}", "__SRT__"):
        text = text.replace(token, srt)
    for token in ("{{LANG}}", "__LANG__"):
        text = text.replace(token, lang)
    for token in ("{{RANGE_HINT}}", "__RANGE_HINT__", "{{RANGE}}", "__RANGE__"):
        text = text.replace(token, str(range_text or "").strip())
    has_range_placeholder = any(
        token in content
        for token in ("{{RANGE}}", "__RANGE__", "{{RANGE_HINT}}", "__RANGE_HINT__")
    )
    if range_text and not has_range_placeholder:
        # 旧模板没有范围占位符：分段时把「只输出第 k~m 条」放在最前面，
        # 保证长片分段复制不会让模型误以为要输出整片。
        text = str(range_text).strip() + "\n\n" + text

    has_srt_placeholder = any(
        token in content for token in ("{{SRT}}", "__SRT__", "{{SRT_A}}", "__SRT_A__")
    )
    if not has_srt_placeholder:
        text = text.rstrip() + "\n\n<subtitles>\n" + srt + "\n</subtitles>"
        if srt_b:
            text += "\n\n<reference_b>\n" + srt_b + "\n</reference_b>"
    return text


def render_prompt(
    srt_text: str,
    lang_name: str,
    *,
    template_id: str | None = None,
    category: str = DEFAULT_CATEGORY,
    srt_a: str = "",
    srt_b: str = "",
    range_text: str = "",
    path: str | Path | None = None,
    settings_path: str | Path | None = None,
) -> tuple[str, dict | None]:
    library = load_library(path=path, settings_path=settings_path)
    template = find_template(library, template_id, category)
    if template is None:
        return "", None
    return (
        render_template(
            template["content"],
            srt_text,
            lang_name,
            srt_a=srt_a,
            srt_b=srt_b,
            range_text=range_text,
        ),
        template,
    )
