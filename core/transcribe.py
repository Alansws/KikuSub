"""日语影视音频提取、Silero VAD 语音切分与 Anime Whisper 转录流水线。

包含：
- 电影/动漫音轨提取、时间切片与单声道动态响度归一化 (dynaudnorm)
- Silero VAD 语音活动检测与智能片段合并
- Anime Whisper 模型推理与重复抑制 (no_repeat_ngram_size, repetition_penalty)
- 智能分句与时间轴生成 (SRT / VTT / TXT)
- 支持中途打断取消、现场保护并保存已完成的部分字幕
"""

from __future__ import annotations

import gc
import logging
import os
import re
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

from . import audio_cache
from .coverage import find_coverage_spans
from .paths import APP_ROOT, MODELS_DIR as PATHS_MODELS_DIR
from .procutil import CommandCancelled, CommandTimeout, run_command, tail

log = logging.getLogger(__name__)

# 模型加载/下载是进程级单例操作；并发首次调用不能各自 from_pretrained 一份权重。
_MODEL_LOAD_LOCK = threading.Lock()

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

SAMPLE_RATE = 16000
# 单条 ffmpeg 解码命令的硬超时。音频解码通常远快于实时，30 分钟足够覆盖
# 数小时素材；超时说明输入/解码器异常，不应无限占用工作线程。
FFMPEG_DECODE_TIMEOUT_S = 1800.0

ROOT = APP_ROOT
MODELS_DIR = PATHS_MODELS_DIR


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
    
    log.info("模型下载开始 repo=%s dest=%s endpoint=%s", ANIME_WHISPER_REPO, dest, os.environ.get("HF_ENDPOINT", ""))
    dest.mkdir(parents=True, exist_ok=True)
    
    snapshot_download(
        repo_id=ANIME_WHISPER_REPO,
        local_dir=str(dest),
        ignore_patterns=["figs/*", "*.png", ".gitattributes"],
        max_workers=2,
    )
    log.info("模型下载完成 repo=%s dest=%s", ANIME_WHISPER_REPO, dest)
    return dest


MAX_SEGMENT_S = 9.0
MERGE_GAP_S = 0.30
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

# 阈值历史（2026-10-26，整段一次 VAD，46 分钟素材）：0.45 → 25.08% CER / 插入 69；
# 0.35 → 23.35%；0.30 → 22.46%；0.25 → 21.30%（插入 94）；0.20 → 20.51%（插入 103）。
# 当时的结论是「0.30 是插入量还能接受的最低档」——但那份结论建立在**整段一次**跑
# Silero 之上，插入量随阈值下降而涨，主要是低阈值把呼吸/杂音也判成语音。
# 2026-11-13 改成**分窗检测 + 句首尾非台词发声剔除**之后，这个权衡被拆掉了：
# 830s 耳语素材上阈值 0.25 的 CER 反而最低（0.20 = 8.06%、0.25 = 8.22%、0.30 = 9.3%），
# 且插入量已由发声剔除压住。默认因此下调到 0.25。
VAD_THRESHOLD = 0.25
VAD_MIN_SPEECH_MS = 80
VAD_MIN_SILENCE_MS = 200
# 留白给到 250ms：耳语的开头很容易被判成静音（吞头音），句尾多带的气声由
# strip_edge_nonverbal() 在解码后剔掉，所以「调大留白」不再有插入的副作用。
# （300ms 在耳语素材上再好一点点，但 47 分钟正常对话的长片回归里会把相邻两句
# 并进同一块，块准确率掉 3pt，取 250ms 折中。）
VAD_SPEECH_PAD_MS = 250
MAX_SEGMENT_S_LIMIT = 29.0

# 分窗 VAD：Silero 是带隐状态的流式模型，整段十几分钟一次跑完时隐状态会漂移。
# 2026-11-13 实测（Jap_test.mp4，830s 耳语素材）：整段一次跑，461.8–463.8s 这段
# 概率 0.4–0.9 的清晰台词被判成静音；同一段音频从 30s 窗内重新检测则稳定命中。
# 因此按固定窗长分块检测（每窗 reset_states），再用区间并集消掉重叠窗的重复段。
# 窗长实测（阈值 0.25 / 留白 300ms，830s 素材，7 个「整段跑必漏」的时间点）：
# 30s 窗仍漏 2 个（461.8s 的清晰台词就在窗内第 12 秒，隐状态已经漂掉）；
# 20s / 15s / 10s 窗 7 个全中。窗越短越灵敏，同时误检也会变多（30s→173 段，
# 20s→179，10s→200），20s 是「不漏」与「不吵」的平衡点。
VAD_WINDOW_S = 20.0
VAD_WINDOW_OVERLAP_S = 1.0

# 句首补回（路线文档 P0-1）：Silero 的段起点系统性晚于真实发声。830s 素材实测，
# 即使已经带 250ms 的 `speech_pad_ms`，段起点仍比人工版晚中位 +0.5s、最多 +1.1s；
# 人工时间窗左右各扩 0.25s 直送模型，9 个「句首缺字」样本的句首全部回来了。
# 做法是把**合并后**的块起点整体向左扩 `pad`，而不是调阈值（0.20 会换来 7 处强制
# 切分与更多音乐误检）。`0` = 关闭，与旧行为一致。
ONSET_PAD_MAX_MS = 600
# 左扩不得吃进上一块：`start = max(0, prev_end + gap, start - pad)`。
ONSET_PREV_GAP_MS = 80
# 闸门只在 A/B 里用，不进参数面板：被吞的句首多是「す / そ / え」这类清辅音，
# 按段内峰值百分比设闸恰好把想救的音拦在门外（见路线文档 P0-1「不要默认死绑能量闸门」）。
ONSET_GATE_NONE = "none"
ONSET_GATE_SNR = "snr"  # 回看窗内有 ≥ 底噪 + 6dB 的帧
ONSET_GATE_SNR_CAP = "snr_cap"  # clamp(段峰值×0.08, 底噪+6dB, 底噪+18dB)
ONSET_FRAME = 512  # 32ms @16k，与 Silero 的窗口一致
ONSET_HOP = 160  # 10ms
ONSET_NOISE_QUANTILE = 0.10
ONSET_SNR_DB = 6.0
ONSET_CAP_DB = 18.0
ONSET_RELATIVE_PEAK = 0.08

# 非台词发声（笑声 / 喘气 / 亲吻声）。模型会如实转写这些东西，但它们几乎从不
# 该进字幕：句首尾挂着「んふふ」「えへへ」会让整条字幕读起来像噪声。只在**端点**
# 删（句中不动），且不删「あー」「うー」这类可能是台词本身的感叹（人工整理版里
# 「あー…すっごい…」是保留的）。
_NONVERBAL_UNIT = (
    r"(?:ん|ン)?[ふフはハへヘほホひヒ][ふフはハへヘほホひヒ]+"
    r"|くすくす|あはは|うふふ|はぁ|んー+|ふー+|ちゅっ"
    # 「えへへへ」这种：正则下面那条要求首字就是呼气字，'え' 会剩下来。
    r"|え[へヘ][へヘ]+"
)
_EDGE_LEAD_RE = re.compile(
    r"^(?:[、。…！？!?ー~〜っッ♪\s]*(?:" + _NONVERBAL_UNIT + r"))+[、。…！？!?ー~〜っッ♪\s]*"
)
_EDGE_TAIL_RE = re.compile(
    r"(?:(?:" + _NONVERBAL_UNIT + r")[、。…！？!?ー~〜っッ♪\s]*)+$"
)
# 整条只剩发声/单个假名碎片（「っ」「へ」「ー」）——不值得占一条字幕
_NONVERBAL_ONLY_RE = re.compile(r"^[ふフはハへヘほホひヒんンっッー~〜…、。！？!?♪\s]*$")

# ==============================================================================
# 日语断句语言学资产：两条引擎共用（Whisper 分句兜底 / Qwen 断句 DP）
# ==============================================================================

SMALL_KANA = set("っッゃゅょャュョぁぃぅぇぉァィゥェォゎヮヵヶ")
PROLONGED_SOUNDS = set("ー〜～")
JAPANESE_PARTICLES = set("は が を に で へ と も から まで より ね よ わ か の".split())
HONORIFIC_PREFIXES = set("おご御")

# 禁切词：在这些词内部下刀等于把词劈开
FORBIDDEN_WORDS = (
    "これ", "それ", "あれ", "どれ",
    "なんか", "なんて", "なんで", "ちょっと",
    "やっぱり", "どうして", "だから", "だけど",
    "ありま", "ございま", "お願い",
    "あと", "けれども", "けれど", "なんです", "んです",
    "として", "ですから", "なので",
    "まして", "ました", "ません", "ったら", "ったり",
    "てまして", "てました", "ていた", "ている", "ていく", "てみる", "てた",
)


def _is_kana(ch: str) -> bool:
    return bool(ch) and ("\u3040" <= ch <= "\u30ff" or "\u31f0" <= ch <= "\u31ff")


def _is_kanji(ch: str) -> bool:
    return bool(ch) and ("\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf")


def forbidden_cut_positions(text: str) -> bytearray:
    """禁切表：返回长度 len(text)+1 的布尔数组，1 表示"在下标处下刀"禁止。

    覆盖两类硬禁则：**音节级**（小假名、长音符、片假名连写、汉字连写、ASCII 词内、
    敬语前缀、ま+す/せ/し、こそ+う）与**词级**（FORBIDDEN_WORDS 内部）。
    只判"能不能切"，不判"该不该切"——助词后/汉字转假名这类偏好仍由调用方决定。

    实现要点：词级禁则一次扫描全文本标进数组（O(n·W)），而不是对每个候选切点
    重扫一遍（O(n·W·n)）。`_break_costs` 与 Whisper 的超长兜底共用这一份结果。
    """
    n = len(text)
    blocked = bytearray(n + 1)
    if n < 2:
        return blocked

    for p in range(1, n):
        prev_ch, next_ch = text[p - 1], text[p]
        if (
            next_ch in SMALL_KANA
            or prev_ch in SMALL_KANA
            or next_ch in PROLONGED_SOUNDS
            or prev_ch in PROLONGED_SOUNDS
            or (prev_ch.isascii() and prev_ch.isalnum() and next_ch.isascii() and next_ch.isalnum())
            or ("\u30a0" <= prev_ch <= "\u30ff" and "\u30a0" <= next_ch <= "\u30ff")
            or (_is_kanji(prev_ch) and _is_kanji(next_ch))
            or (prev_ch in HONORIFIC_PREFIXES and _is_kanji(next_ch))
            or (prev_ch == "ま" and next_ch in ("す", "せ", "し"))
            or (prev_ch in "こそことのほもろよごぞどぼぽ" and next_ch == "う")
        ):
            blocked[p] = 1

    for word in FORBIDDEN_WORDS:
        start = 0
        while (idx := text.find(word, start)) != -1:
            # 词内部（首字之后、末字之前）的每个位置都禁止下刀
            blocked[idx + 1 : idx + len(word)] = b"\x01" * (len(word) - 1)
            start = idx + 1
    return blocked


_HARD_SPLIT_PUNCT = set("、。！？!?…‥，,・：:；;")
_HARD_SPLIT_PARTICLES = set("はがをにでへともねよわかの")
# 超长单句在「助词后」断句的候选助词（用户口径：は が を に で と て）。
# 含 へ/も/の/や 是同一类「格助词/系助词后」的延伸，切出来同样是完整短语。
_CUE_SPLIT_PARTICLES = set("はがをにでとてへものや")


def _hard_split_text(text: str, max_chars: int, lookback_ratio: float = 0.34) -> list[str]:
    """超长单行的兜底切分：从目标点向前找最近的**自然**切点。

    优先级：标点后 > 助词后 > 窗口内任何未被禁则挡住的位置 > 按 max_chars 硬切。
    标点/助词在更宽的窗口里找（宁可切短一点换一个自然边界），都没有才退回窄窗口
    取最近合法点。宁可切得短一点，也不在词中间下刀，更不让一条字幕超出宽度上限。
    """
    max_chars = max(1, int(max_chars))
    text = text or ""
    n = len(text)
    if n <= max_chars:
        return [text] if text else []

    blocked = forbidden_cut_positions(text)
    narrow = max(2, int(max_chars * lookback_ratio))
    wide = max(narrow + 1, int(max_chars * 0.5))
    out: list[str] = []
    start = 0
    while start < n:
        if n - start <= max_chars:
            out.append(text[start:])
            break
        target = start + max_chars

        cut = 0
        particle_cut = 0
        for p in range(target, max(start + 1, target - wide) - 1, -1):
            if blocked[p]:
                continue
            if text[p - 1] in _HARD_SPLIT_PUNCT:
                cut = p
                break
            if not particle_cut and text[p - 1] in _HARD_SPLIT_PARTICLES:
                particle_cut = p
        if not cut:
            cut = particle_cut
        if not cut:
            for p in range(target, max(start + 1, target - narrow) - 1, -1):
                if not blocked[p]:
                    cut = p
                    break
        if cut <= start:
            cut = target
        out.append(text[start:cut])
        start = cut
    return out


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
    # 句首尾的喘气/笑声是否自动剔除（整条只剩发声的碎片一并丢弃）
    strip_nonverbal_edges: bool = True
    # 借用 Qwen 的 CTC 对齐头拿逐字时间（core/align_layer.py）。
    # 默认关：要多常驻一份 Qwen 权重（MPS 4.3 GB），而且要先装 Qwen 引擎。
    use_ctc_alignment: bool = False
    # 句首补回：把 VAD 块起点向左扩多少毫秒（0 = 关闭，与旧行为逐字节一致）。
    # 见 `extend_segment_onsets()` 与路线文档 P0-1。
    onset_pad_ms: int = 0
    # 闸门只在 A/B 里切换（不入参数面板）：none / snr / snr_cap。
    onset_gate: str = ONSET_GATE_NONE


