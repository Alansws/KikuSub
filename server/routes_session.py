"""会话路由：把当前会话绑定到某个媒体。

`gr.State` 时代，一个浏览器标签页天然只对应一个媒体（上传即绑定）。服务化之后
「导入媒体」和「开一个会话」是两件独立的事，需要显式绑定，否则质检队列 / 字幕表
不知道自己在为哪个文件服务。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.audit import load_audit_payload

from .deps import get_session
from .security import require_token
from .sessions import Session

router = APIRouter(tags=["session"], dependencies=[Depends(require_token)])


class BindRequest(BaseModel):
    media_id: str


@router.get("/api/session")
def read_session(request: Request, session: Session = Depends(get_session)) -> dict:
    media = None
    if session.media_id:
        try:
            media = request.app.state.media.get(session.media_id).to_dict()
        except Exception:
            media = None
    return {
        "id": session.id,
        "media": media,
        "cue_count": len(session.review_cues),
        "latest_cue_count": len(session.latest_cues),
        "review_source": dict(session.review_source),
        "can_undo": session.can_undo,
        "can_redo": session.can_redo,
        "export_ui": dict(session.export_ui),
        "ai_draft": dict(session.ai_draft),
    }


@router.post("/api/session/bind")
def bind_media(payload: BindRequest, request: Request, session: Session = Depends(get_session)) -> dict:
    try:
        info = request.app.state.media.get(payload.media_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    changed = session.media_id != info.id
    session.media_id = info.id
    session.media_path = str(info.path)
    if changed:
        # 换片必须清空上一部片的字幕 / 译文 / 历史：否则新片核对台会继续
        # 显示上一部的原文字幕，而译文轨还会永远占着，软件看起来彻底不可用。
        session.reset_for_media()
    # 质检队列按媒体落盘；会话缓存一份，之后的工作区快照才能回滚待核状态。
    session.set_qa_payload(load_audit_payload(session.media_path))
    return {"id": session.id, "media": info.to_dict(), "review_cleared": changed}
