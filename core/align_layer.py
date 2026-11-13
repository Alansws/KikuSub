"""通用逐字对齐层：把 Qwen 的 CTC 对齐头借给任何引擎（目前是 Anime Whisper）。

**为什么可以这么借**：`ctc_aligner_jav_vocalisation_v3.pt` 是 acoustic-only 的字符
CTC 头（`schema=asr_ctc_alignment_head_v2`，输入 2048 维 = Qwen 音频塔输出，
词表 2601 个日语字），推理时只要「音频特征 + 目标文本」——文本是**外部给的**，
不是它自己解码出来的。所以它天生能给别人的转写结果打时间，不需要重训。

**能到什么精度**（`tune/ctc_align_probe.py`，77 条人工字幕、同一支 830s 素材）：
用人工文本当天花板，逐字时间对人工字幕边界的误差（去掉「人工习惯的提前 0.2s /
停留 0.45s」这类系统性偏移后）起点 p90 320ms、终点 p90 477ms。对照 Anime Whisper
现在按字符比例分配的起点 p90 1.35s：改进了 4 倍，但**达不到** backlog P1-5 定的
±150ms——它解决的是「一个 VAD 块里两句话切在哪」，不是「帧级精确测量」。

**代价**：要多常驻一份 Qwen 权重（实测 MPS 4.3GB）。所以这是**可选层**：
`whisper.use_ctc_alignment` 默认关，开启前要求 Qwen 引擎已装好。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np

from .qwen_ctc import AlignmentResult, FoldedText, QwenCtcConfig, QwenCtcEngine
from .transcribe import SubtitleCue, _is_blank, strip_edge_nonverbal_ex

log = logging.getLogger(__name__)

_LAYER_LOCK = threading.Lock()


@dataclass
class AlignOutcome:
    ok: bool
    reason: str = ""
    cues: list[SubtitleCue] | None = None


class CtcAlignLayer:
    """惰性加载的对齐器；同一时刻只允许一份。"""

    def __init__(self) -> None:
        self._engine: QwenCtcEngine | None = None

    @staticmethod
    def weights_present() -> bool:
        """不加载模型，只看权重在不在（设置页/报告用它回答「能不能开」）。"""
        # 构造引擎只解析路径与设备，不碰权重文件内容。
        return QwenCtcEngine().model_available

    @property
    def ready(self) -> bool:
        return self._engine is not None and self._engine.ready

    def ensure_loaded(self, progress_cb=None) -> bool:
        if self.ready:
            return True
        with _LAYER_LOCK:
            if self.ready:
                return True
            if not self.weights_present():
                return False
            engine = QwenCtcEngine()
            engine.load(progress_cb=progress_cb)
            self._engine = engine
            return True

    def unload(self) -> None:
        """转写结束后主动卸掉，别让两份大模型同时占着显存。"""
        self._engine = None
        try:
            import torch

            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except Exception:
            log.debug("释放 MPS 缓存失败", exc_info=True)

    def split(
        self,
        audio: np.ndarray,
        text: str,
        *,
        offset: float,
        cue: QwenCtcConfig | None = None,
    ) -> AlignOutcome:
        """把一段音频 + 它的文本切成逐字定时的字幕条。"""
        engine = self._engine
        if engine is None:
            return AlignOutcome(False, "aligner-not-loaded")
        cfg = cue or QwenCtcConfig()
        result = self.align(audio, text, engine=engine)
        if not result.ok or not result.chars:
            return AlignOutcome(False, result.reason or "align-failed")
        folded = FoldedText(text)
        cues = engine._cues_from_alignment(result, offset, folded, cfg)
        if cfg.strip_nonverbal_edges:
            kept: list[SubtitleCue] = []
            for item in cues:
                cleaned = strip_edge_nonverbal_ex(item.text)[0]
                if _is_blank(cleaned):
                    continue
                kept.append(
                    SubtitleCue(start=item.start, end=item.end, text=cleaned)
                )
            cues = kept
        return AlignOutcome(True, cues=cues)

    def align(self, audio: np.ndarray, text: str, *, engine: QwenCtcEngine | None = None) -> AlignmentResult:
        target = engine or self._engine
        if target is None:
            return AlignmentResult(ok=False, reason="aligner-not-loaded")
        try:
            return target.align(audio, text)
        except Exception as exc:  # 对齐失败不能吃掉已识别文本，交给调用方回退
            log.warning("CTC 对齐失败，回退按字数分配时间", exc_info=True)
            return AlignmentResult(ok=False, reason=f"align-error:{type(exc).__name__}")


LAYER = CtcAlignLayer()
