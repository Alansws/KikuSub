"""AI 提案路由：读取、保存、应用。

M1 只做「提案 → 双栏 diff → 应用」这一层，**不调用任何模型**（开发文档 §4）。
生成提案由 M2 的 ``/api/ai/jobs`` 或 M4 的外部 agent 负责，两者写出的都是同一份
``proposal.json``。

两条语义必须保持：

- **应用是整批一次历史**：27 处改动也只让 ⌘Z 退一次（文档 D-5）。实现上就是
  调一次 ``Session.replace_review()``，它内部只压一次栈；**禁止**逐条改。
- **失败不动字幕**：校验不通过时返回 409/422，``session.review_cues`` 一个字节都不改。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core import ai_client
from core import ai_polish
from core import ai_proposal as proposals
from core import ai_translate
from core import prompts as prompt_store
from core import settings as settings_store
from core.subtitles import cues_to_srt
from core.textio import write_text_atomic

from .deps import get_session
from .jobs import JobConflict
from .routes_cues import _media_stem, _snapshot
from .security import require_token
from .sessions import Session

router = APIRouter(tags=["ai"], dependencies=[Depends(require_token)])


class SaveProposalRequest(BaseModel):
    kind: str = "polish"
    lang: str = ""
    proposal: dict = Field(default_factory=dict)


class AiConfigPatch(BaseModel):
    enabled: bool | None = None
    base_url: str | None = None
    model: str | None = None
    chunk_cues: int | None = None
    translate_chunk_cues: int | None = None
    context_cues: int | None = None


class AiTestRequest(BaseModel):
    base_url: str = ""
    model: str = ""


class AiJobRequest(BaseModel):
    # polish = 润色原语种；translate = 翻译（必须给 dst_lang）
    kind: str = "polish"
    base_url: str = ""
    model: str = ""
    chunk_cues: int | None = None
    context_cues: int | None = None
    lang: str = "ja"
    dst_lang: str = ""


class PasteSrtRequest(BaseModel):
    kind: str = "translate"
    lang: str = "zh-Hans"
    text: str = Field(min_length=1, description="从别处粘贴回来的完整 SRT")


class ImportRequest(BaseModel):
    path: str = Field(min_length=1, description="提案文件绝对路径")
    kind: str = "polish"
    lang: str = ""


class ApplyRequest(BaseModel):
    kind: str = "polish"
    lang: str = ""
    # None = 全采纳；[] = 全拒绝（不压历史、不改字幕）
    accept: list[int] | None = None
    edits: dict[int, str] = Field(default_factory=dict)
    # 内联提案优先；缺省则从磁盘读
    proposal: dict | None = None


def _normalize(kind: str, lang: str) -> tuple[str, str]:
    kind = (kind or "polish").strip().lower()
    if kind not in proposals.KINDS:
        raise HTTPException(status_code=422, detail=f"未知的提案类型：{kind}")
    lang = (lang or "").strip()
    if kind == "translate" and not lang:
        raise HTTPException(status_code=422, detail="翻译提案必须指定目标语种")
    return kind, lang


def _output_dir(request: Request) -> Path:
    return Path(request.app.state.config.output_dir)


def _settings_path(request: Request) -> Path:
    return Path(getattr(request.app.state, "settings_path", settings_store.SETTINGS_PATH))


def _ai_settings(request: Request) -> dict:
    return settings_store.load_settings(_settings_path(request))


def _config_payload(settings: dict) -> dict:
    return {
        "enabled": bool(settings.get("ai_enabled")),
        "base_url": str(settings.get("ai_base_url") or ""),
        "model": str(settings.get("ai_model") or ""),
        "chunk_cues": int(settings.get("ai_max_chunk_cues") or 0),
        "translate_chunk_cues": int(settings.get("ai_translate_chunk_cues") or 0),
        "context_cues": int(settings.get("ai_context_cues") or 0),
        # 密钥不归服务层管：渲染进程从 safeStorage 解密后按请求头带上（§5.2.1）
        "key_held_by": "renderer",
    }


def _current_texts(session: Session) -> list[str]:
    return [cue.text for cue in session.review_cues]


def _path_for(request: Request, session: Session, kind: str, lang: str) -> Path:
    stem = _media_stem(request, session) or "subtitles"
    return proposals.proposal_path(_output_dir(request), stem, kind, lang)


def _rejected(check: proposals.ProposalCheck) -> JSONResponse:
    """校验失败：`detail` 给一句人话，`errors` 保留结构化清单（前端可逐条指出）。"""
    return JSONResponse(
        status_code=check.status,
        content={
            "detail": "；".join(check.errors) or "提案无效",
            "errors": check.errors,
            "warnings": check.warnings,
            "digest_match": check.digest_match,
        },
    )


@router.get("/api/ai/config")
def get_config(request: Request) -> dict:
    return _config_payload(_ai_settings(request))


@router.patch("/api/ai/config")
def patch_config(payload: AiConfigPatch, request: Request) -> dict:
    patch: dict = {}
    if payload.enabled is not None:
        patch["ai_enabled"] = payload.enabled
    if payload.base_url is not None:
        url = payload.base_url.strip()
        if url:
            if not url.startswith(("http://", "https://")):
                raise HTTPException(status_code=422, detail="Base URL 必须以 http:// 或 https:// 开头")
            patch["ai_base_url"] = url.rstrip("/")
    if payload.model is not None:
        model = payload.model.strip()
        if model:
            patch["ai_model"] = model
    if payload.chunk_cues is not None:
        patch["ai_max_chunk_cues"] = payload.chunk_cues
    if payload.translate_chunk_cues is not None:
        patch["ai_translate_chunk_cues"] = payload.translate_chunk_cues
    if payload.context_cues is not None:
        patch["ai_context_cues"] = payload.context_cues
    if not patch:
        raise HTTPException(status_code=422, detail="没有需要更新的字段")

    try:
        settings = settings_store.save_settings(patch, _settings_path(request))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"设置写入失败：{exc}") from exc
    return _config_payload(settings)


@router.post("/api/ai/test")
def test_ai(payload: AiTestRequest, request: Request) -> dict:
    """设置页「测试连接」：一次最小往返，不打印任何请求头。"""
    settings = _ai_settings(request)
    key = (request.headers.get("x-ai-key") or "").strip()
    config = ai_client.AiConfig(
        base_url=payload.base_url or str(settings.get("ai_base_url") or ""),
        model=payload.model or str(settings.get("ai_model") or ""),
        api_key=key,
        timeout_s=30.0,
    )
    try:
        return ai_client.test_connection(config)
    except ai_client.AiError as exc:
        # 424：调用方给的东西没问题，是上游不可用（附录 B）
        raise HTTPException(status_code=424, detail=exc.message) from exc


@router.post("/api/ai/jobs", status_code=201)
async def create_ai_job(
    payload: AiJobRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """启动一次润色任务（可能几分钟）。进度走 `/ws/jobs/{id}`，与转写共用一条链路。"""
    settings = _ai_settings(request)
    if not settings.get("ai_enabled"):
        raise HTTPException(status_code=503, detail="AI 优化未启用：设置 → 实验功能里打开它")

    key = (request.headers.get("x-ai-key") or "").strip()
    if not key:
        raise HTTPException(status_code=401, detail="还没有配置 API Key")

    texts = _current_texts(session)
    if not texts:
        raise HTTPException(status_code=409, detail="当前没有可润色的字幕")

    config = ai_client.AiConfig(
        base_url=payload.base_url or str(settings.get("ai_base_url") or ""),
        model=payload.model or str(settings.get("ai_model") or ""),
        api_key=key,
        timeout_s=180.0,
    )
    try:
        config.ensure_ready()
    except ai_client.AiError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc

    kind = (payload.kind or "polish").strip().lower()
    if kind not in ("polish", "translate"):
        raise HTTPException(status_code=422, detail=f"未知的任务类型：{payload.kind}")
    dst_lang = (payload.dst_lang or "").strip()
    if kind == "translate" and not dst_lang:
        raise HTTPException(status_code=422, detail="翻译任务必须指定目标语种")

    stem = _media_stem(request, session) or "subtitles"
    out_path = proposals.proposal_path(_output_dir(request), stem, kind, dst_lang)
    default_chunk = int(
        settings.get("ai_translate_chunk_cues" if kind == "translate" else "ai_max_chunk_cues") or 0
    )

    try:
        if kind == "translate":
            job = request.app.state.jobs.start_ai_translate(
                session=session,
                config=config,
                dst_lang=dst_lang,
                chunk_cues=int(payload.chunk_cues or default_chunk or 120),
                context_cues=int(
                    payload.context_cues
                    if payload.context_cues is not None
                    else settings.get("ai_context_cues") or 0
                ),
                source_path="",
                out_path=out_path,
                session_id=session.id,
                loop=asyncio.get_running_loop(),
            )
            return job.snapshot()
        job = request.app.state.jobs.start_ai_polish(
            session=session,
            config=config,
            chunk_cues=int(payload.chunk_cues or default_chunk or 200),
            context_cues=int(
                payload.context_cues
                if payload.context_cues is not None
                else settings.get("ai_context_cues") or 0
            ),
            lang=(payload.lang or "ja").strip(),
            source_path="",
            out_path=out_path,
            session_id=session.id,
            loop=asyncio.get_running_loop(),
        )
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.snapshot()


@router.get("/api/ai/prompt")
def get_manual_prompt(
    request: Request,
    kind: str = "translate",
    lang: str = "zh-Hans",
    template_id: str = "",
    session: Session = Depends(get_session),
) -> dict:
    """「一键复制提示词」：把当前字幕整成 SRT 塞进所选模板，供用户粘到任意聊天窗。

    模板来自 ``prompts.json``（设置页可编辑、AI 优化台可切换）；没有选择时用
    当前选中的模板。润色走内置提示词，不需要 API Key，也不要求 AI 优化开关。
    """
    kind, lang = _normalize(kind, lang)
    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有字幕")
    srt = cues_to_srt(cues)
    if kind == "polish":
        # 润色也支持「复制提示词 → 网页版模型 → 粘回来」；不绑定 AI 优化。
        prompt = ai_polish.build_manual_prompt(srt)
        return {
            "prompt": prompt,
            "count": len(cues),
            "lang": "",
            "chars": len(prompt),
            "template_id": "builtin-polish",
            "template_name": "内置润色提示词",
        }
    settings_path = _settings_path(request)
    prompt, template = prompt_store.render_prompt(
        srt,
        ai_translate.lang_name(lang),
        template_id=template_id or None,
        settings_path=settings_path,
    )
    if template is None:
        raise HTTPException(status_code=500, detail="提示词库为空")
    return {
        "prompt": prompt,
        "count": len(cues),
        "lang": lang,
        "chars": len(prompt),
        "template_id": template["id"],
        "template_name": template["name"],
    }


@router.post("/api/ai/from-srt")
def proposal_from_pasted_srt(
    payload: PasteSrtRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """把粘贴回来的 SRT 解析成提案（**不落盘、不改字幕**），交给前端走同一套 diff。

    时间戳一律丢弃并使用原文的——这样"模型改了时间轴"也不会污染交付文件。
    """
    kind, lang = _normalize(payload.kind, payload.lang)
    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有字幕")
    try:
        if kind == "polish":
            proposal, warnings = ai_polish.proposal_from_srt(payload.text, cues)
        else:
            proposal, warnings = ai_translate.proposal_from_srt(payload.text, cues, lang)
    except ai_client.AiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"proposal": proposal, "warnings": warnings, "count": len(proposal["items"])}


@router.get("/api/ai/proposal")
def get_proposal(
    request: Request,
    kind: str = "polish",
    lang: str = "",
    session: Session = Depends(get_session),
) -> dict:
    """读当前媒体的提案，并顺带做一次校验（只读，绝不改字幕）。"""
    kind, lang = _normalize(kind, lang)
    path = _path_for(request, session, kind, lang)
    data = proposals.load_proposal(path)
    if data is None:
        raise HTTPException(
            status_code=409,
            detail=f"还没有提案文件：{path.name}。先让 AI 生成，或从外部导入一份。",
        )
    texts = _current_texts(session)
    check = proposals.validate_proposal(data, texts)
    return {
        "path": str(path),
        "proposal": data,
        "ok": check.ok,
        "errors": check.errors,
        "warnings": check.warnings,
        "digest_match": check.digest_match,
        "source_count": int((data.get("source") or {}).get("count") or 0),
        "current_count": len(texts),
    }


@router.post("/api/ai/proposal", status_code=201)
def save_proposal(
    payload: SaveProposalRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """保存/覆盖提案（前端「另存」与外部 agent 的兜底通道）。

    写盘前必须校验：宁可拒绝，也不要落一份应用不了的提案。
    """
    kind, lang = _normalize(payload.kind, payload.lang)
    texts = _current_texts(session)
    if not texts:
        raise HTTPException(status_code=409, detail="当前没有可对照的字幕，无法保存提案")

    data = dict(payload.proposal or {})
    # 前端另存时可能只带 items：把身份字段按本次请求补齐，避免写坏契约
    data["version"] = proposals.PROPOSAL_VERSION
    data["kind"] = kind
    if kind == "translate":
        data["dst_lang"] = data.get("dst_lang") or lang

    check = proposals.validate_proposal(data, texts)
    if not check.ok:
        return _rejected(check)

    path = _path_for(request, session, kind, lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, proposals.dump_proposal(data))
    return {"path": str(path), "count": len(data.get("items") or []), "warnings": check.warnings}


@router.delete("/api/ai/proposal")
def delete_proposal(
    request: Request,
    kind: str = "polish",
    lang: str = "",
    session: Session = Depends(get_session),
) -> dict:
    """删除磁盘上的提案文件。AI 优化台的「丢弃」走这里——只清界面不算丢弃。"""
    kind, lang = _normalize(kind, lang)
    path = _path_for(request, session, kind, lang)
    removed = False
    try:
        if path.exists():
            path.unlink()
            removed = True
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"删除提案失败：{exc}") from exc
    return {"removed": removed, "path": str(path)}


@router.post("/api/ai/proposal/import", status_code=201)
def import_proposal(
    payload: ImportRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """从任意路径导入一份提案，校验通过后落到当前媒体的标准位置。

    外部 agent 可以把提案写到任何地方，用户用原生对话框挑进来即可——
    这比要求 agent 猜 output_dir 更可靠。
    """
    kind, lang = _normalize(payload.kind, payload.lang)
    texts = _current_texts(session)
    if not texts:
        raise HTTPException(status_code=409, detail="当前没有可对照的字幕，无法导入提案")

    src = Path(payload.path)
    data = proposals.load_proposal(src)
    if data is None:
        raise HTTPException(status_code=422, detail=f"不是合法的提案 JSON：{src.name}")

    data = dict(data)
    data["version"] = proposals.PROPOSAL_VERSION
    data["kind"] = kind
    if kind == "translate":
        data["dst_lang"] = data.get("dst_lang") or lang

    check = proposals.validate_proposal(data, texts)
    if not check.ok:
        return _rejected(check)

    dest = _path_for(request, session, kind, lang)
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(dest, proposals.dump_proposal(data))
    return {
        "path": str(dest),
        "from": str(src),
        "count": len(data.get("items") or []),
        "warnings": check.warnings,
    }


@router.post("/api/ai/apply")
def apply_proposal(
    payload: ApplyRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """把提案（或其中被采纳的部分）写进核对台。**时间码不变，历史只压一次。**"""
    kind, lang = _normalize(payload.kind, payload.lang)
    if kind != "polish":
        # 译文走平行轨，不能覆盖 review_cues（文档 D-3 / §6.2.2），M3 再开
        raise HTTPException(status_code=422, detail="翻译提案请走 /api/translations 应用")

    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有可应用的字幕")

    data = payload.proposal
    if data is None:
        data = proposals.load_proposal(_path_for(request, session, kind, lang))
        if data is None:
            raise HTTPException(status_code=409, detail="找不到提案文件，请先生成或导入一份")

    check = proposals.validate_proposal(data, _current_texts(session))
    if not check.ok:
        return _rejected(check)

    accept = None if payload.accept is None else {int(i) for i in payload.accept}
    new_cues, changed = proposals.apply_polish(
        cues,
        list(data.get("items") or []),
        accept=accept,
        edits={int(k): v for k, v in (payload.edits or {}).items()},
    )

    # 空应用 / 无实际改动：不压历史，让 can_undo 保持原样（文档 §4.2.2 第 5 步）
    if changed:
        session.replace_review(new_cues, label=f"应用 AI 提案（{changed} 处）")

    return {**_snapshot(session), "changed": changed, "warnings": check.warnings}
