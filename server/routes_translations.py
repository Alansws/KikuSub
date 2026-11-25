"""译文平行轨：读取、应用、撤销、删除。

译文**不写进** `review_cues.text`（开发文档 D-3），所以这里的写操作一律只动
`session.translations`，不碰时间轴、也不进 `review_cues` 的撤销栈——翻译的撤销是
每个语种自己的一份栈（"应用了一版译文"整批退回）。

校验口径与 `/api/ai/apply` 完全一致：条数必须相等、`i` 必须连续、digest 必须匹配。
不通过就整批拒绝，绝不落一份对不齐的轨。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import ai_gap
from core import ai_proposal as proposals
from core.i18n import merge_translation_texts, pending_indices
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
    # 逐条采纳的**全片 1 基序号**；缺省 = 全采纳。补译 / 取消勾选都靠它。
    accept: list[int] | None = None


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


class GapItem(BaseModel):
    """补译回填的一条：``i`` 全片 1 基序号，``before`` 是复制时的原文（防错位）。"""

    i: int
    before: str = ""
    after: str = ""


class GapApplyRequest(BaseModel):
    lang: str = Field(min_length=1)
    items: list[GapItem] = Field(default_factory=list)


def _require_aligned(session: Session, lang: str, track: TranslationTrack) -> None:
    """译文轨必须与原文逐条对齐；不对齐时宁可拒绝，也不写一份错位的轨。"""
    total = len(session.review_cues)
    if len(track.texts) != total:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{lang} 译文轨与原文条数不一致（{len(track.texts)} / {total}）；"
                "请重新导入译文，或删除这条译文轨后再补译"
            ),
        )


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
            "pending": 0,
            "stale": [],
            "created_at": 0.0,
            "entry": "",
        }
    return {
        "lang": lang,
        "exists": True,
        "count": len(track.texts),
        # 「待译」与「原文已改」是两件事：前者是还没翻，后者是翻了但对不上。
        "pending": len(pending_indices(session.review_cues, track.texts)),
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


def _commit_merged(
    session: Session,
    lang: str,
    cues,
    updates: dict[int, str],
    *,
    skip_empty: bool,
    sync_unchanged_base: bool,
    label: str,
    entry: str = "",
) -> tuple[dict, list[int], int]:
    """把本次要写的条目合并进整片轨，只在真的有变化时压一步历史。

    返回 ``(轨 payload, 文本真正变化的下标, 因空值被保留的条数)``。
    服务端只写 ``updates`` 里的下标——范围外 / 未采纳 / 批外的槽位不会进入写循环，
    这是「补译不覆盖已核对译文」的第一道（也是最硬的一道）锁。
    """
    track = session.translations.get(lang)
    if track is not None and len(track.texts) != len(cues):
        raise HTTPException(
            status_code=409,
            detail=(
                f"{lang} 译文轨与原文条数不一致（{len(track.texts)} / {len(cues)}）；"
                "请重新导入译文，或删除这条译文轨后再应用"
            ),
        )
    texts, base, changed, kept = merge_translation_texts(
        [cue.text for cue in cues],
        track.texts if track is not None else None,
        track.base if track is not None else None,
        updates,
        skip_empty=skip_empty,
        sync_unchanged_base=sync_unchanged_base,
    )
    before_base = list(track.base) if track is not None else []
    base_dirty = any(
        base[index] != (before_base[index] if index < len(before_base) else "")
        for index in updates
    )
    dirty = (
        (track is None and any(text.strip() for text in texts))
        or (track is not None and (texts != list(track.texts) or base_dirty))
    )
    if dirty:
        session.set_translation(
            TranslationTrack(
                lang=lang,
                texts=texts,
                base=base,
                created_at=track.created_at if track is not None else time.time(),
                entry=entry or (track.entry if track is not None else "in-app"),
            ),
            label=label,
        )
    return track_payload(session, lang), changed, kept


@router.post("/api/translations", status_code=201)
def apply_translation(
    payload: ApplyTranslationRequest,
    session: Session = Depends(get_session),
) -> dict:
    """应用一版译文。

    整轨替换会替换整条轨；片段应用只写这一段。**提案里的空槽位不清掉已有译文**：
    模型把相邻两句合并成一条时，被合并槽位的 ``after`` 是空串，它只表示「本批没有
    这一条」，不表示「删掉用户已核对的译文」。逐条取消采纳（``accept``）同理。
    直接给 ``texts`` 数组时每一格都是最终值（允许清空），与「全部替换」同口径。
    """
    lang = (payload.lang or "").strip()
    if not lang:
        raise HTTPException(status_code=422, detail="必须指定语种")
    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有字幕，无法应用译文")

    total = len(cues)
    accept = {int(i) for i in payload.accept} if payload.accept is not None else None
    entry = "in-app"
    partial = False
    first = last = 1
    if payload.proposal is not None:
        data = dict(payload.proposal)
        kind = data.get("kind")
        if kind != "translate":
            raise HTTPException(status_code=422, detail="这不是一份翻译提案")
        try:
            first, last = proposals.source_span(data, total)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        scoped = (first, last) != (1, total)
        check = proposals.validate_proposal(
            data,
            [c.text for c in cues[first - 1 : last]],
            span=(first, last) if scoped else None,
        )
        if not check.ok:
            raise HTTPException(
                status_code=check.status,
                detail="；".join(check.errors) or "提案无效",
            )
        scope_texts = [
            str(item.get("after") or "")
            for item in sorted(data["items"], key=lambda it: it["i"])
        ]
        entry = str(data.get("entry") or "in-app")
        partial = scoped
        updates = {
            first - 1 + offset: text
            for offset, text in enumerate(scope_texts)
            if accept is None or (first + offset) in accept
        }
        label = (
            f"局部应用 {lang} 译文（第 {first}–{last} 条，{len(updates)} 条）"
            if scoped
            else f"应用 {lang} 译文（{len(updates)} 条）"
        )
    else:
        texts = [str(t or "") for t in (payload.texts or [])]
        if len(texts) != total:
            raise HTTPException(
                status_code=422,
                detail=f"译文条数不符：{len(texts)} 条译文 / {len(cues)} 条字幕",
            )
        updates = {
            index: text
            for index, text in enumerate(texts)
            if accept is None or (index + 1) in accept
        }
        label = f"应用 {lang} 译文（{len(updates)} 条）"

    result, changed, kept = _commit_merged(
        session,
        lang,
        cues,
        updates,
        # 提案里的空 after = 本批没有这一条；直接给 texts 数组时每一格都是最终值。
        skip_empty=payload.proposal is not None,
        sync_unchanged_base=True,
        label=label,
        entry=entry,
    )
    result.update({"applied": len(updates), "changed": len(changed), "kept_empty": kept})
    if partial:
        result.update({"partial": True, "range": {"from": first, "to": last}})
    return result


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
    _require_aligned(session, lang, track)
    texts = [str(t or "") for t in payload.texts]
    if len(texts) != len(track.texts):
        raise HTTPException(
            status_code=422,
            detail=f"译文条数不符：{len(texts)} 条译文 / 轨道 {len(track.texts)} 条",
        )
    if texts == track.texts:
        return track_payload(session, lang)
    replaced = sum(1 for before, after in zip(track.texts, texts) if before != after)
    result, _changed, _kept = _commit_merged(
        session,
        lang,
        session.review_cues,
        {index: text for index, text in enumerate(texts)},
        # 整轨替换的每一格都是用户给的最终值：允许清空。
        skip_empty=False,
        # 只改文本，不借机把整条轨的「原文已改」标记抹掉：只有真正变过的条目才重设 base。
        sync_unchanged_base=False,
        label=f"替换 {lang} 译文（{replaced} 处）",
    )
    return result


@router.post("/api/translations/gap", status_code=201)
def apply_gap(
    payload: GapApplyRequest,
    session: Session = Depends(get_session),
) -> dict:
    """补译回填：**只写显式列出的下标**，其余条目一个字节不动。

    与「应用一版译文」的区别：

    - 不接收提案、不校验 digest，条号就是唯一的落位依据；
    - 每条的 ``before`` 必须是当前原文（复制之后原文被改过就 409，什么都不写）；
    - 一次 ``set_translation`` = 一步统一历史，⌘Z 一次退掉整批补译。

    这是 2026-11-25「待译专列」的落点：用户逐句核对完一章后，只剩几条待译；
    外部模型只翻这几条，回填时**不能**碰到其余已经核对过的译文。
    """
    lang = (payload.lang or "").strip()
    if not lang:
        raise HTTPException(status_code=422, detail="必须指定语种")
    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有字幕，无法补译")
    track = session.translations.get(lang)
    if track is None:
        raise HTTPException(status_code=404, detail=f"没有 {lang} 译文轨")
    _require_aligned(session, lang, track)
    total = len(cues)
    try:
        updates = ai_gap.validate_gap_items(payload.items, cues)
    except ai_gap.GapError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    result, changed, kept_empty = _commit_merged(
        session,
        lang,
        cues,
        updates,
        skip_empty=True,
        sync_unchanged_base=True,
        label=f"补译 {lang} 译文（{len(updates)} 条）",
    )
    result.update(
        {
            "gap": True,
            "applied": len(updates),
            "kept": total - len(updates),
            "changed": len(changed),
            "kept_empty": kept_empty,
        }
    )
    log.info(
        "补译回填 | lang=%s | 写入=%d | 保留=%d", lang, len(updates), total - len(updates)
    )
    return result


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
