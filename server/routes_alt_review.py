"""第二版本（双引擎复核）路由。

第二版是**参考文档**：读取、删除、整列替换核对台。2026-11-21（界面重构 Step 2）
起复核页多了「单句采用 B」的页内闭环，但它**没有**在本模块新增写接口：前端只是
把 B 那一行的文本走 ``PATCH /api/cues/{index}``（带 ``label``）写回核对台，因此
仍然是一步统一历史、⌘Z 一次撤回，也不会出现「两套可编辑字幕」。断句与时间戳
不做合并——采纳只换文本，时间轴保持核对台当前值。

四个接口：

- ``GET /api/alt-review``：第二版摘要 + 全量 cues；``diff=1`` 时附上按当前两份
  字幕**实时计算**的对齐行与统计（``core.dual_review``，不持久化下标）。
  ``ignore_punct``（默认 ``1``）只把「标点 / 空白不同」判为一致，不计入差异数。
- ``POST /api/alt-review/import``：把工作流里已经做好的另一版字幕直接导入第二列
  （与转写产出的 B 版同构：同一份 ``AltReview``、同一份边车、同样的 diff/润色链路）。
- ``DELETE /api/alt-review``：丢弃第二版，同时删内存与磁盘边车。
- ``POST /api/alt-review/replace-primary``：整列用 B 覆盖核对台，走统一历史
  （一次 ⌘Z 全退），默认覆盖成功后清掉第二版（避免两列完全相同仍占徽标）。
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import dual_review, export_naming
from core.cues import _unique_sorted_cues
from core.subtitles import cues_from_subtitle_file

from .deps import get_session
from .routes_cues import _BILINGUAL_FILE_RE, _snapshot
from .security import require_token
from .sessions import AltReview, Session

router = APIRouter(tags=["alt-review"], dependencies=[Depends(require_token)])


class ImportAltRequest(BaseModel):
    """按路径导入一份已有字幕作为第二版（与媒体/字幕导入同一约定）。"""

    path: str = Field(min_length=1, max_length=4096)


class ReplacePrimaryRequest(BaseModel):
    # 覆盖成功后默认清空第二版（Q11）；想保留对照可显式传 false。
    clear_alt: bool = True


def _output_dir(request: Request) -> Path:
    return Path(request.app.state.config.output_dir)


def _media_path(request: Request, session: Session) -> str:
    if session.media_id:
        try:
            return str(request.app.state.media.get(session.media_id).path)
        except Exception:
            pass
    return str(session.media_path or "")


def _ensure_synced(request: Request, session: Session) -> str:
    path = _media_path(request, session)
    if path:
        session.sync_alt_review(media_path=path, output_dir=_output_dir(request))
    return path


def _cues_payload(alt: AltReview) -> list[dict]:
    return [{"start": cue.start, "end": cue.end, "text": cue.text} for cue in alt.cues]


@router.post("/api/alt-review/import")
def import_alt_review(
    payload: ImportAltRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """把一份已经导出的 SRT / VTT 作为第二版字幕导入。

    与「转写结果放进第二列」写的是同一个 ``AltReview``：
    边车落盘、切媒体恢复、实时 diff、双源润色、断句重排参考、整列覆盖全部复用。
    核对台一个字都不动，也不进 50 步历史。
    """
    path = Path(payload.path).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"文件不存在：{payload.path}") from exc
    if path.suffix.lower() not in {".srt", ".vtt"}:
        raise HTTPException(status_code=422, detail=f"只支持 .srt / .vtt：{path.suffix}")
    if _BILINGUAL_FILE_RE.search(path.name):
        raise HTTPException(
            status_code=422,
            detail="第二版要比对原文轨：双语交付文件（.bilingual）请先在核对台导入并按语言拆分",
        )

    media_path = _ensure_synced(request, session)
    if not media_path:
        raise HTTPException(
            status_code=409,
            detail="第二版按影片身份保存：请先在「导入」页打开影片，再导入这份字幕",
        )

    try:
        cues = cues_from_subtitle_file(path)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"读取失败：{exc}") from exc
    if not cues:
        raise HTTPException(status_code=422, detail="没有从该文件里解析出字幕")

    cues = _unique_sorted_cues(cues)
    engine = export_naming.engine_from_filename(path.name, Path(media_path).stem)
    source = {
        "kind": "import",
        "engine": engine,
        "name": path.name,
        "path": str(path),
        "job_id": "",
        "at": time.time(),
        "apply": "alt_review",
    }
    alt = session.set_alt_review(
        engine=engine,
        cues=cues,
        source=source,
        params={},
        media_path=media_path,
        output_dir=_output_dir(request),
    )
    return {
        "exists": True,
        "engine": alt.engine,
        "count": len(alt.cues),
        "source": dict(alt.source),
        "created_at": alt.created_at,
        "warning": _duration_warning(request, session, alt.cues),
    }


def _duration_warning(request: Request, session: Session, cues) -> str:
    """时间码明显超出影片时长时给一句提醒；不阻断导入（可能只是长版/加长片）。"""
    if not session.media_id:
        return ""
    try:
        info = request.app.state.media.get(session.media_id)
    except Exception:
        return ""
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    if duration <= 0:
        return ""
    beyond = sum(1 for cue in cues if float(cue.start) > duration + 1.0)
    if not beyond:
        return ""
    return (
        f"有 {beyond} 条字幕的时间码超出当前影片时长（{duration:.1f}s），"
        "确认这份字幕是对应本片的吗？"
    )


@router.get("/api/alt-review")
def get_alt_review(
    request: Request,
    diff: bool = False,
    ignore_punct: bool = True,
    session: Session = Depends(get_session),
) -> dict:
    _ensure_synced(request, session)
    alt = session.alt_review
    if alt is None:
        return {
            "exists": False,
            "engine": "",
            "count": 0,
            "source": {},
            "created_at": 0,
            "cues": [],
            "stats": None,
            "rows": [],
        }
    data = session.alt_review_summary()
    data["cues"] = _cues_payload(alt)
    data["media_path"] = alt.media_path
    data["params"] = dict(alt.params)
    # 2026-11-21（Step 2）：``ignore_punct`` 默认开——只有标点 / 空白不同的行
    # 判为一致，不计入 ``~ 文本不同`` 与侧栏徽标；``?ignore_punct=0`` 回到严格比对。
    review = dual_review.build_review(
        session.review_cues, alt.cues, ignore_punct=ignore_punct
    )
    data["stats"] = review["stats"]
    data["ignore_punct"] = bool(ignore_punct)
    # diff 模式返回全量行；否则只要统计（O(n)，不返回 rows，省传输）。
    data["rows"] = review["rows"] if diff else []
    return data


@router.delete("/api/alt-review")
def delete_alt_review(request: Request, session: Session = Depends(get_session)) -> dict:
    path = _ensure_synced(request, session)
    removed = session.clear_alt_review(
        media_path=path,
        output_dir=_output_dir(request),
        remove_cache=True,
    )
    return {"removed": removed, "exists": False}


@router.post("/api/alt-review/replace-primary")
def replace_primary(
    payload: ReplacePrimaryRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """整列用第二版覆盖核对台：一次历史，时间码逐条取第二版自己的。"""
    path = _ensure_synced(request, session)
    alt = session.alt_review
    if alt is None or not alt.cues:
        raise HTTPException(status_code=409, detail="还没有第二版字幕")
    source = dict(alt.source)
    # 导入稿的来源必须原样保留（kind=import + 原文件名）：
    # 如果强行改写成 transcription，覆盖后检查器会去找一份不存在的转写报告，
    # ⌘Z 退回去时来源也会错位。转写生成的 B 版才标记成 transcription。
    if source.get("kind") != "import":
        source["kind"] = "transcription"
        source["engine"] = alt.engine or source.get("engine", "")
    source["apply"] = "replace"
    source["at"] = source.get("at") or alt.created_at
    label = (
        "整列采用导入的第二版" if source.get("kind") == "import" else "整列采用第二引擎稿"
    )
    session.replace_review(
        alt.copy().cues,
        label=f"{label}（{len(alt.cues)} 条）",
        source=source,
    )
    if payload.clear_alt:
        session.clear_alt_review(
            media_path=path,
            output_dir=_output_dir(request),
            remove_cache=True,
        )
    return {
        **_snapshot(session),
        "replaced": len(alt.cues),
        "alt_cleared": bool(payload.clear_alt),
    }
