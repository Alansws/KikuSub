"""会话路由：把当前会话绑定到某个媒体。

`gr.State` 时代，一个浏览器标签页天然只对应一个媒体（上传即绑定）。服务化之后
「导入媒体」和「开一个会话」是两件独立的事，需要显式绑定，否则质检队列 / 字幕表
不知道自己在为哪个文件服务。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

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
    }


@router.post("/api/session/bind")
def bind_media(payload: BindRequest, request: Request, session: Session = Depends(get_session)) -> dict:
    try:
        info = request.app.state.media.get(payload.media_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.media_id = info.id
    return {"id": session.id, "media": info.to_dict()}
