"""字幕编辑路由：批量读写、单条增删改、撤销/重做、导出。

沿用规划 §4 的结论：**服务端是唯一真源**。前端的撤销栈只做乐观回显，
一旦服务端拒绝（越界、时间非法），前端整表重拉。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core.transcribe import (
    SubtitleCue,
    cues_to_srt,
    cues_to_txt,
    cues_to_vtt,
)

from .deps import get_session
from .security import require_token
from .sessions import Session

router = APIRouter(tags=["cues"], dependencies=[Depends(require_token)])


class Cue(BaseModel):
    start: float
    end: float
    text: str = ""


class CueList(BaseModel):
    cues: list[Cue] = Field(default_factory=list)


class CuePatch(BaseModel):
    start: float | None = None
    end: float | None = None
    text: str | None = None


class InsertRequest(BaseModel):
    index: int
    start: float
    end: float
    text: str = ""


class ExportRequest(BaseModel):
    format: str = "SRT"
    save_beside: bool = False


def _to_dicts(cues: list[SubtitleCue]) -> list[dict]:
    return [{"start": c.start, "end": c.end, "text": c.text} for c in cues]


def _snapshot(session: Session) -> dict:
    return {
        "cues": _to_dicts(session.review_cues),
        "count": len(session.review_cues),
        "can_undo": bool(session.undo_stack),
        "can_redo": bool(session.redo_stack),
    }


def _validate(start: float, end: float) -> None:
    if start < 0:
        raise HTTPException(status_code=422, detail="起始时间不能为负")
    if end <= start:
        raise HTTPException(status_code=422, detail="结束时间必须大于起始时间")


@router.get("/api/cues")
def list_cues(session: Session = Depends(get_session)) -> dict:
    return _snapshot(session)


@router.post("/api/cues")
def replace_cues(payload: CueList, session: Session = Depends(get_session)) -> dict:
    """整表替换：导入 SRT、设为基线、追加局部转写都走这里。"""
    cues = []
    for item in payload.cues:
        _validate(item.start, item.end)
        cues.append(SubtitleCue(start=item.start, end=item.end, text=item.text))
    session.replace_review(cues)
    return _snapshot(session)


@router.patch("/api/cues/{index}")
def patch_cue(index: int, payload: CuePatch, session: Session = Depends(get_session)) -> dict:
    if not 0 <= index < len(session.review_cues):
        raise HTTPException(status_code=404, detail=f"第 {index + 1} 条不存在")
    current = session.review_cues[index]
    start = current.start if payload.start is None else payload.start
    end = current.end if payload.end is None else payload.end
    text = current.text if payload.text is None else payload.text
    _validate(start, end)
    session.update_cue(index, start, end, text)
    return _snapshot(session)


@router.delete("/api/cues/{index}")
def delete_cue(index: int, session: Session = Depends(get_session)) -> dict:
    if not session.delete_cue(index):
        raise HTTPException(status_code=404, detail=f"第 {index + 1} 条不存在")
    return _snapshot(session)


@router.post("/api/cues/{index}/insert")
def insert_cue(index: int, payload: InsertRequest, session: Session = Depends(get_session)) -> dict:
    _validate(payload.start, payload.end)
    if not session.insert_cue(payload.index if payload.index >= 0 else index,
                              payload.start, payload.end, payload.text):
        raise HTTPException(status_code=422, detail=f"插入位置 {payload.index} 越界")
    return _snapshot(session)


@router.post("/api/cues/undo")
def undo(session: Session = Depends(get_session)) -> dict:
    if not session.undo():
        raise HTTPException(status_code=409, detail="没有可撤回的操作")
    return _snapshot(session)


@router.post("/api/cues/redo")
def redo(session: Session = Depends(get_session)) -> dict:
    if not session.redo():
        raise HTTPException(status_code=409, detail="没有可重做的操作")
    return _snapshot(session)


@router.post("/api/cues/clear")
def clear_cues(session: Session = Depends(get_session)) -> dict:
    session.clear_review()
    return _snapshot(session)


_EXPORTERS = {"SRT": (cues_to_srt, ".srt"), "VTT": (cues_to_vtt, ".vtt"), "TXT": (cues_to_txt, ".txt")}


@router.post("/api/cues/export")
def export_cues(
    payload: ExportRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """导出字幕。返回落盘路径与文本，前端可直接展示或另存。"""
    fmt = payload.format.upper()
    exporter = _EXPORTERS.get(fmt)
    if exporter is None:
        raise HTTPException(status_code=422, detail=f"不支持的格式：{payload.format}")
    if not session.review_cues:
        raise HTTPException(status_code=409, detail="当前没有可导出的字幕")

    render, ext = exporter
    text = render(session.review_cues)

    media_name = ""
    if session.media_id:
        try:
            info = request.app.state.media.get(session.media_id)
            media_name = info.path.stem
        except Exception:
            media_name = ""
    stem = media_name or "subtitles"
    out_dir: Path = request.app.state.config.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}{ext}"
    out_path.write_text(text, encoding="utf-8")
    return {"path": str(out_path), "text": text, "format": fmt, "count": len(session.review_cues)}
