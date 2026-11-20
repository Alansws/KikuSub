"""VAD 后端抽象：Silero（现状）/ TEN-VAD / WhisperSeg。

A/B 阶段只通过 ``KIKUSUB_VAD_BACKEND`` 切换，不写进参数表、不进设置页：

- ``silero``（默认，20s 窗）
- ``silero10``（同一模型，10s 窗；零依赖的召回上限对照）
- ``ten``（ten-vad，1.2MB wheel + 745KB dylib）
- ``whisperseg``（WhisperSeg JA-ASMR ONNX，30s 窗 + 20ms 帧）

所有后端只负责产出 KikuSub 统一的 ``[{"start": 样本下标, "end": 样本下标}]``；
之后的 ``merge_vad_segments`` / ``extend_segment_onsets`` 完全同源，这样 A/B
比较的是 VAD 本身，而不是后处理。

设计约束：
- 不在 import 期加载任何模型；TEN/WhisperSeg 只在真正被选中时加载。
- 默认后端与旧实现逐字节一致（Silero 分窗循环原样保留）。
- 任何缺失依赖/权重都抛 ``VadBackendError``，由上层转成可读错误，不能静默回退
  ——静默回退会让 A/B 数字归错因。
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import numpy as np

from .paths import MODELS_DIR

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
VAD_WINDOW_S = 20.0
VAD_WINDOW_OVERLAP_S = 1.0
# 与 Silero 默认迟滞一致：退出阈值 = 进入阈值 - 0.15，且不低于 0.02。
VAD_NEG_THRESHOLD_FLOOR = 0.02

BACKENDS = ("silero", "silero10", "ten", "whisperseg")
DEFAULT_BACKEND = "silero"
ENV_BACKEND = "KIKUSUB_VAD_BACKEND"
ENV_WHISPERSEG_DIR = "KIKUSUB_WHISPERSEG_DIR"

_WHISPERSEG_CHUNK_S = 30.0
_WHISPERSEG_FRAME_SAMPLES = 320  # 20ms @16k
_TEN_HOP = 256  # 16ms @16k

_lock = threading.Lock()
_silero_model = None
_whisperseg_bundle = None


class VadBackendError(RuntimeError):
    """VAD 后端不可用（缺依赖、缺权重、加载失败）。"""


def vad_neg_threshold(threshold: float) -> float:
    """退出阈值：与 Silero 默认迟滞一致，但不低于下限。"""
    return max(float(threshold) - 0.15, VAD_NEG_THRESHOLD_FLOOR)


def resolve_backend(name: str | None = None) -> str:
    """解析后端名；显式参数优先于环境变量，非法值直接报错。"""
    raw = (name if name is not None else os.environ.get(ENV_BACKEND, "")).strip().lower()
    if not raw or raw == "auto":
        raw = (os.environ.get(ENV_BACKEND, "") or "").strip().lower()
        if not raw or raw == "auto":
            return DEFAULT_BACKEND
    aliases = {"silero20": "silero", "whisper_seg": "whisperseg", "ten-vad": "ten"}
    raw = aliases.get(raw, raw)
    if raw not in BACKENDS:
        raise VadBackendError(
            f"未知 VAD 后端 {raw!r}；可选 {', '.join(BACKENDS)}（环境变量 {ENV_BACKEND}）"
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



def _flag_runs_to_stamps(
    flags: np.ndarray,
    *,
    frame_samples: int,
    total_samples: int,
    min_speech_ms: int,
    min_silence_ms: int,
    speech_pad_ms: int,
) -> list[dict]:
    """把逐帧 0/1 判决转成 stamps。

    TEN-VAD 自己已经在 C 层做了迟滞，输出 flag 就是最终判决；再套一层
    「prob < threshold-0.15 才关闭」会把长段音乐/底噪连成整片——实测 0.35 阈值
    下语音占比会从 40% 虚涨到 94%。这里只做最短语音、最短静音与留白。
    """
    flags = np.asarray(flags, dtype=bool).reshape(-1)
    if flags.size == 0:
        return []
    frame_ms = frame_samples * 1000.0 / SAMPLE_RATE
    min_speech_frames = max(1, int(round(min_speech_ms / frame_ms)))
    min_silence_frames = max(1, int(round(min_silence_ms / frame_ms)))

    runs: list[list[int]] = []
    start = None
    for i, on in enumerate(flags):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append([start, i])
            start = None
    if start is not None:
        runs.append([start, len(flags)])

    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] < min_silence_frames:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    merged = [r for r in merged if r[1] - r[0] >= min_speech_frames]

    pad = max(0, int(round(speech_pad_ms / frame_ms)))
    starts = [max(0, s - pad) for s, _ in merged]
    ends = [min(len(flags), e + pad) for _, e in merged]
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

def _ten_detect(
    audio: np.ndarray,
    *,
    threshold: float,
    min_speech_ms: int,
    min_silence_ms: int,
    speech_pad_ms: int,
) -> list[dict]:
    try:
        import importlib

        TenVad = importlib.import_module("ten_vad").TenVad
    except Exception as exc:  # pragma: no cover - 依赖缺失
        raise VadBackendError(
            "TEN-VAD 不可用：需要 ten-vad（uv pip install ten-vad），"
            "打包时还要 collect-data 并签名 dylib"
        ) from exc

    audio = np.asarray(audio, dtype=np.float32)
    if audio.size == 0:
        return []
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    n = (len(pcm) // _TEN_HOP) * _TEN_HOP
    if n <= 0:
        return []
    vad = TenVad(hop_size=_TEN_HOP, threshold=float(threshold))
    flags = np.empty(n // _TEN_HOP, dtype=bool)
    for idx, i in enumerate(range(0, n, _TEN_HOP)):
        _prob, flag = vad.process(pcm[i : i + _TEN_HOP])
        flags[idx] = bool(flag)
    return _flag_runs_to_stamps(
        flags,
        frame_samples=_TEN_HOP,
        total_samples=len(audio),
        min_speech_ms=min_speech_ms,
        min_silence_ms=min_silence_ms,
        speech_pad_ms=speech_pad_ms,
    )


def _whisperseg_dir() -> Path:
    raw = (os.environ.get(ENV_WHISPERSEG_DIR) or "").strip()
    return Path(raw).expanduser() if raw else Path(MODELS_DIR) / "whisperseg"


def _download_whisperseg(model_dir: Path, *, need_model: bool, need_feature: bool) -> None:
    """首次选择 WhisperSeg 时按需下载；失败转成可读错误，不静默回退。"""
    model_dir.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import hf_hub_download, snapshot_download

        if need_model:
            log.info("正在下载 WhisperSeg 权重（约 114MB）到 %s", model_dir)
            snapshot_download(
                repo_id="TransWithAI/Whisper-Vad-EncDec-ASMR-onnx",
                local_dir=str(model_dir),
                allow_patterns=["model.onnx"],
                max_workers=2,
            )
        if need_feature:
            hf_hub_download(
                repo_id="openai/whisper-base",
                filename="preprocessor_config.json",
                local_dir=str(model_dir),
            )
    except Exception as exc:
        raise VadBackendError(
            f"WhisperSeg 权重下载失败：{exc}；"
            "请检查网络/代理，或手动把 model.onnx 与 preprocessor_config.json "
            f"放到 {model_dir}（也可用 KIKUSUB_WHISPERSEG_DIR 指向已有目录）"
        ) from exc


def _load_whisperseg():
    global _whisperseg_bundle
    with _lock:
        if _whisperseg_bundle is not None:
            return _whisperseg_bundle
        model_dir = _whisperseg_dir()
        model_path = model_dir / "model.onnx"
        feature_path = model_dir / "preprocessor_config.json"
        if not model_path.is_file() or not feature_path.is_file():
            _download_whisperseg(model_dir, need_model=not model_path.is_file(),
                                 need_feature=not feature_path.is_file())
        if not model_path.is_file() or not feature_path.is_file():
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
            str(model_path), providers=["CPUExecutionProvider"], sess_options=opts
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
) -> list[dict]:
    session, feature_extractor = _load_whisperseg()
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
) -> list[dict]:
    """按后端产出统一 stamps；默认路径与旧 Silero 实现完全一致。"""
    name = resolve_backend(backend)
    if name == "silero10":
        return _silero_detect(
            audio,
            vad,
            threshold=threshold,
            min_speech_ms=min_speech_ms,
            min_silence_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
            window_s=10.0,
            overlap_s=overlap_s,
        )
    if name == "silero":
        return _silero_detect(
            audio,
            vad,
            threshold=threshold,
            min_speech_ms=min_speech_ms,
            min_silence_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
            window_s=window_s,
            overlap_s=overlap_s,
        )
    if name == "ten":
        return _ten_detect(
            audio,
            threshold=threshold,
            min_speech_ms=min_speech_ms,
            min_silence_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )
    return _whisperseg_detect(
        audio,
        threshold=threshold,
        min_speech_ms=min_speech_ms,
        min_silence_ms=min_silence_ms,
        speech_pad_ms=speech_pad_ms,
    )
