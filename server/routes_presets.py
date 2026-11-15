"""预设路由：`presets.json` 的读写，直接复用 `core.presets.PresetStore`。

旧实现的 `load/save/delete_preset` 三个 Gradio 回调就是这层逻辑，这里只是把
「返回值给 gr.update()」换成 JSON。

2026-11-14 起预设与引擎强绑定：读取（= 加载到参数面板）必须带 `engine`，
互不匹配返回 409；保存必须带 `engine`，服务端会收敛成该引擎的完整快照。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from core.engines import KEYS as ENGINE_KEYS
from core.presets import (
    PresetEngineMismatch,
    PresetError,
    PresetNotFound,
    PresetStore,
)

from .security import require_token

router = APIRouter(prefix="/api/presets", tags=["presets"], dependencies=[Depends(require_token)])


class SaveRequest(BaseModel):
    name: str = Field(min_length=1)
    engine: str
    values: dict = Field(default_factory=dict)


class UpdateRequest(BaseModel):
    new_name: str | None = None
    engine: str | None = None
    values: dict | None = None


def _store(request: Request) -> PresetStore:
    return request.app.state.presets


def _http_error(exc: PresetError) -> HTTPException:
    if isinstance(exc, PresetNotFound):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, PresetEngineMismatch):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=code, detail=str(exc))


@router.get("")
def list_presets(
    request: Request,
    engine: str | None = Query(default=None, description="只列与该引擎绑定的预设；省略为全部"),
) -> dict:
    store = _store(request)
    store.reload()
    if engine is not None and engine not in ENGINE_KEYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"未知引擎「{engine}」"
        )
    return {
        "items": [{"name": name, "engine": bound} for name, bound in store.list(engine)],
        "load_error": store.load_error,
    }


@router.get("/{name}")
def get_preset(
    name: str,
    request: Request,
    engine: str = Query(..., description="当前选中的引擎；不一致时拒绝加载"),
) -> dict:
    store = _store(request)
    store.reload()
    try:
        entry = store.resolve(name, engine)
    except PresetError as exc:
        raise _http_error(exc) from exc
    return {"name": name, "engine": entry.get("引擎"), "values": entry.get("参数", {})}


@router.post("", status_code=status.HTTP_201_CREATED)
def save_preset(payload: SaveRequest, request: Request) -> dict:
    store = _store(request)
    store.reload()
    try:
        name, created = store.save(payload.name, payload.values, payload.engine)
    except PresetError as exc:
        raise _http_error(exc) from exc
    return {"name": name, "created": created}


@router.put("/{name}")
def update_preset(name: str, payload: UpdateRequest, request: Request) -> dict:
    store = _store(request)
    store.reload()
    target = name
    renamed = False
    try:
        if payload.new_name and payload.new_name != name:
            target, _ = store.rename(name, payload.new_name)
            renamed = True
        if payload.values is not None:
            entry = store.get(target)
            if entry is None:
                raise PresetNotFound(f"未找到预设「{target}」。")
            bound = entry.get("引擎")
            if payload.engine is not None and payload.engine != bound:
                raise PresetEngineMismatch(
                    f"预设「{target}」绑定的是「{bound or '未绑定'}」引擎，"
                    f"不能改成「{payload.engine}」。"
                )
            if bound is None:
                raise PresetError("该预设没有绑定引擎，已过时；请重新保存而不是直接改写。")
            target, _ = store.save(target, payload.values, bound)
    except PresetError as exc:
        raise _http_error(exc) from exc
    return {"name": target, "renamed": renamed, "replaced": False}


@router.delete("/{name}")
def delete_preset(name: str, request: Request) -> dict:
    store = _store(request)
    store.reload()
    try:
        removed = store.delete(name)
    except PresetError as exc:
        raise _http_error(exc) from exc
    return {"deleted": removed}
