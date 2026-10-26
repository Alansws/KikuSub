"""Qwen3-ASR (日语动漫/影视/游戏模型) 与 CTC 逐字对齐对齐头。

功能特性：
- 单次前向同时完成文本转写与发声帧 CTC 逐字时间轴对齐
- 动态 Silero VAD 语音分段与电影响度归一化 (Loudnorm)
- 支持视频起止时间切片精准提取与全局时间轴对齐
- 支持中途打断取消并实时抢救已识别的部分字幕
- 日语语法停顿与助词防劈词动态规划分句
- 字幕边界平滑缝合保护器 (_heal_broken_cues)
"""

from __future__ import annotations

import logging
import os
import threading
import unicodedata
import warnings
from dataclasses import dataclass, field
from pathlib import Path

warnings.filterwarnings("ignore", message=".*torch.jit.load is deprecated.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="torch.*")
warnings.filterwarnings("ignore", message=".*processor_kwargs.*")
warnings.filterwarnings("ignore", message=".*Kwargs passed to `processor.__call__`.*")


class _TransformersProcessorFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "processor_kwargs" not in msg and "Kwargs passed to `processor.__call__`" not in msg


logging.getLogger("transformers").addFilter(_TransformersProcessorFilter())

import numpy as np
import torch
import torchaudio
from transformers import logging as hf_logging
hf_logging.set_verbosity_error()
from torch import nn

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

from silero_vad import get_speech_timestamps, load_silero_vad

from transcribe import (
    HONORIFIC_PREFIXES,
    JAPANESE_PARTICLES,
    MODELS_DIR,
    PROLONGED_SOUNDS,
    SAMPLE_RATE,
    SMALL_KANA,
    SubtitleCue,
    _is_blank,
    _is_kana,
    _is_kanji,
    _retry_gain,
    _retry_suspicious,
    _split_overlong_single,
    chunk_level_stats,
    detect_device,
    forbidden_cut_positions,
    load_audio_for_transcription,
    merge_vad_segments,
    split_text_into_cues,
    vad_neg_threshold,
)

REPO_ID = "jaykwok/Qwen3-ASR-1.7B-JA-Anime-Galgame-hf"
HEAD_FILE = "ctc_aligner_jav_vocalisation_v3.pt"

MEL_PER_BLOCK = 100
SECONDS_PER_ENCODER_FRAME = 0.08
UPSAMPLE = 2
FRAME_SECONDS = SECONDS_PER_ENCODER_FRAME / UPSAMPLE
_CONV_STEPS = 3


def _conv_length(length: int) -> int:
    for _ in range(_CONV_STEPS):
        length = (length - 1) // 2 + 1 if length > 0 else 0
    return length


_ZERO_WIDTH_CATEGORIES = {"Pc", "Pd", "Pe", "Pf", "Pi", "Po", "Ps", "Sm", "Sk", "So"}
_ZERO_WIDTH_EXTRA = set("　 \t\n\r─—…‥〜～゛゜")


def _is_zero_width(ch: str) -> bool:
    if ch.isspace() or ch in _ZERO_WIDTH_EXTRA:
        return True
    return unicodedata.category(ch) in _ZERO_WIDTH_CATEGORIES


def fold_text(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text) if not c.isspace())


class FoldedText:
    def __init__(self, text: str) -> None:
        self.original = text
        self.folded = fold_text(text)
        self.orig_index: list[int] | None = []
        chars: list[str] = []
        cursor = 0
        for ch in text:
            if ch.isspace():
                continue
            piece = unicodedata.normalize("NFKC", ch)
            if not piece:
                continue
            chars.append(piece)
            cursor += 1
            self.orig_index.extend([cursor - 1] * len(piece))
        if "".join(chars) != self.folded:
            self.orig_index = None

    def __len__(self) -> int:
        return len(self.folded)

    def slice(self, first: int, stop: int) -> str:
        if self.orig_index is None:
            return self.folded[first:stop]
        return self.original[self.orig_index[first] : self.orig_index[stop - 1] + 1]


def encode_target(
    text: FoldedText, lookup: dict[str, int], unk_index: int
) -> tuple[list[int], list[int | None]]:
    ids: list[int] = []
    char_index: list[int | None] = []
    for pos, ch in enumerate(text.folded):
        idx = lookup.get(ch)
        if _is_zero_width(ch):
            char_index.append(None)
            continue
        if idx is None:
            char_index.append(None)
            ids.append(unk_index)
        else:
            char_index.append(pos)
            ids.append(idx)
    return ids, char_index


