"""断句重排路由：整份换稿。

三条接口：

- ``GET  /api/ai/reshape/prompt``    取「整份重写」提示词（可只取某一段）；
- ``POST /api/ai/reshape/from-text`` 把粘回来的 SRT 解析成一份新稿 + 体检；
- ``POST /api/ai/reshape/apply``     按**原稿索引区间**整段覆盖核对台。

与润色提案的区别：这里不改 ``proposal.json``，也不走 ``apply_polish()``——
条数和时间码都会变，唯一合法的落点是 ``Session.replace_range()``（一次 ⌘Z 整批退回）。
「只改几处」的 ops JSON 仍走 ``/api/ai/structure/*``，两条路共用一个页面、互不混用。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import ai_polish
from core import prompts as prompt_store
from core import reshape
from core.subtitles import SubtitleCue

from .deps import get_session, settings_path
from .routes_cues import _snapshot
from .security import require_token
from .sessions import Session

router = APIRouter(tags=["reshape"], dependencies=[Depends(require_token)])


class PasteReshapeRequest(BaseModel):
    text: str = Field(min_length=1, description="模型返回的整份 SRT（必须带时间码）")
    from_index: int = 1
    to_index: int | None = None


class ReshapeCue(BaseModel):
    start: float
    end: float
    text: str = ""


class ApplyReshapeRequest(BaseModel):
    cues: list[ReshapeCue] = Field(default_factory=list)
    from_index: int = 1
    to_index: int | None = None
    #: 解析时服务端给的源指纹；原稿在这之后被改过就必须拒绝，否则下标已经错位。
    digest: str = ""
    label: str = ""


def _mode(raw: str) -> str:
    mode = (raw or "single").strip().lower()
    if mode not in ("single", "dual"):
        raise HTTPException(status_code=422, detail=f"未知的源：{raw}")
    return mode


def _span(session: Session, from_index: int, to_index: int | None) -> tuple[int, int]:
    total = len(session.review_cues)
    start = max(1, int(from_index or 1))
    end = total if to_index is None else min(total, int(to_index))
    if start > end:
        raise HTTPException(status_code=422, detail=f"片段范围不合法：第 {start}–{end} 条")
    return start, end


def _alt_block(session: Session, cues: list, start: int, end: int, full: bool) -> tuple[str, int]:
    """B 参考稿的 SRT 片段 + 实际纳入了几条（界面上要显示这一段的参考条数，
    不是整片条数——分段复制时写「参考 764 条」会让人以为整份 B 都塞进去了）。"""
    alt = session.alt_review
    if alt is None or not alt.cues:
        return "", 0
    if full:
        return ai_polish.srt_block(alt.cues), len(alt.cues)
    t0 = cues[start - 1].start
    t1 = cues[end - 1].end
    indices = ai_polish.dual_context_cues(alt.cues, t0, t1)
    return ai_polish.srt_block(alt.cues, indices), len(indices)


@router.get("/api/ai/reshape/prompt")
def get_reshape_prompt(
    request: Request,
    mode: str = "single",
    from_index: int = 1,
    to_index: int | None = None,
    template_id: str = "",
    session: Session = Depends(get_session),
) -> dict:
    """整份重写提示词：不要求 1:1，条数与时间码都可以变，所以只给 A（+B 参考）。"""
    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有字幕")
    mode = _mode(mode)
    if mode == "dual" and (session.alt_review is None or not session.alt_review.cues):
        raise HTTPException(
            status_code=409,
            detail="当前没有第二版字幕：先在转写页把另一引擎的稿放进双引擎复核，或到双引擎复核页导入一份已有字幕",
        )
    total = len(cues)
    start, end = _span(session, from_index, to_index)
    full = (start, end) == (1, total)
    indices = list(range(start - 1, end))
    srt_a = ai_polish.srt_block(cues, indices)
    srt_b, alt_count = _alt_block(session, cues, start, end, full) if mode == "dual" else ("", 0)
    range_text = (
        f"这次只处理第 {start}–{end} 条（全片共 {total} 条）。"
        "输出里只保留这些条目的内容，不要带上其它段。"
        if not full
        else f"全片共 {total} 条，一次处理完整份。"
    )
    category = (
        prompt_store.CATEGORY_RESHAPE_DUAL
        if mode == "dual"
        else prompt_store.CATEGORY_RESHAPE_SINGLE
    )
    prompt, template = prompt_store.render_prompt(
        srt_a,
        "",
        template_id=template_id or None,
        category=category,
        srt_a=srt_a,
        srt_b=srt_b,
        range_text=range_text,
        settings_path=settings_path(request),
    )
    if template is None:
        # 提示词库异常时退回出厂文案，绝不返回空提示词。
        content = (
            prompt_store.RESHAPE_DUAL_CONTENT
            if mode == "dual"
            else prompt_store.RESHAPE_SINGLE_CONTENT
        )
        prompt = prompt_store.render_template(
            content, srt_a, "", srt_a=srt_a, srt_b=srt_b, range_text=range_text
        )
        template = {"id": "builtin-reshape", "name": "内置断句重排提示词", "category": category}
    return {
        "prompt": prompt,
        "count": end - start + 1,
        "total": total,
        "chars": len(prompt),
        "mode": mode,
        "from": start,
        "to": end,
        "alt_count": alt_count,
        "template_id": template["id"],
        "template_name": template["name"],
        "category": category,
    }


@router.post("/api/ai/reshape/from-text")
def reshape_from_text(
    payload: PasteReshapeRequest,
    session: Session = Depends(get_session),
) -> dict:
    """解析整份 SRT + 体检。纯文本一律拒绝（不做「按原稿重算时间轴」）。"""
    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有字幕")
    total = len(cues)
    start, end = _span(session, payload.from_index, payload.to_index)
    full = (start, end) == (1, total)
    try:
        block = reshape.parse_draft(payload.text)
    except reshape.ReshapeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        reshape.validate_block(block)
    except reshape.ReshapeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    before_texts = [cue.text for cue in cues[start - 1 : end]]
    diag = reshape.diagnose(
        block,
        before_texts=before_texts,
        range_start=None if full else cues[start - 1].start,
        range_end=None if full else cues[end - 1].end,
    )
    return {
        "format": "srt",
        "cues": [{"start": cue.start, "end": cue.end, "text": cue.text} for cue in block],
        "diagnostics": diag.to_dict(),
        "notes": reshape.summary_notes(
            diag, range_label="" if full else f"只覆盖第 {start}–{end} 条"
        ),
        "digest": reshape.digest_of(cues),
        "range": {
            "from": start,
            "to": end,
            "start": cues[start - 1].start,
            "end": cues[end - 1].end,
            "full": full,
        },
    }


@router.post("/api/ai/reshape/apply")
def reshape_apply(
    payload: ApplyReshapeRequest,
    session: Session = Depends(get_session),
) -> dict:
    """整段覆盖：锚点是原稿索引区间，不是模型的时间边界。"""
    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有字幕")
    if payload.digest and payload.digest != reshape.digest_of(cues):
        raise HTTPException(
            status_code=409,
            detail="原稿在解析之后被改过：这份新稿的条号区间已经不可信，请重新粘贴一次",
        )
    block = [SubtitleCue(float(cue.start), float(cue.end), str(cue.text or "")) for cue in payload.cues]
    try:
        reshape.validate_block(block)
    except reshape.ReshapeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    total = len(cues)
    start, end = _span(session, payload.from_index, payload.to_index)
    label = payload.label.strip() or f"断句重排：覆盖第 {start}–{end} 条（{len(block)} 条）"
    if (start, end) == (1, total) and len(block) >= total * 0.8:
        label = f"断句重排：整份覆盖（{len(block)} 条）"
    try:
        result = session.replace_range(start, end, block, label)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**_snapshot(session), "replace": result}
