"""质检队列的动作语义（无 UI 依赖）。

从 `app.py` 的 `qa_apply_action` 原样搬出并去掉 Gradio：`gr.Warning(...)` 改成结果里的
`warning` 字段，`gr.update()` 的四个编辑框改成 `focus` 结构，撤回栈交给调用方维护
（旧界面用 `gr.State`，服务层用 `Session`）。

**行为约束（改之前先读 AGENTS.md §5）**：

- 所有会改动字幕的动作都走撤回栈，且**只在真的找到对应字幕时**才改——用户在核对台
  尚未设为基线时误删/误插是最容易踩的坑；
- 「短句待确认」点保留时，若核对台缺这句要幂等补齐（`_audit_ensure_item_cues`）；
- `phase` / `engine` / `scanned` / `transcribed_at` 这些「这次运行是什么」的元数据
  必须原样带进新 payload，否则前端会把空闲/引擎能力误判成未知。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .audit import _audit_ensure_item_cues, _audit_match_cues, _parse_audit_payload, empty_audit_payload, make_audit_payload, write_audit_payload
from .cues import _cues_to_dicts, _unique_sorted_cues
from .subtitles import SubtitleCue, format_srt_timestamp

log = logging.getLogger(__name__)

VALID_STATUSES = {"pending", "done", "skipped"}

RESOLUTION_MESSAGES = {
    "filled": "⚡ 已补录并插入核对台。",
    "restored": "↩ 已恢复原句。",
    "deleted": "🗑 已删除此句。",
    "kept": "✅ 已保留。",
    "confirmed": "✓ 已确认删除。",
    "not-speech": "✓ 已标记为不是台词。",
    "skipped": "⏭ 已跳过。",
}


@dataclass
class QaActionResult:
    ok: bool
    message: str
    cues: list[SubtitleCue]
    cues_changed: bool = False
    qa_payload: str = ""
    warning: str = ""
    # 变更前的状态：调用方据此压撤回栈（与旧实现 `_push_history(u_stack, existing)` 同义）
    previous_cues: list[SubtitleCue] = field(default_factory=list)
    # 「定位编辑」要填进单行精修框的四元组；其他动作是 None
    focus: dict | None = None
    # 即使字幕没变，也要求前端刷新表格（保留动作补齐字幕时用）
    force_table_sync: bool = False


def _result(
    cues: list[SubtitleCue],
    message: str,
    *,
    ok: bool = True,
    changed: bool = False,
    payload: str = "",
    warning: str = "",
    previous: list[SubtitleCue] | None = None,
    focus: dict | None = None,
    sync: bool = False,
) -> QaActionResult:
    return QaActionResult(
        ok=ok,
        message=message,
        cues=cues,
        cues_changed=changed,
        qa_payload=payload,
        warning=warning,
        previous_cues=previous if previous is not None else cues,
        focus=focus,
        force_table_sync=sync,
    )


def apply_action(
    cmd: dict | str | None,
    review_cues,
    media_file=None,
    qa_payload: str | None = None,
) -> QaActionResult:
    """处理质检队列里的一次点击：标记 / 删除 / 恢复原句 / 定位编辑。

    `cmd` 可以是 dict 或 JSON 字符串（旧界面传的是隐藏 Textbox 里的 JSON）。
    """
    existing = _unique_sorted_cues(review_cues)
    payload = _parse_audit_payload(qa_payload)
    items = [dict(item) for item in (payload.get("items") or []) if isinstance(item, dict)]

    if isinstance(cmd, str):
        import json

        try:
            cmd = json.loads(cmd or "{}")
        except (TypeError, ValueError):
            cmd = {}
    if not isinstance(cmd, dict):
        cmd = {}

    if not items:
        return _result(
            existing,
            "⚠️ 质检队列为空，请先转写。",
            ok=False,
            warning="⚠️ 质检队列为空或已失效，请先重新转写生成。",
            payload=qa_payload or empty_audit_payload(),
        )

    action = str(cmd.get("action") or "")
    item_id = str(cmd.get("id") or "")
    item = next((entry for entry in items if str(entry.get("id")) == item_id), None)
    if item is None:
        return _result(
            existing,
            "⚠️ 待核记录已失效。",
            ok=False,
            warning="⚠️ 没有找到这条待核记录，可能已重新转写，请刷新队列。",
            payload=qa_payload or empty_audit_payload(),
        )

    statuses = dict(payload.get("statuses") or {})
    media_name = str(payload.get("media") or (Path(media_file).name if media_file else ""))
    start = float(item.get("start", 0.0) or 0.0)
    end = float(item.get("end", 0.0) or 0.0)
    cues_changed = False
    force_table_sync = False
    focus: dict | None = None
    message = ""
    previous = existing

    def mark(status: str, resolution: str = "") -> None:
        if status == "pending":
            statuses.pop(item_id, None)
        else:
            statuses[item_id] = {"status": status, "resolution": resolution}

    if action == "mark":
        status = str(cmd.get("status") or "done")
        if status not in VALID_STATUSES:
            status = "done"
        resolution = str(cmd.get("resolution") or "")
        mark(status, resolution)
        if status == "pending":
            message = "↺ 已重新放回待核队列。"
        else:
            message = RESOLUTION_MESSAGES.get(resolution, "✅ 已标记为本条处理完成。")
            # 短句待确认点「保留」时，核对台可能因为「先设基线、后重转/删改」
            # 而缺少这句。这里幂等补齐，并强制刷新表格，避免状态与表格不同步。
            if resolution == "kept" and str(item.get("kind") or "") == "suspect":
                ensured, added = _audit_ensure_item_cues(existing, item)
                if added:
                    previous = existing
                    existing = ensured
                    cues_changed = True
                    message = (
                        f"✅ 已保留；核对台原先缺少这句，已自动补回 {added} 条字幕"
                        "（可按 Cmd+Z 撤回）。"
                    )
                else:
                    message = "✅ 已保留；核对台已包含这句，表格已刷新对齐。"
                force_table_sync = True

    elif action == "skip":
        mark("skipped", "skipped")
        message = "⏭ 已跳过这一条，可随时点「↺ 重新待核」找回。"

    elif action == "delete_cue":
        targets = [c for c in (item.get("cues") or []) if isinstance(c, dict)]
        remove_keys = {
            (
                int(round(float(c.get("start", 0.0)) * 1000)),
                int(round(float(c.get("end", 0.0)) * 1000)),
                str(c.get("text") or ""),
            )
            for c in targets
        }
        if not remove_keys:
            # 兜底：构建队列时没匹配到（例如用户刚改过字幕），按时间包含关系找
            remove_keys = {
                (int(round(cue.start * 1000)), int(round(cue.end * 1000)), cue.text)
                for cue in existing
                if cue.start >= start - 0.08 and cue.end <= end + 0.08
            }
        remaining = [
            cue
            for cue in existing
            if (int(round(cue.start * 1000)), int(round(cue.end * 1000)), cue.text) not in remove_keys
        ]
        if len(remaining) == len(existing):
            return _result(
                existing,
                "⚠️ 核对台未找到对应字幕，未做删除。",
                ok=False,
                warning="⚠️ 核对台里没有找到这句字幕。请先点「📌 本次设为基线」再试。",
                payload=qa_payload or empty_audit_payload(),
            )
        removed_count = len(existing) - len(remaining)
        previous = existing
        existing = remaining
        cues_changed = True
        mark("done", "deleted")
        message = f"🗑 已从核对台删除该段对应的 {removed_count} 条字幕（可按 Cmd+Z 撤回）。"

    elif action == "restore":
        text = " ".join(str(item.get("text") or "").split())
        if not text:
            return _result(
                existing,
                "⚠️ 没有可恢复的原文。",
                ok=False,
                warning="⚠️ 这条记录没有可恢复的原文，请改用「⚡ 重新识别」。",
                payload=qa_payload or empty_audit_payload(),
            )
        new_cue = SubtitleCue(round(start, 3), round(max(end, start + 0.1), 3), text)
        combined = _unique_sorted_cues([*existing, new_cue])
        if len(combined) == len(existing):
            mark("done", "restored")
            message = "ℹ️ 这句已经在核对台里了，未重复插入。"
        else:
            previous = existing
            existing = combined
            cues_changed = True
            mark("done", "restored")
            message = "↩ 已按原文恢复这句字幕（可按 Cmd+Z 撤回）。"

    elif action == "focus":
        targets = [c for c in (item.get("cues") or []) if isinstance(c, dict)]
        target = targets[0] if targets else None
        if target is None:
            overlapping = _audit_match_cues(existing, start, end)
            target = overlapping[0] if overlapping else None
        idx = 0
        if target is not None:
            for i, cue in enumerate(existing, start=1):
                if (
                    int(round(cue.start * 1000)) == int(round(float(target.get("start", 0.0)) * 1000))
                    and int(round(cue.end * 1000)) == int(round(float(target.get("end", 0.0)) * 1000))
                ):
                    idx = i
                    break
        text = str(target.get("text") if target else item.get("text") or "")
        focus = {
            "index": idx,
            "start": format_srt_timestamp(start),
            "end": format_srt_timestamp(end),
            "text": text,
        }
        message = "✏️ 已定位并填入上方单行精修框，改完点「✏️ 更新此行」。"

    else:
        return _result(
            existing,
            "⚠️ 未知操作。",
            ok=False,
            warning="⚠️ 未知的质检操作。",
            payload=qa_payload or empty_audit_payload(),
        )

    revision = int(payload.get("revision") or 0) + 1
    auto_advance = action in {"mark", "skip", "delete_cue", "restore"} and not (
        action == "mark" and str(cmd.get("status") or "") == "pending"
    )
    new_payload = make_audit_payload(
        media_name,
        items,
        statuses,
        payload.get("latest_cue_count") or len(existing),
        payload.get("hidden_missed") or 0,
        revision,
        {
            "id": item_id,
            "action": action,
            "seq": revision,
            "auto_advance": auto_advance,
            "message": message,
        },
        engine=payload.get("engine") or "",
        phase=payload.get("phase") or "done",
        scanned=payload.get("scanned") or {},
        transcribed_at=payload.get("transcribed_at") or 0.0,
    )
    write_audit_payload(media_file, new_payload)

    if cues_changed or force_table_sync:
        log.info(
            "质检动作 | action=%s | id=%s | cues=%s | media=%s | table_sync=%s",
            action,
            item_id,
            len(existing),
            media_name,
            force_table_sync,
        )

    return _result(
        existing,
        message,
        changed=cues_changed,
        payload=new_payload,
        previous=previous,
        focus=focus,
        sync=force_table_sync,
    )


def cues_as_dicts(cues: list[SubtitleCue]) -> list[dict]:
    return _cues_to_dicts(cues)
