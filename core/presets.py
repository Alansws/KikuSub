"""命名参数预设的读写管理模块。

用于保存、加载、改名和删除参数预设。
对应数据文件：presets.json

**预设与引擎强绑定**（2026-11-14）：参数键本来就带引擎前缀（`qwen.*` /
`sensevoice.*`），把 Qwen 的预设套到 Whisper 上只会得到一份半生效的配置。
所以这里的规则是：

- 保存时必须给出合法引擎，落盘前用 `core.params.normalize()` 收敛成该引擎的
  完整参数快照（补默认值、丢掉别的引擎的键）；
- 读取时必须带上当前选中的引擎，引擎不一致直接拒绝（`PresetEngineMismatch`）；
- 同名预设不能跨引擎改写，避免「保存」把另一套引擎的方案静默覆盖。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from . import params
from .engines import KEYS as ENGINE_KEYS
from .paths import PRESETS_PATH

PRESET_PATH = PRESETS_PATH

SCHEMA_VERSION = 1
MAX_NAME_LENGTH = 40
INVALID_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f/\\]")


class PresetError(ValueError):
    """预设名不合法或操作失败异常。"""


class PresetNotFound(PresetError):
    """按名字找不到预设。"""


class PresetEngineMismatch(PresetError):
    """预设绑定的引擎与当前选中的引擎不一致。"""


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

    # 唯一来源是 `core/engines.py` 的注册表：加引擎不需要再改这里。
    ENGINE_KEYS = ENGINE_KEYS

    def __init__(self, path: Path = PRESET_PATH) -> None:
        self.path = Path(path)
        self._presets: dict[str, dict] = {}
        self.load_error: str = ""
        self.reload()

    @staticmethod
    def _infer_engine(values: dict) -> str | None:
        keys = [str(k) for k in values]
        present = {
            prefix
            for key in keys
            if "." in key
            for prefix in (key.split(".", 1)[0],)
        }
        matched = [engine for engine in PresetStore.ENGINE_KEYS if engine in present]
        return matched[0] if len(matched) == 1 else None

    @staticmethod
    def _normalize(entry: dict) -> dict | None:
        """兼容两种历史格式：`{"引擎", "参数"}` 与直接平铺参数的旧文件。"""
        if not isinstance(entry, dict):
            return None
        params_block = entry.get("参数")
        if params_block is None:
            params_block, engine = entry, None
        else:
            engine = entry.get("引擎")
            if engine not in PresetStore.ENGINE_KEYS:
                engine = None
        if not isinstance(params_block, dict):
            return None
        engine = engine or PresetStore._infer_engine(params_block)
        return {
            "引擎": engine if engine in PresetStore.ENGINE_KEYS else None,
            "参数": {str(k): v for k, v in params_block.items()},
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

    def list(self, engine: str | None = None) -> list[tuple[str, str | None]]:
        """列出预设；给了 `engine` 就只返回与该引擎绑定的那些。"""
        out = []
        for name in sorted(self._presets):
            entry = self.get(name)
            if entry is None:
                continue
            bound = entry.get("引擎")
            if engine is not None and bound != engine:
                continue
            out.append((name, bound))
        return out

    def get(self, name: str) -> dict | None:
        """按名字取预设；绑定引擎的预设会收敛成该引擎的完整参数。"""
        entry = self._normalize(self._presets.get(name))
        if entry is None:
            return None
        engine = entry.get("引擎")
        if engine:
            entry["参数"] = params.normalize(engine, entry["参数"])
        return entry

    def resolve(self, name: str, engine: str) -> dict:
        """取预设并校验引擎绑定；不匹配时抛 `PresetEngineMismatch`。"""
        if engine not in self.ENGINE_KEYS:
            raise PresetError(f"未知引擎「{engine}」，预设必须绑定在已注册的引擎上。")
        entry = self.get(name)
        if entry is None:
            raise PresetNotFound(f"未找到预设「{name}」。")
        bound = entry.get("引擎")
        if bound != engine:
            label = bound or "未绑定"
            raise PresetEngineMismatch(
                f"预设「{name}」属于「{label}」引擎，不能加载到「{engine}」上。"
                "请选择当前引擎自己的预设。"
            )
        return entry

    def save(self, raw_name: str, values: dict, engine: str | None = None) -> tuple[str, bool]:
        """保存预设；必须给引擎，值会被收敛成该引擎的完整参数快照。"""
        name = clean_name(raw_name)
        if engine not in self.ENGINE_KEYS:
            raise PresetError("预设必须绑定一个识别引擎；未指定引擎的预设不再允许保存。")
        if not isinstance(values, dict):
            raise PresetError("预设参数必须是键值对。")
        existing = self.get(name)
        if existing is not None and existing.get("引擎") and existing["引擎"] != engine:
            raise PresetEngineMismatch(
                f"预设「{name}」已绑定「{existing['引擎']}」引擎，不能保存成「{engine}」。"
                "请换一个名字，避免把另一套引擎的方案覆盖掉。"
            )
        created = name not in self._presets
        self._presets[name] = {"引擎": engine, "参数": params.normalize(engine, values)}
        self._flush()
        return name, created

    def rename(self, old_name: str, raw_name: str) -> tuple[str, bool]:
        old_name = clean_name(old_name)
        if old_name not in self._presets:
            raise PresetNotFound(f"未找到预设「{old_name}」。")
        new_name = clean_name(raw_name)
        if new_name == old_name:
            return new_name, False
        if new_name in self._presets:
            raise PresetError(f"已存在同名预设「{new_name}」。")
        self._presets[new_name] = self._presets.pop(old_name)
        self._flush()
        return new_name, False

    def delete(self, name: str) -> str:
        name = clean_name(name)
        if name not in self._presets:
            raise PresetNotFound(f"未找到预设「{name}」。")
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
