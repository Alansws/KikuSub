"""字幕编辑路由：批量读写、单条增删改、撤销/重做、导出。

沿用规划 §4 的结论：**服务端是唯一真源**。前端的撤销栈只做乐观回显，
一旦服务端拒绝（越界、时间非法），前端整表重拉。
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import settings as settings_store
from core.i18n import bilingual_entries, target_cues
from core.subtitles import (
    SubtitleCue,
    cues_to_srt,
    cues_to_txt,
    cues_to_vtt,
    split_multiline_cues,
    srt_to_cues,
)
from core.textio import write_text_atomic

from .deps import get_session

log = logging.getLogger(__name__)
from .security import require_token
from .sessions import Session, TranslationTrack

router = APIRouter(tags=["cues"], dependencies=[Depends(require_token)])


class Cue(BaseModel):
    start: float
    end: float
    text: str = ""


class CueList(BaseModel):
    cues: list[Cue] = Field(default_factory=list)
    # 批量替换（查找替换 / AI 应用）可以自带操作说明，历史列表直接显示它。
    label: str = ""


class CuePatch(BaseModel):
    start: float | None = None
    end: float | None = None
    text: str | None = None


class InsertRequest(BaseModel):
    index: int
    start: float
    end: float
    text: str = ""


class SplitRequest(BaseModel):
    at: float


class MergeRequest(BaseModel):
    indices: list[int] = Field(default_factory=list)


class DeleteManyRequest(BaseModel):
    indices: list[int] = Field(default_factory=list)


class HistoryJumpRequest(BaseModel):
    index: int


class ExportRequest(BaseModel):
    format: str = "SRT"
    save_beside: bool = False
    # source = 只导原文（默认，行为与历史一致）；target = 只导译文；both = 双语（一条两行）
    track: str = "source"
    lang: str = ""


class ImportPathRequest(BaseModel):
    path: str = Field(min_length=1, description="本地字幕文件绝对路径")


def _to_dicts(cues: list[SubtitleCue]) -> list[dict]:
    return [{"start": c.start, "end": c.end, "text": c.text} for c in cues]


def _snapshot(session: Session) -> dict:
    return {
        "cues": _to_dicts(session.review_cues),
        "count": len(session.review_cues),
        "can_undo": session.can_undo,
        "can_redo": session.can_redo,
        # 工具栏按钮的 title 直接显示「下一步会撤回/重做什么」
        "undo_label": session.undo_label(),
        "redo_label": session.redo_label(),
        # 与渲染层「导出设置」的本地历史比先后，决定全局 ⌘Z 撤回哪一边
        "undo_at": session.undo_timestamp(),
        "redo_at": session.redo_timestamp(),
        # 当前核对表来自哪里（转写 / 导入字幕 / 暂存草稿）。检查器据此判断
        # 能不能引用最近一次转写的质检与参数。
        "review_source": dict(session.review_source),
    }


def _validate(start: float, end: float) -> None:
    if start < 0:
        raise HTTPException(status_code=422, detail="起始时间不能为负")
    if end <= start:
        raise HTTPException(status_code=422, detail="结束时间必须大于起始时间")


# 与桌面端暂存/复核版约定使用同一套后缀清理规则：草稿/复核版再存一次仍然回到主干名。
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


def _draft_i18n_path(request: Request, session: Session) -> Path:
    """译文轨的暂存文件：与 SRT 草稿同名，独立一份，避免破坏 SRT 的通用性。"""
    stem = _draft_stem(_media_stem(request, session))
    return Path(request.app.state.config.output_dir) / f"{stem}.autosave_draft.i18n.json"


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
    """核对台快照 + 译文轨摘要（只给条数/过期下标，全量文本走 /api/translations）。"""
    data = _snapshot(session)
    data["translations"] = {
        lang: {
            "count": len(track.texts),
            "stale": session.stale_translation(lang),
            "created_at": track.created_at,
            "entry": track.entry,
        }
        for lang, track in session.translations.items()
    }
    return data


@router.post("/api/cues")
def replace_cues(payload: CueList, session: Session = Depends(get_session)) -> dict:
    """整表替换：导入 SRT、设为基线、追加局部转写都走这里。"""
    cues = []
    for item in payload.cues:
        _validate(item.start, item.end)
        cues.append(SubtitleCue(start=item.start, end=item.end, text=item.text))
    label = (payload.label or "").strip() or f"替换全部字幕（{len(cues)} 条）"
    session.replace_review(cues, label=label)
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
    # 旧版双语交付文件：同一条 cue 里两行。拆成同时间轴的两条，与官方双语 SRT 一致。
    if _BILINGUAL_FILE_RE.search(path.name):
        cues, exploded = split_multiline_cues(cues)
        if exploded:
            log.info("导入双语字幕：按行拆分 | file=%s | cues=%d", path.name, len(cues))
    session.replace_review(
        cues,
        label=f"导入字幕（{len(cues)} 条）",
        source={
            "kind": "import",
            "name": path.name,
            "path": str(path),
            "job_id": "",
            "at": time.time(),
        },
    )
    # 导入会整表替换：与旧表条数对不上的译文轨已经无法逐条对齐，直接丢弃，
    # 否则核对台会继续显示上一版的译文，看起来像“新字幕的译文”。
    for lang in list(session.translations):
        if len(session.translations[lang].texts) != len(cues):
            session.drop_translation(lang)
            log.info("导入字幕时丢弃错位的译文轨 | lang=%s", lang)
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

    # 译文轨一起存：否则重开应用后译文全丢（开发文档 §6.5）
    i18n_path = _draft_i18n_path(request, session)
    tracks = {lang: track.to_dict() for lang, track in session.translations.items()}
    write_text_atomic(
        i18n_path,
        json.dumps({"version": 1, "tracks": tracks}, ensure_ascii=False, indent=2) + "\n",
    )

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
    session.replace_review(
        cues,
        label="恢复暂存草稿",
        source={
            "kind": "draft",
            "name": path.name,
            "path": str(path),
            "job_id": "",
            "at": time.time(),
        },
    )

    # 换了整张表，任何条数对不上的旧轨都已经无法对齐，先丢掉（不留一份错位的轨）
    for lang in list(session.translations):
        if len(session.translations[lang].texts) != len(cues):
            session.drop_translation(lang)
            log.info("恢复草稿时丢弃错位的译文轨 | lang=%s", lang)

    # 译文轨跟着恢复；文件不存在/损坏就跳过（不允许挡住字幕恢复）
    restored_langs: list[str] = []
    i18n_path = _draft_i18n_path(request, session)
    if i18n_path.exists():
        try:
            payload = json.loads(i18n_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            payload = {}
        tracks = payload.get("tracks") if isinstance(payload, dict) else None
        if isinstance(tracks, dict):
            for lang, raw in tracks.items():
                if not isinstance(raw, dict):
                    continue
                raw.setdefault("lang", lang)
                track = TranslationTrack.from_dict(raw)
                if len(track.texts) == len(cues):
                    # 走 set_translation：同步历史快照，之后删字幕按 ⌘Z 才能带回译文
                    session.set_translation(track)
                    restored_langs.append(track.lang)
                else:
                    # 条数对不上就丢弃，宁可让用户重翻，也不给一份错位的轨
                    log.warning(
                        "暂存译文轨条数不符，已忽略 | lang=%s | %d vs %d",
                        lang,
                        len(track.texts),
                        len(cues),
                    )

    return {**_snapshot(session), "source": str(path), "translations": sorted(restored_langs)}


# ---------------------------------------------------------------------------
# 可回溯历史（20 步）
#
# 放在 `/api/cues/{index}` 之前：未来若新增 GET 详情路由，"history" 不能被当成 index。
# ---------------------------------------------------------------------------


@router.get("/api/cues/history")
def cue_history(session: Session = Depends(get_session)) -> dict:
    """当前会话的时间线：每一步的说明、时间、是否当前状态。

    ``state`` 取 ``past``（可点回去）/ ``current`` / ``undone``（可重做）。
    """
    return {
        "items": session.history_items(),
        "cursor": session.history_cursor,
        "can_undo": session.can_undo,
        "can_redo": session.can_redo,
        "undo_label": session.undo_label(),
        "redo_label": session.redo_label(),
        "undo_at": session.undo_timestamp(),
        "redo_at": session.redo_timestamp(),
    }


@router.post("/api/cues/history/jump")
def cue_history_jump(
    payload: HistoryJumpRequest,
    session: Session = Depends(get_session),
) -> dict:
    """点历史里的任意一步：直接回到那个状态（后面的步骤仍可重做）。"""
    label = session.jump_history(payload.index)
    if label is None:
        raise HTTPException(status_code=422, detail=f"历史位置 {payload.index} 不存在")
    return {**_snapshot(session), "label": label, "index": payload.index}


@router.post("/api/cues/merge")
def merge_cues(payload: MergeRequest, session: Session = Depends(get_session)) -> dict:
    """合并连续的多条字幕（双语时译文一起拼），一次历史。

    前端在音轨上框选两句后右键「合并这 N 句」走这里；时间轴取首尾，
    文本按顺序直接相连（日文不需要空格）。
    """
    index = session.merge_cues(payload.indices)
    if index < 0:
        raise HTTPException(status_code=422, detail="只能合并两条以上、下标连续的字幕")
    return {**_snapshot(session), "index": index}


@router.post("/api/cues/delete")
def delete_cues(payload: DeleteManyRequest, session: Session = Depends(get_session)) -> dict:
    """批量删除（底部轨道 ⌘ 多选后按删除键）：一次历史、译文轨同步。"""
    removed = session.delete_cues(payload.indices)
    if not removed:
        raise HTTPException(status_code=422, detail="没有可删除的字幕")
    return {**_snapshot(session), "removed": removed}


@router.post("/api/cues/{index}/split")
def split_cue(index: int, payload: SplitRequest, session: Session = Depends(get_session)) -> dict:
    """在音频时间轴的当前位置把一条字幕切成两条；两段都保留完整原文。"""
    left = session.review_cues[index] if 0 <= index < len(session.review_cues) else None
    if left is None:
        raise HTTPException(status_code=404, detail=f"第 {index + 1} 条不存在")
    if not (left.start < payload.at < left.end):
        raise HTTPException(status_code=422, detail="切割点不在这条字幕的时间范围内")
    new_index = session.split_cue(index, payload.at)
    if new_index < 0:
        raise HTTPException(status_code=422, detail="切割点太靠近字幕边缘，至少各留 0.05 秒")
    return {**_snapshot(session), "index": index, "new_index": new_index}


@router.patch("/api/cues/{index}")
def patch_cue(index: int, payload: CuePatch, session: Session = Depends(get_session)) -> dict:
    if not 0 <= index < len(session.review_cues):
        raise HTTPException(status_code=404, detail=f"第 {index + 1} 条不存在")
    current = session.review_cues[index]
    start = current.start if payload.start is None else payload.start
    end = current.end if payload.end is None else payload.end
    text = current.text if payload.text is None else payload.text
    _validate(start, end)
    # 没有实际变化就不压历史：否则历史列表里会出现一串「点了但没改」的空操作
    if start == current.start and end == current.end and text == current.text:
        return _snapshot(session)
    parts = []
    if text != current.text:
        parts.append("文本")
    if start != current.start or end != current.end:
        parts.append("时间")
    label = f"修改第 {index + 1} 条{'与'.join(parts)}"
    session.update_cue(index, start, end, text, label=label)
    return _snapshot(session)


@router.delete("/api/cues/{index}")
def delete_cue(index: int, session: Session = Depends(get_session)) -> dict:
    """删除一条；同一位置的译文也一起删，后面的轨不会整体错位。"""
    if not session.delete_cue(index):
        raise HTTPException(status_code=404, detail=f"第 {index + 1} 条不存在")
    return {**_snapshot(session), "removed": 1}


@router.post("/api/cues/{index}/insert")
def insert_cue(index: int, payload: InsertRequest, session: Session = Depends(get_session)) -> dict:
    _validate(payload.start, payload.end)
    target = payload.index if payload.index >= 0 else index
    if not session.insert_cue(target, payload.start, payload.end, payload.text):
        raise HTTPException(status_code=422, detail=f"插入位置 {payload.index} 越界")
    return {**_snapshot(session), "index": target}


@router.post("/api/cues/undo")
def undo(session: Session = Depends(get_session)) -> dict:
    label = session.undo()
    if label is None:
        raise HTTPException(status_code=409, detail="没有可撤回的操作")
    return {**_snapshot(session), "undone": label}


@router.post("/api/cues/redo")
def redo(session: Session = Depends(get_session)) -> dict:
    label = session.redo()
    if label is None:
        raise HTTPException(status_code=409, detail="没有可重做的操作")
    return {**_snapshot(session), "redone": label}


@router.post("/api/cues/clear")
def clear_cues(session: Session = Depends(get_session)) -> dict:
    session.clear_review()
    return _snapshot(session)


_EXPORTERS = {"SRT": (cues_to_srt, ".srt"), "VTT": (cues_to_vtt, ".vtt"), "TXT": (cues_to_txt, ".txt")}

# 旧版（≤2026-11）双语导出把原文/译文写进同一条 cue 的两行；文件名带 `.bilingual`
# 时按行拆开，重新导入才不会显示成「日文 中文」挤在一行（开发文档 D-4）。
_BILINGUAL_FILE_RE = re.compile(r"\.bilingual(?=\.(?:srt|vtt)$)", re.IGNORECASE)


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

    track = (payload.track or "source").strip().lower()
    if track not in ("source", "target", "both"):
        raise HTTPException(status_code=422, detail=f"不支持的 track：{payload.track}")

    cues = session.review_cues
    suffix = ""
    skipped = 0
    lang = (payload.lang or "").strip()
    if track != "source":
        if not lang:
            raise HTTPException(status_code=422, detail="导出译文时必须指定语种")
        translation = session.translations.get(lang)
        if translation is None:
            raise HTTPException(status_code=409, detail=f"还没有 {lang} 的译文可用")
        if track == "target":
            cues, skipped = target_cues(cues, translation.texts)
            suffix = f".{lang}"
        else:
            # 交付文件用「每语种一条 cue」，与官方双语 SRT 的写法一致：
            # 播放器里叠成两行，重新导入核对台也不会把两种语言挤成一行。
            cues = bilingual_entries(cues, translation.texts)
            suffix = ".bilingual"
        if not cues:
            raise HTTPException(status_code=409, detail="译文全是空的，没有可导出的内容")

    text = render(cues)

    stem = _media_stem(request, session) or "subtitles"
    current = settings_store.load_settings(
        Path(getattr(request.app.state, "settings_path", settings_store.SETTINGS_PATH))
    )
    out_dir: Path = settings_store.resolve_export_dir(
        current,
        Path(request.app.state.config.output_dir),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}{suffix}{ext}"
    out_path.write_text(text, encoding="utf-8")
    return {
        "path": str(out_path),
        "text": text,
        "format": fmt,
        "count": len(cues),
        "track": track,
        "lang": lang,
        "skipped": skipped,
    }
