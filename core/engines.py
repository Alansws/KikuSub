"""引擎注册表（无 UI、无 torch 依赖）。

**新增引擎时只改这里 + `core/pipeline.py` 的引擎映射**，桌面端的「引擎配置页」
会自动多出一张卡片（语种、体积、启用开关、一键下载都由这张表驱动）。

为什么单独成文件：旧实现把引擎元信息散在 `server/app.py` 的 `/api/config`
里，只有 key/label/desc 三项，前端没法知道「装没装、多大、支持什么语种」。
现在安装检测只看文件名与目录，不 import torch，所以设置页可以秒开。
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .paths import MODELS_DIR

GiB = 1024**3


@dataclass(frozen=True, slots=True)
class EngineSpec:
    key: str
    label: str
    short_label: str
    description: str
    languages: tuple[str, ...]
    purpose: str
    hf_repo: str
    dir_name: str
    env_var: str
    approx_bytes: int
    min_ram_gb: float
    notes: str = ""
    downloadable: bool = True
    # 判断“装好了没”的必需文件；全部存在才算 installed。
    required_files: tuple[str, ...] = ()

    @property
    def approx_label(self) -> str:
        return f"约 {self.approx_bytes / GiB:.1f} GB"


ENGINES: tuple[EngineSpec, ...] = (
    EngineSpec(
        key="whisper",
        label="Anime Whisper",
        short_label="Whisper",
        description="面向日语动漫/影视语料微调的 Whisper，输出自然连贯的对话字幕，带 VAD 与智能句级分切。",
        languages=("日语",),
        purpose="对话通稿 · 自然断句",
        hf_repo="litagin/anime-whisper",
        dir_name="anime-whisper",
        env_var="ANIME_WHISPER_MODEL",
        approx_bytes=int(2.8 * GiB),
        min_ram_gb=6.0,
        notes="日常对话、长片通稿首选；会做幻觉门控与短句复核。",
        required_files=("model.safetensors",),
    ),
    EngineSpec(
        key="qwen",
        label="Qwen3-ASR + CTC",
        short_label="Qwen3",
        description="Qwen3-ASR 日语微调权重 + CTC 对齐头，先识别文本再用逐字发声时间做动态规划断句。",
        languages=("日语",),
        purpose="逐字对齐 · 精准时间轴",
        hf_repo="jaykwok/Qwen3-ASR-1.7B-JA-Anime-Galgame-hf",
        dir_name="qwen3-asr-ja-anime",
        env_var="QWEN3_ASR_MODEL",
        approx_bytes=int(3.8 * GiB),
        min_ram_gb=16.0,
        notes="需要 transformers >= 5.13；内存建议 16 GB 以上。只覆盖“可能漏句”检查。",
        required_files=("config.json", "ctc_aligner_jav_vocalisation_v3.pt"),
    ),
)

KEYS: tuple[str, ...] = tuple(spec.key for spec in ENGINES)
DEFAULT_ENABLED: tuple[str, ...] = KEYS

_BY_KEY = {spec.key: spec for spec in ENGINES}


def get(key: str) -> EngineSpec:
    spec = _BY_KEY.get(key)
    if spec is None:
        raise KeyError(f"未知引擎：{key}")
    return spec


def spec_or_none(key: str) -> EngineSpec | None:
    return _BY_KEY.get(key)


def model_dir(spec: EngineSpec) -> Path:
    env = (os.environ.get(spec.env_var) or "").strip()
    return Path(env).expanduser() if env else MODELS_DIR / spec.dir_name


def _qwen_weights_present(directory: Path) -> bool:
    index = directory / "model.safetensors.index.json"
    if index.exists():
        try:
            import json

            payload = json.loads(index.read_text(encoding="utf-8"))
            shards = {str(v) for v in (payload.get("weight_map") or {}).values()}
        except (OSError, ValueError):
            return False
        return bool(shards) and all((directory / shard).is_file() for shard in shards)
    return (directory / "model.safetensors").is_file() or any(
        directory.glob("*.safetensors")
    )


def is_installed(spec: EngineSpec) -> bool:
    directory = model_dir(spec)
    if not directory.is_dir():
        return False
    if not all((directory / name).is_file() for name in spec.required_files):
        return False
    if spec.key == "qwen":
        return _qwen_weights_present(directory)
    return True


_size_cache: dict[str, tuple[float, int]] = {}
_size_lock = threading.Lock()


def dir_size(directory: Path, *, ttl_s: float = 5.0) -> int:
    """目录占用（字节）。4 GB 模型有上千文件，做 5 秒缓存，设置页刷新不卡。"""
    key = str(directory)
    now = time.monotonic()
    with _size_lock:
        hit = _size_cache.get(key)
        if hit and now - hit[0] < ttl_s:
            return hit[1]
    total = 0
    if directory.is_dir():
        for path in directory.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
    with _size_lock:
        _size_cache[key] = (now, total)
    return total


def status(spec: EngineSpec, *, enabled: bool | None = None, include_size: bool = True) -> dict:
    directory = model_dir(spec)
    installed = is_installed(spec)
    size = dir_size(directory) if (installed and include_size) else 0
    return {
        "key": spec.key,
        "label": spec.label,
        "short_label": spec.short_label,
        "description": spec.description,
        "languages": list(spec.languages),
        "purpose": spec.purpose,
        "hf_repo": spec.hf_repo,
        "model_dir": str(directory),
        "approx_bytes": spec.approx_bytes,
        "approx_label": spec.approx_label,
        "min_ram_gb": spec.min_ram_gb,
        "notes": spec.notes,
        "downloadable": spec.downloadable,
        "installed": installed,
        "size_bytes": size,
        "enabled": True if enabled is None else bool(enabled),
    }


def describe(
    *,
    enabled_keys: list[str] | tuple[str, ...] | None = None,
    include_size: bool = True,
) -> list[dict]:
    enabled = set(DEFAULT_ENABLED if enabled_keys is None else enabled_keys)
    return [
        status(spec, enabled=spec.key in enabled, include_size=include_size)
        for spec in ENGINES
    ]


def ensure_model(key: str, progress_cb=None, cancel_event=None) -> None:
    """下载（或补齐）某个引擎的权重。

    这里才 import `core.pipeline`——它会拉起 torch，设置页的普通状态查询
    不该付这 7 秒。`ensure_model` 对两个引擎都是幂等的。
    """
    from .pipeline import resolve_engine

    engine = resolve_engine(key)
    ensure = getattr(engine, "ensure_model", None)
    if ensure is None:
        raise RuntimeError(f"引擎 {key} 没有提供自动下载入口")
    ensure(progress_cb=progress_cb)
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("模型下载已取消")
