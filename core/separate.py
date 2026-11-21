"""Demucs htdemucs 人声分离（只服务「强 BGM / 歌曲」区间）。

设计边界（2026-11-15 与用户确认的极简版）：

- **只处理调用方给的区间**：`separate_to_wav(..., start, end)` 先 ffmpeg 截取，
  再分离；绝不为了转写整片而先分离整部影片。
- **单次分离的峰值内存只跟分段长度走，不跟总时长走**：`apply_model` 会一次性
  物化「4 轨 × 2 声道 × 全长」的输出，30 分钟就要 ~2.5GB、2 小时 ~10GB。
  所以超过 :data:`CHUNK_S` 的区间按段分离、段间交叉淡化（见 :func:`plan_chunks`），
  长片不会再因为内存被拒；长度上限只剩「用户愿不愿意等」。
- **权重落在 KikuSub 受管的 `models/demucs/`**：`TORCH_HOME` 指向这里，
  不走 `~/.cache/torch`；权重按需下载（约 80MB），不打进 `.app`。
- **分离完立刻卸载**：`separate_to_wav` 的 `finally` 一定调用 :func:`release`，
  清掉模型引用并回收 MPS 缓存，避免 Demucs 与 Whisper/Qwen 同时常驻。
- 缓存与原子写在 `core.audio_cache.ensure_vocals_wav`；这里只负责「把一段
  音频变成 vocals wav」。

PyInstaller 打包时由 `tools/pack/build_sidecar.sh` 的 `--collect-all demucs`
带上 `demucs/remote/*.yaml` 与 `files.txt`；模型权重不随包。
"""

from __future__ import annotations

import gc
import hashlib
import logging
import os
import shutil
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np

from .paths import MODELS_DIR, ffmpeg_bin
from .procutil import run_command, tail

log = logging.getLogger(__name__)

MODEL_NAME = "htdemucs"
MODEL_URL = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th"
# torch.hub 的 HASH_REGEX 取文件名里 '-' 之后的前 8 位；这个文件的实际 sha256
# 以 8726e21a 开头（文件名前半段 955717e8 是模型签名，不是哈希）。
MODEL_SHA_PREFIX = "8726e21a"
MODEL_FILENAME = "955717e8-8726e21a.th"
SAMPLE_RATE = 44100
MIN_MODEL_BYTES = 50_000_000
# 单段核心长度：demucs 的 apply_model 在 split=True 时先把整段音频的 4 轨输出
# 一次分配出来（4 × 2 × 时长 × 4 字节），所以峰值内存与「这一段多长」成正比。
# 15 分钟 ≈ 1.3GB 输出张量，16GB 机器上给 ASR 留够余量；总时长不再设上限。
CHUNK_S = 15 * 60
# 相邻两段的重叠长度：两段各自分离后线性交叉淡化，避免拼接处出现相位跳变。
CROSSFADE_S = 1.0

MODEL_DIR = MODELS_DIR / "demucs"
TORCH_DIR = MODEL_DIR / "torch"
CHECKPOINT = TORCH_DIR / "hub" / "checkpoints" / MODEL_FILENAME

_MODEL = None
_MODEL_DEVICE = ""
_MODEL_LOCK = threading.Lock()


# --------------------------------------------------------------------------- 模型


def available() -> bool:
    """依赖是否就绪。

    走真实 import 而不是 find_spec：PyInstaller 冻结包里 `find_spec` 对
    `--collect-all demucs` 收进来的子模块不一定可见，而 pipeline 触发到这里时
    torch 已经因为 core.transcribe 加载过，再 import demucs 只多几十毫秒。
    """
    try:
        import demucs  # noqa: F401

        return True
    except Exception:
        return False


def model_ready() -> bool:
    try:
        return CHECKPOINT.exists() and CHECKPOINT.stat().st_size >= MIN_MODEL_BYTES
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_checkpoint(path: Path) -> None:
    actual = _sha256(path)
    if not actual.startswith(MODEL_SHA_PREFIX):
        try:
            path.unlink()
        except OSError:
            pass
        raise RuntimeError(
            "Demucs 人声分离权重校验失败（下载文件可能被代理/镜像改写）："
            f"期望 sha256 前缀 {MODEL_SHA_PREFIX}，实际 {actual[:16]}"
        )


