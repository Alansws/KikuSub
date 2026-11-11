"""本地 TTS：系统语音 + OmniVoice 零样本克隆。

三种音色来源，同一个 ``voice_id`` 命名空间：

- ``system:Kyoko`` —— macOS ``say``，零显存兜底；
- ``clone:<id>`` —— 用户从视频切片或上传参考音频建立的克隆音色；
- 空字符串 —— 由服务端选默认（有可用克隆音色就优先它，否则 ``say`` 默认日语）。

音频通过 ``/media/tts/{file}?token=`` 交给 ``<audio>`` 播放（媒体元素发不了
Authorization 头，和视频流同一套鉴权约定）。真正的引擎实现与音色存储都在
``core/tts/``；这里只做参数校验、错误翻译和 HTTP 语义。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.tts import TTSManager, TTSError

from .security import require_token, token_ok

router = APIRouter(tags=["tts"])

RATE_MIN = 100
RATE_MAX = 260
DEFAULT_RATE = 175
CACHE_NAME_RE = re.compile(r"^[0-9a-f]{24}\.wav$")


class TtsRequest(BaseModel):
    """旧接口请求体（保留兼容：前端旧版本 / 外部脚本）。"""

    text: str = Field(default="")
    voice: str = ""
    rate: int = DEFAULT_RATE


class SynthesizeRequest(BaseModel):
    text: str = ""
    voice_id: str = ""
    speed: float = 1.0


class ExtractRequest(BaseModel):
    # media_id 优先；没有时用 path（绝对路径，给测试/无导入场景）
    media_id: str = ""
    path: str = ""
    start: float = 0.0
    end: float = 0.0
    name: str = ""
    text: str = ""
    pad: float = 0.2


class UploadRequest(BaseModel):
    path: str = Field(min_length=1)
    name: str = ""
    ref_text: str = ""


class RenameRequest(BaseModel):
    name: str = Field(min_length=1)


class RefTextRequest(BaseModel):
    ref_text: str = ""


def _manager(request: Request) -> TTSManager:
    return request.app.state.tts


def _fail(exc: TTSError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


def _media_path(request: Request, payload: ExtractRequest) -> tuple[Path, str]:
    if payload.media_id:
        try:
            info = request.app.state.media.get(payload.media_id)
        except Exception as exc:  # noqa: BLE001 —— MediaError 转 404
            raise HTTPException(status_code=404, detail="媒体不存在，请重新导入") from exc
        return Path(info.path), info.name
    raw = (payload.path or "").strip()
    if not raw:
        raise HTTPException(status_code=422, detail="缺少 media_id 或 path")
    path = Path(raw).expanduser()
    if not path.is_file():
        raise HTTPException(status_code=422, detail=f"视频文件不存在：{path}")
    return path, path.name


@router.get("/api/tts/voices", dependencies=[Depends(require_token)])
def tts_voices(request: Request) -> dict:
    """可用音色：系统语音 + 克隆音色 + 引擎/模型状态。"""
    return _manager(request).list_voices()


@router.get("/api/tts/status", dependencies=[Depends(require_token)])
def tts_status(request: Request) -> dict:
    return _manager(request).status()


@router.post("/api/tts/synthesize", dependencies=[Depends(require_token)])
def synthesize(payload: SynthesizeRequest, request: Request) -> dict:
    """生成（或命中缓存）一句日语语音，返回可供 ``<audio>`` 播放的文件名。"""
    try:
        return _manager(request).synthesize(
            payload.text, voice_id=payload.voice_id, speed=payload.speed
        )
    except TTSError as exc:
        raise _fail(exc) from exc


@router.post("/api/tts", dependencies=[Depends(require_token)])
def synthesize_legacy(payload: TtsRequest, request: Request) -> dict:
    """兼容旧接口：``voice`` 是 say 音色名，``rate`` 是 100–260 的语速。"""
    rate = max(RATE_MIN, min(RATE_MAX, int(payload.rate or DEFAULT_RATE)))
    speed = rate / float(DEFAULT_RATE)
    try:
        result = _manager(request).synthesize(
            payload.text, voice_id=payload.voice, speed=speed
        )
    except TTSError as exc:
        raise _fail(exc) from exc
    return {
        **result,
        "voice": result.get("voice_name", ""),
        "rate": rate,
        "chars": len(str(payload.text or "")),
    }


@router.post("/api/tts/voices/extract-from-media", dependencies=[Depends(require_token)])
def extract_voice(payload: ExtractRequest, request: Request) -> dict:
    """从当前视频的指定区间切出一段参考音频，保存为克隆音色。

    这是 KikuSub 的杀手级入口：核对台右键某句 → 后端直接用 ffmpeg 精准切出
    这句的人声 → 之后所有台词都能用这个角色的声线读出来。
    """
    media_path, media_name = _media_path(request, payload)
    if not payload.name.strip():
        raise HTTPException(status_code=422, detail="请给这个音色起个名字")
    if payload.end <= payload.start:
        raise HTTPException(status_code=422, detail="起止时间不合法")
    try:
        return _manager(request).extract_voice_from_media(
            media_path,
            start=payload.start,
            end=payload.end,
            name=payload.name,
            ref_text=payload.text,
            pad=payload.pad,
            source={"media_id": payload.media_id, "media_name": media_name},
        )
    except TTSError as exc:
        raise _fail(exc) from exc


@router.post("/api/tts/voices/upload", dependencies=[Depends(require_token)])
def upload_voice(payload: UploadRequest, request: Request) -> dict:
    """从本地音频文件建立克隆音色（原生对话框拿到绝对路径后调这里）。"""
    path = Path(payload.path).expanduser()
    if not path.is_file():
        raise HTTPException(status_code=422, detail=f"音频文件不存在：{path}")
    name = payload.name.strip() or path.stem
    try:
        return _manager(request).create_voice_from_file(
            path, name=name, ref_text=payload.ref_text
        )
    except TTSError as exc:
        raise _fail(exc) from exc


@router.patch("/api/tts/voices/{voice_id}", dependencies=[Depends(require_token)])
def rename_voice(voice_id: str, payload: RenameRequest, request: Request) -> dict:
    try:
        return _manager(request).rename_voice(voice_id, payload.name)
    except TTSError as exc:
        raise _fail(exc) from exc


@router.put("/api/tts/voices/{voice_id}/ref-text", dependencies=[Depends(require_token)])
def update_ref_text(voice_id: str, payload: RefTextRequest, request: Request) -> dict:
    try:
        return _manager(request).update_voice_ref_text(voice_id, payload.ref_text)
    except TTSError as exc:
        raise _fail(exc) from exc


@router.delete("/api/tts/voices/{voice_id}", dependencies=[Depends(require_token)])
def delete_voice(voice_id: str, request: Request) -> dict:
    try:
        _manager(request).delete_voice(voice_id)
    except TTSError as exc:
        raise _fail(exc) from exc
    return {"ok": True}


@router.post("/api/tts/model/download", dependencies=[Depends(require_token)])
def download_model(request: Request) -> dict:
    """后台下载 OmniVoice 权重；进度由 ``/api/tts/voices`` 的 engine.download 带出。"""
    return _manager(request).downloader.start()


@router.get("/api/tts/model/status", dependencies=[Depends(require_token)])
def model_status(request: Request) -> dict:
    return _manager(request).downloader.status()


@router.get("/api/tts/model/verify", dependencies=[Depends(require_token)])
def verify_model(request: Request) -> dict:
    """只读校验权重完整度；不触发下载，也不占任何任务槽。"""
    return _manager(request).verify_model()


@router.get("/media/tts/{filename}")
def stream_tts(filename: str, request: Request):
    """TTS 音频流。``<audio>`` 发不了 Authorization 头，所以走 ``?token=``。"""
    if not token_ok(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing token",
        )
    if not CACHE_NAME_RE.fullmatch(filename):
        raise HTTPException(status_code=404, detail="TTS 文件不存在")
    manager = _manager(request)
    path = manager.cache_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="TTS 文件不存在")
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Cache-Control": "private, max-age=86400"},
    )
