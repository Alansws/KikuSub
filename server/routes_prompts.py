"""提示词模板库接口。

模板是用户可见、可编辑的普通 JSON；服务层只做校验、原子写和渲染。手动通道
``/api/ai/prompt`` 也从这里取模板，保证「在提示词库改完 → 回 AI 优化台复制」
拿到的是同一份内容。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import prompts as prompt_store
from core import settings as settings_store

from .security import require_token

router = APIRouter(tags=["prompts"], dependencies=[Depends(require_token)])

log = logging.getLogger("kikusub.server")


class TemplatePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None


class TemplateCreate(BaseModel):
    name: str = Field(default="新模板", max_length=60)
    description: str = Field(default="", max_length=200)
    content: str = Field(min_length=1, max_length=prompt_store.MAX_CONTENT)
    # polish_single / polish_dual / translate；缺省按翻译（旧客户端兼容）
    category: str = prompt_store.DEFAULT_CATEGORY


def settings_path_for(request: Request) -> Path:
    return Path(getattr(request.app.state, "settings_path", settings_store.SETTINGS_PATH))


def prompts_path_for(request: Request) -> Path:
    return prompt_store.default_prompts_path(settings_path_for(request))


def _library(request: Request) -> dict:
    library = prompt_store.load_library(path=prompts_path_for(request))
    return {**library, "path": str(prompts_path_for(request))}


@router.get("/api/prompts")
def get_prompts(request: Request) -> dict:
    return _library(request)


@router.post("/api/prompts", status_code=201)
def create_prompt(payload: TemplateCreate, request: Request) -> dict:
    library = prompt_store.load_library(path=prompts_path_for(request))
    try:
        saved, template = prompt_store.create_template(
            library,
            payload.name,
            payload.content,
            payload.description,
            category=prompt_store.normalize_category(payload.category),
            path=prompts_path_for(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log.info("提示词模板新建 | id=%s | name=%s", template["id"], template["name"])
    return {**saved, "path": str(prompts_path_for(request)), "created": template["id"]}


@router.patch("/api/prompts/{template_id}")
def update_prompt(template_id: str, payload: TemplatePatch, request: Request) -> dict:
    library = prompt_store.load_library(path=prompts_path_for(request))
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=422, detail="没有需要更新的字段")
    try:
        saved = prompt_store.update_template(
            library, template_id, patch, path=prompts_path_for(request)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模板不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log.info("提示词模板更新 | id=%s | fields=%s", template_id, ",".join(patch))
    return {**saved, "path": str(prompts_path_for(request))}


@router.post("/api/prompts/{template_id}/select")
def select_prompt(template_id: str, request: Request, category: str = "") -> dict:
    library = prompt_store.load_library(path=prompts_path_for(request))
    try:
        saved = prompt_store.set_selected(
            library,
            template_id,
            category=category,
            path=prompts_path_for(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模板不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**saved, "path": str(prompts_path_for(request))}


@router.delete("/api/prompts/{template_id}")
def remove_prompt(template_id: str, request: Request) -> dict:
    library = prompt_store.load_library(path=prompts_path_for(request))
    if len(library.get("templates") or []) <= 1:
        raise HTTPException(status_code=409, detail="至少保留一个模板")
    try:
        saved = prompt_store.delete_template(
            library, template_id, path=prompts_path_for(request)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模板不存在") from exc
    return {**saved, "path": str(prompts_path_for(request))}


@router.post("/api/prompts/{template_id}/reset")
def reset_prompt(template_id: str, request: Request) -> dict:
    default = next(
        (item for item in prompt_store.DEFAULT_TEMPLATES if item["id"] == template_id),
        None,
    )
    if default is None:
        raise HTTPException(status_code=404, detail="没有可恢复的内置模板")
    library = prompt_store.load_library(path=prompts_path_for(request))
    try:
        saved = prompt_store.update_template(
            library,
            template_id,
            {
                "name": default["name"],
                "description": default["description"],
                "content": default["content"],
            },
            path=prompts_path_for(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模板不存在") from exc
    return {**saved, "path": str(prompts_path_for(request))}