def _progress(cb, ratio: float, message: str) -> None:
    if cb is not None:
        try:
            cb(max(0.0, min(1.0, float(ratio))), message)
        except Exception:
            log.debug("人声分离进度回调失败", exc_info=True)


def _cancel(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        from .procutil import CommandCancelled

        raise CommandCancelled("人声分离已取消")


def _download(url: str, dest: Path, cb=None, cancel_event=None) -> None:
    import ssl

    context = ssl.create_default_context()
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "KikuSub/0.2 (+demucs htdemucs)"},
    )
    part = dest.with_name(dest.name + ".part")
    if part.exists():
        try:
            part.unlink()
        except OSError:
            pass

    done = 0
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=60, context=context) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            with open(part, "wb") as fh:
                while True:
                    _cancel(cancel_event)
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    ratio = (done / total) if total else min(0.95, done / 80_000_000)
                    _progress(
                        cb,
                        ratio,
                        "正在下载 Demucs 人声分离权重（约 80MB）…",
                    )
        _progress(cb, 1.0, "Demucs 权重下载完成")
        _cancel(cancel_event)
        os.replace(part, dest)
    finally:
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass


def ensure_model(cb=None, cancel_event=None) -> Path:
    """确保权重在 `models/demucs/torch/hub/checkpoints/`；返回本地路径。"""
    if model_ready():
        return CHECKPOINT

    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    legacy = (
        Path.home()
        / ".cache"
        / "torch"
        / "hub"
        / "checkpoints"
        / MODEL_FILENAME
    )
    target = CHECKPOINT
    part = target.with_name(target.name + ".part")
    if part.exists():
        try:
            part.unlink()
        except OSError:
            pass

    _progress(cb, 0.01, "正在准备 Demucs 人声分离权重…")
    if legacy.exists() and legacy.stat().st_size >= MIN_MODEL_BYTES:
        # 只读复用旧缓存，不往 ~/.cache 写任何东西。
        shutil.copyfile(legacy, part)
        _progress(cb, 0.6, "已复用本机已有的 Demucs 权重")
        _verify_checkpoint(part)
        os.replace(part, target)
    else:
        # _download 自己写 target.part 并原子替换到 target。
        _download(MODEL_URL, target, cb=cb, cancel_event=cancel_event)
        _verify_checkpoint(target)

    log.info("Demucs 权重就绪 | %s", target)
    return target


def _device() -> str:
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _load_model(cb=None, cancel_event=None):
    global _MODEL, _MODEL_DEVICE
    if _MODEL is not None:
        return _MODEL

    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        ensure_model(cb=cb, cancel_event=cancel_event)
        os.environ["TORCH_HOME"] = str(TORCH_DIR)
        _progress(cb, 0.75, "正在加载 Demucs 人声分离模型…")
        from demucs.pretrained import get_model

        model = get_model(MODEL_NAME)
        model.eval()
        _MODEL = model
        _MODEL_DEVICE = _device()
        log.info("Demucs 模型已加载 | device=%s", _MODEL_DEVICE)
        return model


def release() -> None:
    """卸载模型并回收加速器缓存；分离结束必须调用。"""
    global _MODEL, _MODEL_DEVICE
    had_model = _MODEL is not None
    _MODEL = None
    _MODEL_DEVICE = ""
    gc.collect()
    try:
        import torch

        if torch.backends.mps.is_available():
            try:
                torch.mps.synchronize()
            except Exception:
                pass
            torch.mps.empty_cache()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        log.debug("清理加速器缓存失败", exc_info=True)
    if had_model:
        log.info("Demucs 模型已卸载，MPS 缓存已清理")


# --------------------------------------------------------------------------- 分离


def _extract_clip(media: Path, dest: Path, start: float, end: float, cancel_event=None) -> None:
    duration = max(0.1, float(end) - float(start))
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{float(start):.3f}",
        "-i",
        str(media),
        "-t",
        f"{duration:.3f}",
        "-vn",
        "-ac",
        "2",
        "-ar",
        str(SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        str(dest),
    ]
    proc = run_command(cmd, timeout=900, cancel_event=cancel_event)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 提取分离片段失败：\n{tail(proc.stderr, 800)}")