class ResidualConvBlock(nn.Module):
    def __init__(self, channels: int, dilation: int) -> None:
        super().__init__()
        self.norm = nn.LayerNorm(channels)
        self.depthwise = nn.Conv1d(
            channels, channels, kernel_size=5, padding=2 * dilation, dilation=dilation, groups=channels
        )
        self.pointwise = nn.Conv1d(channels, channels, kernel_size=1)
        self.activation = nn.GELU()
        self.dropout = nn.Dropout(0.0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.norm(x).transpose(1, 2)
        y = self.pointwise(self.activation(self.depthwise(y)))
        return x + self.dropout(y.transpose(1, 2))


class CtcAlignmentHead(nn.Module):
    def __init__(
        self,
        vocab_size: int,
        input_dim: int = 2048,
        hidden_dim: int = 512,
        upsample: int = 2,
        blocks: int = 4,
        frame_classes: int = 0,
    ) -> None:
        super().__init__()
        self.upsample = upsample
        self.input_norm = nn.LayerNorm(input_dim)
        self.project = nn.Linear(input_dim, hidden_dim)
        self.expand = (
            nn.ConvTranspose1d(hidden_dim, hidden_dim, kernel_size=upsample, stride=upsample)
            if upsample > 1
            else None
        )
        self.blocks = nn.ModuleList([ResidualConvBlock(hidden_dim, dilation=2**i) for i in range(blocks)])
        self.output_norm = nn.LayerNorm(hidden_dim)
        self.classifier = nn.Linear(hidden_dim, vocab_size)
        self.frame_classifier = nn.Linear(hidden_dim, frame_classes) if frame_classes else None

    def trunk(self, features: torch.Tensor) -> torch.Tensor:
        x = self.project(self.input_norm(features))
        if self.expand is not None:
            x = self.expand(x.transpose(1, 2)).transpose(1, 2)
        for block in self.blocks:
            x = block(x)
        return self.output_norm(x)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return nn.functional.log_softmax(self.classifier(self.trunk(features)), dim=-1)

    def forward_with_frames(self, features: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor | None]:
        x = self.trunk(features)
        ctc = nn.functional.log_softmax(self.classifier(x), dim=-1)
        if self.frame_classifier is None:
            return ctc, None
        return ctc, nn.functional.log_softmax(self.frame_classifier(x), dim=-1)


def _load_head_file(model_dir: Path) -> Path:
    local = model_dir / HEAD_FILE
    if local.exists():
        return local
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo_id=REPO_ID, filename=HEAD_FILE, local_dir=str(model_dir)))


def load_alignment_head(model_dir: Path) -> tuple[CtcAlignmentHead, dict]:
    payload = torch.load(_load_head_file(model_dir), map_location="cpu", weights_only=False)
    frame_classes = payload.get("frame_classes") or ()
    head = CtcAlignmentHead(
        vocab_size=payload["vocab"]["size"],
        input_dim=payload["input_dim"],
        hidden_dim=payload["hidden_dim"],
        upsample=payload["upsample"],
        blocks=payload["blocks"],
        frame_classes=len(frame_classes),
    )
    head.load_state_dict(payload["state_dict"])
    head.eval()
    return head, payload


SENTENCE_END = "。！？!?\n"
PAUSE_PUNCT = "、。！？!?…‥，,・：:；;\n"

BREAK_MID_PHRASE = 35.0
BREAK_SENTENCE_END = -6.0
BREAK_COMMA = 0.0
BREAK_FREE = 0.0
BREAK_PARTICLE = 1.2
BREAK_KANJI_KANA_PHRASE = 2.5
BREAK_FORBIDDEN = 1000.0
SEG_BASE_COST = 0.1
OVERRUN_COST = 1.2
MIN_CUE_DUR = 0.04

# 可读性下限（A5）：只影响"在哪切"，不改变任何文本
MIN_CUE_DUR_FLOOR = 0.80   # 单条字幕最短可读时长（秒）
CPS_READABLE = 9.0         # "能读"的下限：字/秒，用于反推最短时长
CPS_COMFORT = 6.5          # "读得舒服"的上限：字/秒
DUR_DEFICIT_COST = 3.0     # 时长缺口：每秒罚分（与硬超时 3.5/s 同量级）
CPS_EXCESS_COST = 0.9      # 语速超额：每字罚分
CPS_EXCESS_CAP = 6.0       # 单条 cps 罚分上限，防止"靠合并掩盖密度"反转目标

# 劈词缝合的时间闸门（问题 6）：只有首尾相接才可能是同一个词被切开
HEAL_MAX_GAP_S = 0.15

# 生成上限自适应（P4）：按送模时长反推 token 上限
TOKENS_PER_SEC = 12        # 日语语速上限约 8 字/秒 × 1.5 余量（汉字/片假名常一字多 token）
TOKENS_HEADROOM = 32       # 句首句尾与标点的固定余量
# 撞上限后"是不是真截断"的判据：字/token。正常日语对白约 1.0–1.7；
# 复读/空转时 token 被同一段反复吃掉，实测可低至 0.01–0.05。
CHARS_PER_TOKEN_FLOOR = 0.5


def classify_capped(n_chars: int, n_gen: int, cap: int) -> tuple[bool, bool]:
    """判断"吃满生成上限"到底是真截断还是复读。

    返回 ``(capped, truncated)``：

    * ``capped``：token 数吃满上限，可能是截断，也可能是复读/空转；
    * ``truncated``：吃满上限**且**字/token 密度正常 —— 说明 token 确实花在字上，
      是上限不够导致末尾被砍，值得加长上限重跑。

    复读时同一段 token 反复循环，解码后只剩几个字（实测 212 token → 3 字，
    密度 0.014），加长上限只会多循环几遍，一个字也救不回来，所以不重跑。
    正常日语对白密度约 1.0–1.7，取 0.5 作保守下限，宁可多跑一次也不漏真截断。
    """
    capped = n_gen >= cap
    if not capped:
        return False, False
    truncated = n_chars >= CHARS_PER_TOKEN_FLOOR * max(n_gen, 1)
    return True, truncated


