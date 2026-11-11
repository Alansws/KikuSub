"""可编辑的提示词模板库。

「手动粘贴通道」原本把提示词写死在 ``core/ai_translate.MANUAL_PROMPT`` 里。用户
需要在网页版模型和不同翻译风格之间切换，所以模板必须变成可保存、可编辑、可选中
的数据，而不是改一次代码换一次提示词。

设计约束：

- 文件是普通 JSON，放在 ``settings.json`` 旁边，原子写；
- 内置模板（legacy / localization）始终存在；用户对它们的修改会持久化，删掉文件
  就回到出厂文案；
- 模板正文支持两个占位符：``{{SRT}}``（当前字幕）与 ``{{LANG}}``（目标语种）。
  没有 ``{{SRT}}`` 时自动把 SRT 追加到末尾，这样用户可以直接粘贴一份纯指令模板；
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
1. 彻底去除翻译腔（母语化）：严禁机翻和二次元生硬翻译腔（避免通篇“呐…”、“毕竟…呢”、“……的说”等）。请想象一位真实的中文母语者在耳边低语调情，用最地道、顺畅的中文日常口语重构台词。
2. 性暗示与动作具象化：日语习惯用代词、拟声词或委婉语表达生理状态与身体互动。翻译时请结合视听画面与上下文，将其意译为生动、有画面感的中文生理/性爱动作描写，不要浮于表面字面。
3. 自然补全人称代词：日语音频极常省略主语和宾语。请结合互动视听情境，自然补全“我/你/看我/我的”等代词，强化听众的代入感与视听沉浸感。
4. 跨字幕语流连贯：当一句话被切分在多行时间戳内，或遇到日式倒装时，请在保留原时间戳的前提下，让多行字幕在阅读逻辑上像一句连贯自然的中文，避免碎片感。
5. 准确捕捉人设语气：综合全篇把握角色的微表情与语调（如：是主导挑逗、娇嗔撒娇、还是沉溺享受），用中文地道的虚词（“可”、“倒”、“吧”、“呢”、“行”、“看你…”）还原角色的情绪拉扯感。
【格式要求】严格保留原 SRT 的序号和时间戳不变。仅输出翻译后的简体中文内容，不要解释、不要 markdown 代码块。
内容如下：
{{SRT}}"""

