"""SenseVoice-Small / FireRedASR2-AED 中文转写引擎（sherpa-onnx · ONNX Runtime · CPU）。

为什么是这两个：仓库原本只有日语引擎（Anime Whisper / Qwen3-ASR）。中文需求有两条
互相独立的路线——SenseVoice-Small 体积小、多语种（中英日韩粤）、CPU 很快；FireRedASR2
（小红书）中文精度更高、覆盖 20 多种方言，但权重约 1.2 GB。两个都作为**可选引擎**
注册，权重不随包分发，用户在设置页自己点下载。

为什么不直接用 FunASR / FireRedASR2S 的原生 PyTorch 实现：

- 原实现要求把仓库 clone 下来（不在 PyPI），`firederasr2s` 还依赖 kaldi 那套原生库，
  PyInstaller sidecar 几乎没法稳定打包；
- sherpa-onnx 已经提供同一份权重的 ONNX 转写（SenseVoice int8 228MB、
  FireRedASR2-AED int8 约 1.2GB），且**不需要 torch**，CPU 上就是目标形态；
- 它返回的是 token + 时间戳，与 Qwen 的 CTC 对齐结果同一层级，可以直接喂给
  `core/text_cues_zh.py` 分句，不必为中文再造一套断句 DP。

硬约束（与 `core/qwen_ctc.py` 一致）：

- 模块顶层**不 import sherpa_onnx**，只在 `load()` 里延迟导入——设置页查询引擎状态
  时不该拉起原生库；
- 取消只发信号，已产出的字幕要保留（`last_interrupted`），由调用方决定是否落盘；
- 模型没给时间戳时按字均分并在 `last_align_stats` 里记为降级，不假装逐字对齐。
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .coverage import find_coverage_spans
from .model_fetch import snapshot_download_files
from .paths import MODELS_DIR
from .procutil import CommandCancelled
from .punctuation import PunctuationModel, needs_punctuation
from .text_cues_zh import (
    TimedChar,
    build_timed_chars,
    split_cues,
    spread_text,
    spread_text_voiced,
    voiced_spans,
)
from .transcribe import (
    SAMPLE_RATE,
    SubtitleCue,
    _is_blank,
    chunk_level_stats,
    load_audio_for_transcription,
    merge_vad_segments,
    vad_neg_threshold,
)

log = logging.getLogger(__name__)

SENSEVOICE_REPO = "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
FIRERED_REPO = "csukuangfj2/sherpa-onnx-fire-red-asr2-zh_en-int8-2026-02-26"
_LOAD_LOCK = threading.Lock()


def _import_sherpa():
    """延迟导入 sherpa-onnx（原生库）。单独成函数是为了测试能替换掉它。"""
    import sherpa_onnx

    return sherpa_onnx


def _load_vad():
    """Silero VAD 与日语引擎共用同一份实现（torch 已随包）。"""
    from silero_vad import load_silero_vad

    return load_silero_vad()


@dataclass(slots=True)
class SherpaAsrConfig:
    """两个中文引擎共用的参数（字段名与 `core/params.py` 的 config_field 对齐）。

    注意：**产品默认值不在这里**，在 `core/params.py` 的 ParamSpec 里（两个引擎的
    窗口长度不同，共用一份 dataclass 默认值表达不了）。引擎构造时会用 params 的
    默认值实例化，所以从这里拿到的 config 与界面上的默认值一致。
    """

    enable_loudnorm: bool = True
    vad_threshold: float = 0.30
    vad_min_speech_ms: int = 100
    vad_min_silence_ms: int = 200
    vad_speech_pad_ms: int = 150
    merge_gap_s: float = 0.50
    max_segment_s: float = 16.0
    min_speech_s: float = 0.08
    min_pause_s: float = 0.20
    max_cue_dur: float = 4.3
    max_cue_chars: int = 18
    cue_pad_s: float = 0.10
    # CPU 线程数：默认 2，Apple Silicon 上 2–4 性价比最高（再高收益递减）。
    num_threads: int = 2
    # 仅 SenseVoice 有意义：auto / zh / en / ja / ko / yue。
    language: str = "auto"
    # SenseVoice 的逆文本归一化（数字、标点）；关掉输出就是无标点的一串字。
    use_itn: bool = True
    # FireRedASR2 没有标点；开启后用 FireRedPunc 补（ONNX，约 160 MB，随引擎一起下载）。
    use_punc: bool = True
    # 没有 token 时间戳时，用能量把字铺在「有声区间」上，而不是整段均分。
    energy_align: bool = True


class _SherpaEngine:
    """sherpa-onnx 离线识别器的共用外壳。"""

    # 只有没有 token 时间戳、且原始输出无标点的引擎（FireRed）才需要标点恢复。
    # SenseVoice 用 `use_itn` 直接输出标点，再跑一遍 punc 反而会多出符号。
    supports_punc = False
    key = ""
    label = ""
    repo_id = ""
    dir_name = ""
    env_var = ""
    allow_patterns: tuple[str, ...] = ()
    required_files: tuple[str, ...] = ()
    approx_label = ""

    def __init__(self, model_dir: str | Path | None = None, config: SherpaAsrConfig | None = None) -> None:
        env = str(model_dir or os.environ.get(self.env_var) or "").strip()
        self.model_dir = Path(env).expanduser() if env else MODELS_DIR / self.dir_name
        self.config = config or self.default_config()
        self.last_interrupted = False
        self.last_missed_spans: list[dict] = []
        self.last_coverage_spans: list[dict] = []
        self.last_segment_stats: dict = {}
        self.last_align_stats: dict = {}
        self._recognizer = None
        self._recognizer_key: tuple | None = None
        self._vad = None
        self._punc: PunctuationModel | None = None

    @classmethod
    def default_config(cls) -> SherpaAsrConfig:
        """界面上的默认参数（来自 `core/params.py`，不在 dataclass 里重复一份）。"""
        from . import params as param_specs

        return SherpaAsrConfig(**param_specs.config_kwargs(cls.key, {}))

    @property
    def ready(self) -> bool:
        return self._recognizer is not None

    @property
    def model_available(self) -> bool:
        return all((self.model_dir / name).is_file() for name in self.required_files)

    def ensure_model(self, progress_cb=None) -> None:
        """下载（或补齐）ONNX 权重。只取 int8 与 token 表，不拉 fp32 副本。"""
        if self.model_available:
            return
        snapshot_download_files(
            repo_id=self.repo_id,
            dest=self.model_dir,
            allow_patterns=self.allow_patterns,
            progress_cb=progress_cb,
            label=self.label,
        )
        missing = [name for name in self.required_files if not (self.model_dir / name).is_file()]
        if missing:
            raise RuntimeError(
                f"{self.label} 权重不完整，缺少：{', '.join(missing)}（目录 {self.model_dir}）"
            )

    def load(self, progress_cb=None, config: SherpaAsrConfig | None = None) -> None:
        """加载（或按需换配置重建）识别器。

        `config` 必须是**本次调用**的配置：用户在参数面板里改线程数 / ITN 之后，
        下一次转写要按新值重建 recognizer，不能沿用构造时的默认值。
        """
        cfg = config or self.config
        key = (int(cfg.num_threads), str(cfg.language), bool(cfg.use_itn))
        if self._recognizer is not None and self._recognizer_key == key:
            return
        with _LOAD_LOCK:
            if self._recognizer is not None and self._recognizer_key == key:
                return
            self.ensure_model(progress_cb)
            if progress_cb:
                progress_cb(0.02, f"正在加载 {self.label}（ONNX / CPU）…")
            sherpa_onnx = _import_sherpa()

            recognizer = self._create_recognizer(sherpa_onnx, cfg)
            vad = _load_vad()

            # 全部成功后再一次性发布，避免半初始化状态被其他线程看到。
            self._recognizer = recognizer
            self._recognizer_key = key
            self._vad = vad
            log.info(
                "中文引擎已加载 | engine=%s | dir=%s | threads=%s",
                self.key,
                self.model_dir,
                cfg.num_threads,
            )

    def _create_recognizer(self, sherpa_onnx, cfg: SherpaAsrConfig):  # pragma: no cover - 子类实现
        raise NotImplementedError

    def _decode_segment(self, chunk: np.ndarray) -> tuple[str, list[str], list[float]]:
        stream = self._recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE, np.asarray(chunk, dtype=np.float32))
        self._recognizer.decode_stream(stream)
        result = stream.result
        text = str(getattr(result, "text", "") or "").strip()
        tokens = [str(token) for token in (getattr(result, "tokens", None) or [])]
        timestamps = [float(value) for value in (getattr(result, "timestamps", None) or [])]
        return text, tokens, timestamps

    def _cues_for_segment(
        self,
        tokens: list[str],
        timestamps: list[float],
        text: str,
        offset: float,
        seg_end: float,
        cfg: SherpaAsrConfig,
        chunk: np.ndarray | None = None,
    ) -> tuple[list[SubtitleCue], int, bool]:
        """把一段的识别结果切成字幕；返回 (cues, 字符数, 是否逐字时间轴可用)。"""
        timed = bool(tokens) and len(timestamps) == len(tokens)
        if timed:
            chars: list[TimedChar] = build_timed_chars(
                tokens, timestamps, offset, offset + seg_end
            )
        elif cfg.energy_align and chunk is not None and len(chunk):
            chars = spread_text_voiced(
                text,
                offset,
                offset + seg_end,
                voiced_spans(chunk),
            )
        else:
            chars = spread_text(text, offset, offset + seg_end)

        drafts = split_cues(
            chars,
            seg_start=offset,
            seg_end=offset + seg_end,
            max_cue_chars=cfg.max_cue_chars,
            max_cue_dur=cfg.max_cue_dur,
            min_pause_s=cfg.min_pause_s,
            cue_pad_s=cfg.cue_pad_s,
        )
        cues = [SubtitleCue(start=d.start, end=d.end, text=d.text) for d in drafts]
        return cues, sum(len(cue.text) for cue in cues), timed

    def transcribe_array(
        self,
        audio: np.ndarray,
        *,
        progress_cb=None,
        config: SherpaAsrConfig | None = None,
        cancel_event: threading.Event | None = None,
        time_offset: float = 0.0,
    ) -> list[SubtitleCue]:
        cfg = config or self.config
        self.load(progress_cb=progress_cb, config=cfg)
        self.last_interrupted = False
        self.last_missed_spans = []
        self.last_coverage_spans = []
        self.last_segment_stats = {}
        self.last_align_stats = {}

        if progress_cb:
            progress_cb(0.06, "正在使用动态 VAD 切分语音段落…")

        from silero_vad import get_speech_timestamps
        import torch

        stamps = get_speech_timestamps(
            torch.from_numpy(np.asarray(audio, dtype=np.float32)),
            self._vad,
            sampling_rate=SAMPLE_RATE,
            threshold=float(cfg.vad_threshold),
            min_speech_duration_ms=int(cfg.vad_min_speech_ms),
            min_silence_duration_ms=int(cfg.vad_min_silence_ms),
            speech_pad_ms=int(cfg.vad_speech_pad_ms),
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

        total = len(segments)
        cues: list[SubtitleCue] = []
        timed_segments = 0
        degraded: list[dict] = []
        char_count = 0
        punc_applied = 0
        punc_failed = 0
        punc_warned = False

        if not total:
            if progress_cb:
                progress_cb(0.95, "未检测到有效语音（VAD 未命中任何语音段）…")
            self.last_align_stats = {
                "enabled": True,
                "segments": 0,
                "aligned": 0,
                "noop": 0,
                "degraded": 0,
                "empty": 0,
                "align_chars": 0,
                "interp_chars": 0,
                "truncated": 0,
                "capped_repeat": 0,
                "spans": [],
                "family": "sherpa",
            }
            return []

        for index, (start, end) in enumerate(segments, start=1):
            if cancel_event and cancel_event.is_set():
                self.last_interrupted = True
                if progress_cb:
                    progress_cb(0.99, f"🛑 用户已中途取消，正在保存前 {len(cues)} 条字幕…")
                break
            if progress_cb:
                progress_cb(
                    0.1 + 0.8 * (index - 1) / max(total, 1),
                    f"正在用 {self.label} 识别第 {index}/{total} 段… (可随时点击取消)",
                )
            chunk = audio[start:end]
            if chunk.size == 0:
                continue
            offset = (start / SAMPLE_RATE) + time_offset
            seg_dur_s = (end - start) / SAMPLE_RATE

            try:
                text, tokens, timestamps = self._decode_segment(chunk)
            except Exception:
                log.exception("中文引擎解码失败 | engine=%s | 第 %s 段", self.key, index)
                text, tokens, timestamps = "", [], []

            # FireRed 的原始输出没有标点：在切字幕之前补，切点才有标点可依。
            if (
                self.supports_punc
                and self._punc is not None
                and cfg.use_punc
                and text
                and needs_punctuation(text)
            ):
                try:
                    restored = self._punc.restore(text)
                except Exception as exc:  # noqa: BLE001 - 标点是可选增强，不能拖垮转写
                    punc_failed += 1
                    if not punc_warned:
                        punc_warned = True
                        log.warning(
                            "标点模型不可用，本次输出保持无标点 | engine=%s | %s",
                            self.key,
                            exc,
                        )
                else:
                    if restored != text:
                        text = restored
                        punc_applied += 1

            if _is_blank(text):
                if cancel_event and cancel_event.is_set():
                    self.last_interrupted = True
                    break
                self.last_missed_spans.append(
                    {
                        "start": round(offset, 3),
                        "end": round(offset + seg_dur_s, 3),
                        "dur": round(seg_dur_s, 2),
                        "reason": "empty",
                        **chunk_level_stats(chunk),
                    }
                )
                continue

            seg_cues, chars, timed = self._cues_for_segment(
                tokens, timestamps, text, offset, seg_dur_s, cfg, chunk=chunk
            )
            char_count += chars
            if timed:
                timed_segments += 1
            else:
                degraded.append(
                    {
                        "start": round(offset, 3),
                        "end": round(offset + seg_dur_s, 3),
                        "dur": round(seg_dur_s, 2),
                        "reason": "no-token-timestamps",
                        "chars": len(text),
                    }
                )
            cues.extend(seg_cues)

        empty = len(self.last_missed_spans)
        if self.supports_punc:
            self.last_segment_stats["punc_applied"] = punc_applied
            self.last_segment_stats["punc_failed"] = punc_failed
        self.last_align_stats = {
            "enabled": True,
            "segments": total,
            "aligned": timed_segments,
            "noop": 0,
            "degraded": len(degraded),
            "empty": empty,
            "align_chars": char_count,
            "interp_chars": 0,
            "truncated": 0,
            "capped_repeat": 0,
            "spans": degraded[:50],
            "family": "sherpa",
        }

        if progress_cb and not self.last_interrupted:
            progress_cb(0.95, "正在整理字幕…")

        cues.sort(key=lambda cue: (cue.start, cue.end))
        final_cues = _dedupe(cues)
        if not self.last_interrupted and final_cues:
            try:
                self.last_coverage_spans = find_coverage_spans(
                    audio, final_cues, self._vad, time_offset=time_offset
                )
            except Exception:
                log.debug("覆盖审计失败（不影响转写）", exc_info=True)
        return final_cues

    def transcribe_file(
        self,
        media_path: str | Path,
        *,
        progress_cb=None,
        config: SherpaAsrConfig | None = None,
        cancel_event: threading.Event | None = None,
        start_time_s: float | None = None,
        end_time_s: float | None = None,
        time_offset: float = 0.0,
    ) -> list[SubtitleCue]:
        self.last_coverage_spans = []
        cfg = config or self.config
        media_path = Path(media_path)
        if progress_cb:
            slice_desc = (
                f"（片段：{start_time_s or 0.0:.1f}s ~ {end_time_s:.1f}s）" if end_time_s else ""
            )
            progress_cb(0.02, f"正在提取 16kHz 音频并进行响度优化{slice_desc}…")
        try:
            audio = load_audio_for_transcription(
                media_path,
                enable_loudnorm=cfg.enable_loudnorm,
                start_time_s=start_time_s,
                end_time_s=end_time_s,
                tmp_prefix="sherpa-asr-",
                cancel_event=cancel_event,
            )
        except CommandCancelled:
            self.last_interrupted = True
            if progress_cb:
                progress_cb(0.99, "🛑 已取消音频解码…")
            return []
        return self.transcribe_array(
            audio,
            progress_cb=progress_cb,
            config=cfg,
            cancel_event=cancel_event,
            time_offset=time_offset,
        )


class SenseVoiceEngine(_SherpaEngine):
    key = "sensevoice"
    label = "SenseVoice-Small"
    repo_id = SENSEVOICE_REPO
    dir_name = "sensevoice-small"
    env_var = "KIKUSUB_SENSEVOICE_MODEL"
    allow_patterns = ("model.int8.onnx", "tokens.txt", "LICENSE", "README.md")
    required_files = ("model.int8.onnx", "tokens.txt")
    approx_label = "约 230 MB"

    def _create_recognizer(self, sherpa_onnx, cfg: SherpaAsrConfig):
        return sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(self.model_dir / "model.int8.onnx"),
            tokens=str(self.model_dir / "tokens.txt"),
            num_threads=int(cfg.num_threads),
            use_itn=bool(cfg.use_itn),
            language=str(cfg.language or "auto"),
        )


class FireRedAsrEngine(_SherpaEngine):
    supports_punc = True
    key = "firered"

    def __init__(self, model_dir=None, config=None) -> None:
        super().__init__(model_dir, config)
        # 标点权重跟 ASR 权重放同一个目录：设置页的体积、下载进度、清理都是一体的。
        self._punc = PunctuationModel(self.model_dir / "punc")
    label = "FireRedASR2-AED"
    repo_id = FIRERED_REPO
    dir_name = "fireredasr2-aed"
    env_var = "KIKUSUB_FIRERED_MODEL"
    allow_patterns = ("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt", "README.md")
    required_files = ("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt")
    approx_label = "约 1.2 GB"

    def ensure_model(self, progress_cb=None) -> None:
        """FireRed 的安装包含 ASR + FireRedPunc（约 160 MB）。

        标点模型下载失败不让整次安装失败：ASR 可用，只是输出没有标点；
        用户之后可以用设置页的「校验 / 补齐」再补。
        """
        super().ensure_model(progress_cb)
        try:
            self._punc.ensure_model(progress_cb)
        except Exception as exc:  # noqa: BLE001 - 配套模型失败不阻塞主引擎
            log.warning("FireRedPunc 下载失败，FireRed 仍可用 | %s", exc, exc_info=True)
            if progress_cb:
                progress_cb(0.995, "标点模型下载失败：FireRed 仍可转写，但输出没有标点")

    def _create_recognizer(self, sherpa_onnx, cfg: SherpaAsrConfig):
        return sherpa_onnx.OfflineRecognizer.from_fire_red_asr(
            encoder=str(self.model_dir / "encoder.int8.onnx"),
            decoder=str(self.model_dir / "decoder.int8.onnx"),
            tokens=str(self.model_dir / "tokens.txt"),
            num_threads=int(cfg.num_threads),
        )


def _dedupe(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    """去掉完全重复/零时长字幕、缝合被切开的多位数字，并把重叠时间轴夹平。

    与 `core/qwen_ctc._dedupe` 同口径（那边是日语专用模块，这里不 import 它，
    避免中文引擎为了一个 10 行函数把整条 Qwen/torch 依赖链拉起来）。
    """
    out: list[SubtitleCue] = []
    for cue in cues:
        text = " ".join(cue.text.split())
        if not text:
            continue
        start = max(0.0, float(cue.start))
        end = max(start + 0.08, float(cue.end))
        if out and start < out[-1].end:
            start = out[-1].end
            if end <= start:
                continue
        if out and text == out[-1].text and start - out[-1].end < 0.05:
            out[-1].end = max(out[-1].end, end)
            continue
        # VAD 会在数字中间切开（「50円」→「5」+「0円」）。停顿为 0 的相邻段
        # 一定是同一个词，直接缝回去；只缝数字，避免把两个英文单词粘成一个。
        if (
            out
            and start - out[-1].end <= 0.05
            and out[-1].text[-1:].isdigit()
            and text[:1].isdigit()
        ):
            out[-1].text += text
            out[-1].end = max(out[-1].end, end)
            continue
        out.append(SubtitleCue(start=round(start, 3), end=round(end, 3), text=text))
    return out