def _break_costs(folded: FoldedText, positions: list[int]) -> list[float]:
    n = len(positions)
    costs = [BREAK_MID_PHRASE] * (n + 1)
    if n == 0:
        return costs

    rank = {p: i for i, p in enumerate(positions)}
    for p, ch in enumerate(folded.folded):
        if p in rank or ch not in PAUSE_PUNCT:
            continue
        nxt = p + 1
        while nxt < len(folded) and nxt not in rank:
            nxt += 1
        if nxt in rank and rank[nxt] < n:
            if ch in "。！？!?\n":
                costs[rank[nxt]] = BREAK_SENTENCE_END
            else:
                costs[rank[nxt]] = BREAK_COMMA

    text_str = folded.folded
    # 禁切表一次算好：音节级 + 词级硬禁则全部标进 bytearray，
    # 每个候选切点 O(1) 查表，避免"每个切点重扫 35 个词"的平方级开销。
    blocked = forbidden_cut_positions(text_str)
    for i in range(1, n):
        prev_pos, next_pos = positions[i - 1], positions[i]
        # 只在相邻（连续）字符之间判断禁则：positions 跳过零宽字符时，
        # 这个边界不是真实切点，任何禁则判断都无从谈起。
        if next_pos > prev_pos + 1:
            continue
        if blocked[next_pos]:
            costs[i] = BREAK_FORBIDDEN
            continue

        prev_ch = text_str[prev_pos]
        next_ch = text_str[next_pos]

        if prev_ch in JAPANESE_PARTICLES and not (next_ch in SMALL_KANA or next_ch in PROLONGED_SOUNDS):
            costs[i] = BREAK_PARTICLE
            continue

        if not _is_kana(prev_ch) and _is_kana(next_ch):
            costs[i] = BREAK_KANJI_KANA_PHRASE

    return costs


def collapse_token_spans(label_list: list[int], n_ids: int) -> list[tuple[int, int] | None]:
    spans: list[tuple[int, int] | None] = [None] * n_ids
    tok = 0
    frame = 0
    n_frames = len(label_list)
    while frame < n_frames and tok < n_ids:
        label = label_list[frame]
        if label <= 0:
            frame += 1
            continue
        run_end = frame
        while run_end + 1 < n_frames and label_list[run_end + 1] == label:
            run_end += 1
        spans[tok] = (frame, run_end)
        tok += 1
        frame = run_end + 1
    return spans


def _apply_pauses(costs: list[float], char_spans: list["AlignedChar"], pauses, min_pause: float) -> None:
    for start, end in pauses:
        if end - start < min_pause:
            continue
        for i in range(1, len(char_spans)):
            if char_spans[i].start >= end and char_spans[i - 1].end <= start:
                if 0.0 < costs[i] < BREAK_FORBIDDEN:
                    costs[i] = BREAK_FREE
                break


def _fill_unaligned(folded: FoldedText, chars: list["AlignedChar"], audio_end: float) -> list["AlignedChar"]:
    have = {c.pos: c for c in chars}
    out: list[AlignedChar] = []
    for pos, ch in enumerate(folded.folded):
        if pos in have:
            out.append(have[pos])
        elif not _is_zero_width(ch):
            out.append(AlignedChar(pos=pos, char=ch, start=-1.0, end=-1.0))
    if not have or not out:
        return chars

    n = len(out)
    i = 0
    while i < n:
        if out[i].start >= 0.0:
            i += 1
            continue
        j = i
        while j < n and out[j].start < 0.0:
            j += 1
        lo = out[i - 1].end if i > 0 else 0.0
        hi = out[j].start if j < n else max(audio_end, lo)
        width = max(0.0, hi - lo)
        for k in range(i, j):
            t = lo + width * (k - i + 1) / (j - i + 1)
            out[k].start = t
            out[k].end = t
        i = j
    return out


def partition_cues(
    char_spans: list["AlignedChar"],
    costs: list[float],
    max_dur: float,
    max_chars: int,
    hard_max_dur: float,
    soft_max_dur: float = 3.8,
) -> list[list[int]]:
    n = len(char_spans)
    if n == 0:
        return []

    inf = float("inf")
    best = [inf] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for j in range(1, n + 1):
        for i in range(j):
            if best[i] == inf:
                continue
            dur = char_spans[j - 1].end - char_spans[i].start
            if dur > hard_max_dur and j > i + 1:
                continue
            cost = best[i] + (costs[j] if j < n else 0.0) + SEG_BASE_COST
            if dur > soft_max_dur:
                cost += (dur - soft_max_dur) * 1.5
            if dur > max_dur:
                cost += (dur - max_dur) * 3.5
            n_chars = j - i
            if n_chars > max_chars:
                cost += (n_chars - max_chars) * OVERRUN_COST
            if dur > 0:
                # 下限一：时长缺口——"太短"与"太长"对称罚，但量级压在同一档，
                # 保证它只抵消便宜的切分（助词 1.2 / 逗号 0），永远敌不过
                # 句中禁切 35，因此不会为了凑时长把词劈开。
                need = max(MIN_CUE_DUR_FLOOR, n_chars / CPS_READABLE)
                if dur < need:
                    cost += (need - dur) * DUR_DEFICIT_COST
                # 下限二：语速超额——按"多出来的字数"计并单条封顶。
                # 若改成 (cps - 6.5) * k 直接累加，切两条要交两份罚、合成一条只交
                # 一份，DP 会为了省罚分而倾向合并，方向正好相反。
                excess = max(0.0, n_chars - CPS_COMFORT * dur)
                cost += min(excess * CPS_EXCESS_COST, CPS_EXCESS_CAP)
            if cost < best[j]:
                best[j] = cost
                back[j] = i

    if best[n] == inf:
        step = max(1, max_chars)
        return [list(range(i, min(i + step, n))) for i in range(0, n, step)]

    groups: list[list[int]] = []
    j = n
    while j > 0:
        i = back[j]
        groups.append(list(range(i, j)))
        j = i
    groups.reverse()
    return groups


@dataclass
class AlignedChar:
    pos: int
    char: str
    start: float
    end: float


@dataclass
class AlignmentResult:
    chars: list[AlignedChar] = field(default_factory=list)
    pauses: list[tuple[float, float]] = field(default_factory=list)
    mean_logprob: float = 0.0
    ok: bool = True
    reason: str = ""
    interpolated: int = 0   # 本段被插值（时间靠猜、零宽）的字数


@dataclass
class QwenCtcConfig:
    # 与 Whisper 侧保持一致（transcribe.VAD_THRESHOLD = 0.30）。两引擎共用同一套
    # Silero VAD 与合并逻辑，默认值分裂只会让「换个引擎结果差一截」无法归因。
    vad_threshold: float = 0.30
    vad_min_speech_ms: int = 100
    vad_min_silence_ms: int = 200
    vad_speech_pad_ms: int = 150
    merge_gap_s: float = 0.5
    min_speech_s: float = 0.08
    enable_loudnorm: bool = True

    max_segment_s: float = 16.0
    max_cue_dur: float = 4.3
    soft_max_cue_dur: float = 3.8
    max_cue_chars: int = 21
    hard_max_cue_dur: float = 5.2
    min_pause_s: float = 0.12
    min_cue_dur: float = 0.35
    cue_pad_start_s: float = 0.12
    cue_pad_end_s: float = 0.12
    max_new_tokens: int = 440


def _char_times_in_span(
    chars: list["AlignedChar"],
    first_pos: int,
    tail_pos: int,
    offset: float,
    cue_start: float,
) -> list[tuple[float, float]]:
    """把 CTC 逐字时间映射成「cue 文本下标 → (start, end)」，相对 `cue_start`。

    D6 的第一优先级分支（`_split_overlong_single` 的 `char_times`）要求序列长度与
    cue 文本等长：折叠文本里有些字不发声（长音符、标点、被折叠的符号），
    这些位置沿用前一个字的结束时间，保证一一对应、切点永远落在真实发声边界上。
    """
    by_pos = {c.pos: c for c in chars}
    out: list[tuple[float, float]] = []
    last_end = 0.0
    for pos in range(first_pos, tail_pos):
        c = by_pos.get(pos)
        if c is None:
            out.append((last_end, last_end))
            continue
        start = max(0.0, offset + c.start - cue_start)
        end = max(start, offset + c.end - cue_start)
        out.append((start, end))
        last_end = end
    return out


class QwenCtcEngine:
    def __init__(self, model_dir: str | Path | None = None, config: QwenCtcConfig | None = None) -> None:
        env = model_dir or os.environ.get("QWEN3_ASR_MODEL")
        self.model_dir = Path(env).expanduser() if env else MODELS_DIR / "qwen3-asr-ja-anime"
        self.device = detect_device()
        self.config = config or QwenCtcConfig()
        self.last_interrupted = False
        self.last_missed_spans: list[dict] = []
        self.last_segment_stats: dict = {}
        self.last_align_stats: dict = {}
        self._last_truncated = False
        self._last_capped = False
        self._model = None
        self._processor = None
        self._head = None
        self._lookup: dict[str, int] = {}
        self._unk_index = 1
        self._frame_classes: tuple[str, ...] = ()
        self._vad = None
        self._dtype = torch.float32

    @property
    def ready(self) -> bool:
        return self._model is not None

    @property
    def model_available(self) -> bool:
        return (self.model_dir / "config.json").exists()

    def ensure_model(self, progress_cb=None) -> None:
        if self.model_available and (self.model_dir / HEAD_FILE).exists():
            return
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        if progress_cb:
            progress_cb(0.005, f"正在通过国内镜像下载 {REPO_ID} 到 {self.model_dir}…")
        from huggingface_hub import snapshot_download

        self.model_dir.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=REPO_ID,
            local_dir=str(self.model_dir),
            ignore_patterns=["*.md", "conversion_report.json", "ctc_aligner.pt", "ctc_aligner_jav_vocalisation_v2.pt"],
            max_workers=2,
        )

    def load(self, progress_cb=None) -> None:
        if self._model is not None:
            return
        self.ensure_model(progress_cb)
        if not self.model_available:
            raise FileNotFoundError(
                f"未找到 {REPO_ID} 权重（{self.model_dir}）。\n"
                "运行 ./install.sh 下载，或用 QWEN3_ASR_MODEL 指向已有权重。"
            )

        from transformers import AutoModelForMultimodalLM, AutoProcessor

        if progress_cb:
            progress_cb(0.01, "正在加载 Qwen3-ASR 权重…")
        self._processor = AutoProcessor.from_pretrained(str(self.model_dir))
        if hasattr(self._processor, "tokenizer") and self._processor.tokenizer is not None:
            self._processor.tokenizer.clean_up_tokenization_spaces = False

        self._dtype = torch.bfloat16 if self.device in {"mps", "cuda"} else torch.float32
        try:
            model = AutoModelForMultimodalLM.from_pretrained(str(self.model_dir), dtype=self._dtype)
        except TypeError:
            model = AutoModelForMultimodalLM.from_pretrained(str(self.model_dir), torch_dtype=self._dtype)
        self._model = model.to(self.device).eval()

        head, payload = load_alignment_head(self.model_dir)
        self._head = head.to(self.device).float().eval()
        vocab = payload["vocab"]
        self._lookup = {ch: i + 2 for i, ch in enumerate(vocab["chars"])}
        self._unk_index = int(vocab.get("unk_index", 1))
        self._frame_classes = tuple(payload.get("frame_classes") or ())
        self._vad = load_silero_vad()

    def _encode_audio(self, audio: np.ndarray):
        inputs = self._processor.feature_extractor(
            audio,
            sampling_rate=SAMPLE_RATE,
            return_tensors="pt",
            padding=True,
            truncation=False,
            return_attention_mask=True,
            n_window=self._model.config.audio_config.n_window,
        )
        feats = inputs["input_features"].to(self.device, self._dtype)
        mask = inputs["attention_mask"].to(self.device)
        return feats, mask

    def _encoder_features(self, feats: torch.Tensor, mask: torch.Tensor) -> tuple[torch.Tensor, np.ndarray]:
        with torch.inference_mode():
            hidden = self._model.model.audio_tower(input_features=feats, input_features_mask=mask).last_hidden_state
            projected = self._model.model.multi_modal_projector(hidden)

        valid_mel = mask[0].to(torch.long).cpu()
        hop = self._processor.feature_extractor.hop_length
        times: list[float] = []
        block_start = 0.0
        for i in range(0, valid_mel.numel(), MEL_PER_BLOCK):
            count = _conv_length(int(valid_mel[i : i + MEL_PER_BLOCK].sum().item()))
            times.extend(block_start + p * SECONDS_PER_ENCODER_FRAME for p in range(count))
            block_start += MEL_PER_BLOCK * hop / SAMPLE_RATE
        return projected.float(), np.asarray(times, dtype=np.float64)

    def _transcribe(
        self,
        audio: np.ndarray,
        config: QwenCtcConfig | None = None,
        cap_override: int | None = None,
    ) -> str:
        cfg = config or self.config
        self._last_truncated = False
        self._last_capped = False
        # 送模窗口最长 16s，日语上限约 8 字/秒；按 12 token/秒（含一字多 token 的余量）
        # 反推上限。正常段由 EOS 提前终止，cap 不参与；只有复读段才吃满。
        dur = audio.size / SAMPLE_RATE
        if cap_override is not None:
            cap = int(cap_override)
        else:
            cap = min(int(cfg.max_new_tokens), max(64, int(dur * TOKENS_PER_SEC) + TOKENS_HEADROOM))
        with torch.inference_mode():
            inputs = self._processor.apply_transcription_request(
                audio=audio, sampling_rate=SAMPLE_RATE, language="Japanese"
            ).to(device=self.device, dtype=self._dtype)
            output_ids = self._model.generate(**inputs, max_new_tokens=cap)
        generated = output_ids[:, inputs["input_ids"].shape[1] :]
        text = self._processor.decode(generated, return_format="transcription_only")[0]
        text = (text or "").strip()
        self._last_capped, self._last_truncated = classify_capped(len(text), int(generated.shape[1]), cap)
        return text

    def align(self, audio: np.ndarray, text: str) -> AlignmentResult:
        folded = FoldedText(text)
        ids, char_index = encode_target(folded, self._lookup, self._unk_index)
        if not ids:
            return AlignmentResult(ok=True, reason="no-acoustic-chars")

        feats, mask = self._encode_audio(audio)
        projected, enc_times = self._encoder_features(feats, mask)
        if projected.shape[0] != enc_times.size:
            return AlignmentResult(ok=False, reason=f"frame-mismatch({projected.shape[0]}!={enc_times.size})")

        out_times = np.repeat(enc_times, UPSAMPLE)
        n_out = out_times.size
        n_repeat = sum(1 for i in range(1, len(ids)) if ids[i] == ids[i - 1])
        required = len(ids) + n_repeat
        if n_out < required:
            return AlignmentResult(ok=False, reason=f"too-few-frames({n_out}<{required})")

        with torch.inference_mode():
            log_probs = self._head(projected.unsqueeze(0))[0]
        log_probs = log_probs[:n_out]

        try:
            labels, scores = torchaudio.functional.forced_align(
                log_probs.detach().float().unsqueeze(0).cpu(),
                torch.tensor([ids], dtype=torch.long),
                blank=0,
            )
        except Exception as exc:
            return AlignmentResult(ok=False, reason=f"forced-align-failed:{type(exc).__name__}")
        labels = labels[0]
        label_list = labels.tolist()

        spans = collapse_token_spans(label_list, len(ids))

        folded_text = folded.folded
        chars: list[AlignedChar] = []
        for k, span in enumerate(spans):
            if span is None:
                continue
            pos = char_index[k]
            if pos is None:
                continue
            chars.append(
                AlignedChar(
                    pos=pos,
                    char=folded_text[pos],
                    start=float(out_times[min(span[0], n_out - 1)]),
                    end=float(out_times[min(span[1], n_out - 1)]),
                )
            )
        if not chars:
            return AlignmentResult(ok=False, reason="no-spans")

        pauses: list[tuple[float, float]] = []
        run_start: int | None = None
        for frame, label in enumerate(label_list):
            if label <= 0:
                if run_start is None:
                    run_start = frame
            elif run_start is not None:
                pauses.append((float(out_times[run_start]), float(out_times[frame - 1])))
                run_start = None
        if run_start is not None:
            pauses.append((float(out_times[run_start]), float(out_times[-1])))

        voiced = scores[0][labels > 0]
        mean_lp = float(voiced.mean().item()) if voiced.numel() else 0.0
        aligned_count = len(chars)
        chars = _fill_unaligned(folded, chars, float(out_times[-1]))
        # 插值字数 = 补出来的字数。不能用"零宽"判定：CTC 只占 1 帧的合法对齐
        # 也是 start == end，那样会把正常对齐误报成插值。
        interp = max(0, len(chars) - aligned_count)
        return AlignmentResult(
            chars=chars, pauses=pauses, mean_logprob=mean_lp, ok=True, interpolated=interp
        )

    def _cues_from_alignment(
        self, result: AlignmentResult, offset: float, folded: FoldedText, cfg: QwenCtcConfig
    ) -> list[SubtitleCue]:
        positions = [c.pos for c in result.chars]
        costs = _break_costs(folded, positions)
        _apply_pauses(costs, result.chars, result.pauses, cfg.min_pause_s)
        groups = partition_cues(
            result.chars, costs, cfg.max_cue_dur, cfg.max_cue_chars, cfg.hard_max_cue_dur, cfg.soft_max_cue_dur
        )

        cues: list[SubtitleCue] = []
        spans: list[tuple[float, float, str, int, int]] = []
        for group in groups:
            if not group:
                continue
            first, last = result.chars[group[0]], result.chars[group[-1]]
            tail = last.pos + 1
            while tail < len(folded) and _is_zero_width(folded.folded[tail]):
                tail += 1
            spans.append(
                (
                    offset + first.start - cfg.cue_pad_start_s,
                    offset + last.end + cfg.cue_pad_end_s,
                    folded.slice(first.pos, tail),
                    first.pos,
                    tail,
                )
            )

        for i in range(len(spans) - 1):
            start, end, text, first_pos, tail = spans[i]
            spans[i] = (start, min(end, spans[i + 1][0]), text, first_pos, tail)

        for i, (start, end, text, first_pos, tail) in enumerate(spans):
            ceiling = spans[i + 1][0] if i + 1 < len(spans) else None
            if end - start < cfg.min_cue_dur:
                wanted = start + cfg.min_cue_dur
                end = wanted if ceiling is None else min(wanted, max(ceiling, start + MIN_CUE_DUR))
            cue = SubtitleCue(start=round(max(0.0, start), 3), end=round(end, 3), text=text)
            # DP 允许单条最长到 hard_max_cue_dur（5.2s），因此对齐路径也会产出
            # 超过 max_cue_dur 的条。这里用 CTC 逐字时间（D6 第一优先级）再切一刀：
            # 切点落在真实发声边界上，比按比例分配精确得多。
            if cue.end - cue.start > cfg.max_cue_dur:
                char_times = _char_times_in_span(result.chars, first_pos, tail, offset, cue.start)
                pieces = _split_overlong_single(
                    cue.text, cue.start, cue.end, cfg.max_cue_dur, char_times=char_times,
                )
                cues.extend(
                    SubtitleCue(start=round(a, 3), end=round(b, 3), text=t) for a, b, t in pieces
                )
            else:
                cues.append(cue)
        return cues

    def _cues_fallback(
        self,
        text: str,
        offset: float,
        duration: float,
        cfg: QwenCtcConfig,
        *,
        audio: np.ndarray | None = None,
    ) -> list[SubtitleCue]:
        # 对齐失败（degraded）时没有 char_times 可用，但仍可走 D6 的第二优先级：
        # 字符比例定位 + 该段音频的能量谷吸附，避免退回按时间对半。
        return split_text_into_cues(
            text,
            seg_start=offset,
            seg_end=offset + duration,
            max_cue_dur=cfg.max_cue_dur,
            max_cue_chars=cfg.max_cue_chars,
            audio=audio,
            sample_rate=SAMPLE_RATE,
        )

    def transcribe_array(
        self,
        audio: np.ndarray,
        *,
        progress_cb=None,
        use_alignment: bool = True,
        config: QwenCtcConfig | None = None,
        cancel_event: threading.Event | None = None,
        time_offset: float = 0.0,
    ) -> list[SubtitleCue]:
        self.load(progress_cb=progress_cb)
        self.last_interrupted = False
        self.last_missed_spans = []
        self.last_segment_stats = {}
        self.last_align_stats = {}
        cfg = config or self.config
        if progress_cb:
            progress_cb(0.06, "正在使用动态 VAD 切分语音段落…")

        speech_pad_ms = int(cfg.vad_speech_pad_ms)
        stamps = get_speech_timestamps(
            torch.from_numpy(audio),
            self._vad,
            sampling_rate=SAMPLE_RATE,
            threshold=float(cfg.vad_threshold),
            min_speech_duration_ms=int(cfg.vad_min_speech_ms),
            min_silence_duration_ms=int(cfg.vad_min_silence_ms),
            speech_pad_ms=speech_pad_ms,
            neg_threshold=vad_neg_threshold(cfg.vad_threshold),
        )
        segments = merge_vad_segments(
            stamps,
            max_segment_s=cfg.max_segment_s,
            merge_gap_s=cfg.merge_gap_s,
            min_speech_s=cfg.min_speech_s,
            audio=audio,
            snap_stats=self.last_segment_stats,
        )
        if not segments:
            segments = [(0, len(audio))]

        cues: list[SubtitleCue] = []
        aligned = 0
        noop = 0
        empty = 0
        align_chars = 0
        interp_chars = 0
        truncated = 0
        capped_repeat = 0
        degraded: list[dict] = []
        total = len(segments)
        prev_text = ""
        stage = "转写并对齐" if use_alignment else "转写"
        for i, (start, end) in enumerate(segments, start=1):
            if cancel_event and cancel_event.is_set():
                self.last_interrupted = True
                if progress_cb:
                    progress_cb(0.99, f"🛑 用户已中途取消，正在保存前 {len(cues)} 条字幕…")
                break

            if progress_cb:
                progress_cb(0.1 + 0.8 * (i - 1) / max(total, 1), f"正在{stage}第 {i}/{total} 段… (可随时点击取消)")
            chunk = audio[start:end]
            if chunk.size == 0:
                empty += 1      # 退化段（时长为 0），无文本可对齐
                continue
            offset = (start / SAMPLE_RATE) + time_offset
            seg_dur_s = (end - start) / SAMPLE_RATE

            text = self._transcribe(chunk, cfg)
            if self._last_capped:
                if self._last_truncated:
                    # 密度正常却撞上限 = 真被砍：按完整上限重跑一次，宁可慢也不吃字。
                    # 只保留更长的结果，重跑更差不至于把已有文本弄丢。
                    retried = self._transcribe(chunk, cfg, cap_override=int(cfg.max_new_tokens))
                    if len(retried) > len(text):
                        text = retried
                    if self._last_truncated:
                        truncated += 1
                else:
                    capped_repeat += 1   # 复读/空转吃满上限：加长上限也救不回字，不重跑
            reason = ""
            if _is_blank(text):
                if cancel_event and cancel_event.is_set():
                    self.last_interrupted = True
                    if progress_cb:
                        progress_cb(0.99, f"🛑 用户已中途取消，正在保存前 {len(cues)} 条字幕…")
                    break
                text = self._transcribe(_retry_gain(chunk), cfg)
                if not _is_blank(text) and _retry_suspicious(text, seg_dur_s, prev_text):
                    text, reason = "", "retry-suspicious"
                elif _is_blank(text):
                    reason = "empty-after-retry"

            if _is_blank(text):
                self.last_missed_spans.append({
                    "start": round(offset, 3),
                    "end": round(offset + seg_dur_s, 3),
                    "dur": round(seg_dur_s, 2),
                    "reason": reason or "empty-after-retry",
                    **chunk_level_stats(chunk),
                })
                empty += 1      # 空结果段：没有文本，谈不上对齐，单独成桶
                continue
            prev_text = text

            if not use_alignment:
                cues.extend(
                    split_text_into_cues(
                        text,
                        seg_start=offset,
                        seg_end=(end / SAMPLE_RATE) + time_offset,
                        max_cue_dur=cfg.max_cue_dur,
                        max_cue_chars=cfg.max_cue_chars,
                        audio=chunk,
                        sample_rate=SAMPLE_RATE,
                    )
                )
                continue
            result = self.align(chunk, text)
            if result.ok and result.chars:
                aligned += 1
                align_chars += len(result.chars)
                interp_chars += result.interpolated
                cues.extend(self._cues_from_alignment(result, offset, FoldedText(text), cfg))
            else:
                if result.reason == "no-acoustic-chars":
                    noop += 1          # 纯符号文本，无需对齐，不计入降级率
                else:
                    degraded.append({
                        "start": round(offset, 3),
                        "end": round(offset + seg_dur_s, 3),
                        "dur": round(seg_dur_s, 2),
                        "reason": result.reason or "unknown",
                        "chars": len(text),
                    })
                cues.extend(self._cues_fallback(text, offset, seg_dur_s, cfg, audio=chunk))

        # 四桶互斥且穷尽（仅 use_alignment 时成立）：aligned + noop + degraded + empty == total
        # empty = 空结果段（已进 last_missed_spans），没有文本就谈不上对齐，必须单独成桶，
        # 否则报告里的"共 N 段"会和三个分项对不上。
        self.last_align_stats = {
            "enabled": bool(use_alignment),
            "segments": total,
            "aligned": aligned,
            "noop": noop,
            "degraded": len(degraded),
            "empty": empty,
            "align_chars": align_chars,
            "interp_chars": interp_chars,
            "truncated": truncated,
            "capped_repeat": capped_repeat,
            "spans": degraded[:50],
        }

        if progress_cb and not self.last_interrupted:
            note = f"（{aligned}/{total} 段完成逐字对齐）" if use_alignment else ""
            progress_cb(0.95, f"正在整理字幕…{note}")
        cues.sort(key=lambda c: (c.start, c.end))
        return _dedupe(cues)

    def transcribe_file(
        self,
        media_path: str | Path,
        *,
        progress_cb=None,
        use_alignment: bool = True,
        config: QwenCtcConfig | None = None,
        cancel_event: threading.Event | None = None,
        start_time_s: float | None = None,
        end_time_s: float | None = None,
        time_offset: float = 0.0,
    ) -> list[SubtitleCue]:
        cfg = config or self.config
        media_path = Path(media_path)
        if progress_cb:
            slice_desc = f"（片段：{start_time_s or 0.0:.1f}s ~ {end_time_s:.1f}s）" if end_time_s else ""
            progress_cb(0.02, f"正在提取 16kHz 音频并进行响度优化{slice_desc}…")
        audio = load_audio_for_transcription(
            media_path,
            enable_loudnorm=cfg.enable_loudnorm,
            start_time_s=start_time_s,
            end_time_s=end_time_s,
            tmp_prefix="qwen3-asr-",
        )
        return self.transcribe_array(
            audio,
            progress_cb=progress_cb,
            use_alignment=use_alignment,
            config=cfg,
            cancel_event=cancel_event,
            time_offset=time_offset,
        )


