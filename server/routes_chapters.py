"""章节 / 时刻点标记接口：读取、整表保存（一步历史 + 落盘）。

标记属于**工作区状态**：和字幕共用 `Session.history` 那条 50 步时间线，
所以新建 / 改名 / 改时间 / 删除都能被 ⌘Z 退掉；同时按媒体身份写边车文件，
切片与重启都不丢（详见 `core/chapters.py`）。

为什么是「整表保存」而不是 POST/PATCH/DELETE 三个动作：界面上的四种操作都只是
「新列表」的不同来源，整表 + 一个 label 恰好等于一次 ⌘Z；拆成三个接口会让
「改名 + 微调时间」变成两步历史。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import chapters as chapter_store

from .deps import get_session
from .security import require_token
from .sessions import Session

router = APIRouter(tags=["chapters"], dependencies=[Depends(require_token)])
log = logging.getLogger("kikusub.server")


class ChapterMarkPayload(BaseModel):
    id: str = Field(default="", max_length=64)
    start: float = Field(default=0.0, ge=0.0)
    # None = 时刻点（结束时间由下一个标记或片尾决定）
    end: float | None = Field(default=None, ge=0.0)
    title: str = Field(default="", max_length=chapter_store.MAX_TITLE)


class ChaptersRequest(BaseModel):
    # 上限在 core 里也有一份（MAX_MARKS），这里只是把明显超量的请求挡在解析层
    marks: list[ChapterMarkPayload] = Field(default_factory=list, max_length=chapter_store.MAX_MARKS)
    label: str = Field(default="", max_length=120)


def _output_dir(request: Request) -> Path:
    return Path(getattr(request.app.state.config, "output_dir", "."))


def _duration(request: Request, session: Session) -> float:
    """当前媒体的总时长；取不到时 0（章节衔接会退到「起点 + 1s」兜底）。"""
    if not session.media_id:
        return 0.0
    try:
        info = request.app.state.media.get(session.media_id)
    except Exception:  # noqa: BLE001 - 媒体被删 / 未导入都只是没有片长
        return 0.0
    return float(getattr(info, "duration", 0.0) or 0.0)


def _payload(session: Session, request: Request) -> dict:
    duration = _duration(request, session)
    laid_out = chapter_store.layout_chapters(session.chapters, duration)
    return {
        "marks": [mark.to_dict() for mark in session.chapters],
        # 导出/播放器实际会看到的区间：前端用它显示「写入后是这几段」
        "chapters": [chapter.to_dict() for chapter in laid_out],
        "count": len(session.chapters),
        "duration": duration,
        "media_path": session.media_path,
    }


@router.get("/api/chapters")
def get_chapters(request: Request, session: Session = Depends(get_session)) -> dict:
    """当前媒体的全部标记。没有媒体时返回空表（不报错，界面据此显示空态）。"""
    if not session.media_path:
        return {"marks": [], "chapters": [], "count": 0, "duration": 0.0, "media_path": ""}
    # 同一会话里可能刚被别的路径改过边车：内存是唯一真源，这里只补一次绑定。
    if not session.chapters_dir:
        session.sync_chapters(
            media_path=session.media_path,
            output_dir=_output_dir(request),
            duration=_duration(request, session),
        )
    return _payload(session, request)


@router.post("/api/chapters")
def save_chapters(
    payload: ChaptersRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """整表替换标记：一步历史 + 原子落盘。label 由前端给（「新建章节…」等）。"""
    if not session.media_path:
        raise HTTPException(status_code=409, detail="还没有导入媒体：章节标记需要绑定一部影片")
    duration = _duration(request, session)
    if not session.chapters_dir:
        # 会话可能是旧进程 / 刚重启：先把落盘目录绑上，否则这次改动进不了边车
        session.sync_chapters(
            media_path=session.media_path,
            output_dir=_output_dir(request),
            restore=False,
            duration=duration,
        )
    session.set_chapters(
        [mark.model_dump() for mark in payload.marks],
        label=payload.label or "编辑章节标记",
        duration=duration,
    )
    data = _payload(session, request)
    data.update(
        {
            "can_undo": bool(session.can_undo),
            "can_redo": bool(session.can_redo),
            "undo_label": session.undo_label(),
            "redo_label": session.redo_label(),
        }
    )
    return data
