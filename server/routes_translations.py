"""译文平行轨：读取、应用、撤销、删除。

译文**不写进** `review_cues.text`（开发文档 D-3），所以这里的写操作一律只动
`session.translations`，不碰时间轴、也不进 `review_cues` 的撤销栈——翻译的撤销是
每个语种自己的一份栈（"应用了一版译文"整批退回）。

校验口径与 `/api/ai/apply` 完全一致：条数必须相等、`i` 必须连续、digest 必须匹配。
不通过就整批拒绝，绝不落一份对不齐的轨。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import ai_proposal as proposals
from core.subtitles import align_translation_texts, cues_from_subtitle_file

from .deps import get_session
from .security import require_token
from .sessions import Session, TranslationTrack

router = APIRouter(tags=["translations"], dependencies=[Depends(require_token)])
log = logging.getLogger(__name__)


class ApplyTranslationRequest(BaseModel):
    lang: str = Field(min_length=1)
    # 二选一：直接给译文数组（长度必须与核对台一致），或给一份 translate 提案
    texts: list[str] | None = None
    proposal: dict | None = None


class ImportTranslationRequest(BaseModel):
    path: str = Field(min_length=1, description="本地译文 SRT / VTT 绝对路径")
    lang: str = Field(min_length=1, description="译文语种，例如 zh-Hans / en")


class LangRequest(BaseModel):
    lang: str = Field(min_length=1)


class PatchTextRequest(BaseModel):
    text: str = ""


class ReplaceTextsRequest(BaseModel):
    """整轨替换文本：查找替换「全部替换」一次提交，避免逐条压历史。"""

    texts: list[str] = Field(default_factory=list)


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


@router.post("/api/translations/import", status_code=201)
def import_translation(
    payload: ImportTranslationRequest,
    session: Session = Depends(get_session),
) -> dict:
    """按路径导入一份译文 SRT / VTT。

    译文轨**只替换文本**，时间轴始终取自当前原文：条数必须与核对台一致，
    否则整批拒绝——宁可让用户重新导出对齐的译文，也不落一份错位的轨。
    这是「已经翻译好、只是重开应用后没有入口」的补录通道，与 AI 提案互不影响。
    """
    lang = (payload.lang or "").strip()
    if not lang:
        raise HTTPException(status_code=422, detail="必须指定译文语种")

    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有原文字幕，请先导入原文轨")

    path = Path(payload.path).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"文件不存在：{payload.path}") from exc
    if path.suffix.lower() not in {".srt", ".vtt"}:
        raise HTTPException(status_code=422, detail=f"只支持 .srt / .vtt：{path.suffix}")
    try:
        imported = cues_from_subtitle_file(path)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"读取失败：{exc}") from exc

    if not imported:
        raise HTTPException(status_code=422, detail="没有从该文件里解析出字幕")
    texts = align_translation_texts(cues, imported)
    if texts is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"译文无法与当前原文对齐：译文 {len(imported)} 条 / 原文 {len(cues)} 条。"
                "请导出与当前原文时间轴一致的译文字幕，或先删掉原文轨再重新导入。"
            ),
        )

    session.set_translation(
        TranslationTrack(
            lang=lang,
            texts=texts,
            base=[cue.text for cue in cues],
            entry="import",
        ),
        label=f"导入 {lang} 译文（{len(texts)} 条）",
    )
    log.info(
        "导入译文字幕 | lang=%s | file=%s | cues=%d", lang, path.name, len(texts)
    )
    return {**track_payload(session, lang), "path": str(path)}


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
        ),
        label=f"应用 {lang} 译文（{len(texts)} 条）",
    )
    return track_payload(session, lang)


# 注意：这条必须声明在 `/api/translations/{lang}/{index}` 之前。FastAPI 按声明顺序
# 匹配，否则 "replace" 会先被当成 index 解析并回 422。
@router.post("/api/translations/{lang}/replace")
def replace_translation_texts(
    lang: str,
    payload: ReplaceTextsRequest,
    session: Session = Depends(get_session),
) -> dict:
    """整轨替换文本（查找替换 - 全部替换走这里，一次提交）。

    与逐条 PATCH 的区别：不改变轨道版本来源，也不会产生 N 步撤销；前端先算好
    整份文本数组再提交。条数必须与当前轨道一致，否则整批拒绝。
    """
    track = session.translations.get(lang)
    if track is None:
        raise HTTPException(status_code=404, detail=f"没有 {lang} 译文轨")
    texts = [str(t or "") for t in payload.texts]
    if len(texts) != len(track.texts):
        raise HTTPException(
            status_code=422,
            detail=f"译文条数不符：{len(texts)} 条译文 / 轨道 {len(track.texts)} 条",
        )
    if texts == track.texts:
        return track_payload(session, lang)
    replaced = sum(1 for a, b in zip(track.texts, texts) if a != b)
    session.set_translation(
        TranslationTrack(
            lang=lang,
            texts=texts,
            # 批量替换是基于当前原文做的，直接视为已同步，避免整轨被标成过期。
            base=[cue.text for cue in session.review_cues],
            created_at=track.created_at,
            entry=track.entry,
        ),
        label=f"替换 {lang} 译文（{replaced} 处）",
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
    removed = session.drop_translation(lang, label=f"删除 {lang} 译文")
    return {"lang": lang, "removed": removed, "count": len(session.translations)}