def build_whisper_config(**overrides) -> WhisperVadConfig:
    values = {k: v for k, v in overrides.items() if v is not None}
    cfg = WhisperVadConfig(**values)
    cfg.max_segment_s = min(max(cfg.max_segment_s, 1.0), MAX_SEGMENT_S_LIMIT)
    cfg.speech_pad_ms = max(0, int(cfg.speech_pad_ms))
    cfg.min_speech_ms = max(0, int(cfg.min_speech_ms))
    cfg.min_silence_ms = max(0, int(cfg.min_silence_ms))
    cfg.min_speech_s = max(0.0, float(cfg.min_speech_s))
    cfg.onset_pad_ms = max(0, min(int(cfg.onset_pad_ms), ONSET_PAD_MAX_MS))
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
    hallucinations: int = 0
    suspect_cues: int = 0

    @property
    def speech_ratio(self) -> float:
        return self.speech_s / self.audio_s if self.audio_s else 0.0

    @property
    def covered_ratio(self) -> float:
        return self.covered_s / self.audio_s if self.audio_s else 0.0

    def describe(self) -> str:
        cut = f"｜实际切分边界 {self.cut_s * 1000:.0f}ms（由{self.cut_driver}决定）" if self.cut_s else ""
        hallucination = f"｜丢弃疑似幻觉 {self.hallucinations} 段" if self.hallucinations else ""
        suspect = f"｜疑似幻觉待复核 {self.suspect_cues} 段" if self.suspect_cues else ""
        return (
            f"VAD 语音占比 {self.speech_ratio * 100:.1f}%"
            f"（送模音频占比 {self.covered_ratio * 100:.1f}%）"
            f"｜{self.segments} 个切片 → 产出 {self.cues} 条字幕 / {self.chars} 字"
            f"｜音频总长 {self.audio_s:.1f}s"
            f"{cut}"
            f"{hallucination}"
            f"{suspect}"
        )


# 字幕数据结构与格式转换在 core.subtitles 里（不依赖 torch），这里原样再导出，
# 保证 `from core.transcribe import SubtitleCue` 等旧写法继续有效。
from .subtitles import (  # noqa: F401
    ELLIPSIS_ONLY_RE,
    SRT_TIME_LINE_RE,
    SubtitleCue,
    cues_to_srt,
    cues_to_txt,
    cues_to_vtt,
    format_duration,
    format_srt_timestamp,
    format_time_tag,
    format_vtt_timestamp,
    is_ellipsis_only,
    parse_srt_timestamp,
    parse_time_str,
    remove_ellipsis_only_cues,
    srt_to_cues,
)


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



def decode_wav_16k(
    input_path: str | Path,
    output_wav: str | Path,
    enable_loudnorm: bool = True,
    start_time_s: float | None = None,
    end_time_s: float | None = None,
    cancel_event=None,
) -> None:
    """真正调用 ffmpeg 解码出 16k mono wav（缓存层与降级路径共用）。

    ``cancel_event`` 可以是 ``threading.Event`` 或 ``jobs.CancelToken``；
    ``run_command`` 会轮询它并在取消/超时时终止 ffmpeg 子进程。
    """
    cmd = ["ffmpeg", "-y", "-nostdin"]

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

    try:
        proc = run_command(
            cmd,
            timeout=FFMPEG_DECODE_TIMEOUT_S,
            cancel_event=cancel_event,
        )
    except CommandCancelled:
        raise
    except CommandTimeout as exc:
        raise RuntimeError(
            f"ffmpeg 解码超时（>{FFMPEG_DECODE_TIMEOUT_S:.0f}s）：{tail(exc.stderr)}"
        ) from exc
    except Exception as exc:
        log.warning("主解码命令启动失败，尝试回退：%s", exc)
        proc = None

    if proc is not None and proc.returncode == 0:
        return

    if proc is not None:
        log.warning(
            "主解码命令返回 %s，尝试回退：%s",
            proc.returncode,
            tail(proc.stderr, 800),
        )

    fallback_cmd = ["ffmpeg", "-y", "-nostdin"]
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
    try:
        fallback_proc = run_command(
            fallback_cmd,
            timeout=FFMPEG_DECODE_TIMEOUT_S,
            cancel_event=cancel_event,
        )
    except CommandCancelled:
        raise
    except CommandTimeout as exc:
        raise RuntimeError(
            f"ffmpeg 解码超时（>{FFMPEG_DECODE_TIMEOUT_S:.0f}s）：{tail(exc.stderr)}"
        ) from exc
    if fallback_proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 提取音频失败:\n{tail(fallback_proc.stderr)}")


def extract_audio_16k(
    input_path: str | Path,
    output_wav: str | Path | None = None,
    enable_loudnorm: bool = True,
    start_time_s: float | None = None,
    end_time_s: float | None = None,
    cancel_event=None,
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
                cancel_event=cancel_event,
            )
        except CommandCancelled:
            # 取消不应触发“回退为现场解码”——那等于无视用户的取消。
            raise
        except Exception as exc:
            if output_wav is None:
                raise
            logging.warning("音频缓存不可用，回退为现场解码：%s", exc)

    if output_wav is None:
        raise ValueError("未启用音频缓存时必须提供 output_wav 路径")
    decode_wav_16k(
        input_path,
        output_wav,
        enable_loudnorm,
        start_time_s,
        end_time_s,
        cancel_event=cancel_event,
    )
    return Path(output_wav)


def load_audio_for_transcription(
    media_path: str | Path,
    *,
    enable_loudnorm: bool = True,
    start_time_s: float | None = None,
    end_time_s: float | None = None,
    tmp_prefix: str = "kikusub-",
    cancel_event=None,
) -> np.ndarray:
    """取送模用的 16k 单声道数组：缓存开启时直接读缓存，关闭时走临时目录。"""
    if audio_cache.enabled():
        wav_path = extract_audio_16k(
            media_path,
            None,
            enable_loudnorm=enable_loudnorm,
            start_time_s=start_time_s,
            end_time_s=end_time_s,
            cancel_event=cancel_event,
        )
        return load_wav_mono(wav_path)

    with tempfile.TemporaryDirectory(prefix=tmp_prefix) as tmp:
        wav_path = extract_audio_16k(
            media_path,
            Path(tmp) / "audio_16k.wav",
            enable_loudnorm=enable_loudnorm,
            start_time_s=start_time_s,
            end_time_s=end_time_s,
            cancel_event=cancel_event,
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
    audio: np.ndarray | None = None,
    cut_snap_s: float = CUT_SNAP_S,
    snap_stats: dict | None = None,
) -> list[tuple[int, int]]:
    """VAD 段合并 + 超长段强制切分。

    注意：首尾留白不在这里处理。Silero 的 `speech_pad_ms` 已经在 VAD 阶段把留白
    并进了每个 stamp 的边界，此处再收一个 `speech_pad_s` 只会让人误以为"留白参与
    了合并判断"——该参数此前收而未用，已删除。
    """
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


def chunk_level_stats(chunk: np.ndarray | None) -> dict:
    """该段音频的峰值与有效值，供漏句告警降噪使用（E5）。

    模型对「VAD 判成语音、实际是静音/底噪」的段同样会返回空或占位符，这类段进
    漏句清单是纯噪声（实测 2 条记录的 RMS 处于全片 VAD 段的第 5/6 百分位）。
    把 peak / rms 记进记录，报告层就能只展示「真有声音却没出字」的那些。
    """
    if chunk is None or getattr(chunk, "size", 0) == 0:
        return {"peak": 0.0, "rms": 0.0}
    data = np.asarray(chunk, dtype=np.float64)
    return {
        "peak": round(float(np.max(np.abs(data))), 4),
        "rms": round(float(np.sqrt(np.mean(data ** 2))), 5),
    }


