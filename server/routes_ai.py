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
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core import ai_arbitrate
from core import ai_client
from core import ai_gap
from core import ai_local_model
from core import ai_polish
from core import ai_proposal as proposals
from core import ai_translate
from core import ai_translate_cue
from core import prompts as prompt_store
from core import settings as settings_store
from core.subtitles import cues_to_srt
from core.textio import write_text_atomic

from .deps import get_session, settings_path
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
    # 单句判定模型覆盖：空字符串 = 清除覆盖、跟随全局。
    arbitrate_base_url: str | None = None
    arbitrate_model: str | None = None
    local_context: int | None = None
    auto_arbitrate: bool | None = None


class AiTestRequest(BaseModel):
    base_url: str = ""
    model: str = ""


class LocalModelLoadRequest(BaseModel):
    context: int = ai_local_model.DEFAULT_CONTEXT


class ArbitrateHistoryItem(BaseModel):
    role: str = ""
    text: str = ""


class ArbitrateRequest(BaseModel):
    text_a: str = ""
    text_b: str = ""
    before: list[str] = Field(default_factory=list)
    after: list[str] = Field(default_factory=list)
    lang: str = "ja"
    # 用户的听音线索（空耳 / 罗马音 / 描述）；不是时间轴，也不是音频。
    hint: str = Field(default="", max_length=ai_arbitrate.MAX_HINT_CHARS)
    # 多轮追问记录；角色只认 user / assistant，具体轮数与字符预算由 core 裁剪。
    history: list[ArbitrateHistoryItem] = Field(default_factory=list)


class TranslateCueRequest(BaseModel):
    """单句补译：索引 + 目标语种；材料（原文 / 上下文 / 已有译文）由服务端取。"""

    index: int = Field(ge=0)
    lang: str = ""


class AiJobRequest(BaseModel):
    # polish = 润色原语种；translate = 翻译（必须给 dst_lang）
    kind: str = "polish"
    base_url: str = ""
    model: str = ""
    chunk_cues: int | None = None
    context_cues: int | None = None
    lang: str = "ja"
    dst_lang: str = ""
    # polish 专用：single = 只吃 A；dual = 同时参考第二版 B（要求会话里有 alt_review）
    mode: str = "single"
    # 处理范围（1 基、含两端）：只给这一段的字幕生成提案，其余条目不动。
    from_index: int = 1
    to_index: int | None = None


class PasteSrtRequest(BaseModel):
    kind: str = "translate"
    lang: str = "zh-Hans"
    text: str = Field(min_length=1, description="从别处粘贴回来的完整 SRT")
    # 长片分段粘贴：本段覆盖第 from_index..to_index 条（1 基、含两端）；缺省整片。
    from_index: int = 1
    to_index: int | None = None
    mode: str = "single"
    # 处理范围：提案只覆盖这一段（source.range），items 的 i 仍是全片序号。
    range_from: int | None = None
    range_to: int | None = None
    # 翻译：默认允许带时间轴的译文条数与原文不同（按时间轴区间交集对齐）；
    # 打开后保持旧的「等条数强校验」行为。润色恒为严格模式，不受此开关影响。
    strict_count: bool = True


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



def _ai_settings(request: Request) -> dict:
    return settings_store.load_settings(settings_path(request))


def _arbitrate_target(settings: dict) -> tuple[str, str, bool]:
    """单句判定实际使用的 base_url / model；任一覆盖字段非空即视为覆盖。"""
    override = bool(
        str(settings.get("ai_arbitrate_base_url") or "").strip()
        or str(settings.get("ai_arbitrate_model") or "").strip()
    )
    base_url = str(
        settings.get("ai_arbitrate_base_url") or settings.get("ai_base_url") or ""
    )
    model = str(settings.get("ai_arbitrate_model") or settings.get("ai_model") or "")
    return base_url, model, override


