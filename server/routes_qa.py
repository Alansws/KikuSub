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
    return _parse(load_audit_payload(path))


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

    cmd = payload.model_dump(exclude_none=True)
    res = qa.apply_action(cmd, session.review_cues, path, payload_text)

    if res.cues_changed:
        # replace_review 内部会记一步历史，服务端仍是唯一真源
        action_label = {
            "mark": "标记",
            "skip": "跳过",
            "delete_cue": "删除字幕",
            "restore": "恢复字幕",
            "focus": "定位",
        }.get(payload.action, payload.action)
        session.replace_review(res.cues, label=f"质检：{action_label}")

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
