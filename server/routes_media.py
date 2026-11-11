"""媒体与波形路由。

`GET /media/{id}` 必须支持 Range——没有它，`<video>` 无法 seek，拖动进度条会整段
重下。Starlette 的 `FileResponse` 原生处理 `Range` / `If-Range`，这里只负责鉴权与
响应头补齐（`Accept-Ranges`、缓存策略）。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from core.thumbnails import ThumbnailError, thumbnail_for

from .media import MEDIA_SUFFIXES, MediaError, MediaInfo, MediaStore
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


@router.get("/api/media/thumb", dependencies=[Depends(require_token)])
def get_media_thumb(
    request: Request,
    path: str = Query(min_length=1, description="本地视频绝对路径"),
    width: int = Query(default=480, ge=160, le=960),
) -> FileResponse:
    """最近打开列表的封面。

    按需生成并缓存到 `{output_dir}/thumbnails/`。只解开头 30 秒，FFmpeg 的
    ``thumbnail`` 滤镜会挑一张非黑场的代表帧；失败时返回 404，前端退回胶片图标。
    """
    source = Path(path).expanduser()
    if not source.is_absolute():
        raise HTTPException(status_code=422, detail="缩略图路径必须是绝对路径")
    if source.suffix.lower() not in MEDIA_SUFFIXES:
        raise HTTPException(status_code=404, detail="不是支持的媒体文件")
    output_dir = Path(getattr(request.app.state.config, "output_dir", "."))
    try:
        thumb = thumbnail_for(source, output_dir / "thumbnails", width=width)
    except ThumbnailError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        thumb,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


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
def get_peaks(
    media_id: str,
    request: Request,
    bins: int = 4000,
    lod: str | None = None,
    start: float | None = Query(default=None, alias="from"),
    end: float | None = Query(default=None, alias="to"),
) -> dict:
    """波形包络。

    `bins` 直接给点数；`lod` 是便捷档位（`overview` / `mid` / `fine`），前端缩放时
    按可视窗口选档，避免每次都传具体数字。

    带 `from` / `to` 时只算这个时间窗口——核对台放大到几秒区间要靠它，
    否则整片包络的横向精度根本不够画。
    """
    if lod:
        bins = _LOD_BINS.get(lod, bins)
    bins = max(64, min(int(bins), MAX_BINS))
    try:
        if start is not None and end is not None and end > start:
            duration, values = _store(request).peaks_window(media_id, start, end, bins)
        else:
            duration, values = _store(request).peaks(media_id, bins)
    except MediaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "id": media_id,
        "bins": len(values),
        "duration": duration,
        "start": start,
        "end": end,
        "peaks": values,
    }


_LOD_BINS = {
    "overview": 4_000,
    "mid": 16_000,
    "fine": 64_000,
    "ultra": 256_000,
}


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$", re.IGNORECASE)


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    """解析单段 Range；返回 `(start, end)`，无效返回 None。

    Chromium 的 `<video>` 只发单段 Range；多段请求直接按第一段处理，避免把
    一个 3 GB 的 MKV 整段重新下载。``bytes=-500``（后缀范围）也要支持。
    """
    match = _RANGE_RE.match((header or "").strip())
    if not match:
        return None
    raw_start, raw_end = match.groups()
    if not raw_start and not raw_end:
        return None
    if not raw_start:
        suffix = int(raw_end)
        if suffix <= 0:
            return None
        start = max(0, size - suffix)
        return start, size - 1
    start = int(raw_start)
    end = int(raw_end) if raw_end else size - 1
    if start >= size or end < start:
        return None
    return start, min(end, size - 1)


def _media_response(path: Path, request: Request):
    """带 Range 的媒体响应。

    Starlette 0.38 的 ``FileResponse`` 还没有 Range 支持（0.39 才加），
    直接返回 200 + 整文件会让 `<video>` 拖进度条时重新下载整段。这里自己
    处理单段 Range：206 + `Content-Range`，只读请求的那一段。
    """
    total = path.stat().st_size
    range_header = request.headers.get("range", "")
    parsed = _parse_range(range_header, total) if range_header else None
    if range_header and parsed is None:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{total}", "Accept-Ranges": "bytes"},
        )
    if parsed is None:
        return FileResponse(
            path,
            media_type=_guess_media_type(path),
            filename=path.name,
            headers={"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"},
        )

    start, end = parsed
    length = end - start + 1
    chunk_size = 256 * 1024

    def iter_range():
        with open(path, "rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        iter_range(),
        status_code=206,
        media_type=_guess_media_type(path),
        headers={
            "Content-Range": f"bytes {start}-{end}/{total}",
            "Content-Length": str(length),
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, max-age=3600",
        },
    )


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

    return _media_response(path, request)


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
