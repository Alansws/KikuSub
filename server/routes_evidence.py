"""证据接口：给 `kikusub cues / cue` 提供「这一句到底有多响、长什么样、听起来是什么」。

设计口径：

- **只读**。不写会话、不进历史、不改字幕；CLI 拿到的是一份可复核的证据。
- **绝对电平用未归一化 wav**。`load_wav_mono()` 会对轻音频做峰值归一化，
  用它判断「有没有人声」会把 -85 dBFS 的底噪看成 -5，所以这里直接读原始
  16k wav 采样算 RMS。
- **人声电平只在分离缓存已存在时给**。Demucs 很重，不能在一次 `cue` 查询里
  偷偷跑一遍；没有缓存就返回 `vocals_dbfs: null`，让用户先做分离。
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from core import audio_cache, audio_metrics, dual_review
from core.paths import ffmpeg_bin
from core.procutil import CommandTimeout, run_command

from .deps import get_session, media_path
from .security import require_token

router = APIRouter(tags=["evidence"], dependencies=[Depends(require_token)])


def _media_or_409(request: Request, session) -> tuple[str, float]:
    path = media_path(request, session)
    if not path:
        raise HTTPException(status_code=409, detail="还没有绑定媒体，先打开一部影片")
    if not Path(path).exists():
        raise HTTPException(status_code=409, detail=f"媒体文件已被移走：{path}")
    try:
        raw = audio_cache.ensure_wav(path, loudnorm=False)
    except Exception as exc:  # noqa: BLE001 - ffmpeg 的原始报错太长，给一句人话
        raise HTTPException(status_code=422, detail=f"取不到音频：{exc}") from exc
    duration = audio_metrics.wav_duration(raw)
    if duration <= 0:
        raise HTTPException(status_code=422, detail="媒体没有可解码的音轨")
    return path, duration


def _cue_or_404(cues, index: int):
    if index < 1 or index > len(cues):
        raise HTTPException(status_code=404, detail=f"第 {index} 句不存在（共 {len(cues)} 条）")
    return cues[index - 1]


def _vocals_path(media: str, duration: float) -> Path | None:
    candidate = audio_cache.vocals_wav_path(media, start=0.0, end=duration)
    if candidate.exists() and candidate.stat().st_size > 44:
        return candidate
    return None


def _items(request: Request, session, *, start: int, end: int) -> dict:
    media, duration = _media_or_409(request, session)
    cues = session.review_cues
    if not cues:
        raise HTTPException(status_code=409, detail="当前没有字幕")
    first = max(1, int(start))
    last = min(len(cues), int(end))
    if first > last:
        raise HTTPException(status_code=422, detail=f"范围不合法：第 {first}–{last} 条")

    raw = audio_cache.ensure_wav(media, loudnorm=False)
    vocals = _vocals_path(media, duration)
    items = []
    for position in range(first, last + 1):
        cue = cues[position - 1]
        items.append(
            {
                "i": position,
                "start": round(cue.start, 3),
                "end": round(cue.end, 3),
                "text": cue.text,
                "raw_dbfs": audio_metrics.segment_dbfs(raw, cue.start, cue.end),
                "vocals_dbfs": (
                    audio_metrics.segment_dbfs(vocals, cue.start, cue.end)
                    if vocals is not None
                    else None
                ),
            }
        )
    return {
        "from": first,
        "to": last,
        "total": len(cues),
        "vocals_cached": vocals is not None,
        "items": items,
    }


@router.get("/api/evidence/cues")
def evidence_cues(
    request: Request,
    start: int = Query(default=1, ge=1),
    end: int | None = Query(default=None, ge=1),
    session=Depends(get_session),
) -> dict:
    """批量电平证据；`end` 缺省 = 最后一条。"""
    total = len(session.review_cues)
    return _items(request, session, start=start, end=end or total)


@router.get("/api/evidence/cues/{index}")
def evidence_cue(
    index: int,
    request: Request,
    with_b: bool = Query(default=False, alias="with_b"),
    session=Depends(get_session),
) -> dict:
    """单句证据：电平 + 可选第二版对照文本。"""
    _cue_or_404(session.review_cues, index)
    payload = _items(request, session, start=index, end=index)
    item = payload["items"][0]
    item["vocals_cached"] = payload["vocals_cached"]
    b_text = None
    alt = session.alt_review
    if with_b and alt is not None and alt.cues:
        review = dual_review.build_review(session.review_cues, alt.cues)
        for row in review["rows"]:
            if (index - 1) in row.get("a_indices", []):
                b_text = {
                    "text": row.get("b_text") or "",
                    "kind": row.get("kind"),
                    "ratio": row.get("ratio"),
                }
                break
    item["b"] = b_text
    return item


def _frame_bytes(media: str, at: float) -> bytes:
    with tempfile.TemporaryDirectory(prefix="kikusub-evidence-") as tmp:
        out = Path(tmp) / "frame.jpg"
        cmd = [
            ffmpeg_bin(),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, at):.3f}",
            "-i",
            media,
            "-frames:v",
            "1",
            "-q:v",
            "3",
            "-y",
            str(out),
        ]
        try:
            result = run_command(cmd, timeout=45)
        except CommandTimeout as exc:
            raise HTTPException(status_code=504, detail="截帧超时") from exc
        if result.returncode != 0 or not out.exists():
            detail = (result.stderr or "").strip().splitlines()
            raise HTTPException(
                status_code=422,
                detail=f"截帧失败：{detail[-1] if detail else 'ffmpeg 没有产出图片'}",
            )
        return out.read_bytes()


@router.get("/api/evidence/cues/{index}/frame")
def evidence_frame(index: int, request: Request, session=Depends(get_session)) -> Response:
    """该句中点的一帧 JPEG（与界面里看到的是同一部片源）。"""
    media, _duration = _media_or_409(request, session)
    cue = _cue_or_404(session.review_cues, index)
    at = (float(cue.start) + float(cue.end)) / 2.0
    return Response(
        content=_frame_bytes(media, at),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


def _wav_slice(path: Path, start: float, end: float) -> bytes:
    import soundfile as sf

    try:
        with sf.SoundFile(str(path)) as handle:
            rate = int(handle.samplerate or 0)
            lo = max(0, int(round(start * rate)))
            hi = min(int(handle.frames), int(round(end * rate)))
            if hi <= lo:
                return b""
            handle.seek(lo)
            chunk = handle.read(hi - lo, dtype="float32", always_2d=True)
            samplerate = rate
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=f"读取音频失败：{exc}") from exc
    buffer = io.BytesIO()
    sf.write(buffer, chunk, samplerate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


@router.get("/api/evidence/cues/{index}/audio")
def evidence_audio(
    index: int,
    request: Request,
    track: str = Query(default="original", pattern="^(original|vocals)$"),
    session=Depends(get_session),
) -> Response:
    """该句的 wav 片段；`track=vocals` 只在分离缓存已存在时可用。"""
    media, duration = _media_or_409(request, session)
    cue = _cue_or_404(session.review_cues, index)
    if track == "vocals":
        vocals = _vocals_path(media, duration)
        if vocals is None:
            raise HTTPException(
                status_code=409,
                detail="这部片还没有分离人声缓存：先在核对台对这一段做一次人声分离",
            )
        data = _wav_slice(vocals, cue.start, cue.end)
    else:
        try:
            wav = audio_cache.ensure_wav(
                media, loudnorm=False, start=cue.start, end=cue.end
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=f"切片失败：{exc}") from exc
        data = Path(wav).read_bytes()
    if not data:
        raise HTTPException(status_code=422, detail="这段没有可导出的音频")
    return Response(
        content=data,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )
