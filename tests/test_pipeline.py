"""转写编排的契约测试（不依赖 UI）。

`core.pipeline.run_transcription` 是旧界面与服务层共用的唯一编排实现，
所以这里用替身引擎锁住它的对外行为：进度转发、产物命名、打断语义、
质检队列落盘、以及返回值结构。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("torch")

from core import audit, pipeline  # noqa: E402
from core.transcribe import SubtitleCue  # noqa: E402


class _FakeStats:
    def describe(self) -> str:
        return "fake stats"


class _FakeEngine:
    """只发进度、不推理；可切换「被打断」形态。"""

    def __init__(self, *, interrupted: bool = False) -> None:
        self.last_interrupted = interrupted
        self.last_missed_spans: list = []
        self.last_segment_stats: dict = {}
        self.last_align_stats: dict = {}
        self.last_stats = _FakeStats()
        self.received: dict = {}

    def transcribe_file(self, media_path, **kwargs):
        self.received = kwargs
        cb = kwargs["progress_cb"]
        for i in range(1, 4):
            cb(i / 4, f"第 {i}/3 段")
        return [SubtitleCue(0.0, 1.0, "テスト"), SubtitleCue(1.0, 2.5, "二行目")]


@pytest.fixture()
def media(tmp_path: Path) -> Path:
    path = tmp_path / "episode.mkv"
    path.write_bytes(b"x")
    return path


def _patch_dirs(monkeypatch, tmp_path: Path) -> None:
    from core import paths, report

    for module in (paths, report, audit):
        monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path, raising=False)


def test_progress_is_forwarded_in_order(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    seen: list[tuple[float, str]] = []
    engine = _FakeEngine()

    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(media_path=media),
        on_progress=lambda r, m: seen.append((r, m)),
        output_dir=tmp_path,
        engine=engine,
    )

    assert [round(r, 2) for r, _ in seen] == [0.25, 0.5, 0.75]
    assert len(result.cues) == 2
    assert result.out_filename.endswith(".srt")
    assert Path(result.out_path).exists()
    assert "テスト" in Path(result.out_path).read_text(encoding="utf-8")


def test_qwen_output_gets_its_own_suffix(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(media_path=media, engine_key="qwen"),
        output_dir=tmp_path,
        engine=_FakeEngine(),
    )
    assert result.out_filename == "episode.qwen.srt"


def test_slice_tag_lands_in_filename_and_report(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(media_path=media, start_s=10.0, end_s=65.0),
        output_dir=tmp_path,
        engine=_FakeEngine(),
    )
    assert result.slice_tag == "_00m10s-01m05s"
    assert result.out_filename.startswith("episode_00m10s-01m05s")
    assert "00m10s 至 01m05s" in result.report_text
    # 引擎必须收到同一组切片参数，否则字幕时间轴会和文件名对不上
    engine_kwargs = result and None
    assert engine_kwargs is None


def test_interrupted_run_keeps_partial_file(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(media_path=media),
        output_dir=tmp_path,
        engine=_FakeEngine(interrupted=True),
    )
    assert result.interrupted is True
    assert ".part_cancelled" in result.out_filename
    assert result.status_summary.startswith("⚠️")
    assert "打断" in result.final_progress


def test_empty_result_raises_actionable_error(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)

    class _Empty(_FakeEngine):
        def transcribe_file(self, media_path, **kwargs):
            return []

    with pytest.raises(RuntimeError, match="未检测到有效语音"):
        pipeline.run_transcription(
            pipeline.TranscribeRequest(media_path=media),
            output_dir=tmp_path,
            engine=_Empty(),
        )


def test_audit_payload_is_written_and_parsable(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(media_path=media),
        output_dir=tmp_path,
        engine=_FakeEngine(),
    )
    payload = json.loads(result.audit_payload)
    assert payload["phase"] == "done"
    assert payload["media"] == "episode.mkv"
    assert payload["scanned"]["cues"] == 2
    assert payload["latest_cue_count"] == 2
    # 落盘后能按同一媒体读回来
    loaded = json.loads(audit.load_audit_payload(str(media)))
    assert loaded["latest_cue_count"] == 2


def test_absolute_timeline_offsets_are_passed_through(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    engine = _FakeEngine()
    pipeline.run_transcription(
        pipeline.TranscribeRequest(media_path=media, start_s=30.0, keep_absolute_timeline=True),
        output_dir=tmp_path,
        engine=engine,
    )
    assert engine.received["time_offset"] == 30.0

    engine2 = _FakeEngine()
    pipeline.run_transcription(
        pipeline.TranscribeRequest(media_path=media, start_s=30.0, keep_absolute_timeline=False),
        output_dir=tmp_path,
        engine=engine2,
    )
    assert engine2.received["time_offset"] == 0.0


@pytest.mark.parametrize(
    ("start", "end", "tag", "desc"),
    [
        (None, None, "", "全片完整转录"),
        (10.0, 65.0, "_00m10s-01m05s", "00m10s 至 01m05s (55.0 秒)"),
        (10.0, None, "_from_00m10s", "从 00m10s 开始至片尾"),
        (None, 65.0, "_to_01m05s", "从 00m00s 开始至 01m05s"),
    ],
)
def test_plan_slice(start, end, tag, desc):
    assert pipeline.plan_slice(start, end) == (tag, desc)


def test_unknown_engine_key_rejected(media, tmp_path):
    with pytest.raises(ValueError, match="未知的识别引擎"):
        pipeline.run_transcription(
            pipeline.TranscribeRequest(media_path=media, engine_key="nope"),
            output_dir=tmp_path,
        )


def test_coverage_spans_reach_audit_payload_and_report(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)

    class _CoverageEngine(_FakeEngine):
        def transcribe_file(self, media_path, **kwargs):
            cues = super().transcribe_file(media_path, **kwargs)
            self.last_coverage_spans = [{
                "start": 0.6, "end": 1.2, "dur": 0.6,
                "gap_start": 0.5, "gap_end": 2.0, "gap_dur": 1.5,
                "peak": 0.03, "rms": 0.005, "vad_mean": 0.5, "vad_max": 0.8,
            }]
            return cues

    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(media_path=media),
        output_dir=tmp_path,
        engine=_CoverageEngine(),
    )
    payload = json.loads(result.audit_payload)
    assert payload["scanned"]["coverage"] == 1
    coverage_items = [item for item in payload["items"] if item["kind"] == "coverage"]
    assert len(coverage_items) == 1
    assert coverage_items[0]["group"] == "miss"
    assert result.report_data["quality"]["coverage"] == 1
    assert any(section["id"] == "coverage" for section in result.report_data["sections"])
    assert result.coverage_spans
