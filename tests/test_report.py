"""任务详报的展示契约：疑似漏句 / 幻觉门控与复核（需要 gradio 构建 app）。"""

from __future__ import annotations

import html as html_lib

import pytest

pytest.importorskip("gradio")

import app  # noqa: E402
from core import report as core_report  # noqa: E402
from core.transcribe import WhisperVadConfig  # noqa: E402


def _report(**overrides) -> str:
    params = dict(
        media_name="sample.mkv",
        out_filename="sample.whisper.srt",
        out_path="/tmp/sample.whisper.srt",
        engine_name="Anime Whisper",
        output_format="SRT",
        elapsed_time=12.0,
        cue_count=3,
        char_count=30,
        is_qwen=False,
        config=WhisperVadConfig(),
    )
    params.update(overrides)
    return core_report.build_transcription_report(**params)


_SPANS = [
    {
        "start": 1.0, "end": 1.5, "dur": 0.5, "text": "…ッ!",
        "rule": "short", "verdict": "dropped", "peak": 0.9, "rms": 0.1,
    },
    {
        "start": 3.0, "end": 4.14, "dur": 1.14, "text": "ぐぬっ…!",
        "rule": "low-density", "verdict": "suspect", "peak": 0.42, "rms": 0.08,
    },
]


def test_report_lists_each_hallucination_span_with_time_and_rule():
    text = _report(
        segment_stats={
            "hallucination_drops": 1,
            "suspect_cues": 1,
            "hallucination_spans": _SPANS,
        },
        align_stats={},
    )

    assert "【幻觉门控】已丢弃 1 段经时间戳复核为空的疑似幻觉" in text
    assert "【幻觉复核】1 段短/低密度结果未被丢弃，建议人工核对" in text
    # 明细行必须带时间轴、判据标签、峰值与原文，方便直接对时补录
    assert "• 00:00:01.000 → 00:00:01.500  (0.50s)  短段复核  峰值 0.900  「…ッ!」" in text
    assert "• 00:00:03.000 → 00:00:04.140  (1.14s)  低密度  峰值 0.420  「ぐぬっ…!」" in text


def test_report_states_gate_ran_when_nothing_triggered():
    text = _report(segment_stats={}, align_stats={})
    assert "【幻觉门控】未触发（没有段落复核为空被删）" in text
    assert "【幻觉复核】未触发（无短段/低密度结果需要复核）" in text


def test_report_marks_gate_absent_for_qwen():
    text = _report(is_qwen=True, segment_stats={}, align_stats={})
    assert "【幻觉门控】该引擎不启用（仅 Anime Whisper 做时间戳复核）" in text
    assert "【幻觉复核】" not in text


def test_report_caps_long_hallucination_lists():
    spans = [
        {**span, "start": float(i), "end": float(i) + 0.5}
        for i, span in enumerate(_SPANS * 60)
    ]
    text = _report(
        segment_stats={"hallucination_drops": 60, "suspect_cues": 60, "hallucination_spans": spans},
        align_stats={},
    )
    over = 60 - core_report.HALLUCINATION_SPAN_LIMIT
    assert text.count(f"另有 {over} 段未列出") == 2


def test_report_panel_keeps_quoted_colons_in_one_row():
    spans = [{
        "start": 3.0, "end": 3.4, "dur": 0.4, "text": "「はい」：そう",
        "rule": "short", "verdict": "suspect", "peak": 0.3,
    }]
    html = app.render_report_panel(_report(
        segment_stats={"suspect_cues": 1, "hallucination_spans": spans}, align_stats={}
    ))
    # 引用原文里的全角冒号不得被当成「标签：值」拆成两列
    assert "「「はい」：そう」" in html
    assert "短段复核  峰值 0.300  「「はい」：そう」</span></div></section>" in html


def test_report_raw_text_matches_panel_copy_source():
    text = _report(
        segment_stats={"hallucination_drops": 1, "hallucination_spans": _SPANS[:1]},
        align_stats={},
    )
    assert f'<pre id="report-raw-text" class="report-raw-src">{html_lib.escape(text)}</pre>' in app.render_report_panel(text)


def test_report_explains_qwen_coverage_instead_of_faking_clean():
    """Qwen 没有幻觉悟复核：0 条必须写成「不启用」，不能读成「复查过且干净」。"""
    text = _report(is_qwen=True, segment_stats={}, align_stats={})
    assert "引擎差异：Qwen3-ASR 只执行「🔍 可能漏句」检查" in text
    assert "「✂️ 误删待核 / 👂 短句待确认」依赖 Anime Whisper 的时间戳复核，本引擎不启用" in text
    # 队列入口常驻的说明也必须在报告里，避免用户以为 0 条就代表功能不存在
    assert "队列入口常驻右下角「🔎 质检」" in text


def test_report_offers_plain_language_summary_and_queue_pointer():
    text = _report(
        missed_spans=[{"start": 2.0, "end": 3.0, "dur": 1.0, "peak": 0.2}],
        segment_stats={
            "hallucination_drops": 1,
            "suspect_cues": 1,
            "hallucination_spans": _SPANS,
        },
        align_stats={},
    )
    # 术语之外先给一句人话总览（两组），并明确告诉用户去可交互队列处理
    assert "【质检速览】📭 未覆盖空白 0 处 ｜ 🔎 切片内异常 3 处" in text
    assert "「🔎 质检待核」" in text
    assert "有声音、但两次识别都为空" in text
    assert "若你听到台词请点「恢复原句」补回" in text
