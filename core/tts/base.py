"""TTS 引擎抽象：音色描述、合成接口与错误类型。

这个模块**不 import torch / omnivoice / fastapi**，服务层和单测都可以随意导入。
真正重量级的推理依赖只在具体引擎的 ``load()`` 里延迟导入，保证：

- 服务启动时不会因为装了 OmniVoice 就多付几秒 import 成本；
- 没装克隆模型时，``mac_say`` 兜底照常可用；
- ``tests/test_core_boundary.py`` 的边界约束不被破坏。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class TTSError(RuntimeError):
    """TTS 的可预期失败（无可用引擎、文本太长、模型没装…）。

    ``status`` 让服务层直接翻译成 HTTP 状态码，前端不必猜。
    """

    status = 502
    code = "tts_error"

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None):
        super().__init__(message)
        if code:
            self.code = code
        if status:
            self.status = status


class EngineUnavailable(TTSError):
    """引擎不可用（没装依赖 / 没下载模型 / 平台不支持）。"""

    status = 503
    code = "engine_unavailable"


class VoiceNotFound(TTSError):
    status = 404
    code = "voice_not_found"


class VoiceInvalid(TTSError):
    status = 422
    code = "voice_invalid"


class VoiceConflict(TTSError):
    status = 409
    code = "voice_conflict"


CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

MAX_NAME_CHARS = 40
MAX_TEXT_CHARS = 300
MAX_SAY_TEXT_CHARS = 600


def clean_text(raw: str, *, limit: int = MAX_TEXT_CHARS) -> str:
    """去掉控制字符、保留换行（朗读时换行当停顿），并校验长度。"""
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = "".join(ch for ch in text if ch >= " " or ch in "\n\t")
    text = text.strip()
    if len(text) > limit:
        raise TTSError(
            f"文本太长（{len(text)} 字），最多 {limit} 字", code="text_too_long", status=422
        )
    return text


def clean_name(raw: str) -> str:
    """音色名：去控制字符、折叠空白、限制长度，禁止路径分隔符。"""
    name = CONTROL_CHARS_RE.sub("", str(raw or ""))
    name = re.sub(r"\s+", " ", name).strip()
    for ch in ("/", "\\", ":", "\0"):
        name = name.replace(ch, "")
    name = name.strip(" .")
    if not name:
        raise VoiceInvalid("音色名不能为空")
    if len(name) > MAX_NAME_CHARS:
        name = name[:MAX_NAME_CHARS].strip()
    return name


@dataclass(frozen=True, slots=True)
class TTSVoice:
    """一个可选音色。

    - ``kind='system'``：macOS ``say`` 的本机语音，``id='system:Kyoko'``；
    - ``kind='clone'``：用户从视频切片 / 上传参考音频得到的克隆音色，
      ``id='clone:<8位id>'``，参考音频与元数据存放在 ``outputs/voices/<id>/``。
    """

    id: str
    name: str
    engine: str
    kind: str
    locale: str = "ja"
    sample: str = ""
    duration: float = 0.0
    ref_text: str = ""
    created_at: float = 0.0
    source: dict = field(default_factory=dict)

    @property
    def is_clone(self) -> bool:
        return self.kind == "clone"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "engine": self.engine,
            "kind": self.kind,
            "locale": self.locale,
            "sample": self.sample,
            "duration": round(float(self.duration or 0.0), 3),
            "ref_text": self.ref_text,
            "created_at": self.created_at,
            "source": dict(self.source or {}),
        }


class TTSEngine(Protocol):
    """合成引擎的最小契约。

    ``synthesize`` 必须把 WAV 写到 ``out_path``，失败抛 :class:`TTSError`。
    实现方自己负责串行化（模型不是线程安全的），管理器只保证同一缓存键只算一次。
    """

    key: str
    label: str

    def available(self) -> bool: ...

    def synthesize(self, text: str, voice: TTSVoice, speed: float, out_path: Path) -> None: ...

    def unload(self) -> None: ...
