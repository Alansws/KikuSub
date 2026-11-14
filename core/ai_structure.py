"""结构建议（Phase 1）：合并 / 改时间 / 改字 / 新增 / 删除。

这是**独立于润色提案**的第二条车道。润色提案只认 ``{i, after}``，时间轴永远
取自 A（D-1）；结构建议要动断句与时间轴，所以单独一种提案、单独一个文件、
单独一次原子应用，绝不混进 ``ai_proposal.apply_polish()``。

外部模型只输出极简 JSON::

    {"ops": [ ... ]}

**不让模型输出 version / kind / digest**：网页版模型算不出本地哈希，抄也容易抄错。
``version/kind/source.digest/revision`` 全部由本地在「粘贴入库」那一刻绑定。
所有 ops 的下标都是**应用前当前字幕的 1-based 原序号**；一次应用只压一步历史。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import ai_proposal as proposals
from .subtitles import SubtitleCue, cues_to_srt, join_cue_texts

STRUCTURE_VERSION = 1
KIND = "structure"
SUPPORTED_OPS = ("merge", "retime", "replace_text", "insert", "delete")
# 一次粘贴最多多少条操作：防止误贴一整段对话把界面卡死。
MAX_OPS = 500
# 时间比较的浮点容差（毫秒级）。
EPS = 1e-6

OP_LABELS = {
    "merge": "合并",
    "retime": "改时间",
    "replace_text": "改文字",
    "insert": "新增",
    "delete": "删除",
}

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


class StructureError(ValueError):
    """结构建议的语法/字段错误（路由转 422，字幕零改动）。"""


class StructureConflict(ValueError):
    """选中的操作之间/与当前字幕有冲突（路由转 409，字幕零改动）。"""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("；".join(self.errors[:3]))


# --------------------------------------------------------------------------- 路径


def structure_path(output_dir: Path | str, stem: str) -> Path:
    """结构建议文件：与润色/翻译提案并列，但**不共用**文件名。"""
    base = str(stem or "").strip() or "subtitles"
    return Path(output_dir) / f"{base}.ai-structure.json"


def dump_proposal(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def load_proposal(path: Path | str) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("version") != STRUCTURE_VERSION or data.get("kind") != KIND:
        return None
    if not isinstance(data.get("source"), dict):
        return None
    if not isinstance(data.get("ops"), list):
        return None
    return data


def build_proposal(
    cues: list[SubtitleCue],
    ops: list[dict],
    *,
    revision: str = "",
    source_path: str = "",
) -> dict:
    """本地包装：补上模型不负责的 version/kind/源指纹/revision。"""
    texts = [cue.text for cue in cues]
    return {
        "version": STRUCTURE_VERSION,
        "kind": KIND,
        "source": {
            "path": str(source_path or ""),
            "count": len(texts),
            "digest": proposals.source_digest(texts),
        },
        "revision": str(revision or uuid.uuid4().hex),
        "created_at": time.time(),
        "ops": [dict(op) for op in ops],
    }


def current_digest(cues: list[SubtitleCue]) -> str:
    return proposals.source_digest([cue.text for cue in cues])


def source_matches(data: dict, cues: list[SubtitleCue]) -> bool:
    """提案绑定的源指纹是否仍是当前字幕；apply 前必须过。"""
    source = data.get("source") or {}
    return str(source.get("digest") or "") == current_digest(cues)


# --------------------------------------------------------------------------- 解析


def _balanced_json(text: str, start: int) -> str:
    """从 ``start`` 的 { 或 [ 开始，找配对的结尾（跳过字符串里的括号）。"""
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for pos in range(start, len(text)):
        char = text[pos]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : pos + 1]
    return text[start:]


def _loads_first_json(text: str) -> Any:
    """容忍 markdown 围栏和前后解释：逐个尝试第一个能解析的 JSON 值。"""
    fenced = _FENCE_RE.search(text)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except ValueError:
            pass
    starts: list[int] = []
    for opener in ("{", "["):
        pos = text.find(opener)
        while pos >= 0:
            starts.append(pos)
            pos = text.find(opener, pos + 1)
    for start in sorted(starts):
        try:
            return json.loads(_balanced_json(text, start))
        except ValueError:
            continue
    raise StructureError("没有找到合法的 JSON：需要外部模型返回 {\"ops\": [...]}")


def extract_ops(text: str) -> list[dict]:
    """从粘贴内容里取出 ops；空 ops 返回 []，由路由决定怎么提示。"""
    raw = str(text or "").strip()
    if not raw:
        raise StructureError("粘贴内容为空")
    payload = _loads_first_json(raw)
    if isinstance(payload, dict):
        ops = payload.get("ops")
    elif isinstance(payload, list):
        # 容忍模型直接回一个 ops 数组
        ops = payload
    else:
        raise StructureError("JSON 顶层必须是对象 {\"ops\": [...]} 或 ops 数组")
    if not isinstance(ops, list):
        raise StructureError("缺少 ops 数组")
    if len(ops) > MAX_OPS:
        raise StructureError(f"操作太多（{len(ops)} 条，最多 {MAX_OPS} 条）")
    out: list[dict] = []
    for index, item in enumerate(ops, start=1):
        if not isinstance(item, dict):
            raise StructureError(f"第 {index} 条 op 必须是对象")
        name = str(item.get("op") or "").strip()
        if name not in SUPPORTED_OPS:
            raise StructureError(
                f"第 {index} 条 op 不支持：{name!r}（只支持 {' / '.join(SUPPORTED_OPS)}）"
            )
        out.append(dict(item))
    return out


# --------------------------------------------------------------------------- 校验


def _as_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StructureError(f"{label} 必须是整数")
    return value


def _as_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StructureError(f"{label} 必须是数字")
    return float(value)


def _truncate(value: Any, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


def _add_conflict(view: dict, message: str) -> None:
    if message and message not in view["conflict"]:
        view["conflict"].append(message)


def _op_label(view: dict) -> str:
    return OP_LABELS.get(view["op"], view["op"])


@dataclass
class Preview:
    """一次预览的计算结果；``cues`` 只给 apply 用，不进 JSON 响应。"""

    views: list[dict]
    cues: list[SubtitleCue]
    warnings: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    @property
    def ops(self) -> list[dict]:
        return self.views

    def to_dict(self) -> dict:
        return {
            "ops": self.views,
            "warnings": self.warnings,
            "summary": self.summary,
        }


def _base_view(op_id: int, kind: str, reason: Any) -> dict:
    return {
        "id": op_id,
        "op": kind,
        "reason": _truncate(reason),
        "conflict": [],
        "before": "",
        "after": "",
        "text": "",
        "old_start": None,
        "old_end": None,
        "new_start": None,
        "new_end": None,
        "index_label": "",
        "from_index": None,
        "to_index": None,
        "after_index": None,
    }


def _merge_span(cues: list[SubtitleCue], start: int, end: int) -> tuple[float, float]:
    """合并区间的时间取 min(start)…max(end)，不信任模型给的时间。"""
    span = cues[start - 1 : end]
    # 合并区间的时间取原 cue 的精确 min/max；不要在这里 round，否则「时间轴
    # 取自 A」会被抹成毫秒。显示层/SRT 导出各自再格式化。
    return (
        min(cue.start for cue in span),
        max(cue.end for cue in span),
    )


def _preview(
    cues: list[SubtitleCue],
    ops: list[dict],
    *,
    translation_langs: list[str] | None = None,
) -> Preview:
    n = len(cues)
    views: list[dict] = []
    merges: list[dict] = []
    merge_by_from: dict[int, dict] = {}
    deletes: dict[int, dict] = {}
    replacements: dict[int, dict] = {}
    retimes: dict[int, dict] = {}
    inserts: dict[int, list[dict]] = {}

    for op_id, raw in enumerate(ops):
        kind = str(raw.get("op") or "").strip()
        if kind not in SUPPORTED_OPS:
            raise StructureError(f"第 {op_id + 1} 条 op 不支持：{kind!r}")
        view = _base_view(op_id, kind, raw.get("reason"))

        if kind == "merge":
            start = _as_int(raw.get("from"), f"第 {op_id + 1} 条 merge 的 from")
            end = _as_int(raw.get("to"), f"第 {op_id + 1} 条 merge 的 to")
            if not (1 <= start < end <= n):
                raise StructureError(
                    f"第 {op_id + 1} 条 merge 的范围不合法：{start}–{end}（当前 {n} 条）"
                )
            span = cues[start - 1 : end]
            before = join_cue_texts([cue.text for cue in span])
            text_value = raw.get("text")
            if text_value is not None and not isinstance(text_value, str):
                raise StructureError(f"第 {op_id + 1} 条 merge 的 text 必须是字符串")
            after = text_value.strip() if isinstance(text_value, str) else ""
            if not after:
                after = before
            old_start, old_end = _merge_span(cues, start, end)
            view.update(
                before=before,
                after=after,
                text=after,
                old_start=old_start,
                old_end=old_end,
                new_start=old_start,
                new_end=old_end,
                index_label=f"#{start}–#{end}",
                from_index=start,
                to_index=end,
            )
            merges.append(view)
            if start in merge_by_from:
                _add_conflict(merge_by_from[start], "同一个起始序号有多个合并操作")
                _add_conflict(view, "同一个起始序号有多个合并操作")
            else:
                merge_by_from[start] = view
            views.append(view)
            continue

        if kind == "delete":
            index = _as_int(raw.get("i"), f"第 {op_id + 1} 条 delete 的 i")
            if not 1 <= index <= n:
                raise StructureError(f"第 {op_id + 1} 条 delete 的 i 越界：{index}（当前 {n} 条）")
            cue = cues[index - 1]
            view.update(
                before=cue.text,
                old_start=round(cue.start, 3),
                old_end=round(cue.end, 3),
                index_label=f"#{index}",
            )
            if index in deletes:
                _add_conflict(deletes[index], "同一条字幕有多个删除操作")
                _add_conflict(view, "同一条字幕有多个删除操作")
            else:
                deletes[index] = view
            views.append(view)
            continue

        if kind == "replace_text":
            index = _as_int(raw.get("i"), f"第 {op_id + 1} 条 replace_text 的 i")
            if not 1 <= index <= n:
                raise StructureError(
                    f"第 {op_id + 1} 条 replace_text 的 i 越界：{index}（当前 {n} 条）"
                )
            after = raw.get("after")
            if not isinstance(after, str):
                raise StructureError(f"第 {op_id + 1} 条 replace_text 的 after 必须是字符串")
            cue = cues[index - 1]
            view.update(
                before=cue.text,
                after=after,
                text=after,
                old_start=round(cue.start, 3),
                old_end=round(cue.end, 3),
                index_label=f"#{index}",
            )
            if not after.strip():
                _add_conflict(view, "替换文本不能为空（要删整条请用 delete）")
            if index in replacements:
                _add_conflict(replacements[index], "同一条字幕有多个改文字操作")
                _add_conflict(view, "同一条字幕有多个改文字操作")
            else:
                replacements[index] = view
            views.append(view)
            continue

        if kind == "retime":
            index = _as_int(raw.get("i"), f"第 {op_id + 1} 条 retime 的 i")
            if not 1 <= index <= n:
                raise StructureError(f"第 {op_id + 1} 条 retime 的 i 越界：{index}（当前 {n} 条）")
            start = _as_float(raw.get("start"), f"第 {op_id + 1} 条 retime 的 start")
            end = _as_float(raw.get("end"), f"第 {op_id + 1} 条 retime 的 end")
            cue = cues[index - 1]
            view.update(
                before=cue.text,
                after=cue.text,
                old_start=round(cue.start, 3),
                old_end=round(cue.end, 3),
                index_label=f"#{index}",
            )
            if start < 0 or end <= start:
                _add_conflict(view, "时间范围不合法：必须 0 ≤ start < end")
            else:
                view.update(new_start=round(start, 3), new_end=round(end, 3))
            if index in retimes:
                _add_conflict(retimes[index], "同一条字幕有多个改时间操作")
                _add_conflict(view, "同一条字幕有多个改时间操作")
            else:
                retimes[index] = view
            views.append(view)
            continue

        # insert
        after_index = _as_int(raw.get("after"), f"第 {op_id + 1} 条 insert 的 after")
        if not 0 <= after_index <= n:
            raise StructureError(
                f"第 {op_id + 1} 条 insert 的 after 越界：{after_index}（允许 0–{n}）"
            )
        text = raw.get("text")
        if not isinstance(text, str):
            raise StructureError(f"第 {op_id + 1} 条 insert 的 text 必须是字符串")
        start = _as_float(raw.get("start"), f"第 {op_id + 1} 条 insert 的 start")
        end = _as_float(raw.get("end"), f"第 {op_id + 1} 条 insert 的 end")
        label = "最前" if after_index == 0 else f"#{after_index} 后"
        view.update(
            after=text,
            text=text,
            new_start=round(start, 3) if start >= 0 and end > start else None,
            new_end=round(end, 3) if start >= 0 and end > start else None,
            index_label=label,
            after_index=after_index,
        )
        if not text.strip():
            _add_conflict(view, "新增字幕的文本不能为空")
        if start < 0 or end <= start:
            _add_conflict(view, "时间范围不合法：必须 0 ≤ start < end")
        inserts.setdefault(after_index, []).append(view)
        views.append(view)

    # ---- 交叉冲突 ---------------------------------------------------------

    for left_pos, left in enumerate(merges):
        for right in merges[left_pos + 1 :]:
            if not (left["to_index"] < right["from_index"] or right["to_index"] < left["from_index"]):
                _add_conflict(left, "合并区间与另一条合并重叠")
                _add_conflict(right, "合并区间与另一条合并重叠")

    for merge in merges:
        for index in range(merge["from_index"], merge["to_index"] + 1):
            if index in deletes:
                _add_conflict(merge, f"合并区间包含第 {index} 条的删除操作")
                _add_conflict(deletes[index], f"与合并区间 {merge['index_label']} 冲突")
            if index in replacements:
                _add_conflict(merge, f"合并区间包含第 {index} 条的改文字操作")
                _add_conflict(replacements[index], f"与合并区间 {merge['index_label']} 冲突")
            if index in retimes:
                _add_conflict(merge, f"合并区间包含第 {index} 条的改时间操作")
                _add_conflict(retimes[index], f"与合并区间 {merge['index_label']} 冲突")

    for index in set(deletes) & set(replacements):
        _add_conflict(deletes[index], "同一条字幕同时被删除和改文字")
        _add_conflict(replacements[index], "同一条字幕同时被删除和改文字")
    for index in set(deletes) & set(retimes):
        _add_conflict(deletes[index], "同一条字幕同时被删除和改时间")
        _add_conflict(retimes[index], "同一条字幕同时被删除和改时间")

    for merge in merges:
        for boundary in range(merge["from_index"], merge["to_index"]):
            for insert in inserts.get(boundary, []):
                _add_conflict(
                    insert,
                    f"新增位置落在合并区间 {merge['index_label']} 内部",
                )

    # ---- 译文轨保护 -------------------------------------------------------

    langs = [str(lang) for lang in (translation_langs or []) if str(lang).strip()]
    if langs:
        label = "、".join(langs)
        for view in views:
            if view["op"] in ("merge", "insert", "delete"):
                _add_conflict(
                    view,
                    f"已有译文轨（{label}）：{_op_label(view)}会改变条数，请先处理译文",
                )

    # ---- 生成结果并做时间轴检查 ------------------------------------------

    entries = _build_entries(cues, views, inserts)
    for left, right in zip(entries, entries[1:]):
        if right["cue"].start < left["cue"].end - EPS:
            _pair_conflict(views, left, right, "时间重叠")
        elif right["cue"].start < left["cue"].start - EPS:
            _pair_conflict(views, left, right, "顺序不一致")
    new_cues = [entry["cue"] for entry in entries]

    conflicts = sum(1 for view in views if view["conflict"])
    counts = {name: 0 for name in SUPPORTED_OPS}
    for view in views:
        counts[view["op"]] += 1
    output_count = len(new_cues)
    warnings: list[str] = []
    if langs:
        warnings.append(
            f"已有译文轨（{'、'.join(langs)}）：合并/新增/删除不可用；改文字/改时间仍可应用。"
        )
    if output_count != n:
        warnings.append(f"应用后总条数 {n} → {output_count}。")
    if conflicts:
        warnings.append(f"有 {conflicts} 项冲突；冲突项不能勾选。")
    summary = {
        "input_count": n,
        "output_count": output_count,
        "total_ops": len(views),
        "conflicts": conflicts,
        "counts": counts,
    }
    return Preview(views=views, cues=new_cues, warnings=warnings, summary=summary)


def _entry(cue: SubtitleCue, blame: set[int], label: str) -> dict:
    return {"cue": cue, "blame": blame, "label": label}


def _build_entries(
    cues: list[SubtitleCue],
    views: list[dict],
    inserts: dict[int, list[dict]],
) -> list[dict]:
    """按原 1-based 序号一次生成新列表（绝不在循环里边应用边重算下标）。"""
    n = len(cues)
    merge_by_from = {v["from_index"]: v for v in views if v["op"] == "merge"}
    delete_indices = {
        int(v["index_label"].lstrip("#")): v for v in views if v["op"] == "delete"
    }
    replacements = {
        int(v["index_label"].lstrip("#")): v for v in views if v["op"] == "replace_text"
    }
    retimes = {
        int(v["index_label"].lstrip("#")): v for v in views if v["op"] == "retime"
    }
    out: list[dict] = []

    def append_inserts(boundary: int) -> None:
        for view in inserts.get(boundary, []):
            if view["new_start"] is None or view["new_end"] is None:
                continue
            if not str(view["text"] or "").strip():
                continue
            out.append(
                _entry(
                    SubtitleCue(view["new_start"], view["new_end"], view["text"]),
                    {view["id"]},
                    f"新增（{view['index_label']}）",
                )
            )

    append_inserts(0)
    index = 1
    while index <= n:
        merge = merge_by_from.get(index)
        if merge is not None:
            out.append(
                _entry(
                    SubtitleCue(merge["new_start"], merge["new_end"], merge["after"]),
                    {merge["id"]},
                    merge["index_label"],
                )
            )
            index = merge["to_index"] + 1
            append_inserts(merge["to_index"])
            continue
        if index in delete_indices:
            append_inserts(index)
            index += 1
            continue
        cue = cues[index - 1]
        start, end, text = cue.start, cue.end, cue.text
        blame: set[int] = set()
        replace = replacements.get(index)
        if replace is not None and str(replace["after"]).strip():
            text = replace["after"]
            blame.add(replace["id"])
        retime = retimes.get(index)
        if retime is not None and retime["new_start"] is not None:
            start, end = retime["new_start"], retime["new_end"]
            blame.add(retime["id"])
        out.append(
            # 没动时间的条目必须保留原始时间（replace_text 只改字，不能顺手把
            # 6 位小数的 start/end 抹成 3 位；那会让「时间轴不变」失真）。
            _entry(SubtitleCue(start, end, text), blame, f"#{index}")
        )
        append_inserts(index)
        index += 1
    return out


def _pair_conflict(views: list[dict], left: dict, right: dict, kind: str) -> None:
    """时间重叠/顺序不一致时，只把责任落到**改时间**的那一侧。

    改文字/删除不会造成时间重叠；如果把 replace_text 也标红，用户会以为
    「改个字也不让用」。原句之间本来就重叠时两边都没有时间 op，直接忽略。
    """
    for source, target in ((left, right), (right, left)):
        if not source["blame"]:
            continue
        message = f"与 {target['label']} {kind}"
        for view_id in source["blame"]:
            if not 0 <= view_id < len(views):
                continue
            if views[view_id]["op"] in ("merge", "retime", "insert"):
                _add_conflict(views[view_id], message)


def preview(
    cues: list[SubtitleCue],
    ops: list[dict],
    *,
    translation_langs: list[str] | None = None,
) -> Preview:
    return _preview(cues, ops, translation_langs=translation_langs)


def apply_selected(
    cues: list[SubtitleCue],
    ops: list[dict],
    accepted_ids: list[int] | set[int],
    *,
    translation_langs: list[str] | None = None,
) -> tuple[list[SubtitleCue], int]:
    """只应用选中的 op；重新校验选中子集，冲突则整批拒绝。"""
    ids = sorted({int(i) for i in accepted_ids if 0 <= int(i) < len(ops)})
    if not ids:
        return list(cues), 0
    selected = [ops[i] for i in ids]
    result = _preview(cues, selected, translation_langs=translation_langs)
    conflicts = [view for view in result.views if view["conflict"]]
    if conflicts:
        errors = [
            f"{view['index_label']}（{_op_label(view)}）：{'；'.join(view['conflict'])}"
            for view in conflicts
        ]
        raise StructureConflict(errors)
    return result.cues, len(selected)


# --------------------------------------------------------------------------- 提示词


def build_prompt(cues: list[SubtitleCue], alt_cues: list[SubtitleCue] | None = None) -> str:
    """给外部模型的「结构检查提示词」。

    只要求模型输出 ``{"ops": [...]}``；version/kind/digest 由本地绑定，
    不写进提示词，避免模型抄哈希。
    """
    srt_a = cues_to_srt(cues).strip()
    lines = [
        "你是日语影视字幕的结构审校员。",
        "输入是 A：当前核对台的字幕（带 1-based 序号与时间戳）。",
        "你的任务不是普通润色，而是找出 A 的结构性问题：",
        "相邻句被硬切、时间轴错位、明显的漏句/多一句、需要整句重写的严重错听。",
        "",
        "只输出一个 JSON 对象，不要解释、不要输出 markdown 代码围栏：",
        '{"ops":[...]}',
        "",
        "所有序号都是 A 的 1-based 原序号；一次输出里不要根据前一个操作重算下标。",
        "支持的操作：",
        '- merge：合并连续的 A 条目。{"op":"merge","from":3,"to":4,"text":"…","reason":"…"}',
        "  text 可选；不给就按原句直接拼接。时间取合并区间的 min(start)…max(end)。",
        '- retime：只改时间，不改文本。{"op":"retime","i":22,"start":85.829,"end":89.486,"reason":"…"}',
        '- replace_text：只改文本，不改时间。{"op":"replace_text","i":22,"after":"…","reason":"…"}',
        '- insert：在 after 条之后插入；after=0 表示插在第 1 条之前。',
        '  {"op":"insert","after":83,"start":309.010,"end":310.000,"text":"…","reason":"…"}',
        '- delete：删除一条。{"op":"delete","i":12,"reason":"…"}',
        "",
        "规则：",
        "- 不要使用 split；需要拆分的句子请保留原样。",
        "- replace_text 的 after 不能为空；要删整条请用 delete。",
        "- insert 必须给 start/end/text；不能与相邻字幕时间重叠。",
        "- reason 用不超过 20 个汉字说明理由。",
        '- 如果不需要修改，输出 {"ops":[]}。',
    ]
    lines += ["", "A（当前核对台）：", srt_a]
    if alt_cues:
        lines += [
            "",
            "B（第二引擎参考稿，只用于判断 A 的错听/断句；B 的序号不能写进 ops）：",
            cues_to_srt(alt_cues).strip(),
        ]
    return "\n".join(lines).strip() + "\n"
