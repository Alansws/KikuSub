"""OmniVoice 零样本克隆引擎（延迟加载 torch / omnivoice）。

选它的理由（相对 F5-TTS / CosyVoice / StyleTTS2）：

- 权重与推理代码都是 Apache-2.0，与项目的 MIT 兼容；不复制任何 AGPL 代码；
- 官方建议 **3–10 秒**参考音频，正好覆盖「从一句字幕切声线」；
- 600+ 语种里包含日语，且明确支持 Apple Silicon MPS；
- 0.6B 主干 + HiggsAudioV2 tokenizer，16GB 内存的 Mac 也放得下；
- ``create_voice_clone_prompt()`` 可以把声线编码缓存成 ~10KB 的 ``prompt.pt``，
  换句合成时不必每次重算参考音频。

失败策略：没装 ``omnivoice``、没下模型、MPS 不可用都只让**这个引擎**不可用，
``mac_say`` 兜底不受影响；界面会拿到可读的 503，而不是整页崩掉。
"""

from __future__ import annotations

import gc
import importlib.util
import logging
import os
import threading
from pathlib import Path

from core.paths import MODELS_DIR

from .base import EngineUnavailable, TTSVoice, TTSError, clean_text
from .voice_manager import VoiceStore

log = logging.getLogger(__name__)

REPO_ID = "k2-fsa/OmniVoice"
REQUIRED_FILES = (
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "audio_tokenizer/config.json",
    "audio_tokenizer/model.safetensors",
)
DEFAULT_STEPS = 32
MAX_TEXT_CHARS = 300


