"""字幕编辑路由：批量读写、单条增删改、撤销/重做、导出。

沿用规划 §4 的结论：**服务端是唯一真源**。前端的撤销栈只做乐观回显，
一旦服务端拒绝（越界、时间非法），前端整表重拉。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import settings as settings_store
from core.subtitles import SubtitleCue, cues_to_srt, cues_to_txt, cues_to_vtt, srt_to_cues
from core.textio import write_text_atomic

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


class ImportPathRequest(BaseModel):
    path: str = Field(min_length=1, description="本地字幕文件绝对路径")


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


# 与 app.py 的校对断点使用同一套后缀清理规则：草稿/复核版再存一次仍然回到主干名。
_DRAFT_SUFFIX_RE = re.compile(r"(\.autosave_draft|\.reviewed|\.clean|\.part_cancelled)$")


def _media_stem(request: Request, session: Session) -> str:
    """当前会话绑定媒体的主干名；未绑定或文件已被移走时返回空串。"""
    if not session.media_id:
        return ""
    try:
        info = request.app.state.media.get(session.media_id)
        return Path(info.path).stem
    except Exception:
        return ""


def _draft_stem(stem: str) -> str:
    return _DRAFT_SUFFIX_RE.sub("", stem) or "subtitles"


def _draft_path(request: Request, session: Session) -> Path:
    """工作草稿放在运行数据目录，绝不占用导出文件夹里的交付文件名。

    文件名沿用旧界面的 `{stem}.autosave_draft.srt`：两个界面共用同一份草稿，
    用户在桌面版里接着 Legacy 的进度核对时不会出现两套互相覆盖的备份。
    """
    stem = _draft_stem(_media_stem(request, session))
    return Path(request.app.state.config.output_dir) / f"{stem}.autosave_draft.srt"


def _draft_info(path: Path) -> dict:
    if not path.exists():
        return {"exists": False, "path": str(path), "count": 0, "saved_at": 0.0}
    try:
        stat = path.stat()
        cues = srt_to_cues(path.read_text(encoding="utf-8-sig", errors="replace"))
    except OSError:
        return {"exists": False, "path": str(path), "count": 0, "saved_at": 0.0}
    return {"exists": True, "path": str(path), "count": len(cues), "saved_at": stat.st_mtime}


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


@router.post("/api/cues/import")
def import_cues(payload: ImportPathRequest, session: Session = Depends(get_session)) -> dict:
    """按路径导入 SRT / VTT 作为核对基线。

    与媒体导入同一个约定：传路径而不是上传内容——桌面端拿到的就是本地路径。
    导入会整表替换并压入撤回栈，用户可立即 Cmd+Z 退回。
    """
    path = Path(payload.path).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"文件不存在：{payload.path}") from exc
    if path.suffix.lower() not in {".srt", ".vtt"}:
        raise HTTPException(status_code=422, detail=f"只支持 .srt / .vtt：{path.suffix}")

    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"读取失败：{exc}") from exc

    # VTT 的 WEBVTT 头 / NOTE 块不是字幕行；时间戳格式与 SRT 兼容（解析器认 . 和 ,）
    if path.suffix.lower() == ".vtt":
        body: list[str] = []
        skipping = False
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            stripped = line.strip()
            if stripped.upper().startswith("WEBVTT"):
                continue
            if stripped.upper().startswith(("NOTE", "STYLE", "REGION")):
                skipping = True
                continue
            if skipping:
                if not stripped:
                    skipping = False
                continue
            body.append(line)
        text = "\n".join(body)

    cues = srt_to_cues(text)
    if not cues:
        raise HTTPException(status_code=422, detail="没有从该文件里解析出字幕")
    session.replace_review(cues)
    return {**_snapshot(session), "source": str(path)}


# ---------------------------------------------------------------------------
# 核对草稿（临时全量保存）
#
# 注意：`/api/cues/draft/restore` 必须在 `/api/cues/{index}/insert` 之前注册。
# FastAPI 按声明顺序匹配，否则 "draft" 会被当成 index 并回 422。
# ---------------------------------------------------------------------------


@router.get("/api/cues/draft")
def get_draft(request: Request, session: Session = Depends(get_session)) -> dict:
    """查询当前媒体的工作草稿是否存在、多少条、最后写入时间。"""
    return _draft_info(_draft_path(request, session))


@router.post("/api/cues/draft")
def save_draft(request: Request, session: Session = Depends(get_session)) -> dict:
    """把核对台**全部**字幕写进工作草稿。

    这是核对精修期间的防丢备份：只写运行数据目录里的 `*.autosave_draft.srt`，
    不改导出文件夹里的交付文件，也不进入撤回栈（保存本身不是一次编辑）。
    """
    if not session.review_cues:
        raise HTTPException(status_code=409, detail="当前没有可暂存的字幕")
    path = _draft_path(request, session)
    write_text_atomic(path, cues_to_srt(session.review_cues))
    return {
        "exists": True,
        "path": str(path),
        "count": len(session.review_cues),
        "saved_at": path.stat().st_mtime,
    }


@router.post("/api/cues/draft/restore")
def restore_draft(request: Request, session: Session = Depends(get_session)) -> dict:
    """用工作草稿覆盖核对台（压入撤回栈，⌘Z 可一步退回）。"""
    path = _draft_path(request, session)
    if not path.exists():
        raise HTTPException(status_code=404, detail="还没有可恢复的暂存草稿")
    try:
        cues = srt_to_cues(path.read_text(encoding="utf-8-sig", errors="replace"))
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"读取暂存草稿失败：{exc}") from exc
    if not cues:
        raise HTTPException(status_code=422, detail="暂存草稿里没有解析出字幕")
    session.replace_review(cues)
    return {**_snapshot(session), "source": str(path)}


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

    stem = _media_stem(request, session) or "subtitles"
    current = settings_store.load_settings(
        Path(getattr(request.app.state, "settings_path", settings_store.SETTINGS_PATH))
    )
    out_dir: Path = settings_store.resolve_export_dir(
        current,
        Path(request.app.state.config.output_dir),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}{ext}"
    out_path.write_text(text, encoding="utf-8")
    return {"path": str(out_path), "text": text, "format": fmt, "count": len(session.review_cues)}
