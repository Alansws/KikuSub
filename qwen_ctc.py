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
    MODELS_DIR,
    SAMPLE_RATE,
    SubtitleCue,
    _is_blank,
    _retry_gain,
    _retry_suspicious,
    detect_device,
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

SMALL_KANA = set("っッゃゅょャュョぁぃぅぇぉァィゥェォゎヮヵヶ")
PROLONGED_SOUNDS = set("ー〜～")
JAPANESE_PARTICLES = set("は が を に で へ と も から まで より ね よ わ か の".split())
HONORIFIC_PREFIXES = set("おご御")

FORBIDDEN_WORDS = (
    "これ", "それ", "あれ", "どれ",
    "なんか", "なんて", "なんで", "ちょっと",
    "やっぱり", "どうして", "だから", "だけど",
    "ありま", "ございま", "お願い",
    "あと", "けれども", "けれど", "なんです", "んです",
    "として", "关于", "ですから", "なので",
    "まして", "ました", "ません", "ったら", "ったり",
    "てまして", "てました", "ていた", "ている", "ていく", "てみる",
)


def _is_kana(ch: str) -> bool:
    return bool(ch) and ("\u3040" <= ch <= "\u30ff" or "\u31f0" <= ch <= "\u31ff")


def _is_kanji(ch: str) -> bool:
    return bool(ch) and ("\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf")


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
    for i in range(1, n):
        prev_pos, next_pos = positions[i - 1], positions[i]
        if next_pos > prev_pos + 1:
            continue

        prev_ch = text_str[prev_pos]
        next_ch = text_str[next_pos]
        cut_pos = prev_pos + 1

        if next_ch in SMALL_KANA or prev_ch in SMALL_KANA:
            costs[i] = BREAK_FORBIDDEN
            continue
        if next_ch in PROLONGED_SOUNDS or prev_ch in PROLONGED_SOUNDS:
            costs[i] = BREAK_FORBIDDEN
            continue
        if (prev_ch.isascii() and prev_ch.isalnum()) and (next_ch.isascii() and next_ch.isalnum()):
            costs[i] = BREAK_FORBIDDEN
            continue
        if "\u30a0" <= prev_ch <= "\u30ff" and "\u30a0" <= next_ch <= "\u30ff":
            costs[i] = BREAK_FORBIDDEN
            continue
        if _is_kanji(prev_ch) and _is_kanji(next_ch):
            costs[i] = BREAK_FORBIDDEN
            continue
        if prev_ch in HONORIFIC_PREFIXES and _is_kanji(next_ch):
            costs[i] = BREAK_FORBIDDEN
            continue
        if prev_ch == "ま" and next_ch in ("す", "せ", "し"):
            costs[i] = BREAK_FORBIDDEN
            continue

        word_cut_cross = False
        for word in FORBIDDEN_WORDS:
            start_search = max(0, cut_pos - len(word))
            idx = text_str.find(word, start_search)
            while idx != -1 and idx < cut_pos:
                if idx < cut_pos < idx + len(word):
                    costs[i] = BREAK_FORBIDDEN
                    word_cut_cross = True
                    break
                idx = text_str.find(word, idx + 1)
            if word_cut_cross:
                break
        if word_cut_cross:
            continue

        if prev_ch in "こそことのほもろよごぞどぼぽ" and next_ch == "う":
            costs[i] = BREAK_FORBIDDEN
            continue

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
                cost += (n_chars - max_chars) * 1.2
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


@dataclass
class QwenCtcConfig:
    vad_threshold: float = 0.28
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


class QwenCtcEngine:
    def __init__(self, model_dir: str | Path | None = None, config: QwenCtcConfig | None = None) -> None:
        env = model_dir or os.environ.get("QWEN3_ASR_MODEL")
        self.model_dir = Path(env).expanduser() if env else MODELS_DIR / "qwen3-asr-ja-anime"
        self.device = detect_device()
        self.config = config or QwenCtcConfig()
        self.last_interrupted = False
        self.last_missed_spans: list[dict] = []
        self.last_segment_stats: dict = {}
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

    def _transcribe(self, audio: np.ndarray, config: QwenCtcConfig | None = None) -> str:
        cfg = config or self.config
        with torch.inference_mode():
            inputs = self._processor.apply_transcription_request(
                audio=audio, sampling_rate=SAMPLE_RATE, language="Japanese"
            ).to(device=self.device, dtype=self._dtype)
            output_ids = self._model.generate(**inputs, max_new_tokens=cfg.max_new_tokens)
        generated = output_ids[:, inputs["input_ids"].shape[1] :]
        text = self._processor.decode(generated, return_format="transcription_only")[0]
        return (text or "").strip()

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
        chars = _fill_unaligned(folded, chars, float(out_times[-1]))
        return AlignmentResult(chars=chars, pauses=pauses, mean_logprob=mean_lp, ok=True)

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
        spans: list[tuple[float, float, str]] = []
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
                )
            )

        for i in range(len(spans) - 1):
            start, end, text = spans[i]
            spans[i] = (start, min(end, spans[i + 1][0]), text)

        for i, (start, end, text) in enumerate(spans):
            ceiling = spans[i + 1][0] if i + 1 < len(spans) else None
            if end - start < cfg.min_cue_dur:
                wanted = start + cfg.min_cue_dur
                end = wanted if ceiling is None else min(wanted, max(ceiling, start + MIN_CUE_DUR))
            cues.append(SubtitleCue(start=round(max(0.0, start), 3), end=round(end, 3), text=text))
        return cues

    def _cues_fallback(self, text: str, offset: float, duration: float, cfg: QwenCtcConfig) -> list[SubtitleCue]:
        return split_text_into_cues(
            text,
            seg_start=offset,
            seg_end=offset + duration,
            max_cue_dur=cfg.max_cue_dur,
            max_cue_chars=cfg.max_cue_chars,
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
            speech_pad_s=speech_pad_ms / 1000.0,
            audio=audio,
            snap_stats=self.last_segment_stats,
        )
        if not segments:
            segments = [(0, len(audio))]

        cues: list[SubtitleCue] = []
        aligned = 0
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
                continue
            offset = (start / SAMPLE_RATE) + time_offset
            seg_dur_s = (end - start) / SAMPLE_RATE

            text = self._transcribe(chunk, cfg)
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
                })
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
                    )
                )
                continue
            result = self.align(chunk, text)
            if result.ok and result.chars:
                aligned += 1
                cues.extend(self._cues_from_alignment(result, offset, FoldedText(text), cfg))
            else:
                cues.extend(self._cues_fallback(text, offset, (end - start) / SAMPLE_RATE, cfg))

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

            should_merge = False
            if nxt_text and (nxt_text[0] in SMALL_KANA or nxt_text[0] in PROLONGED_SOUNDS):
                should_merge = True
            elif any(nxt_text.startswith(broken) for broken in ["ったら", "てまして", "てta", "てない", "まして", "ました", "ども", "ティ"]):
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
            if should_merge and combined_dur <= max_merge_dur and combined_chars <= 24:
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
