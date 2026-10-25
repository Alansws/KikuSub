"""命名参数预设的读写管理模块。

用于保存、加载、改名和删除参数预设。
对应数据文件：presets.json
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

PRESET_PATH = Path(__file__).resolve().parent / "presets.json"

SCHEMA_VERSION = 1
MAX_NAME_LENGTH = 40
INVALID_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f/\\]")


class PresetError(ValueError):
    """预设名不合法或操作失败异常。"""


def clean_name(raw: str | None) -> str:
    """规范化预设名；空名或含非法字符时抛出 PresetError。"""
    name = (raw or "").strip()
    if not name:
        raise PresetError("请填写预设名称。")
    if len(name) > MAX_NAME_LENGTH:
        raise PresetError(f"预设名称最多支持 {MAX_NAME_LENGTH} 个字符。")
    if INVALID_NAME_CHARS.search(name):
        raise PresetError("预设名称不能包含换行、制表符、斜杠或反斜杠。")
    return name


class PresetStore:
    """参数预设持久化存储类。"""

    ENGINE_KEYS = ("whisper", "qwen")

    def __init__(self, path: Path = PRESET_PATH) -> None:
        self.path = Path(path)
        self._presets: dict[str, dict] = {}
        self.load_error: str = ""
        self.reload()

    @staticmethod
    def _infer_engine(values: dict) -> str | None:
        keys = [str(k) for k in values]
        has_whisper = any(k.startswith("whisper.") for k in keys)
        has_qwen = any(k.startswith("qwen.") for k in keys)
        if has_whisper and has_qwen:
            return None
        if has_qwen:
            return "qwen"
        if has_whisper:
            return "whisper"
        return None

    @staticmethod
    def _normalize(entry: dict) -> dict | None:
        if not isinstance(entry, dict):
            return None
        params = entry.get("参数")
        if params is None:
            params, engine = entry, None
        else:
            engine = entry.get("引擎")
            if engine not in PresetStore.ENGINE_KEYS:
                engine = None
        if not isinstance(params, dict):
            return None
        engine = engine or PresetStore._infer_engine(params)
        return {
            "引擎": engine if engine in PresetStore.ENGINE_KEYS else None,
            "参数": {str(k): v for k, v in params.items()},
        }

    def reload(self) -> None:
        self._presets = {}
        self.load_error = ""
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.load_error = f"读取预设文件失败：{exc}"
            return
        if not isinstance(raw, dict) or not isinstance(raw.get("预设"), dict):
            self.load_error = "预设文件格式不正确。"
            return
        for name, entry in raw["预设"].items():
            if not isinstance(name, str):
                continue
            normalized = self._normalize(entry)
            if normalized is not None:
                self._presets[name] = normalized

    def names(self) -> list[str]:
        return list(self._presets)

    def list(self) -> list[tuple[str, str | None]]:
        out = []
        for name in sorted(self._presets):
            entry = self._normalize(self._presets[name])
            out.append((name, entry["引擎"] if entry else None))
        return out

    def get(self, name: str) -> dict | None:
        return self._normalize(self._presets.get(name))

    def save(self, raw_name: str, values: dict, engine: str | None = None) -> tuple[str, bool]:
        name = clean_name(raw_name)
        created = name not in self._presets
        self._presets[name] = {"引擎": engine, "参数": dict(values)}
        self._flush()
        return name, created

    def rename(self, old_name: str, raw_name: str) -> tuple[str, bool]:
        old_name = clean_name(old_name)
        if old_name not in self._presets:
            raise PresetError(f"未找到预设「{old_name}」。")
        new_name = clean_name(raw_name)
        values = self._presets.pop(old_name)
        if new_name in self._presets:
            self._presets[new_name] = values
            self._flush()
            return new_name, True
        self._presets[new_name] = values
        self._flush()
        return new_name, False

    def delete(self, name: str) -> str:
        name = clean_name(name)
        if name not in self._presets:
            raise PresetError(f"未找到预设「{name}」。")
        del self._presets[name]
        self._flush()
        return name

    def _flush(self) -> None:
        payload = {
            "版本": SCHEMA_VERSION,
            "预设": {name: self._presets[name] for name in sorted(self._presets)},
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".presets-", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp_name, self.path)
        except OSError:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
