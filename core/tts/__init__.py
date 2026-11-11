"""本地 TTS 子系统。

- :class:`~core.tts.manager.TTSManager`：对服务层唯一的入口；
- :class:`~core.tts.voice_manager.VoiceStore`：``outputs/voices/`` 的克隆音色管理；
- :mod:`core.tts.mac_say`：零显存兜底；
- :mod:`core.tts.clone_engine`：OmniVoice 零样本克隆（延迟导入 torch/omnivoice）。

服务层只 import 本包，不直接碰 torch。``KIKUSUB_TTS_ENGINE=off`` 可以整体关掉
（例如 CI 里不想加载任何 TTS 依赖）。
"""

from __future__ import annotations

from .base import (
    EngineUnavailable,
    TTSVoice,
    TTSError,
    VoiceConflict,
    VoiceInvalid,
    VoiceNotFound,
    clean_name,
    clean_text,
)
from .manager import TTSManager
from .voice_manager import VoiceStore

__all__ = [
    "EngineUnavailable",
    "TTSManager",
    "TTSError",
    "TTSVoice",
    "VoiceConflict",
    "VoiceInvalid",
    "VoiceNotFound",
    "VoiceStore",
    "clean_name",
    "clean_text",
]
