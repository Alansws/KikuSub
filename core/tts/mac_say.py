"""macOS ``say`` 兜底引擎：零显存、零下载、永远可用。

从旧 ``server/routes_tts.py`` 原样搬过来的行为：

- 只列 ``say -v ?`` 里的日语 voice；
- 按「文本 + voice + rate」哈希缓存在服务层，这里只负责真正生成 WAV；
- 命令走 ``procutil.run_command`` 的 argv 列表，不经过 shell。

它现在只是 :class:`core.tts.manager.TTSManager` 里的一个引擎；保留它是为了在
OmniVoice 模型没下载、MPS 不可用、或者只想秒出一句时仍能「零显存」朗读。
"""

from __future__ import annotations

import logging
import re
import shutil
import sys
import threading
import time
from pathlib import Path

from core.procutil import CommandTimeout, run_command, tail

from .base import TTSVoice, TTSError, clean_text

log = logging.getLogger(__name__)

DEFAULT_RATE = 175
RATE_MIN = 100
RATE_MAX = 260
_VOICE_TTL_S = 60.0
_VOICE_LINE_RE = re.compile(
    r"^(?P<name>.+?)\s{2,}(?P<locale>[A-Za-z]{2}_[A-Za-z]{2})\s+#\s*(?P<sample>.*)$"
)


def _say_bin() -> str | None:
    if sys.platform != "darwin":
        return None
    for candidate in ("/usr/bin/say", shutil.which("say") or ""):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _parse_voices(output: str) -> list[dict]:
    """解析 ``say -v ?``。只留日语 voice；名字里本身带空格和括号。"""
    voices: list[dict] = []
    for raw in output.splitlines():
        line = raw.strip()
        found = _VOICE_LINE_RE.match(line)
        if not found:
            continue
        locale = found.group("locale")
        if not locale.lower().startswith("ja"):
            continue
        voices.append(
            {
                "name": found.group("name").strip(),
                "locale": locale,
                "sample": found.group("sample").strip(),
            }
        )
    return voices


class MacSayEngine:
    key = "mac_say"
    label = "macOS 系统语音"

    def __init__(self) -> None:
        self._bin = _say_bin()
        self._lock = threading.Lock()
        self._voices: tuple[float, list[dict]] | None = None

    @property
    def platform_ok(self) -> bool:
        return bool(self._bin)

    @property
    def bin(self) -> str | None:
        return self._bin

    def _list_raw(self) -> list[dict]:
        if not self._bin:
            return []
        now = time.monotonic()
        with self._lock:
            if self._voices is not None and now - self._voices[0] < _VOICE_TTL_S:
                return self._voices[1]
        raw: list[dict] = []
        try:
            proc = run_command([self._bin, "-v", "?"], timeout=8)
            if proc.returncode == 0:
                raw = _parse_voices(proc.stdout)
        except (CommandTimeout, OSError):
            log.warning("读取本机语音列表失败", exc_info=True)
        with self._lock:
            self._voices = (now, raw)
        return raw

    def list_voices(self) -> list[TTSVoice]:
        return [
            TTSVoice(
                id=f"system:{item['name']}",
                name=item["name"],
                engine=self.key,
                kind="system",
                locale=item["locale"],
                sample=item["sample"],
            )
            for item in self._list_raw()
        ]

    def default_voice_name(self) -> str:
        names = [voice.name for voice in self.list_voices()]
        if "Kyoko" in names:
            return "Kyoko"
        return names[0] if names else ""

    def available(self) -> bool:
        return bool(self._bin) and bool(self._list_raw())

    def synthesize(self, text: str, voice: TTSVoice, speed: float, out_path: Path) -> None:
        if not self._bin:
            raise TTSError(
                "本机语音朗读仅支持 macOS（未找到 say 命令）", code="platform", status=503
            )
        raw = self._list_raw()
        if not raw:
            raise TTSError(
                "系统里没有可用的日语语音，请先在「系统设置 → 辅助功能 → 朗读内容」下载日语语音",
                code="no_voice",
                status=503,
            )
        names = {item["name"] for item in raw}
        if voice.name not in names:
            raise TTSError(f"本机没有这个日语语音：{voice.name}", status=422)

        rate = max(RATE_MIN, min(RATE_MAX, int(round(DEFAULT_RATE * float(speed)))))
        spoken = clean_text(text, limit=600)
        if not spoken:
            raise TTSError("这句字幕没有可朗读的文本", status=422)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            proc = run_command(
                [
                    self._bin,
                    "-v",
                    voice.name,
                    "--file-format=WAVE",
                    "--data-format=LEI16@22050",
                    "-r",
                    str(rate),
                    "-o",
                    str(out_path),
                    "--",
                    spoken,
                ],
                timeout=30,
            )
        except CommandTimeout as exc:
            raise TTSError("本机语音生成超时", status=504) from exc
        except OSError as exc:
            raise TTSError(f"启动 say 失败：{exc}") from exc

        if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size <= 44:
            detail = tail(proc.stderr or proc.stdout) or "say 没有生成音频"
            log.warning("TTS 生成失败 | voice=%s rate=%s | %s", voice.name, rate, detail)
            raise TTSError(f"本机语音生成失败：{detail}", status=502)

    def unload(self) -> None:
        return None