def _config_payload(settings: dict) -> dict:
    base_url = str(settings.get("ai_base_url") or "")
    arbitrate_url = str(settings.get("ai_arbitrate_base_url") or "")
    arbitrate_model = str(settings.get("ai_arbitrate_model") or "")
    resolved_arbitrate_url = arbitrate_url or base_url
    return {
        "enabled": bool(settings.get("ai_enabled")),
        "base_url": base_url,
        "model": str(settings.get("ai_model") or ""),
        "chunk_cues": int(settings.get("ai_max_chunk_cues") or 0),
        "translate_chunk_cues": int(settings.get("ai_translate_chunk_cues") or 0),
        "context_cues": int(settings.get("ai_context_cues") or 0),
        "arbitrate_base_url": arbitrate_url,
        "arbitrate_model": arbitrate_model,
        "local_context": int(settings.get("ai_local_context") or ai_local_model.DEFAULT_CONTEXT),
        "auto_arbitrate": bool(settings.get("ai_auto_arbitrate")),
        # 本地 OpenAI 兼容服务可以不填 Key；路由据此放行。
        "key_optional": ai_client.is_local_url(base_url),
        "arbitrate_key_optional": ai_client.is_local_url(resolved_arbitrate_url),
        # 只有本机 LM Studio 才显示「本地上下文档位 / 加载重载」。
        "arbitrate_loopback": ai_local_model.is_loopback(resolved_arbitrate_url),
        # 密钥不归服务层管：渲染进程从 safeStorage 解密后按请求头带上（§5.2.1）
        "key_held_by": "renderer",
    }


def _current_texts(session: Session) -> list[str]:
    return [cue.text for cue in session.review_cues]


def _scope_span(total: int, range_from: int | None, range_to: int | None) -> tuple[int, int]:
    """「处理范围」→ 全片 1 基闭区间；两端都缺省 = 整片。非法范围 422。"""
    if total <= 0:
        raise HTTPException(status_code=409, detail="当前没有字幕")
    if range_from is None and range_to is None:
        return (1, total)
    try:
        first = int(range_from if range_from is not None else 1)
        last = int(range_to if range_to is not None else total)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="处理范围不合法") from exc
    first = max(1, first)
    last = min(total, last)
    if first > last:
        raise HTTPException(
            status_code=422, detail=f"处理范围不合法：第 {first}–{last} 条（共 {total} 条）"
        )
    return (first, last)


def _range_text(first: int, last: int, start: int, end: int, total: int) -> str:
    """提示词里的范围说明（润色 / 翻译共用同一口径）。"""
    if (first, last) == (1, total):
        if (start, end) == (1, total):
            return f"全片共 {total} 条。"
        return f"本段第 {start}–{end} 条（全片共 {total} 条）；只输出这些条目。"
    if (start, end) == (first, last):
        return f"本次只处理片段第 {first}–{last} 条（全片共 {total} 条）；只输出这些条目。"
    return (
        f"本次只处理片段第 {first}–{last} 条（全片共 {total} 条）；"
        f"当前分段是其中第 {start}–{end} 条，只输出这些条目。"
    )


