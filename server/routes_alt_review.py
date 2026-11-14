"""第二版本（双引擎复核）路由。

第二版是**参考文档**：读取、删除、整列替换核对台。逐句采用不做——复核页只做
只读对照，真正的编辑仍回核对台（避免断句/时间戳不一致带来的合并 Bug）。

三个接口：

- ``GET /api/alt-review``：第二版摘要 + 全量 cues；``diff=1`` 时附上按当前两份
  字幕**实时计算**的对齐行与统计（``core.dual_review``，不持久化下标）。
- ``DELETE /api/alt-review``：丢弃第二版，同时删内存与磁盘边车。
- ``POST /api/alt-review/replace-primary``：整列用 B 覆盖核对台，走统一历史
  （一次 ⌘Z 全退），默认覆盖成功后清掉第二版（避免两列完全相同仍占徽标）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core import dual_review

from .deps import get_session
from .routes_cues import _snapshot
from .security import require_token
from .sessions import AltReview, Session

router = APIRouter(tags=["alt-review"], dependencies=[Depends(require_token)])


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


@router.get("/api/alt-review")
def get_alt_review(
    request: Request,
    diff: bool = False,
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
    if diff:
        review = dual_review.build_review(session.review_cues, alt.cues)
        data["rows"] = review["rows"]
        data["stats"] = review["stats"]
    else:
        # 徽标只需要差异行数：仍然实时算一份统计（O(n)，不返回 rows，省传输）。
        review = dual_review.build_review(session.review_cues, alt.cues)
        data["rows"] = []
        data["stats"] = review["stats"]
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
    source["kind"] = "transcription"
    source["engine"] = alt.engine or source.get("engine", "")
    source["apply"] = "replace"
    source["at"] = source.get("at") or alt.created_at
    session.replace_review(
        alt.copy().cues,
        label=f"整列采用第二引擎稿（{len(alt.cues)} 条）",
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
