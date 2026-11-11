"""克隆音色仓库：``outputs/voices/`` 的扫描、切片、命名与增删改。

目录布局（一个音色一个目录，重命名只改元数据、不搬文件）::

    outputs/voices/
      a1b2c3d4/
        ref.wav      # 24 kHz / mono / PCM16，已去首尾静音，≤10s
        meta.json    # 名称、参考文本、时长、来源（cue / upload）
        prompt.pt    # OmniVoice 的声线 embedding 缓存（可选，坏了自动重建）

设计上刻意**不**按音色名建目录：用户会重命名、会用中文/空格/emoji，拿名字当路径
迟早出问题；``id`` 才是稳定主键。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
import time
from pathlib import Path

from core.procutil import CommandTimeout, run_command, tail
from core.textio import write_text_atomic

from .base import (
    TTSVoice,
    VoiceConflict,
    VoiceInvalid,
    VoiceNotFound,
    clean_name,
)

log = logging.getLogger(__name__)

VOICE_ID_PREFIX = "clone:"
REF_SAMPLE_RATE = 24000
MAX_REF_SECONDS = 10.0
MIN_REF_SECONDS = 0.8
# 切片/上传后允许的最长输入；超过就先截到 10s，避免一个 3 分钟的音频把
# prompt 编码拖到几十秒。
MAX_INPUT_SECONDS = 30.0
FFMPEG_TIMEOUT_S = 120.0

AUDIO_SUFFIXES = {
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
    ".aiff",
    ".aif",
    ".wma",
}


def _new_id() -> str:
    return secrets.token_hex(4)


def _meta_path(directory: Path) -> Path:
    return directory / "meta.json"


def _read_meta(directory: Path) -> dict | None:
    try:
        payload = json.loads(_meta_path(directory).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or not payload.get("name"):
        return None
    return payload


def _atomic_json(path: Path, payload: dict) -> None:
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _trim_silence(path: Path, *, max_seconds: float = MAX_REF_SECONDS) -> float:
    """去掉首尾静音，并把超过 ``max_seconds`` 的参考音频截短。

    为什么不是简单 ``ffmpeg silenceremove``：我们需要的是"保住说话区间、掐掉
    空白"，而不是把句中的自然停顿也剪掉。这里按 20ms 帧算 RMS，找第一个/最后一个
    超过阈值的帧，前后各留 80ms。
    """
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if data.size == 0 or sr <= 0:
        raise VoiceInvalid("参考音频是空的")
    mono = data.mean(axis=1)
    frame = max(1, int(sr * 0.02))
    frames = mono[: (len(mono) // frame) * frame].reshape(-1, frame)
    if len(frames) == 0:
        raise VoiceInvalid("参考音频太短")
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    peak = float(rms.max())
    threshold = max(0.004, peak * 0.06)
    active = np.flatnonzero(rms > threshold)
    if len(active) == 0:
        raise VoiceInvalid("参考音频里没有检测到清晰人声")
    first = max(0, int(active[0] * frame - sr * 0.08))
    last = min(len(mono), int((active[-1] + 1) * frame + sr * 0.08))
    clipped = mono[first:last]
    limit = int(max_seconds * sr)
    if len(clipped) > limit:
        clipped = clipped[:limit]
    duration = len(clipped) / float(sr)
    if duration < MIN_REF_SECONDS:
        raise VoiceInvalid(
            f"参考音频太短（{duration:.1f}s），至少需要 {MIN_REF_SECONDS:.1f}s 的有效人声"
        )
    sf.write(str(path), clipped, sr, subtype="PCM_16")
    return float(duration)


def _normalize_audio(source: Path, target: Path, *, start: float | None, end: float | None) -> float:
    """用 ffmpeg 把任意音视频转成 24k 单声道 WAV，再裁静音。

    ``start`` / ``end`` 给定时从媒体里精确切片（``-ss`` 放在 ``-i`` 前面 +
    重编码，ffmpeg 的 accurate_seek 会解到目标帧）；不给就是整段转换（上传）。
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    if start is not None:
        cmd += ["-ss", f"{max(0.0, float(start)):.3f}"]
    if start is not None and end is not None:
        cmd += ["-t", f"{max(0.1, float(end) - float(start)):.3f}"]
    cmd += ["-i", str(source)]
    # 上传整段音频时只解前 30 秒：参考音色最多用 10 秒，没必要把 5 分钟伴奏全解一遍。
    if start is None:
        cmd += ["-t", f"{MAX_INPUT_SECONDS:.0f}"]
    cmd += [
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(REF_SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        "-f",
        "wav",
        str(target),
    ]
    try:
        proc = run_command(cmd, timeout=FFMPEG_TIMEOUT_S)
    except FileNotFoundError as exc:
        raise VoiceInvalid("找不到 ffmpeg，请先安装（brew install ffmpeg）") from exc
    except CommandTimeout as exc:
        raise VoiceInvalid("从媒体提取音频超时") from exc
    if proc.returncode != 0 or not target.exists() or target.stat().st_size <= 44:
        detail = tail(proc.stderr or proc.stdout) or "ffmpeg 没有输出音频"
        raise VoiceInvalid(f"提取参考音频失败：{detail}")
    return _trim_silence(target)


class VoiceStore:
    """``outputs/voices/`` 的读写入口。线程安全由调用方（TTSManager）保证。"""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser()

    # -- 读 -----------------------------------------------------------------

    def _dirs(self) -> list[Path]:
        try:
            return sorted(
                (path for path in self.root.iterdir() if path.is_dir()),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return []

    def list(self) -> list[TTSVoice]:
        voices: list[TTSVoice] = []
        for directory in self._dirs():
            meta = _read_meta(directory)
            if meta is None:
                continue
            ref = directory / "ref.wav"
            if not ref.exists():
                continue
            voices.append(self._to_voice(directory.name, meta))
        voices.sort(key=lambda voice: voice.created_at, reverse=True)
        return voices

    def _to_voice(self, voice_id: str, meta: dict) -> TTSVoice:
        return TTSVoice(
            id=f"{VOICE_ID_PREFIX}{voice_id}",
            name=str(meta.get("name") or voice_id),
            engine=str(meta.get("engine") or "omnivoice"),
            kind="clone",
            locale=str(meta.get("language") or "ja"),
            duration=float(meta.get("duration") or 0.0),
            ref_text=str(meta.get("ref_text") or ""),
            created_at=float(meta.get("created_at") or 0.0),
            source=dict(meta.get("source") or {}),
        )

    def _directory(self, voice_id: str) -> Path:
        bare = voice_id[len(VOICE_ID_PREFIX) :] if voice_id.startswith(VOICE_ID_PREFIX) else voice_id
        if (
            not bare
            or bare in {".", ".."}
            or bare.startswith(".")
            or any(ch in bare for ch in ("/", "\\", ".."))
        ):
            raise VoiceNotFound("音色不存在")
        directory = self.root / bare
        if not directory.is_dir():
            raise VoiceNotFound("音色不存在")
        return directory

    def get(self, voice_id: str) -> TTSVoice:
        directory = self._directory(voice_id)
        meta = _read_meta(directory)
        if meta is None:
            raise VoiceNotFound("音色元数据缺失")
        return self._to_voice(directory.name, meta)

    def ref_path(self, voice_id: str) -> Path:
        return self._directory(voice_id) / "ref.wav"

    def prompt_path(self, voice_id: str) -> Path:
        return self._directory(voice_id) / "prompt.pt"

    # -- 写 -----------------------------------------------------------------

    def _unique_name(self, wanted: str, *, exclude: str = "") -> str:
        names = {voice.name for voice in self.list() if voice.id != exclude}
        if wanted not in names:
            return wanted
        index = 2
        while f"{wanted} {index}" in names:
            index += 1
        return f"{wanted} {index}"

    def _create_from_temp(
        self,
        temp_wav: Path,
        *,
        name: str,
        ref_text: str,
        duration: float,
        source: dict,
    ) -> TTSVoice:
        self.root.mkdir(parents=True, exist_ok=True)
        voice_id = _new_id()
        while (self.root / voice_id).exists():
            voice_id = _new_id()
        directory = self.root / voice_id
        directory.mkdir(parents=True)
        ref = directory / "ref.wav"
        os.replace(temp_wav, ref)
        meta = {
            "version": 1,
            "id": voice_id,
            "name": self._unique_name(clean_name(name)),
            "engine": "omnivoice",
            "language": "ja",
            "ref_text": str(ref_text or "").strip()[:500],
            "duration": round(float(duration), 3),
            "created_at": time.time(),
            "source": dict(source or {}),
        }
        _atomic_json(_meta_path(directory), meta)
        log.info(
            "新建克隆音色 | id=%s name=%s duration=%.1fs source=%s",
            voice_id,
            meta["name"],
            float(duration),
            meta["source"].get("kind", "?"),
        )
        return self._to_voice(voice_id, meta)

    def create_from_media(
        self,
        media_path: Path,
        *,
        start: float,
        end: float,
        name: str,
        ref_text: str = "",
        pad: float = 0.2,
        source: dict | None = None,
    ) -> TTSVoice:
        """从视频/音频的指定区间切出纯净参考音频，保存成一个克隆音色。"""
        media = Path(media_path)
        if not media.is_file():
            raise VoiceInvalid(f"媒体文件不存在：{media}")
        start = max(0.0, float(start))
        end = float(end)
        if end <= start:
            raise VoiceInvalid("切片的起止时间不合法")
        # 前后各留一点上下文：句首的「あ」/句尾的促音经常贴在边界上。
        pad = max(0.0, min(0.5, float(pad)))
        slice_start = max(0.0, start - pad)
        slice_end = min(end + pad, start + MAX_INPUT_SECONDS)
        if slice_end - slice_start > MAX_INPUT_SECONDS:
            slice_end = slice_start + MAX_INPUT_SECONDS

        with tempfile.TemporaryDirectory(prefix="kikusub-voice-") as tmp:
            target = Path(tmp) / "ref.wav"
            duration = _normalize_audio(
                media, target, start=slice_start, end=slice_end
            )
            return self._create_from_temp(
                target,
                name=name,
                ref_text=ref_text,
                duration=duration,
                source={
                    "kind": "cue",
                    "media": str(media),
                    "start": round(start, 3),
                    "end": round(end, 3),
                    **(source or {}),
                },
            )

    def create_from_file(
        self,
        path: Path,
        *,
        name: str,
        ref_text: str = "",
        source: dict | None = None,
    ) -> TTSVoice:
        """从用户上传的音频文件建立音色（格式交给 ffmpeg 统一转换）。"""
        source_path = Path(path)
        if not source_path.is_file():
            raise VoiceInvalid(f"参考音频不存在：{source_path}")
        if source_path.suffix.lower() not in AUDIO_SUFFIXES:
            raise VoiceInvalid(
                "只支持音频文件：" + "、".join(sorted(suffix.lstrip(".") for suffix in AUDIO_SUFFIXES))
            )
        try:
            if source_path.stat().st_size > 200 * 1024 * 1024:
                raise VoiceInvalid("参考音频太大（上限 200MB）")
        except OSError as exc:
            raise VoiceInvalid(f"读取参考音频失败：{exc}") from exc

        with tempfile.TemporaryDirectory(prefix="kikusub-voice-") as tmp:
            target = Path(tmp) / "ref.wav"
            duration = _normalize_audio(source_path, target, start=None, end=None)
            return self._create_from_temp(
                target,
                name=name,
                ref_text=ref_text,
                duration=duration,
                source={"kind": "upload", "path": str(source_path), **(source or {})},
            )

    def rename(self, voice_id: str, name: str) -> TTSVoice:
        directory = self._directory(voice_id)
        meta = _read_meta(directory)
        if meta is None:
            raise VoiceNotFound("音色元数据缺失")
        clean = clean_name(name)
        if clean != meta.get("name"):
            taken = {voice.name for voice in self.list() if voice.id != voice_id}
            if clean in taken:
                raise VoiceConflict(f"已经有叫「{clean}」的音色了")
            meta["name"] = clean
            _atomic_json(_meta_path(directory), meta)
        return self._to_voice(directory.name, meta)

    def update_ref_text(self, voice_id: str, ref_text: str) -> TTSVoice:
        directory = self._directory(voice_id)
        meta = _read_meta(directory)
        if meta is None:
            raise VoiceNotFound("音色元数据缺失")
        meta["ref_text"] = str(ref_text or "").strip()[:500]
        _atomic_json(_meta_path(directory), meta)
        self.clear_prompt(voice_id)
        return self._to_voice(directory.name, meta)

    def delete(self, voice_id: str) -> None:
        directory = self._directory(voice_id)
        for child in directory.iterdir():
            try:
                child.unlink()
            except OSError:
                log.warning("删除音色文件失败：%s", child, exc_info=True)
        try:
            directory.rmdir()
        except OSError as exc:
            raise VoiceInvalid(f"删除音色失败：{exc}") from exc
        log.info("删除克隆音色 | id=%s", voice_id)

    def clear_prompt(self, voice_id: str) -> None:
        try:
            self.prompt_path(voice_id).unlink(missing_ok=True)
        except OSError:
            pass
