"""AI 提案（proposal）：源指纹、结构校验、应用。**无 UI / 无网络 / 无 torch 依赖。**

提案是「AI 的产出」与「软件的核对台」之间唯一的交接格式，契约见
`docs/AI优化与翻译-开发文档-2026-11.md` §3。三条不可动摇的性质：

1. **不含时间戳**（文档 D-1）：模型只收发 ``{i, text}``，时间码由软件 join 回去。
   「时间轴绝对不变」是**结构保证**，不是提示词承诺——任何实现都不得把
   ``start``/``end`` 放进送给模型的载荷，也不得从提案里读取时间码。
2. **条目列满**（文档 D-6）：``items`` 必须与源字幕逐条对应，``i`` 从 1 连续到 n。
   允许「没改动」，不允许「缺一条」——缺一条就会在应用后留下空字幕。
3. **绑定源文本**（文档 §3.2）：``source.digest`` 是源文本列表的 sha256，
   防止把 A 片生成的建议套到 B 片上。前端不得自己算这个值，一切以服务端为准。

``apply_polish`` 只做三件事：按 ``accept`` 挑条、按 ``edits`` 覆盖、**保留原时间码**。
它不重排、不过滤、不合并——那些都会让「时间轴不变」这条保证失效。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .subtitles import SubtitleCue

PROPOSAL_VERSION = 1
KINDS = ("polish", "translate")

# 单条文本相对源文本的最大膨胀倍数：超过就判定模型改写了这一句（见 §4.2.1）。
MAX_TEXT_GROWTH = 3
# 改动率超过这个比例时提示用户确认（防止模型整体改写原话，见 §9 R1）。
WARN_CHANGE_RATE = 0.40
# 一次最多回传多少条 warning，避免把几千条一起塞进响应体。
WARNING_LIMIT = 20


# --------------------------------------------------------------------------- 源指纹


def texts_of(cues: list[SubtitleCue]) -> list[str]:
    return [cue.text for cue in cues]


def source_digest(texts: list[str]) -> str:
    """源文本列表的 sha256（契约见文档 §3.2，agent 必须能逐字节复现）。

    规则：每条 ``f"{1 起的序号}\\t{去首尾空白的文本}"``，用 ``\\n`` 连接，
    **末尾不加换行**，UTF-8 编码。
    """
    lines = [f"{idx}\t{str(text).strip()}" for idx, text in enumerate(texts, start=1)]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- 路径


def proposal_path(output_dir: Path | str, stem: str, kind: str, lang: str = "") -> Path:
    """提案文件位置（文档 §3.3）。润色与翻译用不同后缀，互不覆盖。"""
    base = str(stem or "").strip() or "subtitles"
    root = Path(output_dir)
    if kind == "translate":
        code = str(lang or "").strip() or "und"
        return root / f"{base}.{code}.ai-translate.json"
    return root / f"{base}.ai-polish.json"


# --------------------------------------------------------------------------- 构造 / 读写


def build_proposal(
    *,
    kind: str,
    src_lang: str,
    texts: list[str],
    items: list[dict],
    model: str = "",
    entry: str = "in-app",
    dst_lang: str = "",
    glossary: list[dict] | None = None,
    chunks: int = 1,
    source_path: str = "",
    created_at: float | None = None,
) -> dict:
    """组装一份提案 dict。``items`` 由调用方按 ``{i, after}`` 准备。"""
    import time

    data: dict = {
        "version": PROPOSAL_VERSION,
        "kind": kind,
        "src_lang": str(src_lang or ""),
        "source": {
            "path": str(source_path or ""),
            "count": len(texts),
            "digest": source_digest(texts),
        },
        "model": str(model or ""),
        "entry": str(entry or "in-app"),
        "created_at": float(created_at if created_at is not None else time.time()),
        "chunks": int(chunks or 1),
        "items": list(items),
    }
    if kind == "translate":
        data["dst_lang"] = str(dst_lang or "")
    if glossary:
        data["glossary"] = list(glossary)
    return data


def dump_proposal(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def load_proposal(path: Path) -> dict | None:
    """读提案；不存在/损坏一律返回 None（由路由决定怎么报错）。"""
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------- 校验


@dataclass
class ProposalCheck:
    ok: bool
    status: int = 200
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    digest_match: bool = False
    # i -> 实际采用的文本（已做「空 / 超长退回原文」的兜底）
    effective: dict[int, str] = field(default_factory=dict)


def _effective_after(after, source_text: str) -> tuple[str, str]:
    """单条文本的兜底：空或离谱地长，就退回原文。返回 (文本, 警告)。"""
    text = after if isinstance(after, str) else ""
    if not text.strip():
        return source_text, "空文本已退回原文"
    src = str(source_text or "").strip()
    if src and len(text) > len(src) * MAX_TEXT_GROWTH:
        return source_text, "长度异常已退回原文"
    return text, ""


def validate_proposal(data: dict, texts: list[str]) -> ProposalCheck:
    """结构校验 + 源指纹校验。**结构错误 422 优先于指纹错误 409。**

    错误不抛异常，交给路由转成 HTTP 状态码，这样纯函数也能被单测直接断言。
    """
    n = len(texts)

    def fail(message: str) -> ProposalCheck:
        return ProposalCheck(ok=False, status=422, errors=[message])

    if not isinstance(data, dict):
        return fail("提案必须是一个 JSON 对象")
    if data.get("version") != PROPOSAL_VERSION:
        return fail(f"提案版本不支持：{data.get('version')!r}（只接受 {PROPOSAL_VERSION}）")
    kind = data.get("kind")
    if kind not in KINDS:
        return fail(f"未知的提案类型：{kind!r}")

    items = data.get("items")
    if not isinstance(items, list):
        return fail("items 必须是数组")
    if len(items) != n:
        return fail(f"条目数不符：提案 {len(items)} 条，当前字幕 {n} 条")

    seen: set[int] = set()
    warnings: list[str] = []
    effective: dict[int, str] = {}
    changed = 0

    for item in items:
        if not isinstance(item, dict):
            return fail("items 里的每一项都必须是对象")
        idx = item.get("i")
        if not isinstance(idx, int) or isinstance(idx, bool):
            return fail(f"序号必须是整数：{idx!r}")
        if not 1 <= idx <= n:
            return fail(f"序号越界：{idx}（有效范围 1–{n}）")
        if idx in seen:
            return fail(f"序号重复：{idx}")
        seen.add(idx)
        after = item.get("after")
        if not isinstance(after, str):
            return fail(f"第 {idx} 条的 after 必须是字符串")
        text, note = _effective_after(after, texts[idx - 1])
        effective[idx] = text
        if note:
            warnings.append(f"第 {idx} 条：{note}")
        if text != texts[idx - 1]:
            changed += 1
            if kind == "polish" and not str(item.get("note") or "").strip():
                warnings.append(f"第 {idx} 条改动了但没有写理由")

    missing = sorted(set(range(1, n + 1)) - seen)
    if missing:
        return fail(f"缺少序号：{missing[:8]}{'…' if len(missing) > 8 else ''}")

    digest = str((data.get("source") or {}).get("digest") or "")
    expected = source_digest(texts)
    if digest != expected:
        return ProposalCheck(
            ok=False,
            status=409,
            errors=["源文本已变化：提案是针对另一版字幕生成的，请重新生成"],
            digest_match=False,
        )

    if kind == "polish" and n and changed / n > WARN_CHANGE_RATE:
        warnings.append(
            f"改动率 {changed / n * 100:.0f}%（{changed}/{n}），超过 {WARN_CHANGE_RATE * 100:.0f}%：模型可能整体改写了原话"
        )

    return ProposalCheck(
        ok=True,
        status=200,
        warnings=_trim(warnings),
        digest_match=True,
        effective=effective,
    )


def _trim(warnings: list[str]) -> list[str]:
    if len(warnings) <= WARNING_LIMIT:
        return warnings
    kept = warnings[:WARNING_LIMIT]
    kept.append(f"…另有 {len(warnings) - WARNING_LIMIT} 条提示未列出")
    return kept


# --------------------------------------------------------------------------- 应用


def apply_polish(
    source: list[SubtitleCue],
    items: list[dict],
    accept: set[int] | None = None,
    edits: dict[int, str] | None = None,
) -> tuple[list[SubtitleCue], int]:
    """把提案写回字幕列表，**时间码原样保留**。

    ``accept``：采纳的序号集合；``None`` 表示全采纳，空集合表示全拒绝。
    ``edits``：用户在右栏手工改过的文本，优先于提案原文（同样过兜底）。

    返回 ``(新字幕列表, 实际改动条数)``。不修改传入的 ``source``。
    """
    by_index = {int(item["i"]): item for item in items if isinstance(item.get("i"), int)}
    edit_map = {int(k): str(v) for k, v in (edits or {}).items()}
    out: list[SubtitleCue] = []
    changed = 0

    for idx, cue in enumerate(source, start=1):
        text = cue.text
        wanted = accept is None or idx in accept
        if wanted:
            if idx in edit_map:
                text, _ = _effective_after(edit_map[idx], cue.text)
            elif idx in by_index:
                text, _ = _effective_after(by_index[idx].get("after"), cue.text)
        if text != cue.text:
            changed += 1
        # 注意：start / end 一律取自 cue，提案里的任何时间字段都不参与。
        out.append(SubtitleCue(start=cue.start, end=cue.end, text=text))

    return out, changed