def _proposal_span(request_data: dict, total: int) -> tuple[int, int]:
    """提案声明的作用范围（旧提案 = 整片）；越界 → 422。"""
    try:
        return proposals.source_span(request_data, total)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _validate_scoped(
    data: dict, texts: list[str], alt_texts: list[str] | None
) -> tuple[proposals.ProposalCheck, tuple[int, int]]:
    """按提案自己的 ``source.range`` 取出这一段再做校验。

    digest 只绑这一段（模型看到多少就绑定多少），``items`` 的 ``i`` 仍是全片序号，
    所以校验时必须把「全片序号 → 段内文本」一起交给 ``validate_proposal``。
    """
    total = len(texts)
    first, last = _proposal_span(data, total)
    scoped = (first, last) != (1, total)
    check = proposals.validate_proposal(
        data,
        texts[first - 1 : last],
        alt_texts,
        span=(first, last) if scoped else None,
    )
    return check, (first, last)


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
    if payload.arbitrate_base_url is not None:
        url = payload.arbitrate_base_url.strip()
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="判定模型 Base URL 必须以 http:// 或 https:// 开头")
        patch["ai_arbitrate_base_url"] = url.rstrip("/")
    if payload.arbitrate_model is not None:
        patch["ai_arbitrate_model"] = payload.arbitrate_model.strip()
    if payload.local_context is not None:
        if payload.local_context not in ai_local_model.CONTEXT_CHOICES:
            raise HTTPException(
                status_code=422,
                detail=f"本地上下文档位只能是 {', '.join(map(str, ai_local_model.CONTEXT_CHOICES))}",
            )
        patch["ai_local_context"] = payload.local_context
    if payload.auto_arbitrate is not None:
        patch["ai_auto_arbitrate"] = payload.auto_arbitrate
    if not patch:
        raise HTTPException(status_code=422, detail="没有需要更新的字段")

    try:
        settings = settings_store.save_settings(patch, settings_path(request))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"设置写入失败：{exc}") from exc
    return _config_payload(settings)


@router.post("/api/ai/test")
def test_ai(payload: AiTestRequest, request: Request) -> dict:
    """设置页「测试连接」：一次最小往返，不打印任何请求头。"""
    settings = _ai_settings(request)
    key = (request.headers.get("x-ai-key") or "").strip()
    base_url = payload.base_url or str(settings.get("ai_base_url") or "")
    config = ai_client.AiConfig(
        base_url=base_url,
        model=payload.model or str(settings.get("ai_model") or ""),
        api_key=key,
        timeout_s=30.0,
        allow_no_key=ai_client.is_local_url(base_url),
    )
    try:
        return ai_client.test_connection(config)
    except ai_client.AiError as exc:
        # 424：调用方给的东西没问题，是上游不可用（附录 B）
        raise HTTPException(status_code=424, detail=exc.message) from exc


@router.get("/api/ai/local-model/status")
def local_model_status(request: Request) -> dict:
    """只读探测本机 LM Studio 的模型与 context；远程地址返回 not_local。"""
    settings = _ai_settings(request)
    base_url, model, _ = _arbitrate_target(settings)
    return ai_local_model.status(base_url, model)


@router.post("/api/ai/local-model/load")
def local_model_load(payload: LocalModelLoadRequest, request: Request) -> dict:
    """按档位卸载并重载本机 LM Studio 模型；不参与单句判定请求。"""
    if payload.context not in ai_local_model.CONTEXT_CHOICES:
        raise HTTPException(
            status_code=422,
            detail=f"本地上下文档位只能是 {', '.join(map(str, ai_local_model.CONTEXT_CHOICES))}",
        )
    settings = _ai_settings(request)
    base_url, model, _ = _arbitrate_target(settings)
    try:
        return ai_local_model.load(base_url, model, payload.context)
    except ai_local_model.LocalModelError as exc:
        raise HTTPException(status_code=422, detail=exc.args[0]) from exc


