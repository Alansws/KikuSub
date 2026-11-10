"""媒体与波形路由。

`GET /media/{id}` 必须支持 Range——没有它，`<video>` 无法 seek，拖动进度条会整段
重下。Starlette 的 `FileResponse` 原生处理 `Range` / `If-Range`，这里只负责鉴权与
响应头补齐（`Accept-Ranges`、缓存策略）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .media import MediaError, MediaInfo, MediaStore
from .security import require_token, token_ok

router = APIRouter(tags=["media"])

# 波形档位上限：超过这个数前端也画不出来，纯粹浪费 CPU 与带宽。
MAX_BINS = 400_000


class ImportRequest(BaseModel):
    path: str = Field(min_length=1, description="本地绝对路径（桌面端拖入/文件对话框得到）")


def _store(request: Request) -> MediaStore:
    return request.app.state.media


def _info_or_400(request: Request, media_id: str) -> MediaInfo:
    try:
        return _store(request).get(media_id)
    except MediaError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/api/media", dependencies=[Depends(require_token)])
def import_media(payload: ImportRequest, request: Request) -> dict:
    """按路径导入（不是上传）。同一路径重复导入是幂等的。"""
    try:
        info = _store(request).register(payload.path)
    except MediaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _store(request).describe(info.id)


@router.get("/api/media", dependencies=[Depends(require_token)])
def list_media(request: Request) -> dict:
    store = _store(request)
    return {"items": [store.describe(info.id) for info in store.list()]}


@router.get("/api/media/{media_id}", dependencies=[Depends(require_token)])
def get_media(media_id: str, request: Request) -> dict:
    """元数据。`proxy_ready` 是**实时**的——压制任务在另一个线程写盘，
    前端靠它决定要不要把 `<video>` 切到代理。"""
    _info_or_400(request, media_id)
    return _store(request).describe(media_id)


@router.delete("/api/media/{media_id}", dependencies=[Depends(require_token)])
def delete_media(media_id: str, request: Request) -> dict:
    _store(request).drop(media_id)
    return {"ok": True}


@router.get("/api/media/{media_id}/peaks", dependencies=[Depends(require_token)])
def get_peaks(media_id: str, request: Request, bins: int = 4000, lod: str | None = None) -> dict:
    """波形包络。

    `bins` 直接给点数；`lod` 是便捷档位（`overview` / `mid` / `fine`），前端缩放时
    按可视窗口选档，避免每次都传具体数字。
    """
    if lod:
        bins = _LOD_BINS.get(lod, bins)
    bins = max(64, min(int(bins), MAX_BINS))
    try:
        duration, values = _store(request).peaks(media_id, bins)
    except MediaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"id": media_id, "bins": len(values), "duration": duration, "peaks": values}


_LOD_BINS = {
    "overview": 4_000,
    "mid": 16_000,
    "fine": 64_000,
    "ultra": 256_000,
}


@router.get("/media/{media_id}")
def stream_media(media_id: str, request: Request, proxy: int = 0):
    """媒体流（支持 Range）。

    浏览器 `<video>` 发不了 `Authorization` 头，所以这里用 `?token=` 鉴权。

    `?proxy=1` 时改发 480p 监看代理：Chromium 解不开 MKV / HEVC，
    前端在压制完成后把 src 换成这个地址即可，不必再拉一次元数据。
    """
    if not token_ok(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing token")
    try:
        info = _store(request).get(media_id)
    except MediaError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    path: Path = info.path
    if proxy:
        found = _store(request).proxy_path(info)
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="代理尚未生成")
        path = found

    return FileResponse(
        path,
        media_type=_guess_media_type(path),
        filename=path.name,
        headers={"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"},
    )


def _guess_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".mp4": "video/mp4",
        ".m4v": "video/mp4",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".ts": "video/mp2t",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".opus": "audio/opus",
        ".aac": "audio/aac",
    }.get(suffix, "application/octet-stream")
