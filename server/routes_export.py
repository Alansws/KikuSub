"""成片导出路由：规划与任务创建。

真正干活的是 ``core.video_export``；这里只做参数校验、取当前会话的字幕/译文，
以及把单槽任务交给 ``JobManager``。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from core import settings as settings_store
from core import video_export
from core.procutil import run_command

from .deps import get_session, settings_path
from .jobs import JobConflict, JobManager
from .media import MediaError
from .security import require_token
from .sessions import Session

router = APIRouter(tags=["export"], dependencies=[Depends(require_token)])
log = logging.getLogger("kikusub.server")


class SubtitleStylePayload(BaseModel):
    """烧录样式。字段范围由核心的``from_mapping``再夹紧一次。"""

    preset: str = "fansub"
    font: str = Field(default="pingfang", max_length=40)
    weight: str = Field(default="bold", pattern="^(regular|medium|bold)$")
    size: float = Field(default=1.0, ge=0.7, le=1.6)
    outline: float = Field(default=1.0, ge=0.0, le=2.4)
    shadow: bool = True
    position: str = Field(default="bottom", pattern="^(bottom|top)$")
    margin: float = Field(default=4.5, ge=1.0, le=14.0)
    fill: str = Field(default="#FFFFFF", pattern="^#[0-9a-fA-F]{6}$")
    outline_color: str = Field(default="#000000", pattern="^#[0-9a-fA-F]{6}$")


class ExportRequest(BaseModel):
    media_id: str
    mode: str = Field(default="burn", pattern="^(burn|soft|copy)$")
    track: str = Field(default="source", pattern="^(source|target|both)$")
    lang: str = ""
    resolution: str = Field(default="1080p", pattern="^(source|2160p|1440p|1080p|720p|480p)$")
    preset: str = Field(default="balanced", pattern="^(small|balanced|high|ultra)$")
    export_srt: bool = True
    # 用户可在导出面板里临时换目录；空值跟随设置里的成片目录。
    out_dir: str = ""
    style: SubtitleStylePayload = Field(default_factory=SubtitleStylePayload)


class PlanRequest(ExportRequest):
    pass


class StylePreviewRequest(BaseModel):
    media_id: str = ""
    at: float | None = None
    text: str = Field(default="", max_length=120)
    width: int = Field(default=1280, ge=320, le=1920)
    height: int = Field(default=720, ge=180, le=1080)
    # True 时裁出字幕附近的一条特写，方便看清字重与描边细节。
    zoom: bool = False
    # 预览样本文案跟随导出轨：双语时渲染两行，和成片一致。
    track: str = Field(default="source", pattern="^(source|target|both)$")
    lang: str = ""
    style: SubtitleStylePayload = Field(default_factory=SubtitleStylePayload)



def _out_dir(request: Request, raw: str = "") -> Path:
    text = (raw or "").strip()
    if text:
        target = Path(text).expanduser()
        if not target.is_absolute():
            raise HTTPException(status_code=422, detail="导出位置必须使用绝对路径")
        return target.resolve()
    current = settings_store.load_settings(settings_path(request))
    return settings_store.resolve_video_export_dir(
        current, Path(request.app.state.config.output_dir)
    )


def _media_info(request: Request, media_id: str):
    try:
        return request.app.state.media.get(media_id)
    except MediaError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _source(info) -> video_export.SourceInfo:
    return video_export.SourceInfo(
        width=int(info.video_width or 0),
        height=int(info.video_height or 0),
        duration=float(info.duration or 0.0),
        video_bitrate=int(info.video_bitrate or 0),
        audio_bitrate=0,
        video_codec=str(info.video_codec or ""),
        audio_codec=str(info.audio_codec or ""),
        has_video=bool(info.has_video),
        has_audio=bool(info.audio_codec),
        size=int(info.size or 0),
        container=info.suffix,
    )


def _style(payload: SubtitleStylePayload) -> video_export.SubtitleStyle:
    style = video_export.SubtitleStyle.from_mapping(payload.model_dump())
    try:
        style.validate()
    except video_export.ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return style


def _options(payload: ExportRequest) -> video_export.ExportOptions:
    return video_export.ExportOptions(
        mode=payload.mode,
        track=payload.track,
        lang=payload.lang.strip(),
        resolution=payload.resolution,
        preset=payload.preset,
        export_srt=payload.export_srt,
        style=_style(payload.style),
    )


def _translation_texts(session: Session, track: str, lang: str) -> list[str] | None:
    if track == "source":
        return None
    if not lang:
        raise HTTPException(status_code=422, detail="导出译文时必须指定语种")
    track_data = session.translations.get(lang)
    if track_data is None:
        raise HTTPException(status_code=409, detail=f"还没有 {lang} 的译文可用")
    return list(track_data.texts)


@router.get("/api/export/options")
def export_options() -> dict:
    return {
        "modes": [
            {"key": "burn", "label": "烧录硬字幕", "hint": "字幕画进画面，任何播放器都能看；需要重新编码。"},
            {"key": "soft", "label": "软字幕 MP4", "hint": "字幕作为独立轨封装，可开关；同样按所选分辨率/码率编码。"},
            {"key": "copy", "label": "仅封装（不重编码）", "hint": "视频/音频原样复制，几秒完成；画质无损，体积接近源文件。"},
        ],
        "presets": [
            {"key": key, **value} for key, value in video_export.PRESETS.items()
        ],
        "resolutions": [
            {"key": "source", "label": "原始"},
            {"key": "2160p", "label": "4K"},
            {"key": "1440p", "label": "2K"},
            {"key": "1080p", "label": "1080p"},
            {"key": "720p", "label": "720p"},
            {"key": "480p", "label": "480p"},
        ],
    }


@router.post("/api/export/plan")
def export_plan(payload: PlanRequest, request: Request) -> dict:
    info = _media_info(request, payload.media_id)
    source = _source(info)
    options = _options(payload)
    try:
        plan = video_export.plan_export(source, options)
    except video_export.ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    out_dir = _out_dir(request, payload.out_dir)
    fonts_ok, font_error = video_export.font_status()
    return {
        "plan": plan.to_dict(),
        "out_dir": str(out_dir),
        "fonts_ok": fonts_ok,
        "font_error": font_error,
    }


_PREVIEW_CACHE_KEEP = 24


def _prune_preview_cache(directory: Path) -> None:
    try:
        files = sorted(
            (path for path in directory.glob("*.png") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for stale in files[_PREVIEW_CACHE_KEEP:]:
        try:
            stale.unlink()
        except OSError:
            pass


def _preview_frame(request: Request, media_path: Path, at_s: float, width: int, height: int) -> bytes | None:
    """取真实画面当预览背景；按「媒体 + mtime + 时间点」缓存成 PNG。

    预览必须让人一眼看出字在真实画面上够不够清楚，纯色背景判断不了。
    """
    try:
        stat = media_path.stat()
    except OSError:
        return None
    cache_dir = Path(request.app.state.config.output_dir) / "preview_cache"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    key = hashlib.sha1(
        f"{media_path}|{stat.st_mtime_ns}|{stat.st_size}|{at_s:.2f}|{width}x{height}".encode("utf-8")
    ).hexdigest()[:20]
    cached = cache_dir / f"{key}.png"
    if cached.is_file() and cached.stat().st_size > 1024:
        try:
            return cached.read_bytes()
        except OSError:
            return None
    part = cache_dir / f".{key}.part.png"
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )
    try:
        result = run_command(
            [
                "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-ss", f"{max(0.0, at_s):.3f}",
                "-i", str(media_path),
                "-frames:v", "1", "-vf", video_filter,
                "-f", "image2", str(part),
            ],
            timeout=25,
        )
    except Exception:  # noqa: BLE001 - 背景取不到就退回纯色
        return None
    if result.returncode != 0 or not part.is_file() or part.stat().st_size < 1024:
        try:
            part.unlink()
        except OSError:
            pass
        return None
    try:
        part.replace(cached)
    except OSError:
        pass
    _prune_preview_cache(cache_dir)
    try:
        return cached.read_bytes()
    except OSError:
        return None


def _sample_text(session: Session, requested: str, track: str = "source", lang: str = "") -> str:
    """预览文案优先用用户输入，否则取当前字幕轨的第一条。

    双语轨要渲染成两行，否则预览和成片对不上（双语是「一条 cue 两行」）。
    """
    text = (requested or "").strip()
    if text:
        return text[:120]
    translations = session.translations.get(lang) if track != "source" and lang else None
    best = ""
    for index, cue in enumerate(session.review_cues):
        source = str(cue.text or "").strip().replace("\n", " ")
        target = ""
        if translations is not None and index < len(translations.texts):
            target = str(translations.texts[index] or "").strip().replace("\n", " ")
        if track == "target":
            candidate = target
        elif track == "both":
            candidate = f"{source}\n{target}" if target else source
        else:
            candidate = source
        if not candidate:
            continue
        best = best or candidate
        if len(candidate) >= 8:
            return candidate[:120]
    return best[:120] or "这是一句示例字幕，用来预览字体效果。"


@router.get("/api/export/styles")
def export_styles() -> dict:
    """样式预设 + 本机可用字体。

    字体可用性由后端探测：渲染层不能假设 `PingFang.ttc` 一定存在（macOS 把
    字体放在 AssetsV2 的 hash 目录里，不同机器差异很大）。
    """
    fonts_ok, font_error = video_export.font_status()
    return {
        "presets": video_export.style_preset_list(),
        "fonts": video_export.font_catalog(),
        "default": video_export.default_style().to_dict(),
        "weights": [{"key": key, "label": label} for key, label in video_export.WEIGHTS.items()],
        "ranges": {key: list(value) for key, value in video_export.STYLE_RANGES.items()},
        "fonts_ok": fonts_ok,
        "font_error": font_error,
    }


@router.post("/api/export/style-preview")
def export_style_preview(
    payload: StylePreviewRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    style = _style(payload.style)
    if not video_export._pillow_available():
        raise HTTPException(status_code=422, detail="当前内核缺少 Pillow，无法生成样式预览")
    background = None
    if payload.media_id:
        try:
            info = _media_info(request, payload.media_id)
        except HTTPException:
            info = None
        if info is not None:
            at = payload.at
            if at is None:
                at = 1.5
                for cue in session.review_cues:
                    if str(cue.text or "").strip():
                        at = max(0.0, cue.start + min(0.6, max(0.0, cue.end - cue.start) / 2))
                        break
            background = _preview_frame(request, info.path, float(at), payload.width, payload.height)
    try:
        png = video_export.render_preview(
            style,
            width=payload.width,
            height=payload.height,
            text=_sample_text(session, payload.text, payload.track, payload.lang.strip()),
            background=background,
            zoom=payload.zoom,
        )
    except video_export.ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 预览失败不能把导出页打挂
        log.warning("样式预览渲染失败 | %s", exc)
        raise HTTPException(status_code=500, detail="预览渲染失败") from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )



@router.post("/api/export", status_code=201)
async def create_export(
    payload: ExportRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    info = _media_info(request, payload.media_id)
    if session.media_id != payload.media_id:
        # 字幕来自当前会话，不能把 A 片的字幕烧到 B 片上。
        raise HTTPException(status_code=409, detail="当前会话与导出媒体不一致，请重新导入媒体")
    cues = list(session.review_cues)
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有字幕，先转写或导入一份再导出")
    source = _source(info)
    options = _options(payload)
    try:
        video_export.plan_export(source, options)
    except video_export.ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    texts = _translation_texts(session, payload.track, payload.lang.strip())
    out_dir = _out_dir(request, payload.out_dir)
    manager: JobManager = request.app.state.jobs
    loop = asyncio.get_running_loop()
    try:
        job = manager.start_export(
            media_path=info.path,
            info=source,
            options=options,
            cues=cues,
            translation_texts=texts,
            out_dir=out_dir,
            session_id=session.id,
            loop=loop,
        )
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log.info(
        "成片导出任务 | job=%s | media=%s | mode=%s | track=%s | %sp | %s | out=%s",
        job.id,
        info.name,
        payload.mode,
        payload.track,
        payload.resolution,
        payload.preset,
        out_dir,
    )
    return job.snapshot()
