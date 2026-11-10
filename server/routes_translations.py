"""译文平行轨：读取、应用、撤销、删除。

译文**不写进** `review_cues.text`（开发文档 D-3），所以这里的写操作一律只动
`session.translations`，不碰时间轴、也不进 `review_cues` 的撤销栈——翻译的撤销是
每个语种自己的一份栈（"应用了一版译文"整批退回）。

校验口径与 `/api/ai/apply` 完全一致：条数必须相等、`i` 必须连续、digest 必须匹配。
不通过就整批拒绝，绝不落一份对不齐的轨。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import ai_proposal as proposals

from .deps import get_session
from .security import require_token
from .sessions import Session, TranslationTrack

router = APIRouter(tags=["translations"], dependencies=[Depends(require_token)])


class ApplyTranslationRequest(BaseModel):
    lang: str = Field(min_length=1)
    # 二选一：直接给译文数组（长度必须与核对台一致），或给一份 translate 提案
    texts: list[str] | None = None
    proposal: dict | None = None


class LangRequest(BaseModel):
    lang: str = Field(min_length=1)


class PatchTextRequest(BaseModel):
    text: str = ""


def track_payload(session: Session, lang: str) -> dict:
    """给前端的完整轨：文本 + 哪些条已经过期。"""
    track = session.translations.get(lang)
    if track is None:
        return {
            "lang": lang,
            "exists": False,
            "count": 0,
            "texts": [],
            "base": [],
            "stale": [],
            "created_at": 0.0,
            "entry": "",
        }
    return {
        "lang": lang,
        "exists": True,
        "count": len(track.texts),
        "texts": list(track.texts),
        "base": list(track.base),
        "stale": session.stale_translation(lang),
        "created_at": track.created_at,
        "entry": track.entry,
    }


def translations_payload(session: Session) -> dict:
    return {
        "items": [track_payload(session, lang) for lang in sorted(session.translations)],
        "count": len(session.translations),
        "cue_count": len(session.review_cues),
    }


@router.get("/api/translations")
def list_translations(session: Session = Depends(get_session)) -> dict:
    return translations_payload(session)


@router.post("/api/translations", status_code=201)
def apply_translation(
    payload: ApplyTranslationRequest,
    session: Session = Depends(get_session),
) -> dict:
    """应用一版译文。整轨替换，压一次该语种的撤销栈。"""
    lang = (payload.lang or "").strip()
    if not lang:
        raise HTTPException(status_code=422, detail="必须指定语种")
    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有字幕，无法应用译文")

    entry = "in-app"
    if payload.proposal is not None:
        data = dict(payload.proposal)
        kind = data.get("kind")
        if kind != "translate":
            raise HTTPException(status_code=422, detail="这不是一份翻译提案")
        check = proposals.validate_proposal(data, [c.text for c in cues])
        if not check.ok:
            raise HTTPException(
                status_code=check.status,
                detail="；".join(check.errors) or "提案无效",
            )
        texts = [str(item.get("after") or "") for item in sorted(data["items"], key=lambda it: it["i"])]
        entry = str(data.get("entry") or "in-app")
    else:
        texts = [str(t or "") for t in (payload.texts or [])]

    if len(texts) != len(cues):
        raise HTTPException(
            status_code=422,
            detail=f"译文条数不符：{len(texts)} 条译文 / {len(cues)} 条字幕",
        )

    session.set_translation(
        TranslationTrack(
            lang=lang,
            texts=texts,
            base=[c.text for c in cues],
            entry=entry,
        )
    )
    return track_payload(session, lang)


@router.patch("/api/translations/{lang}/{index}")
def patch_translation(
    lang: str,
    index: int,
    payload: PatchTextRequest,
    session: Session = Depends(get_session),
) -> dict:
    """改某一条译文。核对台「译文 / 双语」模式下直接编辑走这里。"""
    if not session.patch_translation(lang, index, payload.text):
        raise HTTPException(status_code=404, detail="没有这条译文（语种或下标不对）")
    return track_payload(session, lang)


@router.post("/api/translations/undo")
def undo_translation(payload: LangRequest, session: Session = Depends(get_session)) -> dict:
    """退回该语种上一版译文（没有历史时是空操作，不报错）。"""
    lang = (payload.lang or "").strip()
    undone = session.undo_translation(lang)
    return {**track_payload(session, lang), "undone": undone}


@router.delete("/api/translations/{lang}")
def delete_translation(lang: str, session: Session = Depends(get_session)) -> dict:
    removed = session.drop_translation(lang)
    return {"lang": lang, "removed": removed, "count": len(session.translations)}
