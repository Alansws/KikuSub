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
    # 推理运行时族：whisper / qwen / sherpa。pipeline 与报告按它分派，
    # 新加同族引擎（例如再上一个 sherpa 模型）不用改分派代码。
    family: str = "whisper"
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
        family="whisper",
        required_files=("model.safetensors",),
    ),
    EngineSpec(
        key="qwen",
        label="Qwen3-ASR + CTC",
        short_label="Qwen3",
        description="Qwen3-ASR 日语微调权重 + CTC 对齐头，先识别文本，再用逐字发声时间对齐断句。",
        languages=("日语",),
        purpose="逐字对齐 · 精准时间轴",
        hf_repo="jaykwok/Qwen3-ASR-1.7B-JA-Anime-Galgame-hf",
        dir_name="qwen3-asr-ja-anime",
        env_var="QWEN3_ASR_MODEL",
        approx_bytes=int(3.8 * GiB),
        min_ram_gb=16.0,
        notes="内存建议 16 GB 以上；只覆盖“可能漏句”检查。",
        family="qwen",
        required_files=("config.json", "ctc_aligner_jav_vocalisation_v3.pt"),
    ),
    # ---- 中文（可选装）----
    # 两个引擎都走 sherpa-onnx（ONNX Runtime / CPU），不引入 torch 之外的新运行时；
    # 权重不随包分发，默认停用，用户在设置页自己启用并点「下载模型」。
    EngineSpec(
        key="sensevoice",
        label="SenseVoice-Small 中文",
        short_label="SenseVoice",
        description="阿里 FunAudioLLM 的轻量多语种模型（中/英/日/韩/粤），CPU 推理很快，自带 token 时间戳与标点归一化。",
        languages=("中文", "英语", "日语", "韩语", "粤语"),
        purpose="中文通稿 · 轻量快速",
        hf_repo="csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
        dir_name="sensevoice-small",
        env_var="KIKUSUB_SENSEVOICE_MODEL",
        approx_bytes=int(0.23 * GiB),
        min_ram_gb=4.0,
        notes="int8 权重约 230 MB；中文/中英混排首选，也覆盖日语与粤语。",
        family="sherpa",
        required_files=("model.int8.onnx", "tokens.txt"),
    ),
    EngineSpec(
        key="firered",
        label="FireRedASR2-AED 中文",
        short_label="FireRed",
        description="小红书 FireRedASR2 的注意力编解码模型：中文普通话 + 英语 + 20 多种方言，中文准确率高于轻量模型。",
        languages=("中文", "英语", "方言"),
        purpose="中文高精度 · 方言兼容",
        hf_repo="csukuangfj2/sherpa-onnx-fire-red-asr2-zh_en-int8-2026-02-26",
        dir_name="fireredasr2-aed",
        env_var="KIKUSUB_FIRERED_MODEL",
        approx_bytes=int(1.18 * GiB),
        min_ram_gb=8.0,
        notes="int8 权重约 1.2 GB。该模型不输出逐字时间戳，句内时间按字数比例分配（与 Anime Whisper 同口径）。",
        family="sherpa",
        required_files=("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt"),
    ),
)

KEYS: tuple[str, ...] = tuple(spec.key for spec in ENGINES)
# 默认只启用日语两个引擎：中文引擎是可选装件，避免新用户第一次打开就看到
# 四张「未下载」卡片。已经保存过 settings.json 的用户不受影响。
DEFAULT_ENABLED: tuple[str, ...] = ("whisper", "qwen")

_BY_KEY = {spec.key: spec for spec in ENGINES}


def get(key: str) -> EngineSpec:
    spec = _BY_KEY.get(key)
    if spec is None:
        raise KeyError(f"未知引擎：{key}")
    return spec


def spec_or_none(key: str) -> EngineSpec | None:
    return _BY_KEY.get(key)


def family_of(key: str) -> str:
    """引擎运行时的族名；未知 key 直接抛错（不要静默退回 whisper）。"""
    return get(key).family


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
        "family": spec.family,
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
