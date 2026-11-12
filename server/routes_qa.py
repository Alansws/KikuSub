"""质检待核队列路由。

数据层在 `core/audit.py`（生成 / 读写 payload），动作语义在 `core.qa.apply_action`
（标记 / 删除 / 恢复 / 定位）。这里只做三件事：

1. 把会话绑定的媒体解析成路径（payload 是按媒体落盘的）；
2. 调 `core.qa`，把字幕变更写回会话（会话自己的撤销栈因此自动生效）；
3. 把结果转成 JSON——`gr.Warning` 变成 `warning` 字段，`gr.update()` 的编辑框变成
   `focus` 对象。

**旧实现的隐藏坑**：`phase` / `engine` / `scanned` / `transcribed_at` 必须原样透传，
否则前端会把「空闲」或「引擎能力」误判成未知。这条已由 `core.qa` 保证。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import qa
from core.audit import empty_audit_payload, load_audit_payload

from .deps import get_session
from .security import require_token
from .sessions import Session

router = APIRouter(tags=["qa"], dependencies=[Depends(require_token)])

# 只有「这张表是转写结果」时，媒体同名的 .qa.json 才对得上。
# 导入字幕 / 恢复草稿都会整表换掉内容，旧队列的 item id 与当前字幕不再对应，
# 继续允许操作会删错句、补错区间——所以这两类来源一律暂停队列。
_DETACHED_KINDS = {"import", "draft"}


class QaActionRequest(BaseModel):
    id: str = Field(min_length=1)
    action: str = Field(pattern="^(mark|skip|delete_cue|restore|focus)$")
    status: str | None = None
    resolution: str | None = None


def _review_source(session: Session) -> dict:
    return dict(session.review_source or {})


def _detached_reason(session: Session) -> str:
    source = _review_source(session)
    kind = str(source.get("kind") or "")
    name = str(source.get("name") or "外部字幕")
    if kind == "import":
        return f"当前核对表来自导入的「{name}」，这次转写的质检队列只对应转写结果。"
    if kind == "draft":
        return f"当前核对表来自暂存草稿「{name}」，不与这次转写的质检队列对应。"
    return ""


def _is_detached(session: Session) -> bool:
    return str(_review_source(session).get("kind") or "") in _DETACHED_KINDS


def _detached_payload(session: Session, media_path: str) -> dict:
    data = _parse(empty_audit_payload(Path(media_path).name))
    data["detached"] = True
    data["detached_reason"] = _detached_reason(session)
    data["review_source"] = _review_source(session)
    return data


def _media_path(request: Request, session: Session) -> str:
    if not session.media_id:
        raise HTTPException(status_code=409, detail="当前会话还没有绑定媒体，请先导入")
    try:
        return str(request.app.state.media.get(session.media_id).path)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _qa_label(payload: QaActionRequest) -> str:
    """历史列表里的可读说明：用户要能一眼看出这一步在质检面板做了什么。"""
    if payload.action == "delete_cue":
        return "质检：删除字幕"
    if payload.action == "restore":
        return "质检：恢复原句"
    if payload.action == "skip":
        return "质检：跳过这一条"
    if payload.action == "mark":
        if payload.status == "pending":
            return "质检：放回待核"
        resolution = {
            "kept": "保留",
            "confirmed": "确认删除",
            "not-speech": "不是台词",
            "filled": "补录",
            "restored": "恢复",
            "deleted": "删除",
            "skipped": "跳过",
        }.get(payload.resolution or "", "标记已核对")
        return f"质检：{resolution}"
    return "质检：更新"


def _parse(text: str) -> dict:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return json.loads(empty_audit_payload())


@router.get("/api/qa")
def get_qa(request: Request, session: Session = Depends(get_session)) -> dict:
    """读当前媒体的质检队列（从磁盘 payload 恢复，跨请求一致）。

    当前核对表不是转写结果时（导入字幕 / 恢复草稿），旧队列与字幕已经对不上，
    返回一份带 ``detached`` 标记的空态，由界面说明原因；不把 item 交给前端。
    """
    if not session.media_id:
        return _parse(empty_audit_payload())
    path = _media_path(request, session)
    if _is_detached(session):
        return _detached_payload(session, path)
    payload_text = load_audit_payload(path)
    # 缓存到会话：之后任何一步字幕 / 译文 / 导出操作的工作区快照都要带上
    # 当时的质检状态，⌘Z 才能把「删除此句」和它的待核状态一起退回。
    session.set_qa_payload(payload_text)
    return _parse(payload_text)


@router.post("/api/qa/action")
def post_qa_action(
    payload: QaActionRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    path = _media_path(request, session)
    if _is_detached(session):
        raise HTTPException(
            status_code=409,
            detail=_detached_reason(session) or "当前字幕不是转写结果，质检队列不可用",
        )
    payload_text = load_audit_payload(path)
    # 基线必须包含动作之前的队列；否则第一次质检动作会把「空队列」当成
    # 起始状态，撤销时把 .qa.json 写空。
    session.set_qa_payload(payload_text)

    # 质检动作会先改状态再 record；先固定「起始状态」，第一次质检动作才能撤销。
    if payload.action != "focus":
        session.ensure_baseline()
    cmd = payload.model_dump(exclude_none=True)
    res = qa.apply_action(cmd, session.review_cues, path, payload_text)
    session.set_qa_payload(res.qa_payload or payload_text)

    # 质检动作只有 mark / skip / delete_cue / restore 会改变工作区；focus 只定位。
    if res.ok and payload.action != "focus":
        label = _qa_label(payload)
        if res.cues_changed:
            # 先只换字幕，不压历史；下面统一记一步，把字幕与质检状态放在同一条快照。
            session.replace_review(res.cues, label=label, record=False)
        session.record(label)

    return {
        "ok": res.ok,
        "message": res.message,
        "warning": res.warning,
        "cues_changed": res.cues_changed,
        "force_table_sync": res.force_table_sync,
        "focus": res.focus,
        "cues": [{"start": c.start, "end": c.end, "text": c.text} for c in session.review_cues],
        "can_undo": session.can_undo,
        "can_redo": session.can_redo,
        "undo_label": session.undo_label(),
        "redo_label": session.redo_label(),
        "review_source": dict(session.review_source),
        "qa": _parse(res.qa_payload or payload_text),
    }