def plan_chunks(
    total_s: float,
    chunk_s: float = CHUNK_S,
    overlap_s: float = CROSSFADE_S,
) -> list[tuple[float, float, float, float]]:
    """把 `[0, total_s)` 切成连续的核心区间。

    返回 `(core_start, core_end, read_start, read_end)`：分离只信 core 段，
    read 段前后各多 `overlap_s` 秒，给相邻段留交叉淡化的材料。

    纯函数（不碰 torch / ffmpeg），长片内存行为由它决定，单测直接覆盖。
    """
    total = max(0.0, float(total_s))
    chunk = max(1.0, float(chunk_s))
    overlap = max(0.0, float(overlap_s))
    plan: list[tuple[float, float, float, float]] = []
    core_start = 0.0
    while core_start < total - 1e-6:
        core_end = min(total, core_start + chunk)
        plan.append(
            (
                core_start,
                core_end,
                max(0.0, core_start - overlap),
                min(total, core_end + overlap),
            )
        )
        core_start = core_end
    if not plan:
        plan.append((0.0, total, 0.0, total))
    return plan


def _prepare_channels(data: np.ndarray) -> np.ndarray:
    if data.size == 0:
        raise RuntimeError("待分离片段为空")
    if data.shape[1] == 1:
        return np.repeat(data, 2, axis=1)
    if data.shape[1] > 2:
        return np.ascontiguousarray(data[:, :2])
    return data


def _separate_chunk(
    data: np.ndarray,
    model,
    device: str,
    cancel_event=None,
) -> np.ndarray:
    """分离一段 `(frames, 2)` 音频，返回 `(2, frames)` 的 vocals（已 clip）。

    声道在前是 `apply_model` 的形状，也方便长区间按 `acc[:, f0:f1]` 累加；
    写盘时由调用方 `.T` 成 soundfile 要的 `(frames, channels)`。
    """
    import torch
    from demucs.apply import apply_model

    float_data = np.ascontiguousarray(np.asarray(data, dtype=np.float32).T)
    wav = torch.from_numpy(float_data)
    ref = wav.mean(0)
    if float(ref.std()) <= 1e-8:
        raise RuntimeError("待分离片段几乎是静音，无法分离")
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)

    _cancel(cancel_event)
    with torch.no_grad():
        sources = apply_model(
            model,
            wav[None],
            device=device,
            shifts=1,
            split=True,
            overlap=0.25,
            progress=False,
        )[0]
    _cancel(cancel_event)
    # 只还原 vocals 这一轨：整份 4 轨乘加会多出一份 ~4 倍时长的临时张量。
    vocals = sources[model.sources.index("vocals")]
    vocals.mul_(ref.std()).add_(ref.mean())
    return np.ascontiguousarray(np.clip(vocals.cpu().numpy(), -1.0, 1.0))


