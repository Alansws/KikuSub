"""界面事件配置与进度卡片的回归测试（需要 gradio）。"""

from __future__ import annotations

import pytest

pytest.importorskip("gradio")

import app  # noqa: E402
from helpers import patch_output_dir  # noqa: E402
from core.transcribe import SubtitleCue  # noqa: E402


class _FakeRequest:
    session_hash = "sess-ui-test"


class _RecordingProgress:
    """记录原生 progress() 是否被调用；调用即说明又会多画一条进度条。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class _FakeStats:
    def describe(self) -> str:
        return "fake stats"


class _FakeEngine:
    """只发进度、不做推理的引擎，避免测试触发模型下载。"""

    last_interrupted = False
    last_missed_spans: list = []
    last_segment_stats: dict = {}
    last_align_stats: dict = {}
    last_stats = _FakeStats()

    def transcribe_file(self, media_path, **kwargs):
        progress_cb = kwargs["progress_cb"]
        for i in range(1, 4):
            progress_cb(i / 4, f"正在识别第 {i}/3 段… (可随时点击取消)")
        return [SubtitleCue(0.0, 1.0, "测试字幕")]


def test_transcribe_event_hides_native_progress_tracker():
    """原生追踪器会给每个 output 组件各画一条进度条，必须保持 hidden。

    否则「📊 全片转录原始结果、表格与任务详报」区域及以下会出现重复进度条，
    并与顶部 ``transcribe_progress`` 卡片错拍闪烁。
    """
    fns = [
        fn
        for fn in app.demo.fns.values()
        if getattr(fn.fn, "__name__", "") == "transcribe_media"
    ]
    assert len(fns) == 1
    assert fns[0].show_progress == "hidden"


def test_transcribe_progress_card_escapes_and_clamps():
    markup = app._render_transcribe_progress_card(56, "<b>第 154/283 段</b>")
    assert "&lt;b&gt;第 154/283 段&lt;/b&gt;" in markup
    assert 'class="tpc-fill" style="width:56%;"' in markup
    assert '<b class="tpc-pct">56%</b>' in markup

    # 越界或负值一律夹到 0–100，避免样式被注入奇怪的宽度。
    assert "width:0%;" in app._render_transcribe_progress_card(-5, "x")
    assert "width:100%;" in app._render_transcribe_progress_card(180, "x")


def test_transcribe_media_streams_card_without_native_progress(tmp_path, monkeypatch):
    """整条转写 generator 只 yield 顶部卡片，不调用原生 progress()。"""
    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    patch_output_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(app, "ENGINE", _FakeEngine())
    monkeypatch.setattr(app, "resolve_engine", lambda _name: app.ENGINE)

    recorder = _RecordingProgress()
    app.JOB_REGISTRY.reset()
    try:
        generator = app.transcribe_media(
            str(media),
            next(iter(app.ENGINES)),
            "SRT",
            False,
            "",
            "",
            True,
            recorder,
            _FakeRequest(),
            *[spec.default for spec in app.PARAMS],
        )
        # 末尾新增 qa_payload；进度卡片仍在倒数第二个输出（transcribe_progress）。
        statuses = [outputs[-2] for outputs in generator]
    finally:
        app.JOB_REGISTRY.reset()

    assert recorder.calls == []
    progress_cards = [s for s in statuses if "transcribe-progress-card" in s]
    assert len(progress_cards) == 3
    assert "25%" in progress_cards[0]
    assert "75%" in progress_cards[-1]
    assert statuses[-1].startswith("✅ 转录完成")