def default_model_dir() -> Path:
    raw = (os.environ.get("KIKUSUB_TTS_MODEL_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return MODELS_DIR / "omnivoice"


def missing_model_files(model_dir: Path | None = None) -> list[str]:
    """列出缺失 / 空文件的权重。

    「校验 / 补齐」必须比 ``is_file()`` 更严一点：中断的下载经常留下 0 字节
    文件，直接当成就绪会让用户点下载后也没有任何修复动作。
    """
    root = model_dir or default_model_dir()
    missing: list[str] = []
    for name in REQUIRED_FILES:
        target = root / name
        try:
            if not target.is_file() or target.stat().st_size <= 0:
                missing.append(name)
        except OSError:
            missing.append(name)
    return missing


def model_installed(model_dir: Path | None = None) -> bool:
    return not missing_model_files(model_dir)


def package_installed() -> bool:
    try:
        return importlib.util.find_spec("omnivoice") is not None
    except (ImportError, ValueError):
        return False


def _pick_device() -> str:
    requested = (os.environ.get("KIKUSUB_TTS_DEVICE") or "").strip().lower()
    if requested in {"cpu", "mps"}:
        return requested
    try:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
    except Exception:  # noqa: BLE001 —— 没装 torch 就按 CPU 处理
        pass
    return "cpu"


class OmniVoiceEngine:
    key = "omnivoice"
    label = "OmniVoice 克隆"

    def __init__(
        self,
        model_dir: Path | None = None,
        voices: VoiceStore | None = None,
        *,
        steps: int | None = None,
    ) -> None:
        self.model_dir = Path(model_dir or default_model_dir())
        self.voices = voices
        self.steps = int(
            steps or os.environ.get("KIKUSUB_TTS_STEPS") or DEFAULT_STEPS
        )
        self._lock = threading.RLock()
        self._model = None
        self._device = ""
        self._sampling_rate = 24000
        self._prompts: dict[str, object] = {}
        self.last_error = ""

    # -- 状态 ---------------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def device(self) -> str:
        return self._device or _pick_device()

    def model_installed(self) -> bool:
        return model_installed(self.model_dir)

    def available(self) -> bool:
        return package_installed() and self.model_installed()

    def status(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "repo": REPO_ID,
            "model_dir": str(self.model_dir),
            "approx_label": "约 3.3 GB",
            "min_ram_gb": 8.0,
            "downloadable": True,
            "package_installed": package_installed(),
            "installed": self.model_installed(),
            "loaded": self.loaded,
            "device": self.device,
            "steps": self.steps,
            "error": self.last_error,
        }

    # -- 生命周期 -----------------------------------------------------------

    def load(self, progress_cb=None) -> None:
        with self._lock:
            if self._model is not None:
                return
            if not package_installed():
                raise EngineUnavailable(
                    "没有安装 omnivoice 依赖；请在项目 venv 里执行 "
                    "`uv pip install omnivoice`（或重新安装 requirements.txt）",
                    code="package_missing",
                )
            if not self.model_installed():
                raise EngineUnavailable(
                    f"OmniVoice 模型还没下载（{self.model_dir}）。"
                    "在右侧 TTS 面板点「下载克隆模型」，或运行 "
                    "`hf download k2-fsa/OmniVoice --local-dir models/omnivoice`",
                    code="model_missing",
                )
            if progress_cb:
                progress_cb("正在加载 OmniVoice 权重…")
            import torch
            from omnivoice import OmniVoice

            device = _pick_device()
            kwargs: dict = {"device_map": device}
            # MPS 上 fp16 明显更快；CPU 用 fp32 避免算子不支持。
            kwargs["dtype"] = torch.float16 if device == "mps" else torch.float32
            try:
                model = OmniVoice.from_pretrained(str(self.model_dir), **kwargs)
            except Exception as exc:  # noqa: BLE001
                if device != "mps":
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    raise TTSError(f"加载 OmniVoice 失败：{exc}") from exc
                # MPS 出问题（旧系统 / 算子缺失）就退回 CPU；宁可慢，不能不可用。
                log.warning("MPS 加载 OmniVoice 失败，回退 CPU：%s", exc)
                kwargs = {"device_map": "cpu", "dtype": torch.float32}
                model = OmniVoice.from_pretrained(str(self.model_dir), **kwargs)
                device = "cpu"

            self._model = model
            self._device = device
            self._sampling_rate = int(getattr(model, "sampling_rate", 24000) or 24000)
            self._prompts.clear()
            self.last_error = ""
            log.info(
                "OmniVoice 已加载 | device=%s steps=%s model_dir=%s",
                device,
                self.steps,
                self.model_dir,
            )

    def unload(self) -> None:
        with self._lock:
            if self._model is None and not self._prompts:
                return
            self._prompts.clear()
            self._model = None
            gc.collect()
            try:
                import torch

                if torch.backends.mps.is_available():
                    torch.mps.empty_cache()
            except Exception:  # noqa: BLE001
                pass
            log.info("OmniVoice 已卸载，显存已释放")

    # -- 声线 prompt --------------------------------------------------------

    def _prompt_for(self, voice: TTSVoice):
        assert self.voices is not None and self._model is not None
        ref = self.voices.ref_path(voice.id)
        if not ref.is_file():
            raise TTSError(f"音色「{voice.name}」的参考音频丢失", status=404)
        cached = self._prompts.get(voice.id)
        if cached is not None:
            return cached

        prompt_file = self.voices.prompt_path(voice.id)
        # prompt.pt 只是缓存：模型升级/文件损坏都允许重建，不能让它挡住合成。
        if prompt_file.is_file() and prompt_file.stat().st_mtime >= ref.stat().st_mtime:
            try:
                from omnivoice import VoiceClonePrompt

                prompt = VoiceClonePrompt.load(str(prompt_file))
                self._prompts[voice.id] = prompt
                return prompt
            except Exception:  # noqa: BLE001
                log.warning("音色 prompt 读取失败，重建：%s", voice.id, exc_info=True)

        prompt = self._model.create_voice_clone_prompt(
            ref_audio=str(ref), ref_text=voice.ref_text or ""
        )
        try:
            prompt.save(str(prompt_file))
        except Exception:  # noqa: BLE001 —— 缓存写失败不影响合成
            log.debug("音色 prompt 缓存写入失败：%s", voice.id, exc_info=True)
        self._prompts[voice.id] = prompt
        return prompt

    def drop_prompt(self, voice_id: str) -> None:
        self._prompts.pop(voice_id, None)

    # -- 合成 ---------------------------------------------------------------

    def synthesize(self, text: str, voice: TTSVoice, speed: float, out_path: Path) -> None:
        spoken = clean_text(text, limit=MAX_TEXT_CHARS)
        if not spoken:
            raise TTSError("这句字幕没有可朗读的文本", status=422)
        speed = max(0.5, min(2.0, float(speed or 1.0)))
        with self._lock:
            self.load()
            assert self._model is not None
            prompt = self._prompt_for(voice)
            try:
                audio = self._model.generate(
                    text=spoken,
                    language="ja",
                    voice_clone_prompt=prompt,
                    speed=speed,
                    num_step=self.steps,
                )
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"
                raise TTSError(f"OmniVoice 合成失败：{exc}") from exc

            if not audio or len(audio[0]) == 0:
                raise TTSError("OmniVoice 没有生成音频")
            import soundfile as sf

            out_path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(out_path), audio[0], self._sampling_rate, subtype="PCM_16")
