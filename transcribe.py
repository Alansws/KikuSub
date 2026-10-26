"""日语影视音频提取、Silero VAD 语音切分与 Anime Whisper 转录流水线。

包含：
- 电影/动漫音轨提取、时间切片与单声道动态响度归一化 (dynaudnorm)
- Silero VAD 语音活动检测与智能片段合并
- Anime Whisper 模型推理与重复抑制 (no_repeat_ngram_size, repetition_penalty)
- 智能分句与时间轴生成 (SRT / VTT / TXT)
- 支持中途打断取消、现场保护并保存已完成的部分字幕
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path

warnings.filterwarnings("ignore", message=".*torch.jit.load is deprecated.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="torch.*")
warnings.filterwarnings("ignore", message=".*clean_up_tokenization_spaces.*")
warnings.filterwarnings("ignore", message=".*generation_config.*")
warnings.filterwarnings("ignore", message=".*Passing `generation_config` together with.*")


class _TransformersLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "processor_kwargs" in msg or "Kwargs passed to `processor.__call__`" in msg:
            return False
        if "Passing `generation_config`" in msg:
            return False
        return True


logging.getLogger("transformers").addFilter(_TransformersLogFilter())

import numpy as np
import soundfile as sf
import torch
from silero_vad import get_speech_timestamps, load_silero_vad

import audio_cache

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

SAMPLE_RATE = 16000

ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / "models"


def resolve_model_dir() -> Path:
    env = os.environ.get("ANIME_WHISPER_MODEL")
    return Path(env).expanduser() if env else MODELS_DIR / "anime-whisper"


MODEL_DIR = resolve_model_dir()
ANIME_WHISPER_REPO = "litagin/anime-whisper"
_WEIGHTS_FILE = "model.safetensors"


def model_ready(directory: Path) -> bool:
    return (Path(directory) / _WEIGHTS_FILE).exists()


def download_anime_whisper(dest: Path, progress_cb=None) -> Path:
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    from huggingface_hub import snapshot_download

    dest = Path(dest)
    if model_ready(dest):
        return dest
    
    if progress_cb:
        progress_cb(0.005, f"首次运行：正在从国内镜像高速下载 {ANIME_WHISPER_REPO}（支持断点续传）…")
    
    print(f"\n[模型加速下载] 正在通过国内镜像 (hf-mirror.com) 下载 {ANIME_WHISPER_REPO} 到 {dest} ...")
    print("[模型加速下载] 提示：如果之前已下载部分数据，将自动触发断点续传，无需从头下载。")
    dest.mkdir(parents=True, exist_ok=True)
    
    snapshot_download(
        repo_id=ANIME_WHISPER_REPO,
        local_dir=str(dest),
        ignore_patterns=["figs/*", "*.png", ".gitattributes"],
        max_workers=2,
    )
    print(f"[模型加速下载] {ANIME_WHISPER_REPO} 权重下载完成！")
    return dest


MAX_SEGMENT_S = 20.0
MERGE_GAP_S = 0.5
MIN_SPEECH_S = 0.08

# 强制切分点能量谷吸附：搜索窗宽度；0 = 关闭（恢复旧行为）
CUT_SNAP_S = 0.40
# 能量分析帧长（毫秒）
CUT_SNAP_FRAME_MS = 20
# 相邻切点最小间隔，防止切点倒退/交叉
CUT_MIN_CHUNK_S = 0.50

# 空结果段增益重试：目标峰值与增益上下限（≈ -14dB ~ +18dB）
RETRY_TARGET_PEAK = 0.85
RETRY_GAIN_RANGE = (0.2, 8.0)
# 可信度安全阀：日语正常语速 5–7 字/秒，15 已是极限
RETRY_MAX_CHARS_PER_S = 15.0
# 与上一段完全相同且长度超过该值即视为复读
RETRY_REPEAT_MIN_CHARS = 4

# 空文本判定：模型遇到纯静音/配乐时很少返回空串，而是返回「…」「…。」「♪」这类占位符。
# 若只认 ""，这些段会被当成"有内容"写进字幕，却又被清理环节当空条目删掉，
# 结果是字幕出现空档、漏句清单却是空的。这里统一两边的口径。
BLANK_TEXT_RE = re.compile(r"^[\s\u3000…‥⋯。、，．.,!！?？\-ー~〜♪♬「」『』（）()\[\]【】]*$")

# Silero VAD 的退出阈值默认取 threshold - 0.15。阈值低于 0.15 时该值为负，
# 而语音概率恒 >= 0，于是语音段一旦开始就永不结束——整片塌成一段。
# 给退出阈值设下限，让低阈值真正表现为"更灵敏"而不是"退化成整片一段"。
VAD_NEG_THRESHOLD_FLOOR = 0.02

VAD_THRESHOLD = 0.28
VAD_MIN_SPEECH_MS = 100
VAD_MIN_SILENCE_MS = 200
VAD_SPEECH_PAD_MS = 150
MAX_SEGMENT_S_LIMIT = 29.0


@dataclass
class WhisperVadConfig:
    threshold: float = VAD_THRESHOLD
    min_speech_ms: int = VAD_MIN_SPEECH_MS
    min_silence_ms: int = VAD_MIN_SILENCE_MS
    speech_pad_ms: int = VAD_SPEECH_PAD_MS
    merge_gap_s: float = MERGE_GAP_S
    max_segment_s: float = MAX_SEGMENT_S
    min_speech_s: float = MIN_SPEECH_S
    cue_pad_s: float = 0.0
    enable_sentence_split: bool = True
    max_cue_dur: float = 4.2
    max_cue_chars: int = 20
    enable_loudnorm: bool = True


def build_whisper_config(**overrides) -> WhisperVadConfig:
    values = {k: v for k, v in overrides.items() if v is not None}
    cfg = WhisperVadConfig(**values)
    cfg.max_segment_s = min(max(cfg.max_segment_s, 1.0), MAX_SEGMENT_S_LIMIT)
    cfg.speech_pad_ms = max(0, int(cfg.speech_pad_ms))
    cfg.min_speech_ms = max(0, int(cfg.min_speech_ms))
    cfg.min_silence_ms = max(0, int(cfg.min_silence_ms))
    cfg.min_speech_s = max(0.0, float(cfg.min_speech_s))
    return cfg


@dataclass
class VadStats:
    audio_s: float = 0.0
    speech_s: float = 0.0
    covered_s: float = 0.0
    segments: int = 0
    cues: int = 0
    chars: int = 0
    cut_s: float = 0.0
    cut_driver: str = ""

    @property
    def speech_ratio(self) -> float:
        return self.speech_s / self.audio_s if self.audio_s else 0.0

    @property
    def covered_ratio(self) -> float:
        return self.covered_s / self.audio_s if self.audio_s else 0.0

    def describe(self) -> str:
        cut = f"｜实际切分边界 {self.cut_s * 1000:.0f}ms（由{self.cut_driver}决定）" if self.cut_s else ""
        return (
            f"VAD 语音占比 {self.speech_ratio * 100:.1f}%"
            f"（送模音频占比 {self.covered_ratio * 100:.1f}%）"
            f"｜{self.segments} 个切片 → 产出 {self.cues} 条字幕 / {self.chars} 字"
            f"｜音频总长 {self.audio_s:.1f}s"
            f"{cut}"
        )


@dataclass
class SubtitleCue:
    start: float
    end: float
    text: str


ELLIPSIS_ONLY_RE = re.compile(r"^[.…。]+$")
SRT_TIME_LINE_RE = re.compile(
    r"^\s*(?P<start>\d{1,}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,}:\d{2}:\d{2}[,.]\d{1,3})(?:\s+.*)?\s*$"
)


def parse_time_str(val: str | None) -> float | None:
    if not val:
        return None
    s = val.strip().replace(",", ".")
    if not s:
        return None
    try:
        if ":" in s:
            parts = s.split(":")
            if len(parts) == 3:
                h, m, sec = parts
                return int(h) * 3600 + int(m) * 60 + float(sec)
            if len(parts) == 2:
                m, sec = parts
                return int(m) * 60 + float(sec)
        return float(s)
    except (ValueError, TypeError):
        return None


def format_time_tag(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}h{m:02d}m{s:02d}s"
    return f"{m:02d}m{s:02d}s"


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f} 秒"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes} 分 {secs:.2f} 秒 ({seconds:.2f} 秒)"


def is_ellipsis_only(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return bool(compact) and bool(ELLIPSIS_ONLY_RE.fullmatch(compact))


def remove_ellipsis_only_cues(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    return [cue for cue in cues if not is_ellipsis_only(cue.text)]


def parse_srt_timestamp(value: str) -> float:
    time_part, millis_part = re.split(r"[,.]", value.strip(), maxsplit=1)
    hours, minutes, seconds = (int(part) for part in time_part.split(":"))
    millis = int((millis_part + "000")[:3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def srt_to_cues(srt_text: str) -> list[SubtitleCue]:
    """健壮的 SRT 解析器：精准前瞻识别序号行，彻底杜绝序号渗入字幕正文。"""
    normalized = srt_text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    # 过滤纯空白行，仅保留有内容的文本行
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    
    cues: list[SubtitleCue] = []
    curr_start: float | None = None
    curr_end: float | None = None
    curr_text_lines: list[str] = []

    total_lines = len(lines)
    for i, line in enumerate(lines):
        match = SRT_TIME_LINE_RE.match(line)
        if match:
            # 遇到新的时间轴行，先把上一条字幕保存入库
            if curr_start is not None and curr_end is not None:
                text_content = "\n".join(curr_text_lines).strip()
                if text_content:
                    cues.append(SubtitleCue(curr_start, curr_end, text_content))
            curr_start = parse_srt_timestamp(match.group("start"))
            curr_end = parse_srt_timestamp(match.group("end"))
            curr_text_lines = []
            continue

        # 核心修复：当前行是纯数字，且下一行紧接着是时间轴时，才判定为序号行跳过
        if line.isdigit() and i + 1 < total_lines and SRT_TIME_LINE_RE.match(lines[i + 1]):
            continue

        # 收集真正的字幕文本
        if curr_start is not None:
            curr_text_lines.append(line)

    # 收尾保存最后一条字幕
    if curr_start is not None and curr_end is not None:
        text_content = "\n".join(curr_text_lines).strip()
        if text_content:
            cues.append(SubtitleCue(curr_start, curr_end, text_content))

    return cues


def detect_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def detect_dtype(device: str) -> torch.dtype:
    if device in {"mps", "cuda"}:
        return torch.float16
    return torch.float32


def format_srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:
        secs += 1
        millis = 0
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_vtt_timestamp(seconds: float) -> str:
    return format_srt_timestamp(seconds).replace(",", ".")


def cues_to_srt(cues: list[SubtitleCue]) -> str:
    lines: list[str] = []
    for i, cue in enumerate(cues, start=1):
        lines.append(str(i))
        lines.append(f"{format_srt_timestamp(cue.start)} --> {format_srt_timestamp(cue.end)}")
        lines.append(cue.text.strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def cues_to_vtt(cues: list[SubtitleCue]) -> str:
    lines = ["WEBVTT", ""]
    for cue in cues:
        lines.append(f"{format_vtt_timestamp(cue.start)} --> {format_vtt_timestamp(cue.end)}")
        lines.append(cue.text.strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def cues_to_txt(cues: list[SubtitleCue]) -> str:
    return "\n".join(cue.text.strip() for cue in cues if cue.text.strip()) + "\n"


def decode_wav_16k(
    input_path: str | Path,
    output_wav: str | Path,
    enable_loudnorm: bool = True,
    start_time_s: float | None = None,
    end_time_s: float | None = None,
) -> None:
    """真正调用 ffmpeg 解码出 16k mono wav（缓存层与降级路径共用）。"""
    cmd = ["ffmpeg", "-y"]

    if start_time_s is not None and start_time_s > 0:
        cmd.extend(["-ss", f"{start_time_s:.3f}"])

    cmd.extend(["-i", str(input_path)])

    if end_time_s is not None:
        start_val = start_time_s or 0.0
        duration_s = max(0.1, end_time_s - start_val)
        cmd.extend(["-t", f"{duration_s:.3f}"])

    cmd.append("-vn")

    if enable_loudnorm:
        audio_filter = "dynaudnorm=f=150:g=15:m=10.0:r=0.9:b=1,aresample=16000"
        cmd.extend(["-af", audio_filter])
    else:
        cmd.extend(["-ar", str(SAMPLE_RATE)])

    cmd.extend([
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(output_wav),
    ])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        fallback_cmd = ["ffmpeg", "-y"]
        if start_time_s is not None and start_time_s > 0:
            fallback_cmd.extend(["-ss", f"{start_time_s:.3f}"])
        fallback_cmd.extend(["-i", str(input_path)])
        if end_time_s is not None:
            start_val = start_time_s or 0.0
            fallback_cmd.extend(["-t", f"{max(0.1, end_time_s - start_val):.3f}"])
        fallback_cmd.extend([
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(output_wav),
        ])
        fallback_proc = subprocess.run(fallback_cmd, capture_output=True, text=True)
        if fallback_proc.returncode != 0:
            raise RuntimeError(f"ffmpeg 提取音频失败:\n{fallback_proc.stderr[-2000:]}")


def extract_audio_16k(
    input_path: str | Path,
    output_wav: str | Path | None = None,
    enable_loudnorm: bool = True,
    start_time_s: float | None = None,
    end_time_s: float | None = None,
) -> Path:
    """取得 16k mono wav 路径：优先复用缓存，关闭缓存或缓存不可用时现场解码。"""
    if audio_cache.enabled():
        try:
            return audio_cache.ensure_wav(
                input_path,
                loudnorm=enable_loudnorm,
                start=start_time_s,
                end=end_time_s,
                extractor=decode_wav_16k,
            )
        except Exception as exc:
            if output_wav is None:
                raise
            logging.warning("音频缓存不可用，回退为现场解码：%s", exc)

    if output_wav is None:
        raise ValueError("未启用音频缓存时必须提供 output_wav 路径")
    decode_wav_16k(input_path, output_wav, enable_loudnorm, start_time_s, end_time_s)
    return Path(output_wav)


def load_audio_for_transcription(
    media_path: str | Path,
    *,
    enable_loudnorm: bool = True,
    start_time_s: float | None = None,
    end_time_s: float | None = None,
    tmp_prefix: str = "kikusub-",
) -> np.ndarray:
    """取送模用的 16k 单声道数组：缓存开启时直接读缓存，关闭时走临时目录。"""
    if audio_cache.enabled():
        wav_path = extract_audio_16k(
            media_path,
            None,
            enable_loudnorm=enable_loudnorm,
            start_time_s=start_time_s,
            end_time_s=end_time_s,
        )
        return load_wav_mono(wav_path)

    with tempfile.TemporaryDirectory(prefix=tmp_prefix) as tmp:
        wav_path = extract_audio_16k(
            media_path,
            Path(tmp) / "audio_16k.wav",
            enable_loudnorm=enable_loudnorm,
            start_time_s=start_time_s,
            end_time_s=end_time_s,
        )
        return load_wav_mono(wav_path)


def load_wav_mono(path: str | Path) -> np.ndarray:
    audio, sr = sf.read(str(path), always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != SAMPLE_RATE:
        raise RuntimeError(f"音频采样率应为 {SAMPLE_RATE} Hz，实际为 {sr}")
    audio = audio.astype(np.float32, copy=False)

    if audio.size == 0:
        return np.zeros(0, dtype=np.float32)

    max_amp = float(np.max(np.abs(audio)))
    if 1e-4 < max_amp < 0.4:
        audio = audio * (0.85 / max_amp)

    return audio


def _energy_valley_cut(audio: np.ndarray, lo: int, hi: int, frame: int) -> int:
    """在 [lo, hi) 内寻找能量谷，返回吸附后的切点样本索引。

    只向前找、不向后推：窗口过窄、或窗口内能量起伏不足 6dB（连续说话无显著谷）时
    直接返回 hi，即完全退化为原来的机械切点。
    """
    orig_hi = hi
    lo = max(0, int(lo))
    hi = min(int(hi), int(audio.size))
    if frame <= 0 or hi - lo < 3 * frame:
        return orig_hi

    n_frames = (hi - lo) // frame
    if n_frames < 3:
        return orig_hi

    window = np.asarray(audio[lo : lo + n_frames * frame], dtype=np.float32)
    if window.size < 3 * frame:
        return orig_hi

    rms = np.sqrt(np.mean(window.reshape(n_frames, frame) ** 2, axis=1))
    peak = float(rms.max())
    if peak <= 1e-9:
        return orig_hi
    if peak / max(float(rms.min()), 1e-6) < 2.0:
        return orig_hi

    valley = int(np.argmin(rms))
    offset = valley * frame
    local = np.abs(window[offset : offset + frame])
    if local.size == 0:
        return orig_hi
    return lo + offset + int(np.argmin(local))


def _cut_keeps_segment_count(end: int, planned: int, snapped: int, max_samples: int) -> bool:
    """吸附把切点提前后，剩余音频所需的分段数是否保持不变。

    吸附只会让切点更早，若剩余长度刚好卡在 max_samples 的整数倍边界上，
    提前哪怕 10ms 都会凭空多切出一段（末尾剩一小截）。这里用整数上取整精确判定。
    """
    remain = end - planned
    if remain <= 0:
        return False
    shift = planned - snapped
    if shift <= 0:
        return True
    before = (remain + max_samples - 1) // max_samples
    after = (remain + shift + max_samples - 1) // max_samples
    return before == after


def merge_vad_segments(
    stamps: list[dict],
    sample_rate: int = SAMPLE_RATE,
    max_segment_s: float = MAX_SEGMENT_S,
    merge_gap_s: float = MERGE_GAP_S,
    min_speech_s: float = MIN_SPEECH_S,
    speech_pad_s: float = 0.0,
    audio: np.ndarray | None = None,
    cut_snap_s: float = CUT_SNAP_S,
    snap_stats: dict | None = None,
) -> list[tuple[int, int]]:
    if not stamps:
        return []

    merged: list[list[int]] = []
    for stamp in stamps:
        start, end = int(stamp["start"]), int(stamp["end"])
        if end <= start:
            continue
        if not merged:
            merged.append([start, end])
            continue

        prev_start, prev_end = merged[-1]
        padded_gap = max(0.0, (start - prev_end) / sample_rate)
        duration_if_merged = (end - prev_start) / sample_rate

        if padded_gap <= merge_gap_s and duration_if_merged <= max_segment_s:
            merged[-1][1] = max(prev_end, end)
        else:
            merged.append([start, end])

    split: list[tuple[int, int]] = []
    max_samples = int(max_segment_s * sample_rate)
    min_samples = int(min_speech_s * sample_rate)
    snap_frame = max(1, int(sample_rate * CUT_SNAP_FRAME_MS / 1000))
    snap_active = audio is not None and cut_snap_s > 0
    min_chunk = int(CUT_MIN_CHUNK_S * sample_rate)
    forced_cuts = 0
    snapped_cuts = 0
    snap_shift_samples = 0

    for start, end in merged:
        if end - start < min_samples:
            continue
        cursor = start
        while cursor < end:
            nxt = min(end, cursor + max_samples)
            if nxt < end:
                forced_cuts += 1
            if snap_active and nxt < end:
                lo = max(cursor + min_chunk, nxt - int(cut_snap_s * sample_rate))
                if nxt - lo >= 3 * snap_frame:
                    snapped = _energy_valley_cut(audio, lo, nxt, snap_frame)
                    if _cut_keeps_segment_count(end, nxt, snapped, max_samples):
                        if snapped != nxt:
                            snapped_cuts += 1
                            snap_shift_samples += nxt - snapped
                        nxt = snapped
            if nxt - cursor >= min_samples:
                split.append((cursor, nxt))
            cursor = nxt

    if snap_stats is not None:
        snap_stats.update({
            "blocks": len(merged),
            "forced_cuts": forced_cuts,
            "snapped_cuts": snapped_cuts,
            "shift_s": snap_shift_samples / sample_rate,
            "max_block_s": max(((e - s) / sample_rate for s, e in merged), default=0.0),
        })
    return split


JP_SENTENCE_SPLIT_RE = re.compile(r"([^。！？!?…\n]+[。！？!?…\n]+)")
JP_COMMA_SPLIT_RE = re.compile(r"([^、,]+[、,]+)")
REPEATED_CHUNK_RE = re.compile(r"(.{1,4}?)\1{5,}")


def _is_blank(text: str) -> bool:
    """是否为"无内容"：空串，或仅由空白/标点/省略号/音符组成。

    模型对纯静音与配乐段通常返回 "…" 而不是 ""，必须按同一口径判空，
    否则这类段既不重试、也不进漏句清单，却会在清理字幕时被删掉。
    """
    return bool(BLANK_TEXT_RE.match(text or ""))


def vad_neg_threshold(threshold: float) -> float:
    """VAD 退出阈值：与 Silero 默认迟滞（threshold - 0.15）一致，但不低于下限。"""
    return max(float(threshold) - 0.15, VAD_NEG_THRESHOLD_FLOOR)


def _retry_gain(chunk: np.ndarray) -> np.ndarray:
    """把空结果段拉到目标峰值再送模一次，返回新数组（不修改原音频）。"""
    if chunk.size == 0:
        return chunk
    peak = float(np.max(np.abs(chunk)))
    if peak < 1e-6:
        return chunk
    gain = min(max(RETRY_TARGET_PEAK / peak, RETRY_GAIN_RANGE[0]), RETRY_GAIN_RANGE[1])
    return np.clip(chunk * gain, -1.0, 1.0)


def _retry_suspicious(text: str, dur_s: float, prev_text: str) -> bool:
    """重试结果的可信度安全阀：语速超限或与上一段完全复读即判为不可信。"""
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return False
    if dur_s > 0 and len(compact) / dur_s > RETRY_MAX_CHARS_PER_S:
        return True
    prev_compact = re.sub(r"\s+", "", prev_text or "")
    return len(compact) > RETRY_REPEAT_MIN_CHARS and compact == prev_compact


def sanitize_pathological_repeats(text: str) -> str:
    def _repl(match):
        unit = match.group(1)
        return unit * 3 + "…"

    prev = None
    curr = text
    while prev != curr:
        prev = curr
        curr = REPEATED_CHUNK_RE.sub(_repl, curr)
    return curr


def split_text_into_cues(
    text: str,
    seg_start: float,
    seg_end: float,
    max_cue_dur: float = 4.2,
    max_cue_chars: int = 20,
) -> list[SubtitleCue]:
    clean_text = sanitize_pathological_repeats(text.strip())
    seg_dur = max(0.05, seg_end - seg_start)

    if seg_dur <= max_cue_dur and len(clean_text) <= max_cue_chars:
        return [SubtitleCue(start=round(seg_start, 3), end=round(seg_end, 3), text=clean_text)]

    parts = [p.strip() for p in JP_SENTENCE_SPLIT_RE.split(clean_text) if p.strip()]
    if not parts:
        parts = [clean_text]

    refined_parts: list[str] = []
    for p in parts:
        if len(p) > max_cue_chars:
            sub = [s.strip() for s in JP_COMMA_SPLIT_RE.split(p) if s.strip()]
            refined_parts.extend(sub if sub else [p])
        else:
            refined_parts.append(p)

    if not refined_parts:
        return [SubtitleCue(start=round(seg_start, 3), end=round(seg_end, 3), text=clean_text)]

    num_parts = len(refined_parts)
    if num_parts == 1:
        return [SubtitleCue(start=round(seg_start, 3), end=round(seg_end, 3), text=refined_parts[0])]

    weights: list[float] = []
    for p in refined_parts:
        w = 3.0 + min(float(len(p)), max_cue_chars * 1.8)
        weights.append(w)

    total_weight = sum(weights)
    raw_durs = [seg_dur * (w / total_weight) for w in weights]

    min_guard = min(seg_dur / num_parts, 0.45)
    allocated_durs: list[float] = []
    for d in raw_durs:
        allocated_durs.append(max(d, min_guard))

    sum_alloc = sum(allocated_durs)
    if sum_alloc > 0:
        scaled_durs = [seg_dur * (d / sum_alloc) for d in allocated_durs]
    else:
        scaled_durs = [seg_dur / num_parts] * num_parts

    cues: list[SubtitleCue] = []
    curr_t = seg_start
    for i, p in enumerate(refined_parts):
        end_t = seg_end if i == num_parts - 1 else curr_t + scaled_durs[i]
        cues.append(
            SubtitleCue(
                start=round(max(0.0, curr_t), 3),
                end=round(end_t, 3),
                text=p,
            )
        )
        curr_t = end_t

    return cues


def apply_cue_padding(
    cues: list[SubtitleCue],
    pad_s: float,
    duration_s: float | None = None,
) -> list[SubtitleCue]:
    if pad_s <= 0 or not cues:
        return cues
    limit = duration_s if duration_s is not None else max(c.end for c in cues) + pad_s
    padded: list[SubtitleCue] = []
    for i, cue in enumerate(cues):
        start = max(0.0, cue.start - pad_s)
        if i:
            start = max(start, padded[-1].end)
        end = cue.end + pad_s
        if i + 1 < len(cues):
            end = min(end, cues[i + 1].start)
        end = min(float(limit), end)
        if end <= start:
            start, end = cue.start, max(cue.end, cue.start + 0.001)
        padded.append(SubtitleCue(start=start, end=end, text=cue.text))
    return padded


class AnimeWhisperEngine:
    def __init__(self, config: WhisperVadConfig | None = None) -> None:
        self.device = detect_device()
        self.dtype = detect_dtype(self.device)
        self.config = config or WhisperVadConfig()
        self.last_stats = VadStats()
        self.last_interrupted = False
        self.last_missed_spans: list[dict] = []
        self.last_segment_stats: dict = {}
        self._pipe = None
        self._vad = None

    @property
    def ready(self) -> bool:
        return self._pipe is not None

    def ensure_model(self, progress_cb=None) -> None:
        if not model_ready(MODEL_DIR):
            download_anime_whisper(MODEL_DIR, progress_cb=progress_cb)

    def load(self, progress_cb=None) -> None:
        if self._pipe is not None:
            return
        
        self.ensure_model(progress_cb=progress_cb)
        
        if not model_ready(MODEL_DIR):
            raise FileNotFoundError(
                f"未能成功获取 litagin/anime-whisper 权重（{MODEL_DIR}）。\n"
                "请检查网络连接或代理，也可手动指定 ANIME_WHISPER_MODEL。"
            )

        if progress_cb:
            progress_cb(0.015, "模型权重就绪，正在加载至加速设备…")

        from transformers import pipeline

        self._vad = load_silero_vad()
        pipe_kwargs = dict(
            model=str(MODEL_DIR),
            device=self.device,
            chunk_length_s=None,
        )
        try:
            self._pipe = pipeline("automatic-speech-recognition", dtype=self.dtype, **pipe_kwargs)
        except TypeError:
            self._pipe = pipeline("automatic-speech-recognition", torch_dtype=self.dtype, **pipe_kwargs)

        if hasattr(self._pipe, "tokenizer") and self._pipe.tokenizer is not None:
            self._pipe.tokenizer.clean_up_tokenization_spaces = False

        if hasattr(self._pipe.model, "generation_config") and self._pipe.model.generation_config is not None:
            self._pipe.model.generation_config.forced_decoder_ids = None

    def transcribe_file(
        self,
        media_path: str | Path,
        *,
        config: WhisperVadConfig | None = None,
        no_repeat_ngram_size: int = 5,
        repetition_penalty: float = 1.15,
        progress_cb=None,
        cancel_event: threading.Event | None = None,
        start_time_s: float | None = None,
        end_time_s: float | None = None,
        time_offset: float = 0.0,
    ) -> list[SubtitleCue]:
        self.load(progress_cb=progress_cb)
        self.last_interrupted = False
        cfg = config or self.config
        media_path = Path(media_path)
        if progress_cb:
            slice_desc = f"（片段：{start_time_s or 0.0:.1f}s ~ {end_time_s:.1f}s）" if end_time_s else ""
            progress_cb(0.02, f"正在提取 16kHz 音频并进行动态响度优化{slice_desc}…")
        audio = load_audio_for_transcription(
            media_path,
            enable_loudnorm=cfg.enable_loudnorm,
            start_time_s=start_time_s,
            end_time_s=end_time_s,
            tmp_prefix="anime-whisper-",
        )
        return self._transcribe_array(
            audio,
            config=cfg,
            no_repeat_ngram_size=no_repeat_ngram_size,
            repetition_penalty=repetition_penalty,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
            time_offset=time_offset,
        )

    def _transcribe_array(
        self,
        audio: np.ndarray,
        *,
        config: WhisperVadConfig | None = None,
        no_repeat_ngram_size: int = 5,
        repetition_penalty: float = 1.15,
        progress_cb=None,
        cancel_event: threading.Event | None = None,
        time_offset: float = 0.0,
    ) -> list[SubtitleCue]:
        if progress_cb:
            progress_cb(0.08, "正在使用 Silero VAD 精确切分语音段落…")

        cfg = config or self.config
        self.last_missed_spans = []
        self.last_segment_stats = {}
        wav_tensor = torch.from_numpy(audio)
        stamps = get_speech_timestamps(
            wav_tensor,
            self._vad,
            sampling_rate=SAMPLE_RATE,
            threshold=float(cfg.threshold),
            min_speech_duration_ms=int(cfg.min_speech_ms),
            min_silence_duration_ms=int(cfg.min_silence_ms),
            speech_pad_ms=int(cfg.speech_pad_ms),
            neg_threshold=vad_neg_threshold(cfg.threshold),
        )
        raw_speech_s = sum((s["end"] - s["start"]) for s in stamps) / SAMPLE_RATE
        segments = merge_vad_segments(
            stamps,
            max_segment_s=min(float(cfg.max_segment_s), MAX_SEGMENT_S_LIMIT),
            merge_gap_s=float(cfg.merge_gap_s),
            min_speech_s=float(cfg.min_speech_s),
            speech_pad_s=int(cfg.speech_pad_ms) / 1000.0,
            audio=audio,
            snap_stats=self.last_segment_stats,
        )
        if not segments:
            segments = [(0, len(audio))]

        ngram_val = int(no_repeat_ngram_size) if int(no_repeat_ngram_size) > 0 else None
        penalty_val = float(repetition_penalty) if float(repetition_penalty) > 1.0 else 1.0

        for target in (
            getattr(self._pipe, "generation_config", None),
            getattr(getattr(self._pipe, "model", None), "generation_config", None),
        ):
            if target is not None:
                if ngram_val is not None:
                    target.no_repeat_ngram_size = ngram_val
                target.repetition_penalty = penalty_val
                target.forced_decoder_ids = None

        generate_kwargs = {
            "language": "Japanese",
            "task": "transcribe",
        }
        if ngram_val is not None:
            generate_kwargs["no_repeat_ngram_size"] = ngram_val
        if penalty_val > 1.0:
            generate_kwargs["repetition_penalty"] = penalty_val

        cues: list[SubtitleCue] = []
        total = len(segments)
        prev_text = ""

        def _decode(buf: np.ndarray) -> str:
            res = self._pipe(
                {"array": buf, "sampling_rate": SAMPLE_RATE},
                generate_kwargs=generate_kwargs,
                return_timestamps=False,
            )
            return (res.get("text") or "").strip()

        for i, (start, end) in enumerate(segments, start=1):
            if cancel_event and cancel_event.is_set():
                self.last_interrupted = True
                if progress_cb:
                    progress_cb(0.99, f"🛑 用户已中途取消，正在保存前 {len(cues)} 条字幕…")
                break

            if progress_cb:
                ratio = 0.1 + 0.85 * (i - 1) / max(total, 1)
                progress_cb(ratio, f"正在识别第 {i}/{total} 段… (可随时点击取消)")

            chunk = audio[start:end]
            if chunk.size == 0:
                continue

            seg_start_s = (start / SAMPLE_RATE) + time_offset
            seg_end_s = (end / SAMPLE_RATE) + time_offset
            seg_dur_s = (end - start) / SAMPLE_RATE

            text = _decode(chunk)
            reason = ""
            if _is_blank(text):
                if cancel_event and cancel_event.is_set():
                    self.last_interrupted = True
                    if progress_cb:
                        progress_cb(0.99, f"🛑 用户已中途取消，正在保存前 {len(cues)} 条字幕…")
                    break
                text = _decode(_retry_gain(chunk))
                if not _is_blank(text) and _retry_suspicious(text, seg_dur_s, prev_text):
                    text, reason = "", "retry-suspicious"
                elif _is_blank(text):
                    reason = "empty-after-retry"

            if _is_blank(text):
                self.last_missed_spans.append({
                    "start": round(seg_start_s, 3),
                    "end": round(seg_end_s, 3),
                    "dur": round(seg_end_s - seg_start_s, 2),
                    "reason": reason or "empty-after-retry",
                })
                continue
            prev_text = text

            if cfg.enable_sentence_split:
                sub_cues = split_text_into_cues(
                    text,
                    seg_start_s,
                    seg_end_s,
                    max_cue_dur=cfg.max_cue_dur,
                    max_cue_chars=cfg.max_cue_chars,
                )
                cues.extend(sub_cues)
            else:
                cues.append(
                    SubtitleCue(
                        start=seg_start_s,
                        end=seg_end_s,
                        text=text,
                    )
                )

        cues = apply_cue_padding(cues, cfg.cue_pad_s, (len(audio) / SAMPLE_RATE) + time_offset)

        silence_cut = int(cfg.min_silence_ms) / 1000.0
        merge_cut = float(cfg.merge_gap_s)
        cut_s = max(silence_cut, merge_cut)
        cut_driver = "停顿阈值" if silence_cut >= merge_cut else "合并间隔"

        self.last_stats = VadStats(
            audio_s=len(audio) / SAMPLE_RATE,
            speech_s=raw_speech_s,
            covered_s=sum((e - s) for s, e in segments) / SAMPLE_RATE,
            segments=len(segments),
            cues=len(cues),
            chars=sum(len(c.text) for c in cues),
            cut_s=cut_s,
            cut_driver=cut_driver,
        )

        if progress_cb and not self.last_interrupted:
            progress_cb(0.98, "正在整理字幕…")
        return cues


ENGINE = AnimeWhisperEngine()
