"""VAD 后端：Silero（20s 分窗，零额外权重）/ WhisperSeg（ONNX，30s 分窗）。

只保留经过同区间 A/B 验证的两个后端：

- ``silero``：旧默认。Silero 官方模型 + 20s 分窗，无需额外权重；
- ``whisperseg``：WhisperSeg JA-ASMR ONNX。负样本（BGM/环境音）误检 0%，
  同一区间 CER 更低、插入更少、端到端更快；首次使用要下 114MB 权重。

TEN-VAD 与 Silero 10s 窗的对照实现留在 ``tools/eval/``，不再进核心内核：
TEN 在 BGM 上把 85–98% 的非人声判成语音，Silero 10s 则用 +2.4pt CER 换召回，
两者都不该成为用户能选到的产品选项。

所有后端只产出 KikuSub 统一的 ``[{"start": 样本下标, "end": 样本下标}]``；
之后的 ``merge_vad_segments`` / ``extend_segment_onsets`` 完全同源。

设计约束：
- 不在 import 期加载任何模型；WhisperSeg 只在真正被选中时加载。
- Silero 路径与旧实现逐字节一致（分窗循环原样保留），只作为可选兼容。
- 缺失依赖/权重抛 ``VadBackendError``，由上层转成可读错误；下载失败不会静默
  改用另一个后端——那会让用户以为切分器已生效，也会让 A/B 数字归错因。
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import numpy as np

from . import model_fetch
from .paths import MODELS_DIR

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
VAD_WINDOW_S = 20.0
VAD_WINDOW_OVERLAP_S = 1.0
# 与 Silero 默认迟滞一致：退出阈值 = 进入阈值 - 0.15，且不低于 0.02。
VAD_NEG_THRESHOLD_FLOOR = 0.02

#: 分离人声作为 VAD 参考时的绝对能量门控（RMS dBFS）。
#:
#: 为什么需要：Demucs 的人声轨在纯音乐/环境音段并不是「绝对零」，WhisperSeg
#: 会把残响/串音判成语音；这些段送进 ASR 就变成「ちゅぅ…」这类幻觉字幕。
#: 2026-11-21 在 dpmx-014（2h48m）上标定：幻觉段 -76～-85 dBFS，真实对白
#: 中位数 -33.8 dBFS；-65 只丢 57/1101 段（128.5s），既覆盖明显静音幻觉，
#: 又不会碰到 -60.3 dBFS 的轻声句（-60 会误删 3 条）。
#: **只在有分离人声参考时启用**，原声 VAD 路径保持逐字节不变。
VOCAL_GATE_DBFS = -65.0

BACKENDS = ("silero", "whisperseg")
DEFAULT_BACKEND = "whisperseg"
ENV_BACKEND = "KIKUSUB_VAD_BACKEND"
ENV_WHISPERSEG_DIR = "KIKUSUB_WHISPERSEG_DIR"

WHISPERSEG_KEY = "whisperseg"
WHISPERSEG_LABEL = "WhisperSeg 切分器"
WHISPERSEG_REPO = "TransWithAI/Whisper-Vad-EncDec-ASMR-onnx"
WHISPERSEG_FEATURE_REPO = "openai/whisper-base"
WHISPERSEG_FILES = ("model.onnx", "preprocessor_config.json")
WHISPERSEG_APPROX_BYTES = 114 * 1024 * 1024

_WHISPERSEG_CHUNK_S = 30.0
_WHISPERSEG_FRAME_SAMPLES = 320  # 20ms @16k

_lock = threading.Lock()
_download_lock = threading.Lock()
_silero_model = None
_whisperseg_bundle = None


class VadBackendError(RuntimeError):
    """VAD 后端不可用（缺依赖、缺权重、加载失败）。"""


def vad_neg_threshold(threshold: float) -> float:
    """退出阈值：与 Silero 默认迟滞一致，但不低于下限。"""
    return max(float(threshold) - 0.15, VAD_NEG_THRESHOLD_FLOOR)


def resolve_backend(name: str | None = None) -> str:
    """解析后端名；显式参数优先于环境变量，非法值直接报错。

    ``auto`` 只为旧预设/旧环境变量保留：它等价于默认后端，不再是用户可选值。
    """
    raw = (name if name is not None else os.environ.get(ENV_BACKEND, "")).strip().lower()
    if not raw or raw == "auto":
        raw = (os.environ.get(ENV_BACKEND, "") or "").strip().lower()
        if not raw or raw == "auto":
            return DEFAULT_BACKEND
    aliases = {"silero20": "silero", "whisper_seg": "whisperseg"}
    raw = aliases.get(raw, raw)
    if raw not in BACKENDS:
        raise VadBackendError(
            f"未知 VAD 后端 {raw!r}；可选 {', '.join(BACKENDS)}"
        )
    return raw


def _load_silero():
    global _silero_model
    with _lock:
        if _silero_model is None:
            try:
                from silero_vad import load_silero_vad
            except Exception as exc:  # pragma: no cover - 依赖缺失
                raise VadBackendError(f"Silero VAD 不可用：{exc}") from exc
            _silero_model = load_silero_vad()
        return _silero_model


def _silero_detect(
    audio: np.ndarray,
    vad,
    *,
    threshold: float,
    min_speech_ms: int,
    min_silence_ms: int,
    speech_pad_ms: int,
    window_s: float,
    overlap_s: float,
) -> list[dict]:
    """Silero 分窗检测（原 transcribe.detect_speech_stamps 的实现）。"""
    from silero_vad import get_speech_timestamps
    import torch

    audio = np.asarray(audio)
    total = len(audio)
    if total == 0:
        return []
    vad = vad if vad is not None else _load_silero()

    kwargs = dict(
        sampling_rate=SAMPLE_RATE,
        threshold=float(threshold),
        min_speech_duration_ms=int(min_speech_ms),
        min_silence_duration_ms=int(min_silence_ms),
        speech_pad_ms=int(speech_pad_ms),
        neg_threshold=vad_neg_threshold(threshold),
    )

    window = max(1.0, float(window_s))
    hop = max(0.1, window - max(0.0, float(overlap_s)))
    total_s = total / SAMPLE_RATE
    if total_s <= window:
        return list(get_speech_timestamps(torch.from_numpy(audio), vad, **kwargs))

    stamps: list[dict] = []
    start_s = 0.0
    while start_s < total_s:
        end_s = min(total_s, start_s + window)
        a = int(round(start_s * SAMPLE_RATE))
        b = int(round(end_s * SAMPLE_RATE))
        chunk = audio[a:b]
        if chunk.size:
            offset = a
            for stamp in get_speech_timestamps(torch.from_numpy(chunk), vad, **kwargs):
                stamps.append(
                    {"start": int(stamp["start"]) + offset, "end": int(stamp["end"]) + offset}
                )
        if end_s >= total_s:
            break
        start_s += hop

    # 相邻窗口重叠 1s，同一段语音可能被检出两次：排序后做区间并集。
    stamps.sort(key=lambda s: s["start"])
    merged: list[dict] = []
    for stamp in stamps:
        if merged and stamp["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], stamp["end"])
        else:
            merged.append(dict(stamp))
    return merged


def gate_stamps_by_energy(
    stamps: list[dict],
    audio: np.ndarray,
    *,
    floor_dbfs: float,
    stats: dict | None = None,
) -> list[dict]:
    """按段内 RMS 能量丢弃「没有人声」的 VAD 段（dBFS 门控）。

    只用于**分离人声**做 VAD 参考的场景：Demucs 的 vocals 在纯音乐/环境音段
    仍有串音，WhisperSeg 会把它们判成语音；ASR 拿到这些段就会产生
    「ちゅぅ…」这类幻觉。门控在 VAD 之后、合并之前执行，所以不会改变
    原声路径，也不改任何 VAD 参数。

    判据用段内整体 RMS 而不是峰值：瞬态（关门、鼓点）会让峰值很高，但整段
    能量仍然接近静音；用 RMS 才能把「一声响」和「一段持续人声」分开。
    """
    data = np.asarray(audio, dtype=np.float32).reshape(-1)
    total = len(data)
    floor = float(floor_dbfs)
    kept: list[dict] = []
    dropped = 0
    dropped_s = 0.0
    kept_s = 0.0
    min_kept = float("inf")
    max_dropped = float("-inf")

    for stamp in stamps:
        start = max(0, int(stamp.get("start", 0)))
        end = min(total, int(stamp.get("end", 0)))
        if end <= start:
            continue
        chunk = data[start:end].astype(np.float64)
        rms = float(np.sqrt(np.mean(chunk * chunk)))
        dbfs = 20.0 * float(np.log10(max(rms, 1e-9)))
        duration = (end - start) / SAMPLE_RATE
        if dbfs < floor:
            dropped += 1
            dropped_s += duration
            max_dropped = max(max_dropped, dbfs)
            continue
        kept.append(stamp)
        kept_s += duration
        min_kept = min(min_kept, dbfs)

    if stats is not None:
        stats.update(
            {
                "floor_dbfs": round(floor, 1),
                "input": len(stamps),
                "kept": len(kept),
                "dropped": dropped,
                "kept_s": round(kept_s, 1),
                "dropped_s": round(dropped_s, 1),
                "min_kept_dbfs": round(min_kept, 1) if kept else None,
                "max_dropped_dbfs": round(max_dropped, 1) if dropped else None,
            }
        )
    if dropped:
        log.debug(
            "人声能量门控 | floor=%.1f dBFS | 丢弃 %d/%d 段 / %.1fs",
            floor,
            dropped,
            len(stamps),
            dropped_s,
        )
    return kept


def _frames_to_stamps(
    probs: np.ndarray,
    *,
    frame_samples: int,
    total_samples: int,
    threshold: float,
    min_speech_ms: int,
    min_silence_ms: int,
    speech_pad_ms: int,
) -> list[dict]:
    """把逐帧语音概率转成统一 stamps（Silero 风格的迟滞 + 最短时长 + 留白）。"""
    probs = np.asarray(probs, dtype=np.float32).reshape(-1)
    if probs.size == 0:
        return []
    frame_ms = frame_samples * 1000.0 / SAMPLE_RATE
    neg = vad_neg_threshold(threshold)
    min_speech_frames = max(1, int(round(min_speech_ms / frame_ms)))
    min_silence_frames = max(1, int(round(min_silence_ms / frame_ms)))

    speeches: list[tuple[int, int]] = []
    triggered = False
    start = 0
    temp_end = 0
    for i, prob in enumerate(probs):
        if prob >= threshold and not triggered:
            triggered = True
            start = i
            temp_end = 0
        elif triggered:
            if prob < neg:
                if not temp_end:
                    temp_end = i
                elif i - temp_end >= min_silence_frames:
                    end = temp_end
                    if end - start >= min_speech_frames:
                        speeches.append((start, end))
                    triggered = False
                    temp_end = 0
            elif prob >= threshold and temp_end:
                temp_end = 0
    if triggered:
        end = len(probs)
        if end - start >= min_speech_frames:
            speeches.append((start, end))

    pad = max(0, int(round(speech_pad_ms / frame_ms)))
    starts = [max(0, s - pad) for s, _ in speeches]
    ends = [min(len(probs), e + pad) for _, e in speeches]
    # 留白不得吃进相邻段：与 Silero 的 pad 语义一致。
    for i in range(1, len(starts)):
        starts[i] = max(starts[i], ends[i - 1])
    for i in range(len(ends) - 1):
        ends[i] = min(ends[i], starts[i + 1])

    out: list[dict] = []
    for s, e in zip(starts, ends):
        a = max(0, min(total_samples, s * frame_samples))
        b = max(0, min(total_samples, e * frame_samples))
        if b > a:
            out.append({"start": int(a), "end": int(b)})
    return out


# --------------------------------------------------------------------------- WhisperSeg 权重


def whisperseg_dir() -> Path:
    raw = (os.environ.get(ENV_WHISPERSEG_DIR) or "").strip()
    return Path(raw).expanduser() if raw else Path(MODELS_DIR) / WHISPERSEG_KEY


def _dir_bytes(directory: Path) -> int:
    total = 0
    try:
        for item in directory.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
    except OSError:
        return total
    return total


def whisperseg_ready(directory: Path | None = None) -> bool:
    target = Path(directory) if directory is not None else whisperseg_dir()
    return all((target / name).is_file() for name in WHISPERSEG_FILES)


def whisperseg_asset() -> dict:
    """设置页「引擎与模型」用的只读状态；不加载模型、不联网。"""
    directory = whisperseg_dir()
    ready = whisperseg_ready(directory)
    size = _dir_bytes(directory)
    return {
        "key": WHISPERSEG_KEY,
        "label": WHISPERSEG_LABEL,
        "description": "VAD 切分器：对 BGM/环境音几乎不误检，同一区间 CER 更低、转写更快。",
        "installed": ready,
        "model_dir": str(directory),
        "required_files": list(WHISPERSEG_FILES),
        "approx_bytes": WHISPERSEG_APPROX_BYTES,
        "size_bytes": size,
    }


def _report_progress(progress_cb, ratio: float, message: str) -> None:
    if progress_cb is None:
        return
    try:
        progress_cb(max(0.0, min(1.0, float(ratio))), message)
    except Exception:  # noqa: BLE001 - 进度回调失败不该打断下载
        log.debug("WhisperSeg 进度回调失败", exc_info=True)


def _download_whisperseg(progress_cb=None) -> None:
    """下载缺失的 WhisperSeg 权重；直连失败走 hf-mirror（由 model_fetch 统一）。"""
    directory = whisperseg_dir()
    directory.mkdir(parents=True, exist_ok=True)
    missing_model = not (directory / "model.onnx").is_file()
    missing_feature = not (directory / "preprocessor_config.json").is_file()
    _report_progress(progress_cb, 0.01, "正在准备 WhisperSeg 切分器权重（约 114MB）…")
    stop = threading.Event()

    def monitor() -> None:
        # HuggingFace 下载器不回调字节进度；靠目录增长估算，只报单调值。
        while not stop.wait(0.5):
            ratio = min(0.96, 0.02 + _dir_bytes(directory) / WHISPERSEG_APPROX_BYTES * 0.94)
            _report_progress(
                progress_cb,
                ratio,
                f"正在下载 WhisperSeg 切分器 {_dir_bytes(directory) / 1024**2:.0f} / "
                f"{WHISPERSEG_APPROX_BYTES / 1024**2:.0f} MB…",
            )

    watcher = threading.Thread(target=monitor, daemon=True, name="kikusub-whisperseg-dl")
    watcher.start()
    try:
        if missing_model:
            model_fetch.snapshot_download_files(
                repo_id=WHISPERSEG_REPO,
                dest=directory,
                allow_patterns=["model.onnx"],
                progress_cb=progress_cb,
                label="WhisperSeg 切分器",
            )
        if missing_feature:
            model_fetch.hf_hub_download_file(
                repo_id=WHISPERSEG_FEATURE_REPO,
                filename="preprocessor_config.json",
                dest=directory,
                progress_cb=progress_cb,
                label="WhisperSeg 特征配置",
            )
    except Exception as exc:  # noqa: BLE001 - 统一转成可读错误
        raise VadBackendError(
            f"WhisperSeg 权重下载失败：{exc}；请在「设置 → 引擎与模型」预下载，"
            f"或检查网络/代理。也可以把 model.onnx 与 preprocessor_config.json 手动放到 "
            f"{directory}，或用 KIKUSUB_WHISPERSEG_DIR 指向已有目录；"
            "在参数面板把切分器切回 Silero 20s 可先继续转写。"
        ) from exc
    finally:
        stop.set()
        watcher.join(timeout=1.0)
    if not whisperseg_ready(directory):
        raise VadBackendError(
            f"WhisperSeg 权重下载不完整：{directory}；"
            "需要 model.onnx 与 preprocessor_config.json"
        )
    _report_progress(progress_cb, 1.0, "WhisperSeg 切分器已就绪")


def ensure_whisperseg(progress_cb=None) -> dict:
    """确保权重就绪（供设置页预下载）；已就绪时立即返回，不联网。"""
    with _download_lock:
        if not whisperseg_ready():
            _download_whisperseg(progress_cb=progress_cb)
    return whisperseg_asset()


def _load_whisperseg(progress_cb=None):
    global _whisperseg_bundle
    with _lock:
        if _whisperseg_bundle is not None:
            return _whisperseg_bundle
        if not whisperseg_ready():
            with _download_lock:
                if not whisperseg_ready():
                    _download_whisperseg(progress_cb=progress_cb)
        model_dir = whisperseg_dir()
        if not whisperseg_ready(model_dir):
            raise VadBackendError(
                f"WhisperSeg 权重下载不完整：{model_dir}；"
                "需要 model.onnx 与 preprocessor_config.json"
            )
        try:
            import onnxruntime as ort
            from transformers import WhisperFeatureExtractor
        except Exception as exc:  # pragma: no cover - 依赖缺失
            raise VadBackendError(f"WhisperSeg 依赖不可用：{exc}") from exc

        feature_extractor = WhisperFeatureExtractor.from_pretrained(str(model_dir))
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        session = ort.InferenceSession(
            str(model_dir / "model.onnx"),
            providers=["CPUExecutionProvider"],
            sess_options=opts,
        )
        _whisperseg_bundle = (session, feature_extractor)
        return _whisperseg_bundle


def _whisperseg_detect(
    audio: np.ndarray,
    *,
    threshold: float,
    min_speech_ms: int,
    min_silence_ms: int,
    speech_pad_ms: int,
    progress_cb=None,
) -> list[dict]:
    session, feature_extractor = _load_whisperseg(progress_cb=progress_cb)
    audio = np.asarray(audio, dtype=np.float32)
    if audio.size == 0:
        return []
    chunk_samples = int(_WHISPERSEG_CHUNK_S * SAMPLE_RATE)
    wanted = int(np.ceil(len(audio) / _WHISPERSEG_FRAME_SAMPLES))
    probs: list[np.ndarray] = []
    for i in range(0, len(audio), chunk_samples):
        chunk = audio[i : i + chunk_samples]
        if len(chunk) < chunk_samples:
            chunk = np.pad(chunk, (0, chunk_samples - len(chunk)))
        features = feature_extractor(
            chunk, sampling_rate=SAMPLE_RATE, return_tensors="np"
        ).input_features.astype(np.float32)
        logits = session.run(None, {session.get_inputs()[0].name: features})[0][0]
        probs.append(1.0 / (1.0 + np.exp(-logits.astype(np.float32))))
    flat = np.concatenate(probs)[:wanted] if probs else np.zeros(0, dtype=np.float32)
    return _frames_to_stamps(
        flat,
        frame_samples=_WHISPERSEG_FRAME_SAMPLES,
        total_samples=len(audio),
        threshold=threshold,
        min_speech_ms=min_speech_ms,
        min_silence_ms=min_silence_ms,
        speech_pad_ms=speech_pad_ms,
    )


def detect_speech_stamps(
    audio: np.ndarray,
    vad=None,
    *,
    threshold: float,
    min_speech_ms: int,
    min_silence_ms: int,
    speech_pad_ms: int,
    window_s: float = VAD_WINDOW_S,
    overlap_s: float = VAD_WINDOW_OVERLAP_S,
    backend: str | None = None,
    progress_cb=None,
    fallback_backend: str | None = None,
    backend_stats: dict | None = None,
    energy_gate_dbfs: float | None = None,
    energy_gate_stats: dict | None = None,
) -> list[dict]:
    """按后端产出统一 stamps；默认路径与旧 Silero 实现完全一致。

    ``fallback_backend``：WhisperSeg 权重缺失且下载失败时，回退到该后端（产品侧传
    ``"silero"``）。回退会写进 ``backend_stats`` 并让上层在报告里显式说明，不是静默
    切换；不传则把 ``VadBackendError`` 原样抛给用户。
    """
    name = resolve_backend(backend)
    used = name
    reason = ""
    if name == "silero":
        stamps = _silero_detect(
            audio,
            vad,
            threshold=threshold,
            min_speech_ms=min_speech_ms,
            min_silence_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
            window_s=window_s,
            overlap_s=overlap_s,
        )
    else:
        try:
            stamps = _whisperseg_detect(
                audio,
                threshold=threshold,
                min_speech_ms=min_speech_ms,
                min_silence_ms=min_silence_ms,
                speech_pad_ms=speech_pad_ms,
                progress_cb=progress_cb,
            )
        except VadBackendError as exc:
            if not fallback_backend:
                raise
            used = resolve_backend(fallback_backend)
            reason = str(exc)
            log.warning("WhisperSeg 不可用，本次回退 %s：%s", used, exc)
            _report_progress(
                progress_cb, 0.5, f"WhisperSeg 不可用，已回退 {used} 20s 切分…"
            )
            stamps = _silero_detect(
                audio,
                vad,
                threshold=threshold,
                min_speech_ms=min_speech_ms,
                min_silence_ms=min_silence_ms,
                speech_pad_ms=speech_pad_ms,
                window_s=window_s,
                overlap_s=overlap_s,
            )
    if backend_stats is not None:
        backend_stats.update({
            "requested": name,
            "used": used,
            "fallback": used != name,
            "reason": reason,
        })
    if energy_gate_dbfs is not None:
        stamps = gate_stamps_by_energy(
            stamps,
            audio,
            floor_dbfs=float(energy_gate_dbfs),
            stats=energy_gate_stats,
        )
    return stamps
