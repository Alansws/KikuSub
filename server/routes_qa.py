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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import qa
from core.audit import empty_audit_payload, load_audit_payload

from .deps import get_session
from .security import require_token
from .sessions import Session

router = APIRouter(tags=["qa"], dependencies=[Depends(require_token)])


class QaActionRequest(BaseModel):
    id: str = Field(min_length=1)
    action: str = Field(pattern="^(mark|skip|delete_cue|restore|focus)$")
    status: str | None = None
    resolution: str | None = None


def _media_path(request: Request, session: Session) -> str:
    if not session.media_id:
        raise HTTPException(status_code=409, detail="当前会话还没有绑定媒体，请先导入")
    try:
        return str(request.app.state.media.get(session.media_id).path)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _parse(text: str) -> dict:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return json.loads(empty_audit_payload())


@router.get("/api/qa")
def get_qa(request: Request, session: Session = Depends(get_session)) -> dict:
    """读当前媒体的质检队列（从磁盘 payload 恢复，跨请求一致）。"""
    if not session.media_id:
        return _parse(empty_audit_payload())
    path = _media_path(request, session)
    return _parse(load_audit_payload(path))


@router.post("/api/qa/action")
def post_qa_action(
    payload: QaActionRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    path = _media_path(request, session)
    payload_text = load_audit_payload(path)

    cmd = payload.model_dump(exclude_none=True)
    res = qa.apply_action(cmd, session.review_cues, path, payload_text)

    if res.cues_changed:
        # replace_review 内部会压撤回栈，服务端仍是唯一真源
        session.replace_review(res.cues)

    return {
        "ok": res.ok,
        "message": res.message,
        "warning": res.warning,
        "cues_changed": res.cues_changed,
        "force_table_sync": res.force_table_sync,
        "focus": res.focus,
        "cues": [{"start": c.start, "end": c.end, "text": c.text} for c in session.review_cues],
        "can_undo": bool(session.undo_stack),
        "can_redo": bool(session.redo_stack),
        "qa": _parse(res.qa_payload or payload_text),
    }