@router.post("/api/ai/arbitrate")
def arbitrate_cue(payload: ArbitrateRequest, request: Request) -> dict:
    """单句 AI 判定：只回文本，不落盘、不改字幕、不进历史。"""
    settings = _ai_settings(request)
    if not settings.get("ai_enabled"):
        raise HTTPException(status_code=503, detail="AI 优化未启用：设置 → 实验功能里打开它")

    text_a = (payload.text_a or "").strip()
    text_b = (payload.text_b or "").strip()
    hint = (payload.hint or "").strip()
    has_history = any((item.text or "").strip() for item in payload.history)
    has_context = any((item or "").strip() for item in [*payload.before, *payload.after])
    # 不再要求 A/B 双版且不一致：音量太小、B 引擎返回空、只有手动新建的空字幕块
    # 时，只要还有听音线索 / 追问 / 上下文，就允许请求 AI 还原。
    if not (text_a or text_b or hint or has_history or has_context):
        raise HTTPException(
            status_code=422,
            detail="没有可判定的文本、上下文或听音线索",
        )

    base_url, model, override = _arbitrate_target(settings)
    key = (
        request.headers.get("x-ai-arbitrate-key" if override else "x-ai-key") or ""
    ).strip()
    # 覆盖地址指回全局网络时，允许判定 Key 留空并复用全局 Key；本地模型则
    # 由 allow_no_key 放行，**不**把全局 Key 发给本机服务。
    if override and not key and not ai_client.is_local_url(base_url):
        key = (request.headers.get("x-ai-key") or "").strip()
    config = ai_client.AiConfig(
        base_url=base_url,
        model=model,
        api_key=key,
        timeout_s=120.0,
        allow_no_key=ai_client.is_local_url(base_url),
    )
    if not key and not config.allow_no_key:
        raise HTTPException(
            status_code=401,
            detail="单句判定模型还没有配置 API Key" if override else "还没有配置 API Key",
        )
    try:
        config.ensure_ready()
    except ai_client.AiError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc

    # Qwen3 系推理模型默认把答案写进 reasoning_content、content 为空；/no_think
    # 是它认识的软开关。只对 model 名带 qwen/think 的模型追加，避免影响其它模型。
    model_lower = config.model.lower()
    system, user = ai_arbitrate.build_prompt(
        lang=payload.lang,
        text_a=text_a,
        text_b=text_b,
        before=payload.before[-10:],
        after=payload.after[:10],
        hint=hint,
        history=[
            {"role": item.role, "text": item.text} for item in payload.history
        ],
        no_think="qwen" in model_lower or "think" in model_lower,
    )
    # 本地推理模型（尤其 Qwen3 系）用 assistant 前缀把输出钉成 JSON；云端模型
    # 走正常 JSON 模式，避免个别网关不接受 assistant 预填。
    prefill = '{"text": "' if ai_client.is_local_url(base_url) else ""
    started = time.perf_counter()
    try:
        data = ai_client.chat_json(
            config,
            system,
            user,
            retries=1,
            temperature=0.1,
            assistant_prefill=prefill,
        )
        try:
            result = ai_arbitrate.parse_result(data)
        except ai_arbitrate.ArbitrationError:
            data = ai_client.chat_json(
                config,
                system + ai_arbitrate.STRICT_HINT,
                user,
                retries=1,
                temperature=0.1,
                assistant_prefill=prefill,
            )
            result = ai_arbitrate.parse_result(data)
    except ai_client.AiError as exc:
        # 上游鉴权失败与网络/服务失败分开说，但不回显 Key 或请求体。
        detail = (
            f"模型服务拒绝鉴权（{exc.status}）：检查 API Key"
            if exc.status in (401, 403)
            else exc.message
        )
        raise HTTPException(
            status_code=424 if exc.status in (401, 403) else 502,
            detail=detail,
        ) from exc
    except ai_arbitrate.ArbitrationError as exc:
        raise HTTPException(
            status_code=502, detail=f"模型返回格式不正确：{exc}"
        ) from exc

    return {
        **result,
        "model": config.model,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


@router.post("/api/ai/translate-cue")
def translate_cue(payload: TranslateCueRequest, request: Request, session: Session = Depends(get_session)) -> dict:
    """把核对台第 ``index`` 条原文交给**单句判定模型**翻一句，只回文本。

    与 ``/api/ai/arbitrate`` 同一约束：不落盘、不改字幕、不进历史。用户在检查器里
    看一眼（可改）点「采纳」，才走既有的 ``updateTranslation()`` 压一步历史。

    刻意默认走本地 LM Studio（``ai_arbitrate_base_url``）：这类片源云端模型会拒，
    而本地那份已经为逐句复核加载着，不存在额外下载 / 计费。
    """
    settings = _ai_settings(request)
    if not settings.get("ai_enabled"):
        raise HTTPException(status_code=503, detail="AI 优化未启用：设置 → 实验功能里打开它")
    cues = session.review_cues
    if not 0 <= payload.index < len(cues):
        raise HTTPException(status_code=404, detail=f"第 {payload.index + 1} 条不存在")
    text = cues[payload.index].text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="这一句原文是空的，没有可翻译的内容")

    lang = (payload.lang or "").strip()
    if not lang:
        lang = sorted(session.translations)[0] if session.translations else "zh-Hans"
    track = session.translations.get(lang)

    base_url, model, override = _arbitrate_target(settings)
    key = (
        request.headers.get("x-ai-arbitrate-key" if override else "x-ai-key") or ""
    ).strip()
    if override and not key and not ai_client.is_local_url(base_url):
        key = (request.headers.get("x-ai-key") or "").strip()
    config = ai_client.AiConfig(
        base_url=base_url,
        model=model,
        api_key=key,
        timeout_s=120.0,
        allow_no_key=ai_client.is_local_url(base_url),
    )
    if not key and not config.allow_no_key:
        raise HTTPException(
            status_code=401,
            detail="单句判定模型还没有配置 API Key" if override else "还没有配置 API Key",
        )
    try:
        config.ensure_ready()
    except ai_client.AiError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc

    # 上下文只给这一句的邻居：前面的取最近 4 条，后面的取最近 4 条；已有译文当参考。
    radius = ai_translate_cue.MAX_CONTEXT_CUES
    start = max(0, payload.index - radius)
    stop = min(len(cues), payload.index + radius + 1)
    before = [cues[i].text for i in range(start, payload.index)]
    after = [cues[i].text for i in range(payload.index + 1, stop)]
    refs = []
    if track is not None:
        for i in range(start, stop):
            if i == payload.index:
                continue
            dst = track.texts[i].strip() if i < len(track.texts) else ""
            if dst:
                refs.append({"src": cues[i].text, "dst": dst})

    started = time.perf_counter()
    try:
        result = ai_translate_cue.translate_cue(
            text,
            config,
            dst_lang=lang,
            before=before,
            after=after,
            refs=refs,
            # 与单句判定同一条 Qwen3 策略：不加 /no_think 时答案全进
            # reasoning_content，content 为空，重试两次就报 502。
            no_think="qwen" in config.model.lower() or "think" in config.model.lower(),
        )
    except ai_client.AiError as exc:
        detail = (
            f"模型服务拒绝鉴权（{exc.status}）：检查 API Key"
            if exc.status in (401, 403)
            else exc.message
        )
        raise HTTPException(
            status_code=424 if exc.status in (401, 403) else 502, detail=detail
        ) from exc
    except ai_translate_cue.CueTranslateError as exc:
        raise HTTPException(status_code=502, detail=f"模型返回格式不正确：{exc}") from exc

    return {
        **result,
        "lang": lang,
        "model": config.model,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


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

    texts = _current_texts(session)
    if not texts:
        raise HTTPException(status_code=409, detail="当前没有可润色的字幕")
    first, last = _scope_span(len(texts), payload.from_index, payload.to_index)
    cue_span = None if (first, last) == (1, len(texts)) else (first, last)

    base_url = payload.base_url or str(settings.get("ai_base_url") or "")
    config = ai_client.AiConfig(
        base_url=base_url,
        model=payload.model or str(settings.get("ai_model") or ""),
        api_key=key,
        timeout_s=180.0,
        allow_no_key=ai_client.is_local_url(base_url),
    )
    if not key and not config.allow_no_key:
        raise HTTPException(status_code=401, detail="还没有配置 API Key")
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
    mode = (payload.mode or "single").strip().lower()
    if mode not in ("single", "dual"):
        raise HTTPException(status_code=422, detail=f"未知的润色模式：{payload.mode}")
    if kind == "polish" and mode == "dual":
        alt = session.alt_review
        if alt is None or not alt.cues:
            raise HTTPException(status_code=409, detail="当前没有第二版字幕：先在转写页把另一引擎的稿放进双引擎复核，或到双引擎复核页导入一份已有字幕")

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
                cue_span=cue_span,
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
            dual=(kind == "polish" and mode == "dual"),
            cue_span=cue_span,
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
    mode: str = "single",
    from_index: int = 1,
    to_index: int | None = None,
    range_from: int | None = None,
    range_to: int | None = None,
    indices: str = "",
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
    mode = (mode or "single").strip().lower()
    if mode not in ("single", "dual"):
        raise HTTPException(status_code=422, detail=f"未知的润色模式：{mode}")
    alt = session.alt_review
    if kind == "polish" and mode == "dual" and (alt is None or not alt.cues):
        raise HTTPException(status_code=409, detail="当前没有第二版字幕：先在转写页把另一引擎的稿放进双引擎复核，或到双引擎复核页导入一份已有字幕")

    total = len(cues)
    # 作用范围（处理范围）与内容范围（当前分段）分开：整片时段落完全一致。
    first, last = _scope_span(total, range_from, range_to)
    start = max(first, int(from_index or first))
    end = last if to_index is None else min(last, int(to_index))
    if start > end:
        raise HTTPException(status_code=422, detail=f"片段范围不合法：第 {start}–{end} 条")
    full = (first, last) == (1, total)
    content_full = (start, end) == (first, last)

    # 补译批次（2026-11-25）：只复制「待译」的 N 条，而不是整段。
    # 序号用全片条号，回填才能按条号落位；模板仍然用用户当前选中的那一个。
    try:
        sparse = ai_gap.normalize_indices(indices, total) if (indices or "").strip() else []
    except ai_gap.GapError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    if sparse:
        if kind != "translate":
            raise HTTPException(status_code=422, detail="补译批次只支持翻译；润色请走整段")
        if any(index < first or index > last for index in sparse):
            raise HTTPException(
                status_code=422,
                detail=f"补译条号超出当前处理范围（第 {first}–{last} 条）",
            )
        track = session.translations.get(lang)
        track_texts = (
            list(track.texts)
            if track is not None and len(track.texts) == total
            else None
        )
        scope_label = (
            f"处理范围第 {first}–{last} 条，全片共 {total} 条"
            if not full
            else f"全片共 {total} 条"
        )
        gap_srt = ai_gap.gap_srt(cues, sparse)
        hint = ai_gap.gap_instructions(total, sparse, scope_label)
        prompt, template = prompt_store.render_prompt(
            gap_srt,
            ai_translate.lang_name(lang),
            template_id=template_id or None,
            category=prompt_store.CATEGORY_TRANSLATE,
            range_text=hint,
            settings_path=settings_path(request),
        )
        if template is None:
            raise HTTPException(status_code=500, detail="提示词库为空")
        context = ai_gap.context_block(cues, track_texts, sparse)
        if context:
            prompt = prompt.rstrip() + "\n\n" + context
        return {
            "prompt": prompt,
            "count": len(sparse),
            "total": total,
            "lang": lang,
            "chars": len(prompt),
            "mode": "single",
            "from": sparse[0],
            "to": sparse[-1],
            "range_from": first,
            "range_to": last,
            "indices": sparse,
            "sparse": True,
            "digest": ai_gap.digest_of(cues, sparse),
            "template_id": template["id"],
            "template_name": template["name"],
            "category": prompt_store.CATEGORY_TRANSLATE,
        }

    if kind == "polish":
        # 润色也支持「复制提示词 → 网页版模型 → 粘回来」；不绑定 AI 优化。
        indices = list(range(start - 1, end))
        srt_a = ai_polish.srt_block(cues, indices)
        srt_b = ""
        if mode == "dual" and alt is not None:
            if full and content_full:
                srt_b = ai_polish.srt_block(alt.cues)
            else:
                t0 = cues[start - 1].start
                t1 = cues[end - 1].end
                b_indices = ai_polish.dual_context_cues(alt.cues, t0, t1)
                srt_b = ai_polish.srt_block(alt.cues, b_indices)
        range_text = _range_text(first, last, start, end, total)
        category = (
            prompt_store.CATEGORY_POLISH_DUAL
            if mode == "dual"
            else prompt_store.CATEGORY_POLISH_SINGLE
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
            # 提示词库异常时退回内置文案，绝不返回空提示词。
            prompt = ai_polish.build_manual_prompt(
                srt_a, srt_b=srt_b, range_hint=range_text, dual=(mode == "dual")
            )
            template = {"id": "builtin-polish", "name": "内置润色提示词", "category": category}
        return {
            "prompt": prompt,
            "count": end - start + 1,
            "total": total,
            "lang": "",
            "chars": len(prompt),
            "mode": mode,
            "from": start,
            "to": end,
            "range_from": first,
            "range_to": last,
            "template_id": template["id"],
            "template_name": template["name"],
            "category": category,
        }
    # 翻译：剪成这一段的 SRT（长片一次贴不进去时也走同一条路）
    content_cues = list(cues[start - 1 : end])
    srt = cues_to_srt(content_cues)
    range_note = _range_text(first, last, start, end, total) if not full or not content_full else ""
    prompt, template = prompt_store.render_prompt(
        srt,
        ai_translate.lang_name(lang),
        template_id=template_id or None,
        category=prompt_store.CATEGORY_TRANSLATE,
        range_text=range_note,
        settings_path=settings_path(request),
    )
    if template is None:
        raise HTTPException(status_code=500, detail="提示词库为空")
    return {
        "prompt": prompt,
        "count": len(content_cues),
        "total": total,
        "lang": lang,
        "chars": len(prompt),
        "mode": "single",
        "from": start,
        "to": end,
        "range_from": first,
        "range_to": last,
        "template_id": template["id"],
        "template_name": template["name"],
        "category": prompt_store.CATEGORY_TRANSLATE,
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
    mode = (payload.mode or "single").strip().lower()
    if mode not in ("single", "dual"):
        raise HTTPException(status_code=422, detail=f"未知的润色模式：{payload.mode}")
    alt = session.alt_review
    if kind == "polish" and mode == "dual":
        if alt is None or not alt.cues:
            raise HTTPException(status_code=409, detail="当前没有第二版字幕，无法做双源润色")
    texts_b = [cue.text for cue in alt.cues] if (kind == "polish" and alt is not None) else None
    total = len(cues)
    first, last = _scope_span(total, payload.range_from, payload.range_to)
    start = max(first, int(payload.from_index or first))
    end = last if payload.to_index is None else min(last, int(payload.to_index))
    if start > end:
        raise HTTPException(status_code=422, detail=f"片段范围不合法：第 {start}–{end} 条")
    try:
        alignment = None
        if kind == "polish":
            proposal, warnings = ai_polish.proposal_from_srt(
                payload.text,
                cues,
                from_index=start,
                to_index=end,
                texts_b=texts_b if mode == "dual" else None,
                range_from=first,
                range_to=last,
            )
        else:
            proposal, warnings, alignment = ai_translate.proposal_from_srt_ex(
                payload.text,
                cues,
                lang,
                from_index=start,
                to_index=end,
                range_from=first,
                range_to=last,
                strict_count=payload.strict_count,
            )
    except ai_client.AiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "proposal": proposal,
        "warnings": warnings,
        "count": len(proposal["items"]),
        "mode": mode,
        "from": start,
        "to": end,
        "range_from": first,
        "range_to": last,
        "expected": end - start + 1,
        "alignment": alignment,
    }


class GapFromSrtRequest(BaseModel):
    """补译回填的解析请求：条号集合 + 粘贴内容 +（可选）复制时的源指纹。"""

    indices: list[int] = Field(min_length=1)
    text: str = Field(min_length=1)
    digest: str = ""


@router.post("/api/ai/gap-from-srt")
def gap_from_pasted_srt(
    payload: GapFromSrtRequest,
    session: Session = Depends(get_session),
) -> dict:
    """把补译回复解析成 ``[{i, before, after}]``（**只解析，不落盘、不改字幕**）。

    与 ``/api/ai/from-srt`` 的区别：这里按序号落位、条数严格 1:1，不做时间轴对齐。
    时间轴对齐是「整段翻译」的容错通道，但它会猜槽位；补译的每一条都对应一个
    明确的待译下标，猜错就会把 A 句译文写进 B 句。
    """
    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有字幕")
    total = len(cues)
    try:
        indices = ai_gap.normalize_indices(payload.indices, total)
        if not indices:
            raise ai_gap.GapError("补译批次是空的：先点「复制待译」再粘贴回复")
        digest = ai_gap.digest_of(cues, indices)
        if payload.digest and payload.digest != digest:
            raise ai_gap.GapError(
                "原文在复制之后改过了：请重新复制提示词，再把结果粘回来",
                status=409,
            )
        items, warnings = ai_gap.parse_gap_reply(payload.text, cues, indices)
    except ai_gap.GapError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return {
        "items": items,
        "indices": indices,
        "count": len(items),
        "digest": digest,
        "warnings": warnings,
    }


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
    alt_texts = [cue.text for cue in session.alt_review.cues] if session.alt_review else None
    check, span = _validate_scoped(data, texts, alt_texts)
    first, last = span
    scoped = (first, last) != (1, len(texts))
    return {
        "path": str(path),
        "proposal": data,
        "ok": check.ok,
        "errors": check.errors,
        "warnings": check.warnings,
        "digest_match": check.digest_match,
        "source_count": int((data.get("source") or {}).get("count") or 0),
        "current_count": last - first + 1 if scoped else len(texts),
        "total_count": len(texts),
        "range": {"from": first, "to": last} if scoped else None,
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

    alt_texts = [cue.text for cue in session.alt_review.cues] if session.alt_review else None
    check, span = _validate_scoped(data, texts, alt_texts)
    if not check.ok:
        return _rejected(check)

    path = _path_for(request, session, kind, lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, proposals.dump_proposal(data))
    return {
        "path": str(path),
        "count": len(data.get("items") or []),
        "range": {"from": span[0], "to": span[1]} if span != (1, len(texts)) else None,
        "warnings": check.warnings,
    }


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

    alt_texts = [cue.text for cue in session.alt_review.cues] if session.alt_review else None
    check, span = _validate_scoped(data, texts, alt_texts)
    if not check.ok:
        return _rejected(check)

    dest = _path_for(request, session, kind, lang)
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(dest, proposals.dump_proposal(data))
    return {
        "path": str(dest),
        "from": str(src),
        "count": len(data.get("items") or []),
        "range": {"from": span[0], "to": span[1]} if span != (1, len(texts)) else None,
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

    alt_texts = [cue.text for cue in session.alt_review.cues] if session.alt_review else None
    check, span = _validate_scoped(data, _current_texts(session), alt_texts)
    if not check.ok:
        return _rejected(check)

    accept = None if payload.accept is None else {int(i) for i in payload.accept}
    # 片段提案只替换对应索引区间；写回仍然只走 apply_polish（这里只换索引口径）。
    scoped = span != (1, len(cues))
    new_cues, changed = proposals.apply_polish_range(
        cues,
        list(data.get("items") or []),
        span if scoped else None,
        accept=accept,
        edits={int(k): v for k, v in (payload.edits or {}).items()},
    )

    # 空应用 / 无实际改动：不压历史，让 can_undo 保持原样（文档 §4.2.2 第 5 步）
    if changed:
        label = (
            f"应用 AI 提案（片段 {span[0]}–{span[1]}，{changed} 处）"
            if scoped
            else f"应用 AI 提案（{changed} 处）"
        )
        session.replace_review(new_cues, label=label)

    return {
        **_snapshot(session),
        "changed": changed,
        "range": {"from": span[0], "to": span[1]} if scoped else None,
        "warnings": check.warnings,
    }
