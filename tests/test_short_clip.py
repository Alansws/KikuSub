"""短选区轻声兜底（core/short_clip.py）的纯逻辑回归。

这条链只服务核对台的人工短选区；**不能**改 VAD 默认值、整片转写与评测基线。
这里用假引擎把三种结局（原参数命中 / 0.05 命中 / 整段送模命中）都跑一遍。
"""

from __future__ import annotations

from dataclasses import dataclass

from core import short_clip
from core.subtitles import SubtitleCue


@dataclass
class FakeConfig:
    threshold: float = 0.30
    enable_loudnorm: bool = True


@dataclass
class FakeQwenConfig:
    vad_threshold: float = 0.30
    enable_loudnorm: bool = True


class FakeEngine:
    def __init__(self, results: list[list[SubtitleCue]]) -> None:
        self._results = results
        self.configs: list[object] = []
        self.windows: list[object] = []

    def transcribe_file(self, path, *, config=None, **kwargs):  # noqa: ANN001 - 测试替身
        self.configs.append(config)
        if not self._results:
            return []
        return self._results.pop(0)

    def transcribe_window(self, audio, *, config=None, **kwargs):  # noqa: ANN001
        self.windows.append(config)
        return "听得见的台词"


def cue(text: str = "台词") -> SubtitleCue:
    return SubtitleCue(start=1.0, end=2.0, text=text)


def test_selection_seconds_handles_open_ranges():
    assert short_clip.selection_seconds(10, 13, 100) == 3
    assert short_clip.selection_seconds(None, None, 100) == 0
    assert short_clip.selection_seconds(90, None, 100) == 10
    # 倒序 / 负起点都夹到 0，不产生负时长
    assert short_clip.selection_seconds(5, 3, 100) == 0
    assert short_clip.selection_seconds(-5, 5, 100) == 5


def test_plan_fallbacks_only_short_selections():
    assert short_clip.plan_fallbacks(0) == []
    assert short_clip.plan_fallbacks(5) == ["low_threshold", "whole_clip"]
    # 12 < d <= 20：只降阈值，不再整段送模
    assert short_clip.plan_fallbacks(12.5) == ["low_threshold"]
    assert short_clip.plan_fallbacks(20) == ["low_threshold"]
    # 20s 以上不动：那是正常长短句，该用当前参数
    assert short_clip.plan_fallbacks(20.5) == []
    assert short_clip.plan_fallbacks(600) == []


def test_lower_threshold_uses_each_family_field():
    whisper = short_clip.lower_threshold(FakeConfig(), "whisper")
    assert isinstance(whisper, FakeConfig)
    assert whisper.threshold == short_clip.LOW_VAD_THRESHOLD
    assert whisper.enable_loudnorm is True  # 其余字段原样保留

    qwen = short_clip.lower_threshold(FakeQwenConfig(), "qwen")
    assert qwen.vad_threshold == short_clip.LOW_VAD_THRESHOLD


def test_lower_threshold_is_none_when_already_low_or_unknown():
    assert short_clip.lower_threshold(FakeConfig(threshold=0.03), "whisper") is None
    assert short_clip.lower_threshold(None, "whisper") is None
    assert short_clip.lower_threshold(object(), "whisper") is None


def test_whole_clip_cue_covers_the_whole_selection():
    mark = short_clip.whole_clip_cue("  すぅ…  ", 10.1234, 11.9876)
    assert mark.start == 10.123
    assert mark.end == 11.988
    assert mark.text == "すぅ…"


def test_run_fallbacks_returns_first_non_empty(monkeypatch):
    engine = FakeEngine([[cue("降阈值命中")]])
    calls: list[object] = []

    def retry(config):
        calls.append(config)
        return engine.transcribe_file("x", config=config)

    # 整段送模不该被走到：第一次降阈值重试已经命中
    monkeypatch.setattr(short_clip, "read_whole_clip", lambda *a, **k: "不该用到")
    cues = short_clip.run_fallbacks(
        engine=engine,
        family="whisper",
        config=FakeConfig(),
        media_path="x",
        start_s=1,
        end_s=3,
        duration=2,
        retry=retry,
    )
    assert [c.text for c in cues] == ["降阈值命中"]
    assert calls and calls[0].threshold == short_clip.LOW_VAD_THRESHOLD


def test_run_fallbacks_drops_to_whole_clip_only_when_needed(monkeypatch):
    engine = FakeEngine([])
    monkeypatch.setattr(short_clip, "read_whole_clip", lambda *a, **k: "整段送模命中")
    cues = short_clip.run_fallbacks(
        engine=engine,
        family="whisper",
        config=FakeConfig(),
        media_path="x",
        start_s=10,
        end_s=15,
        duration=5,
        retry=lambda config: engine.transcribe_file("x", config=config),
    )
    assert len(cues) == 1
    assert cues[0].start == 10 and cues[0].end == 15
    assert cues[0].text == "整段送模命中"


def test_run_fallbacks_never_whole_clips_long_selection(monkeypatch):
    engine = FakeEngine([])
    called: list[str] = []

    def fake_read(*a, **k):
        called.append("whole")
        return "不该发生"

    monkeypatch.setattr(short_clip, "read_whole_clip", fake_read)
    cues = short_clip.run_fallbacks(
        engine=engine,
        family="whisper",
        config=FakeConfig(),
        media_path="x",
        start_s=0,
        end_s=15,  # > 12s：只降阈值
        duration=15,
        retry=lambda config: engine.transcribe_file("x", config=config),
    )
    assert cues == []
    assert called == []


def test_run_fallbacks_respects_cancel_between_steps():
    engine = FakeEngine([])
    state = {"cancelled": False}

    def retry(config):
        state["cancelled"] = True
        return engine.transcribe_file("x", config=config)

    cues = short_clip.run_fallbacks(
        engine=engine,
        family="whisper",
        config=FakeConfig(),
        media_path="x",
        start_s=0,
        end_s=5,
        duration=5,
        retry=retry,
        cancelled=lambda: state["cancelled"],
    )
    assert cues == []
    assert len(engine.configs) == 1  # 取消后不再尝试第二步


def test_run_fallbacks_swallows_decode_cancel(monkeypatch):
    from core.procutil import CommandCancelled

    def raise_cancel(*a, **k):
        raise CommandCancelled(["ffmpeg"])

    monkeypatch.setattr(short_clip, "read_whole_clip", raise_cancel)
    cues = short_clip.run_fallbacks(
        engine=FakeEngine([]),
        family="qwen",
        config=FakeQwenConfig(),
        media_path="x",
        start_s=0,
        end_s=5,
        duration=5,
        retry=lambda config: [],
    )
    assert cues == []


def test_whole_clip_decodes_vocals_but_cue_uses_absolute_timeline(monkeypatch):
    """人声分离后解码区间是 None（wav 本身=选区），字幕仍要用原片绝对时间。"""
    seen: dict = {}

    def fake_read(engine, family, config, *, media_path, start_time_s, end_time_s, cancel_event=None, **kw):
        seen["decode"] = (start_time_s, end_time_s)
        return "分离后的台词"

    monkeypatch.setattr(short_clip, "read_whole_clip", fake_read)
    cues = short_clip.run_fallbacks(
        engine=FakeEngine([]),
        family="whisper",
        config=FakeConfig(),
        media_path="vocals.wav",
        start_s=100.0,
        end_s=105.0,
        decode_start=None,
        decode_end=None,
        duration=5,
        retry=lambda config: [],
    )
    assert seen["decode"] == (None, None)
    assert len(cues) == 1
    assert (cues[0].start, cues[0].end) == (100.0, 105.0)
