"""预设路由：`presets.json` 的读写，直接复用 `core.presets.PresetStore`。

旧实现的 `load/save/delete_preset` 三个 Gradio 回调就是这层逻辑，这里只是把
「返回值给 gr.update()」换成 JSON。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from core.presets import PresetError, PresetStore

from .security import require_token

router = APIRouter(prefix="/api/presets", tags=["presets"], dependencies=[Depends(require_token)])


class SaveRequest(BaseModel):
    name: str = Field(min_length=1)
    engine: str | None = None
    values: dict = Field(default_factory=dict)


class UpdateRequest(BaseModel):
    new_name: str | None = None
    engine: str | None = None
    values: dict | None = None


def _store(request: Request) -> PresetStore:
    return request.app.state.presets


@router.get("")
def list_presets(request: Request) -> dict:
    store = _store(request)
    store.reload()
    return {
        "items": [{"name": name, "engine": engine} for name, engine in store.list()],
        "load_error": store.load_error,
    }


@router.get("/{name}")
def get_preset(name: str, request: Request) -> dict:
    store = _store(request)
    store.reload()
    entry = store.get(name)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"未找到预设「{name}」")
    return {"name": name, "engine": entry.get("引擎"), "values": entry.get("参数", {})}


@router.post("", status_code=status.HTTP_201_CREATED)
def save_preset(payload: SaveRequest, request: Request) -> dict:
    store = _store(request)
    store.reload()
    try:
        name, created = store.save(payload.name, payload.values, payload.engine)
    except PresetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"name": name, "created": created}


@router.put("/{name}")
def update_preset(name: str, payload: UpdateRequest, request: Request) -> dict:
    store = _store(request)
    store.reload()
    target = name
    renamed = False
    try:
        if payload.new_name and payload.new_name != name:
            target, replaced = store.rename(name, payload.new_name)
            renamed = True
            if replaced:
                return {"name": target, "renamed": True, "replaced": True}
        if payload.values is not None:
            engine = payload.engine
            if engine is None:
                entry = store.get(target)
                engine = entry.get("引擎") if entry else None
            target, _ = store.save(target, payload.values, engine)
    except PresetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"name": target, "renamed": renamed, "replaced": False}


@router.delete("/{name}")
def delete_preset(name: str, request: Request) -> dict:
    store = _store(request)
    store.reload()
    try:
        removed = store.delete(name)
    except PresetError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"deleted": removed}