DEFAULT_TEMPLATES: list[dict] = [
    {
        "id": LEGACY_ID,
        "name": "原有模板",
        "description": "带序号与时间戳的通用翻译提示词，适合大多数网页版模型。",
        "content": LEGACY_CONTENT,
        "builtin": True,
    },
    {
        "id": LOCALIZATION_ID,
        "name": "成熟汉化组",
        "description": "去翻译腔、性张力与画面感；面向成人互动作品的口语化本地化。",
        "content": LOCALIZATION_CONTENT,
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
    return {
        "id": template_id,
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
            "name": item["name"],
            "description": item["description"],
            "content": item["content"],
            "builtin": True,
            "updated_at": now,
        }
        for item in DEFAULT_TEMPLATES
    ]


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
    for default in defaults:
        override = by_id.pop(default["id"], None)
        if override is not None:
            templates.append(
                {
                    "id": default["id"],
                    "name": override["name"] or default["name"],
                    "description": override["description"] or default["description"],
                    "content": override["content"] or default["content"],
                    "builtin": True,
                    "updated_at": override["updated_at"] or default["updated_at"],
                }
            )
        else:
            templates.append(default)

    # 用户自建模板按 id 排序，保证多次读取顺序稳定
    for template in sorted(by_id.values(), key=lambda item: (item["name"], item["id"])):
        template["builtin"] = False
        templates.append(template)

    selected = _clean_text(saved.get("selected"), 64)
    ids = {item["id"] for item in templates}
    if selected not in ids:
        selected = templates[0]["id"] if templates else ""
    return {"version": LIBRARY_VERSION, "selected": selected, "templates": templates}


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


def save_library(library: dict, path: str | Path | None = None, settings_path: str | Path | None = None) -> dict:
    target = Path(path) if path is not None else default_prompts_path(settings_path)
    normalized = _normalize_library(library)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(target, json.dumps(normalized, ensure_ascii=False, indent=2) + "\n")
    return normalized


def find_template(library: dict, template_id: str | None = None) -> dict | None:
    wanted = _clean_text(template_id, 64) or _clean_text(library.get("selected"), 64)
    for item in library.get("templates") or []:
        if item.get("id") == wanted:
            return item
    templates = library.get("templates") or []
    return templates[0] if templates else None


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
        merged["updated_at"] = time.time()
        updated.append(merged)
    if not found:
        raise KeyError(template_id)
    return save_library(
        {"version": LIBRARY_VERSION, "selected": library.get("selected"), "templates": updated},
        path=path,
        settings_path=settings_path,
    )


def create_template(
    library: dict,
    name: str,
    content: str,
    description: str = "",
    *,
    path: str | Path | None = None,
    settings_path: str | Path | None = None,
) -> tuple[dict, dict]:
    name = _clean_text(name, MAX_NAME) or "新模板"
    content = str(content or "")[:MAX_CONTENT]
    if not content.strip():
        raise ValueError("模板内容不能为空")
    token = f"custom-{int(time.time() * 1000):x}"
    template = {
        "id": token,
        "name": name,
        "description": _clean_text(description, MAX_DESCRIPTION),
        "content": content,
        "builtin": False,
        "updated_at": time.time(),
    }
    templates = list(library.get("templates") or []) + [template]
    saved = save_library(
        {"version": LIBRARY_VERSION, "selected": library.get("selected"), "templates": templates},
        path=path,
        settings_path=settings_path,
    )
    return saved, template


def set_selected(
    library: dict,
    template_id: str,
    *,
    path: str | Path | None = None,
    settings_path: str | Path | None = None,
) -> dict:
    ids = {item.get("id") for item in library.get("templates") or []}
    if template_id not in ids:
        raise KeyError(template_id)
    return save_library(
        {"version": LIBRARY_VERSION, "selected": template_id, "templates": library.get("templates") or []},
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
    remaining = [
        item for item in (library.get("templates") or []) if item.get("id") != template_id
    ]
    if len(remaining) == len(library.get("templates") or []):
        raise KeyError(template_id)
    selected = library.get("selected")
    if selected == template_id:
        selected = remaining[0]["id"] if remaining else ""
    return save_library(
        {"version": LIBRARY_VERSION, "selected": selected, "templates": remaining},
        path=path,
        settings_path=settings_path,
    )


def render_template(content: str, srt_text: str, lang_name: str) -> str:
    """把模板正文渲染成可粘贴的完整提示词。

    支持三种写法（兼容旧模板）：``{{SRT}}`` / ``{{LANG}}`` 以及旧版的
    ``__SRT__`` / ``__LANG__``。没有 SRT 占位符时把字幕追加到末尾。
    """
    text = str(content or "")
    srt = str(srt_text or "").strip()
    lang = str(lang_name or "").strip() or "简体中文"
    for token in ("{{SRT}}", "__SRT__"):
        text = text.replace(token, srt)
    for token in ("{{LANG}}", "__LANG__"):
        text = text.replace(token, lang)
    if "{{SRT}}" not in content and "__SRT__" not in content:
        text = text.rstrip() + "\n\n<subtitles>\n" + srt + "\n</subtitles>"
    return text


def render_prompt(
    srt_text: str,
    lang_name: str,
    *,
    template_id: str | None = None,
    path: str | Path | None = None,
    settings_path: str | Path | None = None,
) -> tuple[str, dict | None]:
    library = load_library(path=path, settings_path=settings_path)
    template = find_template(library, template_id)
    if template is None:
        return "", None
    return render_template(template["content"], srt_text, lang_name), template