def _separate_long(
    clip: Path,
    total_frames: int,
    plan: list[tuple[float, float, float, float]],
    model,
    device: str,
    progress_cb=None,
    cancel_event=None,
) -> np.ndarray:
    """按段分离再交叉淡化；峰值内存由 CHUNK_S 决定，与总时长无关。"""
    import soundfile as sf

    acc = np.zeros((2, total_frames), dtype=np.float32)
    weight = np.zeros(total_frames, dtype=np.float32)
    overlap_frames = max(1, int(CROSSFADE_S * SAMPLE_RATE))
    total = len(plan)

    for k, (_core_start, _core_end, read_start, read_end) in enumerate(plan):
        _cancel(cancel_event)
        f0 = max(0, int(round(read_start * SAMPLE_RATE)))
        f1 = min(total_frames, int(round(read_end * SAMPLE_RATE)))
        if f1 - f0 < 2:
            continue
        data, sr = sf.read(
            str(clip), start=f0, frames=f1 - f0, dtype="float32", always_2d=True
        )
        if int(sr) != SAMPLE_RATE:
            raise RuntimeError(f"分离片段的采样率异常：{sr}（期望 {SAMPLE_RATE}）")
        vocals = _separate_chunk(_prepare_channels(data), model, device, cancel_event)

        n = vocals.shape[1]
        w = np.ones(n, dtype=np.float32)
        ramp = int(min(overlap_frames, max(1, n // 2)))
        if ramp > 1:
            # 只在「确实有另一段接着」的一侧做淡入/淡出；文件首尾不需要，
            # 但两侧都淡化也无害——最后按权重归一化，权重和不会出现 0。
            if f0 > 0:
                w[:ramp] = np.linspace(0.0, 1.0, ramp, endpoint=False, dtype=np.float32)
            if f1 < total_frames:
                w[-ramp:] = np.linspace(1.0, 0.0, ramp, endpoint=False, dtype=np.float32)
        acc[:, f0 : f0 + n] += vocals * w
        weight[f0 : f0 + n] += w
        _progress(
            progress_cb,
            0.28 + 0.6 * ((k + 1) / total),
            f"正在分离人声（Demucs htdemucs，{k + 1}/{total} 段）…",
        )

    weight[weight <= 0.0] = 1e-6
    acc /= weight
    return acc


def separate_to_wav(
    media_path: str | Path,
    out_wav: str | Path,
    *,
    start: float,
    end: float,
    progress_cb=None,
    cancel_event=None,
) -> Path:
    """把 `[start, end)` 的人声分离到 `out_wav`（44.1k 立体声 PCM16）。

    只做这一件事：截取、分离、写盘、卸载。缓存/原子替换由调用方
    （``core.audio_cache.ensure_vocals_wav``）负责。区间长度不设上限：
    超过 :data:`CHUNK_S` 的部分按段分离，内存只跟单段长度有关。
    """
    if float(end) <= float(start):
        raise ValueError("人声分离区间的结束必须大于开始")

    media = Path(media_path)
    out = Path(out_wav)
    out.parent.mkdir(parents=True, exist_ok=True)
    clip = out.with_name(f"{out.stem}.clip.wav")
    started = time.perf_counter()

    try:
        _cancel(cancel_event)
        _progress(progress_cb, 0.02, "正在截取待分离的音频片段…")
        _extract_clip(media, clip, start, end, cancel_event=cancel_event)
        _cancel(cancel_event)

        import soundfile as sf

        info = sf.info(str(clip))
        if int(info.frames) <= 0:
            raise RuntimeError("待分离片段为空")
        if int(info.samplerate) != SAMPLE_RATE:
            raise RuntimeError(
                f"分离片段的采样率异常：{info.samplerate}（期望 {SAMPLE_RATE}）"
            )
        total_frames = int(info.frames)
        plan = plan_chunks(total_frames / SAMPLE_RATE)

        _progress(progress_cb, 0.12, "正在加载 Demucs 人声分离模型…")

        def _model_progress(ratio: float, message: str) -> None:
            _progress(progress_cb, 0.12 + 0.16 * max(0.0, min(1.0, float(ratio))), message)

        model = _load_model(cb=_model_progress, cancel_event=cancel_event)
        _cancel(cancel_event)

        device = _MODEL_DEVICE or _device()
        model.to(device)

        if len(plan) == 1:
            _progress(progress_cb, 0.28, "正在分离人声（Demucs htdemucs）…")
            data, _sr = sf.read(str(clip), dtype="float32", always_2d=True)
            vocals = _separate_chunk(_prepare_channels(data), model, device, cancel_event)
        else:
            vocals = _separate_long(
                clip,
                total_frames,
                plan,
                model,
                device,
                progress_cb=progress_cb,
                cancel_event=cancel_event,
            )

        _progress(progress_cb, 0.95, "正在写入人声轨…")
        sf.write(str(out), vocals.T, SAMPLE_RATE, subtype="PCM_16")
        log.info(
            "人声分离完成 | %s | %.2fs-%.2fs | %.1fs | %d 段",
            media.name,
            start,
            end,
            time.perf_counter() - started,
            len(plan),
        )
        return out
    finally:
        # 模型引用与 torch 张量都已在函数内释放；这里只做缓存回收与临时文件清理。
        release()
        if clip.exists():
            try:
                clip.unlink()
            except OSError:
                pass
