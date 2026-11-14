"""结构建议路由（Phase 1）。

与润色提案完全分开：``{stem}.ai-structure.json`` 只给结构建议用，ops 下标
一律以**应用前当前字幕的 1-based 原序号**为准；应用只走一次
``Session.replace_review()``，⌘Z 一步整批退回。

外部模型只返回 ``{"ops":[...]}``；``version/kind/source.digest/revision``
由本地在粘贴入库时绑定，路由不接受模型自带的哈希。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import ai_structure as structure
from core.textio import write_text_atomic

from .deps import get_session
from .routes_cues import _media_stem, _snapshot
from .security import require_token
from .sessions import Session

router = APIRouter(tags=["structure"], dependencies=[Depends(require_token)])


class PasteStructureRequest(BaseModel):
    text: str = Field(min_length=1, description="外部模型返回的 {\"ops\": [...]} JSON")


class ApplyStructureRequest(BaseModel):
    accept: list[int] = Field(default_factory=list, description="选中的 op 下标（0 起）")
    revision: str = Field(default="", description="解析时返回的 revision，防止应用旧预览")


def _output_dir(request: Request) -> Path:
    return Path(request.app.state.config.output_dir)


def _path(request: Request, session: Session) -> Path:
    stem = _media_stem(request, session) or "subtitles"
    return structure.structure_path(_output_dir(request), stem)


def _translation_langs(session: Session) -> list[str]:
    """只把**有内容**的译文轨算进来；空轨不阻止结构应用。"""
    return [
        lang
        for lang, track in session.translations.items()
        if any(str(text or "").strip() for text in track.texts)
    ]


def _source(data: dict) -> dict:
    return dict(data.get("source") or {})


def _payload(data: dict, path: Path, session: Session) -> dict:
    try:
        preview = structure.preview(
            session.review_cues,
            list(data.get("ops") or []),
            translation_langs=_translation_langs(session),
        )
    except structure.StructureError as exc:
        raise HTTPException(status_code=422, detail=f"结构建议文件无效：{exc}") from exc
    return {
        "exists": True,
        "path": str(path),
        "revision": str(data.get("revision") or ""),
        "source": _source(data),
        "current_count": len(session.review_cues),
        "digest_match": True,
        **preview.to_dict(),
    }


def _empty_payload(path: Path, session: Session, warning: str) -> dict:
    preview = structure.preview(session.review_cues, [])
    warnings = [warning, *preview.warnings]
    return {
        "exists": False,
        "path": str(path),
        "revision": "",
        "source": {
            "path": "",
            "count": len(session.review_cues),
            "digest": structure.current_digest(session.review_cues),
        },
        "current_count": len(session.review_cues),
        "digest_match": True,
        "ops": [],
        "warnings": warnings,
        "summary": preview.summary,
    }


def _ensure_source(data: dict, session: Session) -> None:
    if not structure.source_matches(data, session.review_cues):
        raise HTTPException(
            status_code=409,
            detail="字幕已变化：这份结构建议是针对另一版字幕生成的，请重新粘贴结构建议。",
        )


@router.get("/api/ai/structure")
def get_structure(request: Request, session: Session = Depends(get_session)) -> dict:
    """读取当前媒体的结构建议（用于切页/重开后的恢复预览）。"""
    path = _path(request, session)
    data = structure.load_proposal(path)
    if data is None:
        raise HTTPException(
            status_code=409,
            detail="还没有结构建议：先在润色页粘贴外部模型返回的 {\"ops\": [...]}。",
        )
    _ensure_source(data, session)
    return _payload(data, path, session)


@router.post("/api/ai/structure/from-json")
def structure_from_json(
    payload: PasteStructureRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """解析外部模型返回的 ops JSON，绑定当前字幕并落盘。

    **模型只给 ops**：version/kind/source.digest/revision 全部本地补。
    """
    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有可对照的字幕")

    try:
        ops = structure.extract_ops(payload.text)
    except structure.StructureError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    path = _path(request, session)
    if not ops:
        # 模型明确说「不需要改」：清掉旧文件，返回空预览。
        try:
            path.unlink()
        except OSError:
            pass
        return _empty_payload(path, session, "模型没有给出结构修改（ops 为空）。")

    try:
        preview = structure.preview(
            cues, ops, translation_langs=_translation_langs(session)
        )
    except structure.StructureError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    data = structure.build_proposal(cues, ops, revision=uuid.uuid4().hex)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, structure.dump_proposal(data))
    return {
        "exists": True,
        "path": str(path),
        "revision": str(data.get("revision") or ""),
        "source": _source(data),
        "current_count": len(cues),
        "digest_match": True,
        **preview.to_dict(),
    }


@router.post("/api/ai/structure/apply")
def structure_apply(
    payload: ApplyStructureRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """应用选中的结构操作；一次历史，失败不动字幕。"""
    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有可应用的字幕")

    path = _path(request, session)
    data = structure.load_proposal(path)
    if data is None:
        raise HTTPException(status_code=409, detail="找不到结构建议，请先粘贴解析一份")
    if payload.revision and str(data.get("revision") or "") != payload.revision:
        raise HTTPException(status_code=409, detail="结构建议已更新，请重新解析后再应用")
    _ensure_source(data, session)

    ops = list(data.get("ops") or [])
    raw_ids: list[int] = []
    for value in payload.accept:
        try:
            raw_ids.append(int(value))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="选中的操作编号不合法") from exc
    if any(index < 0 or index >= len(ops) for index in raw_ids):
        raise HTTPException(status_code=422, detail="选中的操作编号越界")
    accept = sorted(set(raw_ids))
    if not accept:
        raise HTTPException(status_code=422, detail="没有选中任何结构操作")

    translation_langs = _translation_langs(session)
    if translation_langs and any(
        str(ops[index].get("op") or "") in ("merge", "insert", "delete") for index in accept
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"已有译文轨（{'、'.join(translation_langs)}）：合并/新增/删除会改变条数，"
                "请先处理译文后再试。"
            ),
        )

    try:
        new_cues, applied = structure.apply_selected(
            cues, ops, accept, translation_langs=translation_langs
        )
    except structure.StructureConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    changed = not _same_cues(cues, new_cues)
    if changed:
        session.replace_review(new_cues, label=f"应用结构建议（{applied} 项）")
    # 应用后剩余 ops 的旧下标已不可信：整份丢弃，下一轮重新粘贴。
    try:
        path.unlink()
    except OSError:
        pass
    return {
        **_snapshot(session),
        "changed": int(changed),
        "applied": applied if changed else 0,
        "output_count": len(new_cues),
    }


@router.delete("/api/ai/structure")
def delete_structure(request: Request, session: Session = Depends(get_session)) -> dict:
    path = _path(request, session)
    removed = False
    try:
        if path.exists():
            path.unlink()
            removed = True
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"删除结构建议失败：{exc}") from exc
    return {"removed": removed, "path": str(path)}


@router.get("/api/ai/structure/prompt")
def structure_prompt(
    request: Request,
    mode: str = "single",
    session: Session = Depends(get_session),
) -> dict:
    """复制「结构检查提示词」：A + 可选的 B 参考；不要求 AI 优化开关。"""
    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有字幕")
    mode = (mode or "single").strip().lower()
    if mode not in ("single", "dual"):
        raise HTTPException(status_code=422, detail=f"未知的润色模式：{mode}")
    alt_cues = None
    if mode == "dual":
        alt = session.alt_review
        if alt is None or not alt.cues:
            raise HTTPException(
                status_code=409,
                detail="还没有第二版字幕：先在转写页把另一引擎的稿放进双引擎复核",
            )
        alt_cues = alt.cues
    prompt = structure.build_prompt(cues, alt_cues)
    return {
        "prompt": prompt,
        "count": len(cues),
        "chars": len(prompt),
        "mode": mode,
        "alt_count": len(alt_cues) if alt_cues else 0,
    }


def _same_cues(left, right) -> bool:
    if len(left) != len(right):
        return False
    for a, b in zip(left, right):
        if a.text != b.text:
            return False
        if abs(a.start - b.start) > structure.EPS or abs(a.end - b.end) > structure.EPS:
            return False
    return True