def vad_neg_threshold(threshold: float) -> float:
    """VAD 退出阈值：与 Silero 默认迟滞（threshold - 0.15）一致，但不低于下限。"""
    return max(float(threshold) - 0.15, VAD_NEG_THRESHOLD_FLOOR)


def detect_speech_stamps(
    audio: np.ndarray,
    vad,
    *,
    threshold: float,
    min_speech_ms: int,
    min_silence_ms: int,
    speech_pad_ms: int,
    window_s: float = VAD_WINDOW_S,
    overlap_s: float = VAD_WINDOW_OVERLAP_S,
) -> list[dict]:
    """分窗跑 Silero VAD，返回按样本计的语音段（已消掉重叠窗的重复段）。

    为什么要分窗：Silero 是带隐状态的流式模型，`get_speech_timestamps` 对整段
    音频一次跑完时，越往后隐状态漂移越明显。830s 耳语素材上实测：整段一次跑，
    461.8–463.8s 那段概率稳定在 0.4–0.9 的台词被判成静音（阈值降到 0.08 也检不出）；
    把同一段放进 30s 窗内重跑则稳定命中。分窗后每窗 `reset_states()`，
    结果不再依赖「前面播了多少」。

    `audio` 是 float32 的一维数组；返回的 start/end 是**整段音频内的样本下标**。
    """
    audio = np.asarray(audio)
    total = len(audio)
    if total == 0:
        return []

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


