"""TTS 管理器：音色列表、缓存、懒加载/空闲卸载、切片建音色的唯一入口。

服务层只跟这个类打交道。它把三个关注点收在一处：

- **路由**：``voice_id``（``system:Kyoko`` / ``clone:ab12cd34``）决定用哪个引擎；
- **缓存**：按「引擎 + 音色指纹 + 文本 + 速度」哈希，命中直接返回文件名；
- **资源**：克隆模型第一次真正合成时才加载，空闲 5 分钟卸载，转写/导出启动时
  由 ``release()`` 主动让路（见 ``server/jobs.py`` 的 ``on_heavy_job``）。
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import threading
import time
from pathlib import Path

from .base import (
    EngineUnavailable,
    TTSVoice,
    TTSError,
    VoiceNotFound,
    clean_text,
)
from .clone_engine import MAX_TEXT_CHARS, OmniVoiceEngine, default_model_dir
from .mac_say import MacSayEngine
from .model_store import ModelDownloader
from .voice_manager import VoiceStore

log = logging.getLogger(__name__)

DEFAULT_IDLE_SECONDS = 300.0
CACHE_LIMIT = 240
CACHE_NAME_RE_FMT = r"^[0-9a-f]{24}\.wav$"


def _ref_fingerprint(ref: Path) -> str:
    try:
        stat = ref.stat()
        return f"{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return "missing"


class TTSManager:
    def __init__(
        self,
        output_dir: Path | str,
        *,
        model_dir: Path | str | None = None,
        idle_seconds: float | None = None,
    ) -> None:
        self.output_dir = Path(output_dir).expanduser()
        self.cache_dir = self.output_dir / "tts_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.voices = VoiceStore(self.output_dir / "voices")
        self.say = MacSayEngine()
        self.clone = OmniVoiceEngine(
            Path(model_dir) if model_dir else default_model_dir(), self.voices
        )
        self.downloader = ModelDownloader(self.clone.model_dir)
        self._cache_lock = threading.Lock()
        self._synth_lock = threading.Lock()
        # 连点不同句子时，排队中的旧请求在轮到它时直接作废：前端本来就会丢掉
        # 过期结果，这里再省掉一次 5–10 秒的无意义推理。
        self._synth_epoch = 0
        self._stop = threading.Event()
        self._idle_thread: threading.Thread | None = None
        self._last_used = 0.0
        raw_idle = idle_seconds
        if raw_idle is None:
            try:
                raw_idle = float(os.environ.get("KIKUSUB_TTS_IDLE_SECONDS") or DEFAULT_IDLE_SECONDS)
            except ValueError:
                raw_idle = DEFAULT_IDLE_SECONDS
        self.idle_seconds = max(30.0, float(raw_idle))

    # -- 生命周期 -----------------------------------------------------------

    def close(self) -> None:
        self._stop.set()
        self.clone.unload()

    def verify_model(self) -> dict:
        """只读校验 OmniVoice 权重；用于设置页「校验 / 补齐」不弹下载确认。"""
        return {
            **self.downloader.verify(),
            "package_installed": self.clone.status()["package_installed"],
        }

    def _ensure_idle_thread(self) -> None:
        if self._idle_thread is not None and self._idle_thread.is_alive():
            return
        self._idle_thread = threading.Thread(
            target=self._idle_loop, name="kikusub-tts-idle", daemon=True
        )
        self._idle_thread.start()

    def _idle_loop(self) -> None:
        while not self._stop.wait(15.0):
            if not self.clone.loaded:
                return
            idle_for = time.monotonic() - self._last_used
            if idle_for >= self.idle_seconds:
                self.release(reason=f"空闲 {int(idle_for)}s")
                return

    def release(self, reason: str = "") -> None:
        """主动卸载克隆模型（转写/导出前调用；也用于空闲回收）。"""
        if not self.clone.loaded:
            return
        log.info("释放 TTS 模型 | %s", reason or "manual")
        self.clone.unload()

    # -- 音色 ---------------------------------------------------------------

    def _system_voices(self) -> list[TTSVoice]:
        return self.say.list_voices()

    def _custom_voices(self) -> list[TTSVoice]:
        return self.voices.list()

    def default_voice_id(self) -> str:
        """默认永远是系统语音（Kyoko 等），克隆音色必须由用户主动选择。

        为什么不「有克隆音色就优先克隆」：OmniVoice 要加载 3GB 权重、首次合成
        10 秒级；系统语音是零显存、秒出。用户没明确选克隆时，默认不该悄悄变慢。
        只有完全拿不到系统语音（非 macOS）时才回退到已有克隆音色。
        """
        name = self.say.default_voice_name()
        if name:
            return f"system:{name}"
        custom = self._custom_voices()
        if custom and self.clone.available():
            return custom[0].id
        return ""

    def _find_system(self, name: str) -> TTSVoice | None:
        for voice in self._system_voices():
            if voice.name == name:
                return voice
        return None

    def resolve_voice(self, voice_id: str = "") -> TTSVoice:
        raw = (voice_id or "").strip()
        if not raw:
            raw = self.default_voice_id()
        if not raw:
            raise EngineUnavailable("本机没有可用音色", code="no_voice")
        if raw.startswith("clone:"):
            return self.voices.get(raw)
        if raw.startswith("system:"):
            name = raw[len("system:") :]
            voice = self._find_system(name)
            if voice is None:
                raise VoiceNotFound(f"本机没有这个日语语音：{name}")
            return voice
        # 兼容旧接口 / 旧 localStorage：裸 voice 名按系统音色处理。
        voice = self._find_system(raw)
        if voice is None:
            raise VoiceNotFound(f"未知音色：{raw}")
        return voice

    def list_voices(self) -> dict:
        system = self._system_voices()
        custom = self._custom_voices()
        engine = self.clone.status()
        engine["download"] = self.downloader.status()
        engine["max_chars"] = MAX_TEXT_CHARS
        default = self.default_voice_id()
        default_name = ""
        if default:
            try:
                default_name = self.resolve_voice(default).name
            except TTSError:
                default_name = ""
        return {
            "available": bool(system) or (bool(custom) and self.clone.available()),
            "platform": sys.platform,
            "max_chars": MAX_TEXT_CHARS,
            "say_max_chars": 600,
            "default": default,
            "default_name": default_name,
            "voices_dir": str(self.voices.root),
            "system": [voice.to_dict() for voice in system],
            "custom": [voice.to_dict() for voice in custom],
            # 旧字段：老前端/旧测试仍按 voices + default(名称) 读，保留一版。
            "voices": [voice.to_dict() for voice in system],
            "speeds": [0.8, 1.0, 1.2],
            "engine": engine,
            "say": {
                "available": bool(system),
                "default": self.say.default_voice_name(),
                "platform": sys.platform,
            },
        }

    # -- 合成 ---------------------------------------------------------------

    def _cache_key(self, engine: str, voice: TTSVoice, text: str, speed: float) -> str:
        if voice.is_clone:
            ref = _ref_fingerprint(self.voices.ref_path(voice.id))
            tag = f"{ref}|{voice.ref_text}"
        else:
            tag = voice.name
        payload = f"{engine}\0{voice.id}\0{tag}\0{speed:.3f}\0{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:24]

    def _prune(self) -> None:
        with self._cache_lock:
            try:
                files = sorted(
                    self.cache_dir.glob("*.wav"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
            except OSError:
                return
            for old in files[CACHE_LIMIT:]:
                try:
                    old.unlink()
                except OSError:
                    pass

    def synthesize(self, text: str, voice_id: str = "", speed: float = 1.0) -> dict:
        voice = self.resolve_voice(voice_id)
        engine = self.clone if voice.is_clone else self.say
        limit = MAX_TEXT_CHARS if voice.is_clone else 600
        spoken = clean_text(text, limit=limit)
        if not spoken:
            raise TTSError("这句字幕没有可朗读的文本", status=422)
        speed = max(0.5, min(2.0, float(speed or 1.0)))

        if voice.is_clone and not self.clone.available():
            raise EngineUnavailable(
                "克隆模型还没就绪：先下载 OmniVoice（约 3.3GB），"
                "或改用「系统语音」零显存朗读",
                code="clone_unavailable",
            )

        digest = self._cache_key(engine.key, voice, spoken, speed)
        target = self.cache_dir / f"{digest}.wav"
        if target.exists() and target.stat().st_size > 44:
            return self._result(target, voice, cached=True, elapsed=0.0)

        started = time.perf_counter()
        self._synth_epoch += 1
        epoch = self._synth_epoch
        # 同一时间只跑一个合成：OmniVoice 不是线程安全的，say 也没必要并行；
        # 缓存双检在锁内做，两个请求同时点同一句不会各生成一遍。
        with self._synth_lock:
            if target.exists() and target.stat().st_size > 44:
                return self._result(target, voice, cached=True, elapsed=0.0)
            if epoch != self._synth_epoch:
                raise TTSError(
                    "已经被更新的朗读请求取代", code="superseded", status=409
                )
            temp = self.cache_dir / (
                f".{digest}.{os.getpid()}.{time.time_ns()}.wav"
            )
            try:
                engine.synthesize(spoken, voice, speed, temp)
                os.replace(temp, target)
            finally:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass
            self._last_used = time.monotonic()
            if voice.is_clone:
                self._ensure_idle_thread()
            self._prune()

        elapsed = time.perf_counter() - started
        log.info(
            "TTS 合成 | engine=%s voice=%s chars=%s speed=%.2f %.1fs",
            engine.key,
            voice.name,
            len(spoken),
            speed,
            elapsed,
        )
        return self._result(target, voice, cached=False, elapsed=elapsed)

    def _result(self, path: Path, voice: TTSVoice, *, cached: bool, elapsed: float) -> dict:
        duration = 0.0
        try:
            import soundfile as sf

            info = sf.info(str(path))
            if info.samplerate:
                duration = float(info.frames) / float(info.samplerate)
        except Exception:  # noqa: BLE001
            pass
        return {
            "filename": path.name,
            "voice_id": voice.id,
            "voice_name": voice.name,
            "engine": voice.engine,
            "cached": cached,
            "duration": round(duration, 3),
            "elapsed": round(elapsed, 3),
        }

    # -- 音色管理 -----------------------------------------------------------

    def extract_voice_from_media(
        self,
        media_path: Path | str,
        *,
        start: float,
        end: float,
        name: str,
        ref_text: str = "",
        pad: float = 0.2,
        source: dict | None = None,
    ) -> dict:
        voice = self.voices.create_from_media(
            Path(media_path),
            start=start,
            end=end,
            name=name,
            ref_text=ref_text,
            pad=pad,
            source=source,
        )
        self.clone.drop_prompt(voice.id)
        return voice.to_dict()

    def create_voice_from_file(
        self, path: Path | str, *, name: str, ref_text: str = ""
    ) -> dict:
        voice = self.voices.create_from_file(Path(path), name=name, ref_text=ref_text)
        self.clone.drop_prompt(voice.id)
        return voice.to_dict()

    def rename_voice(self, voice_id: str, name: str) -> dict:
        return self.voices.rename(voice_id, name).to_dict()

    def delete_voice(self, voice_id: str) -> None:
        self.voices.delete(voice_id)
        self.clone.drop_prompt(voice_id)

    def update_voice_ref_text(self, voice_id: str, ref_text: str) -> dict:
        voice = self.voices.update_ref_text(voice_id, ref_text)
        self.clone.drop_prompt(voice_id)
        return voice.to_dict()

    def status(self) -> dict:
        engine = self.clone.status()
        engine["download"] = self.downloader.status()
        return engine
