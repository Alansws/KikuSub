"""AI 提案（proposal）：源指纹、结构校验、应用。**无 UI / 无网络 / 无 torch 依赖。**

提案是「AI 的产出」与「软件的核对台」之间唯一的交接格式，契约见
`docs/contracts/ai-proposal.md`（冻结决定 D-1～D-6 在 §0.1）。三条不可动摇的性质：

1. **不含时间戳**（文档 D-1）：模型只收发 ``{i, text}``，时间码由软件 join 回去。
   「时间轴绝对不变」是**结构保证**，不是提示词承诺——任何实现都不得把
   ``start``/``end`` 放进送给模型的载荷，也不得从提案里读取时间码。
2. **条目列满**（文档 D-6）：``items`` 必须与源字幕逐条对应，``i`` 从 1 连续到 n。
   允许「没改动」，不允许「缺一条」——缺一条就会在应用后留下空字幕。
3. **绑定源文本**（文档 §3.2）：``source.digest`` 是源文本列表的 sha256，
   防止把 A 片生成的建议套到 B 片上。前端不得自己算这个值，一切以服务端为准。

``apply_polish`` 只做三件事：按 ``accept`` 挑条、按 ``edits`` 覆盖、**保留原时间码**。
它不重排、不过滤、不合并——那些都会让「时间轴不变」这条保证失效。

## 片段范围（2026-11-20 新增）

长片可以只处理一段（例如第 291–581 条）。这时提案的 ``source.range`` 记录
``{"from": 291, "to": 581, "count": 291}``：

- **digest 只覆盖这一段**（``source_digest(scope_texts)``）——模型看到多少、绑定多少，
  段外的字幕改了也不会误拒绝（那本来就不该让这段提案失效）；
- **``i`` 仍是全片的 1 基序号**（291…581），界面因此可以直接用全局 ``#i`` 对行，
  粘贴回来的分段合并也不用换坐标系；
- ``validate_proposal`` / ``apply_polish_range`` 用 ``span`` 把全局序号映射到这一段，
  ``apply_polish`` 仍是唯一的写回实现（只换索引口径，不复制逻辑）。

没有 ``source.range`` 的旧提案行为完全不变（``span = (1, n)``）。
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


# --------------------------------------------------------------------------- 片段范围


def cue_range(data: dict) -> tuple[int, int] | None:
    """提案声明的片段范围（1 基、含两端）；整片 / 旧提案返回 None。"""
    if not isinstance(data, dict):
        return None
    raw = (data.get("source") or {}).get("range")
    if not isinstance(raw, dict):
        return None
    try:
        first = int(raw.get("from"))
        last = int(raw.get("to"))
    except (TypeError, ValueError):
        return None
    if first < 1 or last < first:
        return None
    return first, last


def source_span(data: dict, total: int) -> tuple[int, int]:
    """提案实际作用的全片序号区间（1 基、含两端）。没有 range 时是整片。

    非法范围抛 ``ValueError``，由路由转成 422：宁可拒绝，也不要拿一个错位的
    span 去切片（那会把译文写进别的句子）。
    """
    size = max(0, int(total or 0))
    span = cue_range(data)
    if span is None:
        return (1, size)
    first, last = span
    if size <= 0 or first > size:
        raise ValueError(f"提案的片段范围越界：第 {first}–{last} 条（当前 {size} 条）")
    last = min(last, size)
    if last < first:
        raise ValueError(f"提案的片段范围不合法：第 {first}–{last} 条（当前 {size} 条）")
    return (first, last)




# --------------------------------------------------------------------------- 构造 / 读写


def build_proposal(
    *,
    kind: str,
    src_lang: str,
    texts: list[str],
    items: list[dict],
    texts_b: list[str] | None = None,
    model: str = "",
    entry: str = "in-app",
    dst_lang: str = "",
    glossary: list[dict] | None = None,
    chunks: int = 1,
    source_path: str = "",
    created_at: float | None = None,
    cue_span: tuple[int, int] | None = None,
) -> dict:
    """组装一份提案 dict。``items`` 由调用方按 ``{i, after}`` 准备。

    ``texts_b`` 只在双源润色时传入：``source`` 会额外落一份 ``digest_b``，
    应用前据此确认「第二版字幕没有在生成提案之后被换掉」。

    ``cue_span`` 只在片段模式下传入：``source.range`` 记录这一段在全片的
    1 基序号区间（``items`` 的 ``i`` 也用全片序号），``digest`` 仍是**这一段**
    原文的指纹——模型看到多少就绑定多少。
    """
    import time

    source: dict = {
        "path": str(source_path or ""),
        "count": len(texts),
        "digest": source_digest(texts),
    }
    if cue_span is not None:
        first, last = int(cue_span[0]), int(cue_span[1])
        source["range"] = {"from": first, "to": last, "count": len(texts)}
    if texts_b is not None:
        source["count_b"] = len(texts_b)
        source["digest_b"] = source_digest(texts_b)
    data: dict = {
        "version": PROPOSAL_VERSION,
        "kind": kind,
        "src_lang": str(src_lang or ""),
        "source": source,
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


def _effective_after(
    after, source_text: str, *, allow_empty: bool = False
) -> tuple[str, str]:
    """单条文本的兜底：空或离谱地长，就退回原文。返回 (文本, 警告)。

    ``allow_empty`` 只给**翻译**用：一条译文跨多句时，被合并覆盖的槽位与
    「原句没匹配到译文」的槽位在语义上就是空，强行把日语原文填进译文轨会让
    双语画面出现一整行日文。空值仍是合法槽位，只是不写入文本。
    """
    text = after if isinstance(after, str) else ""
    if not text.strip():
        if allow_empty:
            return "", ""
        return source_text, "空文本已退回原文"
    src = str(source_text or "").strip()
    if src and len(text) > len(src) * MAX_TEXT_GROWTH:
        return source_text, "长度异常已退回原文"
    return text, ""


def validate_proposal(
    data: dict,
    texts: list[str],
    texts_b: list[str] | None = None,
    span: tuple[int, int] | None = None,
) -> ProposalCheck:
    """结构校验 + 源指纹校验。**结构错误 422 优先于指纹错误 409。**

    ``texts_b``：当前第二版字幕。双源提案带 ``source.digest_b`` 时**必须**提供并
    匹配；**B 的条数不要求等于 A**（两个引擎断句不同），只校验指纹。
    单源提案（没有 digest_b）即使当前存在第二版也照旧只校验 A，保持
    ``desktop/resources/skill/`` 与旧提案 100% 向后兼容。

    ``texts`` 是这份提案**绑定**的原文：片段模式下已经被切到该段（与
    ``source.digest`` 同一份），``span`` 是这段在全片的 1 基序号区间，
    用来解释 ``items`` 里那些**全片序号**。``span=None`` = 整片（旧行为）。

    错误不抛异常，交给路由转成 HTTP 状态码，这样纯函数也能被单测直接断言。
    """
    n = len(texts)
    first, last = (1, n) if span is None else (int(span[0]), int(span[1]))
    scoped = span is not None

    def fail(message: str) -> ProposalCheck:
        return ProposalCheck(ok=False, status=422, errors=[message])

    if not isinstance(data, dict):
        return fail("提案必须是一个 JSON 对象")
    if data.get("version") != PROPOSAL_VERSION:
        return fail(f"提案版本不支持：{data.get('version')!r}（只接受 {PROPOSAL_VERSION}）")
    kind = data.get("kind")
    if kind not in KINDS:
        return fail(f"未知的提案类型：{kind!r}")
    if scoped and (first < 1 or last < first or last - first + 1 != n):
        return fail(f"片段范围与提案条数不符：第 {first}–{last} 条 vs {n} 条")

    items = data.get("items")
    if not isinstance(items, list):
        return fail("items 必须是数组")
    if len(items) != n:
        where = f"第 {first}–{last} 条" if scoped else "当前字幕"
        return fail(f"条目数不符：提案 {len(items)} 条，{where} {n} 条")

    seen: set[int] = set()
    warnings: list[str] = []
    effective: dict[int, str] = {}
    changed = 0
    # 手动粘贴通道只有 SRT，没有修改理由；逐条提示「没有写理由」只会刷屏。
    # 来源仍然由 entry=manual 表达，不靠每条的 note。
    need_note = kind == "polish" and str(data.get("entry") or "") != "manual"

    for item in items:
        if not isinstance(item, dict):
            return fail("items 里的每一项都必须是对象")
        idx = item.get("i")
        if not isinstance(idx, int) or isinstance(idx, bool):
            return fail(f"序号必须是整数：{idx!r}")
        if not first <= idx <= last:
            return fail(f"序号越界：{idx}（有效范围 {first}–{last}）")
        if idx in seen:
            return fail(f"序号重复：{idx}")
        seen.add(idx)
        after = item.get("after")
        if not isinstance(after, str):
            return fail(f"第 {idx} 条的 after 必须是字符串")
        source_text = texts[idx - first]
        text, note = _effective_after(
            after, source_text, allow_empty=(kind == "translate")
        )
        effective[idx] = text
        if note:
            warnings.append(f"第 {idx} 条：{note}")
        if text != source_text:
            changed += 1
            if need_note and not str(item.get("note") or "").strip():
                warnings.append(f"第 {idx} 条改动了但没有写理由")

    missing = sorted(set(range(first, last + 1)) - seen)
    if missing:
        return fail(f"缺少序号：{missing[:8]}{'…' if len(missing) > 8 else ''}")

    source = data.get("source") or {}
    digest = str(source.get("digest") or "")
    expected = source_digest(texts)
    if digest != expected:
        return ProposalCheck(
            ok=False,
            status=409,
            errors=["源文本已变化：提案是针对另一版字幕生成的，请重新生成"],
            digest_match=False,
        )

    digest_b = str(source.get("digest_b") or "")
    if digest_b:
        if texts_b is None:
            return ProposalCheck(
                ok=False,
                status=409,
                errors=["这份提案绑定了第二版字幕，但当前没有第二版：请重新生成或先导入第二版"],
                digest_match=False,
            )
        if digest_b != source_digest(texts_b):
            return ProposalCheck(
                ok=False,
                status=409,
                errors=["第二版源文本已变化：提案是针对另一版第二稿生成的，请重新生成"],
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


def apply_polish_range(
    source: list[SubtitleCue],
    items: list[dict],
    span: tuple[int, int] | None = None,
    accept: set[int] | None = None,
    edits: dict[int, str] | None = None,
) -> tuple[list[SubtitleCue], int]:
    """片段版 ``apply_polish``：只换索引口径，**写回仍调用 apply_polish**。

    ``span`` 是提案作用的全片 1 基区间（``None`` = 整片）。``items`` / ``accept`` /
    ``edits`` 都用全片序号，这里映射成这一段内部的序号后交给 ``apply_polish``；
    段外条目原样拼回，一个字节都不动。返回 ``(整片新字幕, 改动条数)``。
    """
    total = len(source)
    first, last = (1, total) if span is None else (int(span[0]), int(span[1]))
    first = max(1, min(first, max(1, total)))
    last = max(first, min(last, total))
    scoped = source[first - 1 : last]
    local_items: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("i"))
        except (TypeError, ValueError):
            continue
        mapped = dict(item)
        mapped["i"] = idx - first + 1
        local_items.append(mapped)
    local_accept = (
        None
        if accept is None
        else {int(i) - first + 1 for i in accept if first <= int(i) <= last}
    )
    local_edits = {
        int(k) - first + 1: str(v)
        for k, v in (edits or {}).items()
        if first <= int(k) <= last
    }
    new_slice, changed = apply_polish(
        scoped, local_items, accept=local_accept, edits=local_edits
    )
    return [*source[: first - 1], *new_slice, *source[last:]], changed
