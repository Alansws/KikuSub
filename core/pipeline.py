"""转写任务编排：从 `app.py` 的 `transcribe_media` 里抽出的 worker 主体。

**这段代码原本是一个 Gradio 生成器**：一边跑引擎，一边 `yield gr.update(...)`。
抽出来之后它只做三件事——

1. 调引擎（Whisper / Qwen），把进度通过 `on_progress(ratio, message)` 抛出去；
2. 落盘字幕、生成任务详报、生成质检队列；
3. 返回一个 `TranscribeResult`。

进度怎么呈现（Gradio 的进度卡片 / WebSocket 帧）由调用方决定，这里不关心。
这样旧界面与服务层跑的是同一份编排，不会出现「网页能取消、桌面端不能」这种分叉。

**取消语义**（见 AGENTS.md §3，不要改）：
- 取消只发信号（`cancel_event.set()`），槽位由真正停止工作的 worker 在 `finally` 释放；
- 被打断时已产出的字幕要保存，文件名带 `.part_cancelled`。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .audit import build_audit_items, make_audit_payload, write_audit_payload
from .cues import cues_to_table
from .paths import OUTPUT_DIR
from .report import (
    _missed_hidden_count,
    _visible_missed_spans,
    build_report_data,
    write_missed_report,
)
from .textio import write_text_atomic
from .transcribe import (
    ENGINE,
    SubtitleCue,
    WhisperVadConfig,
    cues_to_srt,
    cues_to_txt,
    cues_to_vtt,
    format_duration,
    format_time_tag,
)
from .qwen_ctc import QwenCtcConfig, QwenCtcEngine

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str], None]

# 引擎是进程级单例：模型权重只加载一次，多任务复用。
QWEN = QwenCtcEngine()

ENGINE_KEYS = ("whisper", "qwen")

ENGINE_DISPLAY = {
    "whisper": "Anime Whisper",
    "qwen": "Qwen3-ASR + 逐字对齐",
}

_ENGINE_OBJECTS = {"whisper": ENGINE, "qwen": QWEN}


def resolve_engine(engine_key: str):
    engine = _ENGINE_OBJECTS.get(engine_key)
    if engine is None:
        raise ValueError(f"未知的识别引擎: {engine_key}")
    return engine


def output_suffix(engine_key: str) -> str:
    """Whisper 产物不加后缀，Qwen 加 `.qwen`，避免两个引擎互相覆盖。"""
    return "" if engine_key == "whisper" else ".qwen"


@dataclass(slots=True)
class TranscribeRequest:
    media_path: Path
    # 服务层用：让结果能回指到 /api/media 的 id（桌面端导入的是路径，id 在服务层）
    media_id: str = ""
    engine_key: str = "whisper"
    output_format: str = "SRT"
    save_beside: bool = False
    start_s: float | None = None
    end_s: float | None = None
    keep_absolute_timeline: bool = True
    whisper_config: WhisperVadConfig | None = None
    qwen_config: QwenCtcConfig | None = None
    no_repeat_ngram_size: int = 5
    repetition_penalty: float = 1.15
    use_alignment: bool = True

    @property
    def is_qwen(self) -> bool:
        return self.engine_key == "qwen"

    @property
    def time_offset(self) -> float:
        return (self.start_s or 0.0) if self.keep_absolute_timeline else 0.0


@dataclass(slots=True)
class TranscribeResult:
    cues: list[SubtitleCue]
    out_path: Path
    out_filename: str
    elapsed: float
    char_count: int
    interrupted: bool
    report_text: str
    audit_payload: str
    pending_qa: int
    status_summary: str
    final_progress: str
    preview: str
    table: list[list] = field(default_factory=list)
    missed_spans: list[dict] = field(default_factory=list)
    report_data: dict = field(default_factory=dict)
    segment_stats: dict = field(default_factory=dict)
    align_stats: dict = field(default_factory=dict)
    slice_tag: str = ""
    time_slice_desc: str = ""

    def to_dict(self) -> dict:
        return {
            "cues": [{"start": c.start, "end": c.end, "text": c.text} for c in self.cues],
            "out_path": str(self.out_path),
            "out_filename": self.out_filename,
            "elapsed": self.elapsed,
            "char_count": self.char_count,
            "cue_count": len(self.cues),
            "interrupted": self.interrupted,
            "report_text": self.report_text,
            "report": self.report_data,
            "audit_payload": self.audit_payload,
            "pending_qa": self.pending_qa,
            "status_summary": self.status_summary,
            "final_progress": self.final_progress,
            "preview": self.preview,
            "table": self.table,
            "missed_spans": self.missed_spans,
            "segment_stats": self.segment_stats,
            "align_stats": self.align_stats,
            "slice_tag": self.slice_tag,
            "time_slice_desc": self.time_slice_desc,
        }


def plan_slice(
    start_s: float | None, end_s: float | None
) -> tuple[str, str]:
    """把起止时间翻译成「文件名后缀 + 人类可读描述」。

    四种组合（全片 / 区间 / 从某点至片尾 / 从片头至某点）各自有固定文案，
    报告与状态行都直接引用，改文案时注意 `test_report` 有断言。
    """
    if start_s is not None and end_s is not None:
        return (
            f"_{format_time_tag(start_s)}-{format_time_tag(end_s)}",
            f"{format_time_tag(start_s)} 至 {format_time_tag(end_s)} ({end_s - start_s:.1f} 秒)",
        )
    if start_s is not None:
        return f"_from_{format_time_tag(start_s)}", f"从 {format_time_tag(start_s)} 开始至片尾"
    if end_s is not None:
        return f"_to_{format_time_tag(end_s)}", f"从 00m00s 开始至 {format_time_tag(end_s)}"
    return "", "全片完整转录"


def render_subtitles(cues: list[SubtitleCue], output_format: str) -> tuple[str, str]:
    if output_format == "SRT":
        return cues_to_srt(cues), ".srt"
    if output_format == "VTT":
        return cues_to_vtt(cues), ".vtt"
    return cues_to_txt(cues), ".txt"


def run_transcription(
    req: TranscribeRequest,
    *,
    on_progress: ProgressCb | None = None,
    cancel_event=None,
    output_dir: Path | None = None,
    engine=None,
) -> TranscribeResult:
    """跑一次转写并落盘。阻塞调用，异常直接抛给调用方。

    `engine` 可显式注入：调用方（旧界面 / 测试）可能自己持有引擎实例或替身，
    不传时按 `req.engine_key` 取进程内单例。
    """
    media_path = Path(req.media_path)
    engine = engine if engine is not None else resolve_engine(req.engine_key)
    is_qwen = req.is_qwen
    out_dir = Path(output_dir or OUTPUT_DIR)
    slice_tag, time_slice_desc = plan_slice(req.start_s, req.end_s)

    def cb(ratio: float, message: str) -> None:
        if on_progress is not None:
            on_progress(max(0.0, min(1.0, float(ratio))), message)

    started = time.perf_counter()
    if is_qwen:
        cues = engine.transcribe_file(
            media_path,
            progress_cb=cb,
            use_alignment=req.use_alignment,
            config=req.qwen_config,
            cancel_event=cancel_event,
            start_time_s=req.start_s,
            end_time_s=req.end_s,
            time_offset=req.time_offset,
        )
        stats_note = ""
    else:
        cues = engine.transcribe_file(
            media_path,
            config=req.whisper_config,
            no_repeat_ngram_size=req.no_repeat_ngram_size,
            repetition_penalty=req.repetition_penalty,
            progress_cb=cb,
            cancel_event=cancel_event,
            start_time_s=req.start_s,
            end_time_s=req.end_s,
            time_offset=req.time_offset,
        )
        stats_note = f"\n\n`{engine.last_stats.describe()}`"

    elapsed = time.perf_counter() - started
    is_interrupted = bool(engine.last_interrupted) or bool(
        cancel_event is not None and cancel_event.is_set()
    )
    missed_spans = list(getattr(engine, "last_missed_spans", []) or [])
    segment_stats = dict(getattr(engine, "last_segment_stats", {}) or {})
    align_stats = dict(getattr(engine, "last_align_stats", {}) or {})

    if not cues:
        if is_interrupted:
            raise RuntimeError("转录已取消，尚未生成有效字幕。")
        raise RuntimeError(
            "未检测到有效语音。请尝试调低 VAD 阈值（如 0.20）或开启「动态响度归一化」后再试。"
        )

    text, ext = render_subtitles(cues, req.output_format)
    tag = output_suffix(req.engine_key)
    interrupted_tag = ".part_cancelled" if is_interrupted else ""
    out_filename = f"{media_path.stem}{slice_tag}{tag}{interrupted_tag}{ext}"

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / out_filename
    write_text_atomic(out_path, text)

    if req.save_beside:
        beside = media_path.with_name(out_filename)
        try:
            beside.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(beside, text)
            out_path = beside
        except OSError:
            pass

    char_count = sum(len(c.text) for c in cues)
    write_missed_report(media_path, slice_tag, "qwen" if is_qwen else "whisper", missed_spans)
    report_data = build_report_data(
        media_name=media_path.name,
        out_filename=out_filename,
        out_path=str(out_path),
        engine_name=ENGINE_DISPLAY[req.engine_key],
        output_format=req.output_format,
        elapsed_time=elapsed,
        cue_count=len(cues),
        char_count=char_count,
        is_qwen=is_qwen,
        config=req.qwen_config if is_qwen else req.whisper_config,
        is_interrupted=is_interrupted,
        time_slice_desc=time_slice_desc,
        ngram=req.no_repeat_ngram_size,
        penalty=req.repetition_penalty,
        use_alignment=req.use_alignment,
        missed_spans=missed_spans,
        segment_stats=segment_stats,
        align_stats=align_stats,
    )
    report_text = report_data["raw_text"]

    preview_lines = [f"[{c.start:7.2f} → {c.end:7.2f}] {c.text}" for c in cues[:100]]
    preview = "\n".join(preview_lines)
    if len(cues) > 100:
        preview += f"\n\n… 共 {len(cues)} 条字幕（已展示前 100 条）"
    preview += stats_note

    if is_interrupted:
        status_summary = (
            f"⚠️ **转录已中途打断** ｜ 已抢救保存前 `{len(cues)}` 条字幕 ｜ "
            f"耗时：`{format_duration(elapsed)}`"
        )
        final_progress = f"⚠️ 转写打断！已抢救保存前 {len(cues)} 条字幕。"
    else:
        status_summary = (
            f"✅ **转写完成** ｜ 耗时：`{format_duration(elapsed)}` ｜ "
            f"条数：`{len(cues)}` 条 ｜ 字符数：`{char_count}` 字"
        )
        final_progress = f"✅ 转录完成！共生成 {len(cues)} 条字幕（耗时 {format_duration(elapsed)}）"

    audit_items = build_audit_items(missed_spans, segment_stats, cues)
    segment_total = int((align_stats or {}).get("segments") or 0)
    if not segment_total:
        segment_total = int(getattr(getattr(engine, "last_stats", None), "segments", 0) or 0)
    scanned = {
        "segments": segment_total,
        "cues": len(cues),
        "missed": len(_visible_missed_spans(missed_spans)),
        "hidden_missed": _missed_hidden_count(missed_spans),
    }
    if not is_qwen:
        scanned["dropped"] = int(segment_stats.get("hallucination_drops", 0) or 0)
        scanned["suspect"] = int(segment_stats.get("suspect_cues", 0) or 0)
    audit_payload = make_audit_payload(
        media_path.name,
        audit_items,
        {},
        len(cues),
        _missed_hidden_count(missed_spans),
        engine="qwen" if is_qwen else "whisper",
        phase="done",
        scanned=scanned,
        transcribed_at=time.time(),
    )
    write_audit_payload(media_path, audit_payload)

    pending_qa = sum(1 for item in audit_items if item.get("status") == "pending")
    if pending_qa and not is_interrupted:
        final_progress += f" ｜ 🔎 质检：{pending_qa} 处待你试听确认（右下角浮标）"
    elif not is_interrupted:
        final_progress += " ｜ ✅ 质检：本次 0 处待核（入口仍在右下角）"
    if is_interrupted:
        final_progress += " ｜ ⚠️ 本次为打断结果，队列只覆盖已保存的字幕"

    log.info(
        "转写完成 | cues=%s | chars=%s | elapsed=%.2fs | interrupted=%s | out=%s | qa=%s",
        len(cues),
        char_count,
        elapsed,
        is_interrupted,
        out_path.name,
        pending_qa,
    )

    return TranscribeResult(
        cues=cues,
        out_path=out_path,
        out_filename=out_filename,
        elapsed=elapsed,
        char_count=char_count,
        interrupted=is_interrupted,
        report_text=report_text,
        audit_payload=audit_payload,
        report_data=report_data,
        pending_qa=pending_qa,
        status_summary=status_summary,
        final_progress=final_progress,
        preview=preview,
        table=cues_to_table(cues),
        missed_spans=missed_spans,
        segment_stats=segment_stats,
        align_stats=align_stats,
        slice_tag=slice_tag,
        time_slice_desc=time_slice_desc,
    )