def _heal_broken_cues(cues: list[SubtitleCue], max_merge_dur: float = 5.2) -> list[SubtitleCue]:
    """缝合被断句切开的两半。

    关键约束：**只有首尾相接（间隙 ≈ 0）才可能是同一个词被劈开**。DP 在同一段音频
    内部切分时，两条字幕的间隙为 0（甚至为负，靠 `_dedupe` 裁掉重叠）；一旦中间有
    可见停顿，就说明这是两句独立台词——「今日は」+「東京に行く」被"汉字接汉字"这条
    规则错并，正是缺了这道闸门。
    """
    if len(cues) < 2:
        return cues

    merged: list[SubtitleCue] = []
    i = 0
    n = len(cues)
    while i < n:
        curr = cues[i]
        if i + 1 < n:
            nxt = cues[i + 1]
            curr_text = curr.text.strip()
            nxt_text = nxt.text.strip()

            if curr_text and curr_text[-1] in "。！？!?\n":
                merged.append(curr)
                i += 1
                continue

            gap = nxt.start - curr.end
            should_merge = False
            if nxt_text and (nxt_text[0] in SMALL_KANA or nxt_text[0] in PROLONGED_SOUNDS):
                should_merge = True
            elif any(nxt_text.startswith(broken) for broken in ["ったら", "てまして", "てた", "てない", "まして", "ました", "ども", "ティ"]):
                should_merge = True
            elif curr_text and nxt_text and _is_kanji(curr_text[-1]) and _is_kanji(nxt_text[0]):
                should_merge = True
            elif curr_text and nxt_text and ("\u30a0" <= curr_text[-1] <= "\u30ff") and ("\u30a0" <= nxt_text[0] <= "\u30ff"):
                should_merge = True
            elif curr_text and nxt_text and (curr_text[-1].isascii() and curr_text[-1].isalnum()) and (nxt_text[0].isascii() and nxt_text[0].isalnum()):
                should_merge = True
            elif curr_text.endswith("あ") and nxt_text.startswith("と"):
                should_merge = True
            elif (curr.end - curr.start <= 0.65) and len(curr_text) <= 3 and not curr_text.endswith(("。", "！", "？", "!", "?")):
                should_merge = True
            elif len(nxt_text) <= 2 and all(ch in "うねよわさぞ" for ch in nxt_text):
                should_merge = True
            elif curr_text.endswith(tuple(HONORIFIC_PREFIXES)) and nxt_text and _is_kanji(nxt_text[0]):
                should_merge = True
            elif curr_text.endswith("ま") and nxt_text and nxt_text[0] in ("す", "せ", "し"):
                should_merge = True

            combined_dur = nxt.end - curr.start
            combined_chars = len(curr_text + nxt_text)
            if (
                should_merge
                and gap <= HEAL_MAX_GAP_S
                and combined_dur <= max_merge_dur
                and combined_chars <= 24
            ):
                curr = SubtitleCue(
                    start=curr.start,
                    end=nxt.end,
                    text=curr_text + nxt_text,
                )
                i += 1
        merged.append(curr)
        i += 1
    return merged


def _dedupe(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    cues = _heal_broken_cues(cues)
    out: list[SubtitleCue] = []
    for cue in cues:
        text = cue.text.strip()
        if not text:
            continue
        start = max(0.0, float(cue.start))
        end = max(float(cue.end), start + MIN_CUE_DUR)
        if out:
            prev = out[-1]
            if start < prev.end:
                if start - prev.start >= MIN_CUE_DUR:
                    prev.end = round(start, 3)
                else:
                    start = prev.end
        out.append(SubtitleCue(start=round(start, 3), end=round(end, 3), text=text))
    return _heal_broken_cues(out)
