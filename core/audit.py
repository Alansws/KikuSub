"""质检待核队列的数据层：把转写统计变成可逐条处理的 item，并落盘恢复状态。

从 `app.py` 原样搬出。只负责生成 / 读写 JSON payload，不含任何渲染或交互——
`qa_apply_action` 因为有 Gradio 提示语仍留在 `app.py`，等阶段 5 再迁。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from .cues import _coerce_cues, _unique_sorted_cues
from .paths import OUTPUT_DIR
from .report import (
    _hallucination_rule_label,
    _missed_reason_label,
    _visible_missed_spans,
)
from .textio import write_text_atomic
from .subtitles import SubtitleCue

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 质检待核队列：把「疑似漏句 / 幻觉门控 / 幻觉复核」三类静态清单
# 变成用户能逐条试听、定位、补录、确认的可操作队列。
#
# 设计要点：
# - 后端只负责生成稳定的 item（带 id / 类型 / 时间 / 原文 / 匹配到的字幕），
#   状态（待核 / 已处理 / 已跳过）单独放在 statuses 里，便于落盘恢复；
# - 同一媒体重复处理时按 id 合并状态，绝不因为重新渲染丢掉“已经听过”的进度；
# - 队列数据走一个隐藏 Textbox（#qa-payload），前端 JS 与 reviewer 共用同一次渲染，
#   不额外引入 Gradio 组件刷新，避免面板闪烁。
# ---------------------------------------------------------------------------
# 每次进程启动生成一个会话标识：质检队列只在同一进程内恢复。
# 重启后旧 .qa.json 视为上一次运行的记录，不自动带入，保证面板默认清空。
AUDIT_SESSION_ID = f"{os.getpid()}:{time.time_ns()}"

AUDIT_KIND_ORDER = {"coverage": -1, "missed": 0, "dropped": 1, "suspect": 2}

# 对用户只暴露两个大组：真正可能漏台词的「漏检」，和切片内部的
# 短句/空结果/误删「低置信」。kind 仍保留，作为组内原因标签。
GROUP_BY_KIND = {
    "coverage": "miss",
    "missed": "low",
    "dropped": "low",
    "suspect": "low",
}

AUDIT_KIND_META = {
    "coverage": {
        "icon": "📭",
        "name": "未覆盖空白",
        "group": "miss",
        "plain": "这段有声音，但一整段没有字幕；主 VAD 没有切到它，Whisper 根本没收到",
        "hint": "先听建议子区间；若确有台词，点「补录」只转这一段；若只是喘息/配乐，点「不是台词」。",
    },
    "missed": {
        "icon": "🔍",
        "name": "切片内为空",
        "group": "low",
        "plain": "VAD 切到了这段，但两次识别都没有出字幕",
        "hint": "听一下：若确实有台词，点「⚡ 补录并插入」；若只是配乐/底噪，点「✓ 不是台词」。",
    },
    "dropped": {
        "icon": "✂️",
        "name": "误删待核",
        "group": "low",
        "plain": "识别出过文字，但复核为空，已自动删除",
        "hint": "若你听到确实有声音，点「↩ 恢复原句」或「⚡ 重新识别」；若确认是脑补，点「✓ 确认删除」。",
    },
    "suspect": {
        "icon": "👂",
        "name": "短句待确认",
        "group": "low",
        "plain": "字幕已保留，但太短或信息量低，容易是模型脑补",
        "hint": "听一遍：没问题点「✓ 保留」（核对台缺这句会自动补回），不对劲点「🗑 删除此句」或「✏️ 定位编辑」。",
    },
}


def _audit_media_stem(media_file) -> str:
    """与校对断点使用同一套主干规则，保证同名媒体的队列能恢复。"""
    if not media_file:
        return ""
    stem = Path(media_file).stem
    return re.sub(r"(\.autosave_draft|\.reviewed|\.clean|\.part_cancelled)$", "", stem)


def audit_state_path(media_file) -> Path | None:
    stem = _audit_media_stem(media_file)
    return OUTPUT_DIR / f"{stem}.qa.json" if stem else None


def _audit_item_id(kind: str, start: float, end: float) -> str:
    return f"{kind}:{int(round(float(start) * 1000))}:{int(round(float(end) * 1000))}"


def _audit_match_cues(cues, start: float, end: float) -> list[dict]:
    """找出被该时间段覆盖的字幕，供「定位编辑 / 删除此句」精确操作。

    短句被断句器拆成多条时，这里会把同一段里的所有子句都带出来；
    只要求“重叠超过自身一半”或“字幕中点落在区间内”，避免误伤相邻句。
    """
    matched: list[dict] = []
    for cue in cues or []:
        c_start = float(cue.start)
        c_end = float(cue.end)
        overlap = min(c_end, end) - max(c_start, start)
        if overlap <= 0:
            continue
        cue_dur = max(0.001, c_end - c_start)
        midpoint = (c_start + c_end) / 2.0
        if overlap / cue_dur >= 0.5 or (start <= midpoint <= end):
            matched.append({
                "start": round(c_start, 3),
                "end": round(c_end, 3),
                "text": str(cue.text or ""),
            })
    return matched


def build_audit_items(
    missed_spans: list[dict] | None,
    segment_stats: dict | None,
    cues,
    coverage_spans: list[dict] | None = None,
) -> list[dict]:
    """把四类问题合并成一条按时间排序的待核队列。

    对用户只暴露两个组：

    · ``miss`` 漏检  —— ``coverage``：字幕空白里还有像语音的声音，主 VAD 没切到。
      这是唯一能看见「Whisper 根本没收到这段音频」的类别，必须排在前面。
    · ``low``  低置信 —— ``missed`` / ``dropped`` / ``suspect``：切片内部已经
      送过模型的空结果、被幻觉门控删掉的、以及太短的句子。它们都发生在主 VAD
      已经切出来的片段里，所以对「整段漏切」不敏感，默认折叠。
    """
    cue_list = _coerce_cues(cues or [])
    items: list[dict] = []
    seen: set[str] = set()
    coverage_items: list[dict] = []

    def add(
        kind: str,
        start: float,
        end: float,
        *,
        peak=None,
        rule: str = "",
        text: str = "",
        reason: str = "",
        extra: dict | None = None,
    ) -> dict | None:
        start = round(max(0.0, float(start or 0.0)), 3)
        end = round(max(start + 0.001, float(end or 0.0)), 3)
        item_id = _audit_item_id(kind, start, end)
        if item_id in seen:
            return None
        seen.add(item_id)
        meta = AUDIT_KIND_META[kind]
        matched = _audit_match_cues(cue_list, start, end)
        if kind == "coverage":
            rule_label = "主 VAD 未切到"
        elif kind == "missed":
            rule_label = _missed_reason_label(reason)
        else:
            rule_label = _hallucination_rule_label(rule)
        item = {
            "id": item_id,
            "kind": kind,
            "group": GROUP_BY_KIND.get(kind, "low"),
            "start": start,
            "end": end,
            "dur": round(end - start, 2),
            "peak": (round(float(peak), 3) if isinstance(peak, (int, float)) else None),
            "rule": rule or reason,
            "rule_label": rule_label,
            "text": " ".join(str(text or "").split())[:160],
            "cues": matched,
            "label": meta["name"],
            "plain": meta["plain"],
            "hint": meta["hint"],
            "status": "pending",
            "resolution": "",
        }
        if extra:
            item.update(extra)
        items.append(item)
        return item

    # 先放覆盖审计：它是唯一不经过主 VAD 判决的类别，优先级最高。
    for span in coverage_spans or []:
        gap_start = float(span.get("gap_start", span.get("start", 0.0)) or 0.0)
        gap_end = float(span.get("gap_end", span.get("end", 0.0)) or 0.0)
        gap_dur = max(0.0, gap_end - gap_start)
        text = (
            f"空白 {gap_dur:.1f}s 中检测到 "
            f"{float(span.get('dur', 0.0) or 0.0):.1f}s 语音"
        )
        item = add(
            "coverage",
            span.get("start", 0.0),
            span.get("end", 0.0),
            peak=span.get("peak"),
            rule="audio-gap",
            text=text,
            reason="uncovered-energy",
            extra={
                "gap_start": round(gap_start, 3),
                "gap_end": round(gap_end, 3),
                "gap_dur": round(gap_dur, 2),
                "rms": span.get("rms"),
                "vad_mean": span.get("vad_mean"),
                "vad_max": span.get("vad_max"),
            },
        )
        if item is not None:
            coverage_items.append(item)

    def overlaps_coverage(span: dict) -> bool:
        """同一个空白里已经有一条覆盖项时，不再重复放切片内的 missed。"""
        start = float(span.get("start", 0.0) or 0.0)
        end = float(span.get("end", 0.0) or 0.0)
        mid = (start + end) / 2.0
        for item in coverage_items:
            if float(item["start"]) <= mid <= float(item["end"]):
                return True
            if min(float(item["end"]), end) - max(float(item["start"]), start) >= 0.5 * max(0.001, end - start):
                return True
        return False

    for span in _visible_missed_spans(missed_spans):
        if overlaps_coverage(span):
            continue
        add(
            "missed",
            span.get("start", 0.0),
            span.get("end", 0.0),
            peak=span.get("peak") if "peak" in span else None,
            reason=str(span.get("reason") or ""),
        )

    for span in list((segment_stats or {}).get("hallucination_spans") or []):
        verdict = str(span.get("verdict") or "")
        kind = "dropped" if verdict == "dropped" else ("suspect" if verdict == "suspect" else "")
        if not kind:
            continue
        add(
            kind,
            span.get("start", 0.0),
            span.get("end", 0.0),
            peak=span.get("peak") if "peak" in span else None,
            rule=str(span.get("rule") or ""),
            text=str(span.get("text") or ""),
        )

    items.sort(key=lambda item: (float(item.get("start", 0.0)), AUDIT_KIND_ORDER.get(item["kind"], 9)))
    return items


def _audit_cue_overlaps(cues, start: float, end: float) -> bool:
    """核对台里是否已有与 [start, end] 重叠的字幕。

    用重叠关系而不是“起止完全相等”判断，原因有两个：
    - 转写结果会做 cue padding，队列里的区间和表格里的起止可能差几十毫秒；
    - 用户可能已经手动改过这句的文字/时间，不能再把旧文本重复插一遍。
    """
    for cue in cues or []:
        c_start = float(cue.start)
        c_end = float(cue.end)
        overlap = min(c_end, end) - max(c_start, start)
        if overlap <= 0:
            continue
        cue_dur = max(0.001, c_end - c_start)
        midpoint = (c_start + c_end) / 2.0
        if overlap / cue_dur >= 0.5 or (start <= midpoint <= end):
            return True
    return False


def _audit_ensure_item_cues(existing, item: dict) -> tuple[list[SubtitleCue], int]:
    """确保「短句待确认」这条记录对应的字幕确实存在核对台里。

    正常流程里核对台由“本次设为基线”写入，应该天然包含这些 cue；但用户可能
    先设了基线、之后又重转/删改，或表格显示与状态不同步。点“保留”时做一次
    幂等补齐：已经重叠的 cue 不重复插，缺的才按转写时的精确文本补回。
    """
    start = float(item.get("start", 0.0) or 0.0)
    end = float(item.get("end", 0.0) or 0.0)
    targets = [dict(c) for c in (item.get("cues") or []) if isinstance(c, dict)]
    if not targets:
        targets = _audit_match_cues(existing, start, end)
    if not targets and str(item.get("text") or "").strip():
        targets = [{"start": start, "end": end, "text": str(item.get("text") or "")}]

    added: list[SubtitleCue] = []
    for target in targets:
        text = " ".join(str(target.get("text") or "").split())
        if not text:
            continue
        t_start = round(max(0.0, float(target.get("start", start) or 0.0)), 3)
        t_end = round(max(t_start + 0.001, float(target.get("end", end) or 0.0)), 3)
        normalized = " ".join(text.split())
        same_text = any(" ".join(cue.text.split()) == normalized for cue in existing)
        same_text = same_text or any(" ".join(cue.text.split()) == normalized for cue in added)
        if same_text or _audit_cue_overlaps(existing, t_start, t_end) or _audit_cue_overlaps(added, t_start, t_end):
            continue
        added.append(SubtitleCue(t_start, t_end, text))

    if not added:
        return existing, 0
    return _unique_sorted_cues([*existing, *added]), len(added)


def _audit_counts(items: list[dict]) -> dict:
    counts = {"total": len(items), "pending": 0, "done": 0, "skipped": 0}
    by_kind = {kind: 0 for kind in AUDIT_KIND_ORDER}
    by_group = {"miss": 0, "low": 0}
    for item in items:
        status = str(item.get("status") or "pending")
        if status not in counts:
            status = "pending"
        counts[status] += 1
        kind = str(item.get("kind") or "")
        if kind in by_kind:
            by_kind[kind] += 1
        group = str(item.get("group") or GROUP_BY_KIND.get(kind) or "low")
        if group not in by_group:
            group = "low"
        by_group[group] += 1
    counts["by_kind"] = by_kind
    counts["by_group"] = by_group
    return counts


def _audit_coverage(engine: str) -> dict:
    """本次实际执行的质检类别。

    · ``missed``  —— VAD 判成语音但识别为空，两个引擎都会产出；
    · ``dropped`` / ``suspect`` —— 依赖 Anime Whisper 的「带时间戳重解码」复核，
      Qwen 路径没有这一步。这里必须如实标成 False，否则空队列会被误读成
      「检查过且干净」。
    """
    is_qwen = str(engine or "") == "qwen"
    return {
        "missed": True,
        "dropped": not is_qwen,
        "suspect": not is_qwen,
    }


def empty_audit_payload(media_name: str = "") -> str:
    return json.dumps({
        "version": 1,
        "session": AUDIT_SESSION_ID,
        "media": str(media_name or ""),
        # idle = 还没有可质检的结果。前端据此显示常驻入口，而不是整个功能消失。
        "phase": "idle",
        "engine": "",
        "coverage": _audit_coverage(""),
        "scanned": {},
        "transcribed_at": 0.0,
        "items": [],
        "statuses": {},
        "counts": _audit_counts([]),
        "latest_cue_count": 0,
        "hidden_missed": 0,
        "revision": 0,
        "last_action": None,
    }, ensure_ascii=False)


def make_audit_payload(
    media_name: str,
    items: list[dict],
    statuses: dict | None = None,
    latest_cue_count: int = 0,
    hidden_missed: int = 0,
    revision: int = 0,
    last_action: dict | None = None,
    *,
    engine: str = "",
    phase: str = "done",
    scanned: dict | None = None,
    transcribed_at: float | None = None,
) -> str:
    """把 item 与状态合并成前端可直接渲染的 JSON。

    status 记录既接受「done」字符串，也接受 {"status":..., "resolution":...}
    的旧/新两种形状，避免升级后把用户已有的核对进度读丢。
    """
    statuses = dict(statuses or {})
    merged: list[dict] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        record = statuses.get(str(item.get("id") or ""))
        if isinstance(record, dict):
            item["status"] = str(record.get("status") or "pending")
            item["resolution"] = str(record.get("resolution") or "")
        elif isinstance(record, str) and record:
            item["status"] = record
            item["resolution"] = ""
        else:
            # statuses 是唯一真源：没有记录 = 待核。
            # 不能用 setdefault —— 重新放回待核时 item 里还留着上一次的 done。
            item["status"] = "pending"
            item["resolution"] = ""
        merged.append(item)

    payload = {
        "version": 1,
        "session": AUDIT_SESSION_ID,
        "media": str(media_name or ""),
        # phase 描述「这次运行走到了哪一步」，与 items 是否为空解耦：
        # idle 还没结果、done 已完成（0 条也是完成）。前端靠它决定入口是否常驻。
        "phase": str(phase or ("done" if merged else "idle")),
        "engine": str(engine or ""),
        "coverage": _audit_coverage(engine),
        "scanned": dict(scanned or {}),
        "transcribed_at": float(transcribed_at or 0.0),
        "items": merged,
        "statuses": statuses,
        "counts": _audit_counts(merged),
        "latest_cue_count": int(latest_cue_count or 0),
        "hidden_missed": int(hidden_missed or 0),
        "revision": int(revision or 0),
        "last_action": last_action,
    }
    return json.dumps(payload, ensure_ascii=False)


def _parse_audit_payload(text) -> dict:
    try:
        data = json.loads(text or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_audit_payload(media_file, payload_text: str) -> Path | None:
    """把队列与处理进度落到媒体同名 .qa.json；失败不阻断主流程。"""
    path = audit_state_path(media_file)
    if path is None:
        return None
    try:
        write_text_atomic(path, payload_text)
    except OSError:
        log.debug("质检队列落盘失败 | %s", path, exc_info=True)
        return None
    return path


def load_audit_payload(media_file) -> str:
    """读取同名媒体的历史质检队列；没有/损坏时返回空队列。"""
    path = audit_state_path(media_file)
    if path is None:
        log.info("质检队列路径不可用 | media=%s", media_file)
        return empty_audit_payload()
    if not path.exists():
        log.info("质检队列文件不存在 | path=%s", path)
        return empty_audit_payload()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("质检队列读取失败 | path=%s", path, exc_info=True)
        return empty_audit_payload()
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        log.warning("质检队列格式不对 | path=%s | keys=%s", path, list(data)[:8] if isinstance(data, dict) else type(data).__name__)
        return empty_audit_payload()
    # 跨进程不恢复：重启应用后默认就是空队列，不把上一次的核对进度带进来。
    if str(data.get("session") or "") != AUDIT_SESSION_ID:
        log.info("忽略上次进程的质检队列 | %s", path.name)
        return empty_audit_payload()
    data.setdefault("statuses", {})
    data.setdefault("revision", 0)
    data.setdefault("latest_cue_count", 0)
    data.setdefault("hidden_missed", 0)
    data.setdefault("media", Path(media_file).name if media_file else "")
    data.setdefault("engine", "")
    data.setdefault("scanned", {})
    data.setdefault("transcribed_at", 0.0)
    # 老版本 .qa.json 没有 phase：只要有条目就视为已完成的队列，避免入口被误判成 idle。
    data.setdefault("phase", "done" if data.get("items") else "idle")
    log.info(
        "质检队列已载入 | path=%s | phase=%s | items=%s | engine=%s",
        path.name,
        data.get("phase"),
        len(data.get("items") or []),
        data.get("engine") or "-",
    )
    # 重新合并一次，保证老文件里的 status 形状也能被前端识别
    return make_audit_payload(
        data.get("media") or (Path(media_file).name if media_file else ""),
        data.get("items") or [],
        data.get("statuses") or {},
        data.get("latest_cue_count") or 0,
        data.get("hidden_missed") or 0,
        data.get("revision") or 0,
        data.get("last_action"),
        engine=data.get("engine") or "",
        phase=data.get("phase") or "done",
        scanned=data.get("scanned") or {},
        transcribed_at=data.get("transcribed_at") or 0.0,
    )