def _frame_rms(audio: np.ndarray) -> np.ndarray:
    """逐帧 RMS（帧长 32ms / 步长 10ms，与 Silero 的窗口一致）。

    分块计算：830s 素材展开成 8 万个帧，一次性 `mean` 会临时吃掉 ~170MB，
    而这里只需要一维结果。帧视图本身是 stride 视图，不复制音频。
    """
    if audio.size < ONSET_FRAME:
        return np.zeros(0, dtype=np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(
        np.asarray(audio, dtype=np.float32), ONSET_FRAME
    )[::ONSET_HOP]
    out = np.empty(len(frames), dtype=np.float32)
    block = 4096
    for start in range(0, len(frames), block):
        chunk = frames[start : start + block]
        out[start : start + block] = np.sqrt(np.mean(np.square(chunk), axis=1))
    return out


def _db_to_gain(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def _gate_threshold(
    gate: str,
    *,
    noise: float,
    peak: float,
) -> float:
    """回看窗的准入阈值（RMS）。三种闸门的定义见路线文档 P0-1 的 A/B 矩阵。"""
    if gate == ONSET_GATE_SNR:
        return noise * _db_to_gain(ONSET_SNR_DB)
    if gate == ONSET_GATE_SNR_CAP:
        low = noise * _db_to_gain(ONSET_SNR_DB)
        high = noise * _db_to_gain(ONSET_CAP_DB)
        # 注意是 clamp 不是 max：段内一声大声喘息会把 peak×0.08 抬起来，
        # 用 max 就防不住「峰值带偏」，这一点在路线文档里专门写了。
        return min(max(peak * ONSET_RELATIVE_PEAK, low), high)
    return 0.0


def extend_segment_onsets(
    segments: list[tuple[int, int]],
    audio: np.ndarray,
    *,
    pad_ms: int,
    gate: str = ONSET_GATE_NONE,
    sample_rate: int = SAMPLE_RATE,
    prev_gap_ms: int = ONSET_PREV_GAP_MS,
    stats: dict | None = None,
) -> list[tuple[int, int]]:
    """把每个语音块的起点向左扩，救回被 VAD 吞掉的句首。

    `segments` 是 `merge_vad_segments()` 的输出（样本下标，已按 max_segment_s 切过）。
    左扩在合并**之后**做：先扩再合并会让 0.3–0.5s 的句间空隙消失，两句话被并成
    一个送模块，那是另一种错误。左扩后块长最多 +pad，仍在 ASR 的单段上限（9s/12s）内。

    返回新的块列表；`stats` 里补 `onset_*` 计数，报告与核对台状态行直接读它。
    """
    pad_ms = int(max(0, min(pad_ms, ONSET_PAD_MAX_MS)))
    if stats is not None:
        stats.update(
            {
                "onset_pad_ms": pad_ms,
                "onset_gate": gate if pad_ms > 0 else ONSET_GATE_NONE,
                "onset_extended": 0,
                "onset_gated": 0,
                "onset_shift_s": 0.0,
            }
        )
    if pad_ms <= 0 or not segments:
        return list(segments)

    pad_samples = int(sample_rate * pad_ms / 1000)
    gap_samples = int(sample_rate * prev_gap_ms / 1000)
    rms = _frame_rms(audio)
    if rms.size:
        noise = float(np.quantile(rms, ONSET_NOISE_QUANTILE))
    else:
        noise = 0.0

    out: list[tuple[int, int]] = []
    extended = 0
    gated = 0
    shift_total = 0
    prev_end = 0
    for index, (start, end) in enumerate(segments):
        floor_start = prev_end + gap_samples if index else 0
        target = max(0, floor_start, start - pad_samples)
        prev_end = end
        if target >= start:
            out.append((start, end))
            continue
        if gate in (ONSET_GATE_SNR, ONSET_GATE_SNR_CAP) and rms.size:
            # 帧 i 覆盖样本 [i*hop, i*hop+frame)：下标直接除 hop，不用浮点换算。
            # 回看窗只取**完整落在 start 之前**的帧：跨在边界上的那一帧会被
            # 段内语音的能量污染，拿它判闸等于永远放行。
            lo = max(0, target // ONSET_HOP)
            hi = max(lo, (start - ONSET_FRAME) // ONSET_HOP + 1)
            window = rms[lo:hi]
            peak = float(
                rms[max(0, start // ONSET_HOP) : max(0, end // ONSET_HOP) + 1].max(initial=0.0)
            )
            threshold = _gate_threshold(gate, noise=noise, peak=peak)
            if window.size and float(window.max()) < threshold:
                gated += 1
                out.append((start, end))
                continue
        extended += 1
        shift_total += start - target
        out.append((target, end))

    if stats is not None:
        stats.update(
            {
                "onset_extended": extended,
                "onset_gated": gated,
                "onset_shift_s": round(shift_total / sample_rate / max(extended, 1), 3),
            }
        )
    return out


def strip_edge_nonverbal(text: str) -> str:
    """删掉句首/句尾的非台词发声（笑声、喘气、亲吻声），句中一律不动。"""
    return strip_edge_nonverbal_ex(text)[0]


def strip_edge_nonverbal_ex(text: str) -> tuple[str, bool, bool]:
    """同 `strip_edge_nonverbal`，另外告诉调用方「句首/句尾是否真的删掉了东西」。

    这两个布尔是给时间轴用的：删掉句首的「んふふ」以后，如果字幕起点还停在笑声
    开始的位置，观众会先看到一条两秒空着的字幕（真踩过）。调用方据此把起点挪到
    真正开始说话的位置（见 `_speech_bounds`）。
    """
    if not text:
        return text, False, False
    lead = _EDGE_LEAD_RE.sub("", text)
    head_removed = len(lead) != len(text)
    out = _EDGE_TAIL_RE.sub("", lead)
    tail_removed = len(out) != len(lead)
    # 只清掉句读与空白；句尾的「…」是语义，不能跟着发声一起删
    return out.strip("、。 　"), head_removed, tail_removed


def _low_prob_runs(
    probs: list[float],
    frame_s: float,
    low: float,
) -> list[tuple[float, float]]:
    """把 VAD 概率里的「低概率连续段」抽出来，单位秒（相对切片起点）。"""
    runs: list[tuple[float, float]] = []
    start: int | None = None
    for i, prob in enumerate(probs):
        if prob < low:
            if start is None:
                start = i
        elif start is not None:
            runs.append((start * frame_s, i * frame_s))
            start = None
    if start is not None:
        runs.append((start * frame_s, len(probs) * frame_s))
    return runs


def _refine_bounds_by_pauses(
    chunk: np.ndarray,
    vad,
    *,
    head_removed: bool,
    tail_removed: bool,
    sample_rate: int = SAMPLE_RATE,
    low: float = 0.15,
    min_pause_s: float = 0.15,
) -> tuple[float, float]:
    """句首/句尾发声被删掉后，把字幕边界挪到段内的停顿处。

    只看「删掉了哪一侧」：删了句首的「んふふ」，起点要挪到笑声之后的那次停顿
    （否则观众先看到一条空字幕）；删了句尾的喘气，终点同理往回收。

    判据用 Silero 自己给的概率曲线，而不是能量：耳语素材里笑声往往比台词还响，
    按能量裁会把笑声留下、把轻声台词裁掉（2026-11-13 实测：段首笑声 RMS 0.24、
    台词峰值 0.35，相对能量法整段裁错）。

    返回 (head_s, tail_s)，表示相对切片起点保留的起止秒数；找不到可信停顿就返回
    整段（即不改边界）——宁可字幕长一点，也不要靠猜把台词切掉。
    """
    dur = chunk.size / sample_rate if chunk.size else 0.0
    head, tail = 0.0, dur
    if dur <= 0:
        return head, tail
    window = 512
    probs = [
        float(vad(torch.from_numpy(chunk[i : i + window]), sample_rate))
        for i in range(0, chunk.size - window + 1, window)
    ]
    if not probs:
        return head, tail
    frame_s = window / sample_rate
    runs = [r for r in _low_prob_runs(probs, frame_s, low) if r[1] - r[0] >= min_pause_s]

    if head_removed:
        # 只认「前半段里最后一次停顿」：它是笑声/喘气与台词之间那道缝。
        # 收得太松会把句中换气当成句首，起点一挪就吃字（cps 飙到 16 的那种）。
        candidates = [r for r in runs if dur * 0.08 < r[1] < dur * 0.6]
        if candidates:
            head = max(r[1] for r in candidates)

    if tail_removed:
        # 对称：只认「后半段里第一次停顿」，且必须离新的起点还有一段话
        candidates = [r for r in runs if r[0] > max(dur * 0.55, head + 0.5)]
        if candidates:
            tail = min(r[0] for r in candidates)

    if tail - head < 0.6:
        return 0.0, dur
    return head, tail


_MEANINGLESS_CHARS = set("っッー〜~・、。…！？!?♪「」『』（） ")


def is_nonverbal_only(text: str, dur_s: float = 0.0) -> bool:
    """整条只剩发声/纯符号碎片时返回 True。

    注意：**单个假名不算碎片**。「え？」「ん…」在动画里是正常台词，丢了就是漏句；
    只有内容全是符号/促音/长音符这类没有语义的东西才丢。
    例外是「一个假名却占了 2 秒以上」——那是 VAD 把一段呼吸/杂音判成了语音，
    真实的一句「え？」不会拖这么久。
    """
    compact = (text or "").strip("　 ")
    if not compact:
        return True
    core = _EDGE_TAIL_RE.sub("", _EDGE_LEAD_RE.sub("", compact))
    core = "".join(ch for ch in core if ch not in _MEANINGLESS_CHARS)
    if not core:
        return True
    return len(core) <= 1 and dur_s > 2.0


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


# 幻觉复核的命中原由（报告里显示为中文标签，见 app.HALLUCINATION_RULE_LABELS）
HALLUCINATION_REPEAT = "repeat"
HALLUCINATION_SHORT = "short"
HALLUCINATION_LOW_DENSITY = "low-density"


def hallucination_risk_reason(text: str, dur_s: float) -> str:
    """判断一段解码结果是否值得用“带时间戳”模式复核，返回命中的判据。

    返回空串表示不触发复核；否则返回下面三取一：

    - ``repeat``：病理性复读（去标点后同一 1–4 字单元连续 >=6 次）；
    - ``short``：时长 <1.2s 且至少 2 字——正常短句（「はい」）在时间戳模式下
      会保留，噪声/音乐段通常被解成「…」；
    - ``low-density``：时长 >=2s 却只有 <0.8 字/秒（8 秒只出 3 字），大概率非对白段。

    这里只判“要不要复核”，不判“是不是幻觉”——是否丢弃由时间戳复核决定。
    """
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return ""
    # 复读常带标点（「じゅるっ、じゅるっ、…」），先去掉标点再匹配连续单元。
    repeat_probe = re.sub(r"[\s、。．，,\.!?！？…‥・〜]+", "", text or "")
    if REPEATED_CHUNK_RE.search(repeat_probe):
        return HALLUCINATION_REPEAT
    # 短段（<0.8s）无论字数多少都复核：正常短句在时间戳模式下会保留，
    # 噪声/音乐段通常解成「…」。门槛不能放到 1.2s——「いいよー」这种 1.0s 的
    # 正常短句会被时间戳复核判空而整条丢掉（2026-11-13 实测踩到）。
    if dur_s < 0.8 and len(compact) >= 2:
        return HALLUCINATION_SHORT
    # 长段却只吐出极少量字（「…信じる」3 字 / 8 秒）：大概率是非对白段。
    if dur_s >= 2.0 and len(compact) / dur_s < 0.8:
        return HALLUCINATION_LOW_DENSITY
    return ""


def hallucination_risk(text: str, dur_s: float, chunk: np.ndarray | None = None) -> bool:
    """兼容旧调用：只要命中任一复核判据就返回 True（``chunk`` 已不再参与判断）。"""
    return bool(hallucination_risk_reason(text, dur_s))


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


def nearest_text_cut(text: str, target: int) -> int:
    """在文本里挑一个最接近 `target` 的**自然**切点（返回切点下标，0 表示找不到）。

    三档优先级，同档内取离 target 最近的那个：
    1. 标点后（、。！？…）——最自然；
    2. 助词后（は が を に で と て へ も の や）——用户指定的兜底口径；
    3. 任何未被禁则挡住的位置。

    禁则（`forbidden_cut_positions`）一律不破：小假名、长音符、汉字连写、词内等位置
    永远不选，宁可不切也不把词劈开。
    """
    n = len(text)
    if n < 4:
        return 0
    blocked = forbidden_cut_positions(text)
    punct: list[int] = []
    particle: list[int] = []
    anypos: list[int] = []
    for p in range(2, n - 1):  # 两侧都至少留 2 字，避免切出「は」「を」这种碎片
        if blocked[p]:
            continue
        anypos.append(p)
        prev_ch = text[p - 1]
        if prev_ch in _HARD_SPLIT_PUNCT:
            punct.append(p)
        elif prev_ch in _CUE_SPLIT_PARTICLES:
            particle.append(p)
    for tier in (punct, particle, anypos):
        if tier:
            return min(tier, key=lambda p: (abs(p - target), p))
    return 0


def _split_overlong_single(
    text: str,
    t0: float,
    t1: float,
    max_cue_dur: float,
    *,
    audio: np.ndarray | None = None,
    sample_rate: int = SAMPLE_RATE,
    char_times: list[tuple[float, float]] | None = None,
    depth: int = 0,
) -> list[tuple[float, float, str]]:
    """把「只有一句、但时长超过 max_cue_dur」的段拆成多条，返回 (start, end, text)。

    关键约束（用户口径）：**不允许脱离文本按时间对半硬切**。切点先从文本里选
    （标点后 > 助词后 > 合法位置，见 `nearest_text_cut`），时间再跟着文本走：

    1. 有字级/词级时间戳（Qwen CTC 路径）→ 直接用该字的时间边界；
    2. 没有时间戳但有音频（Whisper 路径）→ 按字符比例定位，再吸附到 ±0.35s 内的
       发音能量谷（`_energy_valley_cut`）；
    3. 两者都没有 → 纯按字符比例分配（仍然不是时间对半）。

    任一侧剩余时长不足 0.45s、或文本里找不到合法切点，就**不切**——宁可留一条
    超长字幕，也不制造半秒碎片或劈开词。
    """
    dur = t1 - t0
    if dur <= max_cue_dur or len(text) < 4 or depth >= 4:
        return [(t0, t1, text)]

    n = len(text)
    cut = nearest_text_cut(text, int(round(n / 2)))
    if cut <= 0:
        return [(t0, t1, text)]


    head, tail = text[:cut], text[cut:]

    if char_times is not None and len(char_times) >= n:
        cut_t = t0 + float(char_times[cut - 1][1])
    else:
        cut_t = t0 + dur * (cut / n)
        if audio is not None and audio.size:
            frame = max(1, int(sample_rate * CUT_SNAP_FRAME_MS / 1000))
            centre = int((cut_t - t0) * sample_rate)
            # 搜索窗 ±0.60s：语速与标点停顿的偏差通常在这个量级内；
            # 窗太窄（±0.35s）会漏掉真正的停顿，退化成按字符比例硬分。
            lo = max(0, centre - int(0.60 * sample_rate))
            hi = min(int(audio.size), centre + int(0.60 * sample_rate))
            if hi - lo >= 3 * frame:
                valley = _energy_valley_cut(audio, lo, hi, frame)
                # 返回 hi 表示窗口内没有显著能量谷（连续说话），保留按字符比例的位置
                if valley != hi:
                    cut_t = t0 + valley / sample_rate

    if cut_t - t0 < 0.45 or t1 - cut_t < 0.45:
        return [(t0, t1, text)]

    return _split_overlong_single(
        head, t0, cut_t, max_cue_dur,
        audio=audio, sample_rate=sample_rate, char_times=char_times, depth=depth + 1,
    ) + _split_overlong_single(
        tail, cut_t, t1, max_cue_dur,
        audio=audio, sample_rate=sample_rate, char_times=char_times, depth=depth + 1,
    )


def _cap_cue_durations(
    cues: list[SubtitleCue],
    max_cue_dur: float,
    *,
    audio: np.ndarray | None = None,
    sample_rate: int = SAMPLE_RATE,
    char_times: list[tuple[float, float]] | None = None,
) -> list[SubtitleCue]:
    """把仍超过 `max_cue_dur` 的字幕条再拆一刀（文本切点驱动，不按时间对半）。"""
    out: list[SubtitleCue] = []
    for cue in cues:
        if cue.end - cue.start > max_cue_dur:
            pieces = _split_overlong_single(
                cue.text, cue.start, cue.end, max_cue_dur,
                audio=audio, sample_rate=sample_rate, char_times=char_times,
            )
            out.extend(
                SubtitleCue(start=round(a, 3), end=round(b, 3), text=t) for a, b, t in pieces
            )
        else:
            out.append(cue)
    return out


def split_text_into_cues(
    text: str,
    seg_start: float,
    seg_end: float,
    max_cue_dur: float = 4.2,
    max_cue_chars: int = 20,
    *,
    audio: np.ndarray | None = None,
    sample_rate: int = SAMPLE_RATE,
    char_times: list[tuple[float, float]] | None = None,
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
            if not sub:
                sub = [p]
            for piece in sub:
                # 逗号再切后仍超宽的片段（无标点长句 / 一口气说完的台词）走禁则兜底，
                # 否则这一条会以超长单行的形式直接进成品。
                if len(piece) > max_cue_chars:
                    refined_parts.extend(_hard_split_text(piece, max_cue_chars))
                else:
                    refined_parts.append(piece)
        else:
            refined_parts.append(p)

    if not refined_parts:
        return [SubtitleCue(start=round(seg_start, 3), end=round(seg_end, 3), text=clean_text)]

    num_parts = len(refined_parts)
    if num_parts == 1:
        # 单句：先按整段返回，超长部分统一交给末尾的 _cap_cue_durations 处理
        # （旧行为是直接返回、忽略 max_cue_dur，实测最长 6.10s、10 条 >4.3s）。
        cues = [SubtitleCue(start=round(seg_start, 3), end=round(seg_end, 3), text=refined_parts[0])]
        return _cap_cue_durations(cues, max_cue_dur, audio=audio, sample_rate=sample_rate,
                                  char_times=char_times)

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

    cues = []
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

    # 权重分配只看字数，遇到「一句很长 + 一句很短」的段，长的那条仍可能超上限
    # （实测主题歌区间出现过两条连续 5.00s）。这里统一再兜一刀。
    return _cap_cue_durations(cues, max_cue_dur, audio=audio, sample_rate=sample_rate,
                              char_times=None)


_TERMINAL_PUNCT = set("。！？!?…")


def merge_fragmented_cues(
    cues: list[SubtitleCue],
    *,
    max_gap_s: float = 0.08,
    max_cue_chars: int = 20,
    max_cue_dur: float = 4.2,
) -> list[SubtitleCue]:
    """把被 VAD 从句子中间切断的相邻残句并回一条。

    分窗 VAD 的代价是会在长音的停顿处切得比整段检测更碎：「いつも見たそうに」+
    「してたもんねー」原本是一句话。这里只并**看起来就是半句**的组合：

    * 两条几乎贴着（间隔 <= max_gap_s），上一句**没有**以句末标点/省略号收尾；
    * 合并后不超过单条字数与时长上限（不放开上限：一旦为了合并把字幕撑到 4.8s，
      在核对台里就成了「超长条」，得不偿失）。

    以「…」结尾一律不并——那是用户明确断开的地方（「出ちゃうね…」/「出ちゃう出ちゃう…」）。
    """
    merged: list[SubtitleCue] = []
    for cue in cues:
        if merged:
            prev = merged[-1]
            gap = cue.start - prev.end
            tail = prev.text.rstrip()
            combined = prev.text + cue.text
            if (
                -0.02 <= gap <= max_gap_s
                and tail
                and tail[-1] not in _TERMINAL_PUNCT
                and len(combined) <= max_cue_chars
                and cue.end - prev.start <= max_cue_dur + 0.6
            ):
                merged[-1] = SubtitleCue(start=prev.start, end=cue.end, text=combined)
                continue
        merged.append(cue)
    return merged


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
        self.last_coverage_spans: list[dict] = []
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

        with _MODEL_LOAD_LOCK:
            # 双检：等锁期间另一个线程可能已经加载完成。
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
                pipe = pipeline("automatic-speech-recognition", dtype=self.dtype, **pipe_kwargs)
            except TypeError:
                pipe = pipeline("automatic-speech-recognition", torch_dtype=self.dtype, **pipe_kwargs)

            if hasattr(pipe, "tokenizer") and pipe.tokenizer is not None:
                pipe.tokenizer.clean_up_tokenization_spaces = False

            if hasattr(pipe.model, "generation_config") and pipe.model.generation_config is not None:
                pipe.model.generation_config.forced_decoder_ids = None
            # 最后再赋值：加载中途失败时 _pipe 保持 None，下一次还能重试。
            self._pipe = pipe

    def _aligned_pass(
        self,
        pending: list[tuple[int, int, str, float, float]],
        audio: np.ndarray,
        cfg: "WhisperVadConfig",
        stats: dict,
        progress_cb=None,
    ) -> list[SubtitleCue]:
        """第二遍：**先卸掉 Whisper**，再借 Qwen 的 CTC 对齐头切条。

        顺序是硬要求：release() 必须在 ensure_loaded() 之前，否则 6.7GB（Whisper）
        + 5.1GB（对齐器）会同时常驻。对齐器是纯推理借用，用完立刻 unload()；
        任何一段对齐失败都回退到原来的按字数分配，绝不丢已识别的文本。
        """
        from .align_layer import LAYER
        from .qwen_ctc import QwenCtcConfig

        # 对齐层给的是「真实发声边界」，字幕还要按人工核验版的观影惯例补留白：
        # 提前 0.18s、句尾多停 0.43s，剩下的 0.02 由 apply_cue_padding 用用户自己的
        # cue_pad_s 补上（默认 0.02 → 合计 0.20 / 0.45）。
        cue_cfg = QwenCtcConfig(
            max_cue_dur=cfg.max_cue_dur,
            max_cue_chars=cfg.max_cue_chars,
            strip_nonverbal_edges=cfg.strip_nonverbal_edges,
            cue_pad_start_s=0.18,
            cue_pad_end_s=0.43,
        )
        self.release()
        ready = LAYER.ensure_loaded(progress_cb)
        out: list[SubtitleCue] = []
        total = len(pending)
        try:
            for i, (start, end, text, seg_start_s, seg_end_s) in enumerate(pending, start=1):
                if progress_cb and i % 20 == 1:
                    progress_cb(
                        0.9 + 0.05 * (i - 1) / max(total, 1),
                        f"正在对齐第 {i}/{total} 段…",
                    )
                chunk = audio[start:end]
                if ready:
                    outcome = LAYER.split(chunk, text, offset=seg_start_s, cue=cue_cfg)
                    if outcome.ok and outcome.cues:
                        stats["segments"] += 1
                        stats["chars"] += len(text)
                        out.extend(outcome.cues)
                        continue
                stats["degraded"] += 1
                out.extend(
                    split_text_into_cues(
                        text,
                        seg_start_s,
                        seg_end_s,
                        max_cue_dur=cfg.max_cue_dur,
                        max_cue_chars=cfg.max_cue_chars,
                        audio=chunk,
                        sample_rate=SAMPLE_RATE,
                    )
                )
        finally:
            # 无论成功、失败还是被取消，都不能把 5GB 的对齐器留在显存里。
            LAYER.unload()
        return out

    def release(self) -> None:
        """卸掉权重，把内存让给别的模型。

        `whisper.use_ctc_alignment` 打开时，对齐层要再装一份 Qwen（实测 MPS 4.3GB）。
        6.7GB + 5.1GB 同时常驻会在 16GB 机器上把系统挤到换页，所以对齐这一遍
        **必须先卸掉 Whisper 再加载对齐器**（`_aligned_pass` 里按这个顺序调）。
        """
        if self._pipe is None:
            return
        with _MODEL_LOAD_LOCK:
            self._pipe = None
            gc.collect()
            if self.device == "mps":
                try:
                    torch.mps.empty_cache()
                except Exception:
                    log.debug("释放 MPS 缓存失败", exc_info=True)
            log.info("Anime Whisper 权重已卸载（让位给对齐层）")

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
        self.last_coverage_spans = []
        cfg = config or self.config
        media_path = Path(media_path)
        if progress_cb:
            slice_desc = f"（片段：{start_time_s or 0.0:.1f}s ~ {end_time_s:.1f}s）" if end_time_s else ""
            progress_cb(0.02, f"正在提取 16kHz 音频并进行动态响度优化{slice_desc}…")
        audio = None
        try:
            audio = load_audio_for_transcription(
                media_path,
                enable_loudnorm=cfg.enable_loudnorm,
                start_time_s=start_time_s,
                end_time_s=end_time_s,
                tmp_prefix="anime-whisper-",
                cancel_event=cancel_event,
            )
        except CommandCancelled:
            self.last_interrupted = True
            if progress_cb:
                progress_cb(0.99, "🛑 已取消音频解码…")
            return []
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
        self.last_coverage_spans = []
        self.last_segment_stats = {}
        stamps = detect_speech_stamps(
            audio,
            self._vad,
            threshold=float(cfg.threshold),
            min_speech_ms=int(cfg.min_speech_ms),
            min_silence_ms=int(cfg.min_silence_ms),
            speech_pad_ms=int(cfg.speech_pad_ms),
        )
        raw_speech_s = sum((s["end"] - s["start"]) for s in stamps) / SAMPLE_RATE
        segments = merge_vad_segments(
            stamps,
            max_segment_s=min(float(cfg.max_segment_s), MAX_SEGMENT_S_LIMIT),
            merge_gap_s=float(cfg.merge_gap_s),
            min_speech_s=float(cfg.min_speech_s),
            audio=audio,
            snap_stats=self.last_segment_stats,
        )
        # 句首补回在合并之后：先扩再合并会把 0.3–0.5s 的句间空隙填掉，
        # 两句话被并成一个送模块。`0` 时原样返回，不改变任何旧行为。
        segments = extend_segment_onsets(
            segments,
            audio,
            pad_ms=int(cfg.onset_pad_ms),
            gate=str(getattr(cfg, "onset_gate", ONSET_GATE_NONE) or ONSET_GATE_NONE),
            stats=self.last_segment_stats,
        )
        if not segments:
            # VAD 没命中任何语音时**不要**把整段音频兜底送模。
            # 旧行为 segments = [(0, len(audio))] 会把静音/雨声/纯音乐整段交给
            # Whisper，模型在这类非语音输入上会稳定地产出「すぅう…」这类幻觉字幕，
            # 而且能突破 max_segment_s（实测 30s 静音段直接送模）。
            # 这里返回空结果，由上层统一提示「未检测到有效语音」。
            if progress_cb:
                progress_cb(0.95, "未检测到有效语音（VAD 未命中任何语音段）…")
            self.last_stats = VadStats(audio_s=len(audio) / SAMPLE_RATE)
            return []

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

        def _decode(buf: np.ndarray, *, timestamps: bool = False) -> str:
            res = self._pipe(
                {"array": buf, "sampling_rate": SAMPLE_RATE},
                generate_kwargs=generate_kwargs,
                return_timestamps=bool(timestamps),
            )
            return (res.get("text") or "").strip()

        hallucination_drops = 0
        suspect_cues = 0
        nonverbal_skips = 0
        aligned_stats = {"segments": 0, "chars": 0, "degraded": 0}
        # 走对齐层时段落先排队，循环结束后统一处理（前后两遍不共用显存）
        pending: list[tuple[int, int, str, float, float]] = []
        # 逐段留档：报告里的【幻觉门控】/【幻觉复核】直接列这些记录，
        # 不再只把明细打到终端。字段与漏句记录保持同一形状，便于对照。
        hallucination_spans: list[dict] = []
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
            head_removed = tail_removed = False
            if cfg.strip_nonverbal_edges:
                text, head_removed, tail_removed = strip_edge_nonverbal_ex(text)
            reason = ""
            if _is_blank(text):
                if cancel_event and cancel_event.is_set():
                    self.last_interrupted = True
                    if progress_cb:
                        progress_cb(0.99, f"🛑 用户已中途取消，正在保存前 {len(cues)} 条字幕…")
                    break
                text = _decode(_retry_gain(chunk))
                head_removed = tail_removed = False
                if cfg.strip_nonverbal_edges:
                    text, head_removed, tail_removed = strip_edge_nonverbal_ex(text)
                if not _is_blank(text) and _retry_suspicious(text, seg_dur_s, prev_text):
                    text, reason = "", "retry-suspicious"
                elif _is_blank(text):
                    reason = "empty-after-retry"

            # 删掉了句首/句尾的发声，就把字幕边界挪到段内的停顿处：
            # 否则「んふふ」占了 2 秒，字幕会提前两秒空着出现（用户报障过）。
            if (head_removed or tail_removed) and not _is_blank(text):
                head_off, tail_off = _refine_bounds_by_pauses(
                    chunk,
                    self._vad,
                    head_removed=head_removed,
                    tail_removed=tail_removed,
                )
                seg_start_s = (start / SAMPLE_RATE) + head_off + time_offset
                seg_end_s = (start / SAMPLE_RATE) + tail_off + time_offset
                seg_dur_s = max(0.05, tail_off - head_off)

            if (
                cfg.strip_nonverbal_edges
                and not _is_blank(text)
                and is_nonverbal_only(text, seg_dur_s)
            ):
                # 纯喘气/笑声：删掉端点的发声后什么都不剩，不该占一条字幕，
                # 也不该进漏句清单（它本来就不是台词）。
                nonverbal_skips += 1
                log.debug("跳过非台词发声段 | %.2fs | %r", seg_dur_s, text[:40])
                continue

            rule = hallucination_risk_reason(text, seg_dur_s) if not _is_blank(text) else ""
            if rule:
                try:
                    verified = _decode(chunk, timestamps=True)
                except Exception:
                    log.debug("时间戳复核失败，保留原结果", exc_info=True)
                    verified = text
                record = {
                    "start": round(seg_start_s, 3),
                    "end": round(seg_end_s, 3),
                    "dur": round(seg_dur_s, 2),
                    "text": text.strip()[:80],
                    "rule": rule,
                    **chunk_level_stats(chunk),
                }
                if _is_blank(verified):
                    hallucination_drops += 1
                    hallucination_spans.append({**record, "verdict": "dropped"})
                    # 明细进报告（【幻觉门控】），终端只在 debug 留底
                    log.debug(
                        "丢弃疑似幻觉段 | %.2fs | rule=%s | %r",
                        seg_dur_s,
                        rule,
                        text[:60],
                    )
                    continue
                suspect_cues += 1
                hallucination_spans.append({**record, "verdict": "suspect"})
                log.debug(
                    "疑似幻觉（保留待复核） | %.2fs | rule=%s | %r",
                    seg_dur_s,
                    rule,
                    text[:60],
                )

            if _is_blank(text):
                self.last_missed_spans.append({
                    "start": round(seg_start_s, 3),
                    "end": round(seg_end_s, 3),
                    "dur": round(seg_end_s - seg_start_s, 2),
                    "reason": reason or "empty-after-retry",
                    **chunk_level_stats(chunk),
                })
                continue
            prev_text = text

            if cfg.use_ctc_alignment:
                # 只排队，不对齐：对齐器要多占 5GB，必须等 Whisper 卸掉再加载，
                # 否则两份大模型会同时常驻（见 release()）。
                pending.append((start, end, text, seg_start_s, seg_end_s))
                continue
            if cfg.enable_sentence_split:
                sub_cues = split_text_into_cues(
                    text,
                    seg_start_s,
                    seg_end_s,
                    max_cue_dur=cfg.max_cue_dur,
                    max_cue_chars=cfg.max_cue_chars,
                    audio=chunk,
                    sample_rate=SAMPLE_RATE,
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

        if pending:
            if progress_cb and not self.last_interrupted:
                progress_cb(0.9, f"正在对齐第 1/{len(pending)} 段（卸下 Whisper 后借用 Qwen 对齐头）…")
            cues.extend(self._aligned_pass(pending, audio, cfg, aligned_stats, progress_cb))
            self.last_segment_stats["ctc_alignment"] = dict(aligned_stats)

        cues = merge_fragmented_cues(
            cues,
            max_cue_chars=cfg.max_cue_chars,
            max_cue_dur=cfg.max_cue_dur,
        )
        cues = apply_cue_padding(cues, cfg.cue_pad_s, (len(audio) / SAMPLE_RATE) + time_offset)

        # 覆盖审计：只读旁路，不影响上面任何一条字幕。主 VAD 没切到的空白
        # 在这里才有可能被看见；局部归一化后再跑一次 Silero 只用于打分。
        if not self.last_interrupted and cues:
            try:
                self.last_coverage_spans = find_coverage_spans(
                    audio, cues, self._vad, time_offset=time_offset
                )
            except Exception:
                log.debug("覆盖审计失败（不影响转写）", exc_info=True)

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
            hallucinations=hallucination_drops,
            suspect_cues=suspect_cues,
        )
        self.last_segment_stats["nonverbal_skips"] = nonverbal_skips
        self.last_segment_stats["hallucination_drops"] = hallucination_drops
        self.last_segment_stats["suspect_cues"] = suspect_cues
        self.last_segment_stats["hallucination_spans"] = hallucination_spans

        if progress_cb and not self.last_interrupted:
            progress_cb(0.98, "正在整理字幕…")
        return cues


ENGINE = AnimeWhisperEngine()
