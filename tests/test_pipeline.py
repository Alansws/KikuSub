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
        self.media_path = None

    def transcribe_file(self, media_path, **kwargs):
        self.media_path = media_path
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
    assert result.out_filename == "episode.Qwen3-ASR.srt"


def test_slice_tag_lands_in_filename_and_report(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(media_path=media, start_s=10.0, end_s=65.0),
        output_dir=tmp_path,
        engine=_FakeEngine(),
    )
    assert result.slice_tag == "_00m10s-01m05s"
    assert result.out_filename == "episode_00m10s-01m05s.AnimeWhisper.srt"
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
    assert result.out_filename == "episode.AnimeWhisper.part_cancelled.srt"
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


def test_nonverbal_spans_reach_audit_payload_and_report(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)

    class _NonverbalEngine(_FakeEngine):
        def transcribe_file(self, media_path, **kwargs):
            cues = super().transcribe_file(media_path, **kwargs)
            self.last_segment_stats = {
                "nonverbal_spans": [{
                    "start": 4.0, "end": 5.2, "dur": 1.2,
                    "text": "ふふっ", "rule": "sound-only", "peak": 0.2, "rms": 0.02,
                }],
                "nonverbal_skips": 1,
                "start_repair": {
                    "enabled": True, "considered": 2, "pulled": 1,
                    "total_pull_s": 0.8, "max_pull_s": 0.8,
                },
            }
            return cues

    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(media_path=media),
        output_dir=tmp_path,
        engine=_NonverbalEngine(),
    )
    payload = json.loads(result.audit_payload)
    assert payload["scanned"]["nonverbal"] == 1
    nonverbal = [item for item in payload["items"] if item["kind"] == "nonverbal"]
    assert len(nonverbal) == 1
    assert nonverbal[0]["text"] == "ふふっ"
    assert result.report_data["quality"]["nonverbal"] == 1
    section_ids = [section["id"] for section in result.report_data["sections"]]
    assert "nonverbal" in section_ids
    assert "start_repair" in section_ids


def test_sensevoice_uses_sherpa_dispatch_and_own_suffix(media, tmp_path, monkeypatch):
    """中文引擎走 sherpa 分支：只拿 config，不拿 qwen 的 use_alignment。"""
    _patch_dirs(monkeypatch, tmp_path)
    from core.sherpa_asr import SherpaAsrConfig

    engine = _FakeEngine()
    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(
            media_path=media,
            engine_key="sensevoice",
            sherpa_config=SherpaAsrConfig(max_cue_chars=16),
        ),
        output_dir=tmp_path,
        engine=engine,
    )

    assert engine.received["config"].max_cue_chars == 16
    assert "use_alignment" not in engine.received
    assert result.out_filename == "episode.SenseVoice-Small.srt"
    assert result.report_data["quality"]["engine_family"] == "sherpa"
    assert "SenseVoice-Small" in result.report_text


def test_firered_output_gets_its_own_suffix(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(media_path=media, engine_key="firered"),
        output_dir=tmp_path,
        engine=_FakeEngine(),
    )
    assert result.out_filename == "episode.FireRedASR2-AED.srt"
    assert "FireRedASR2-AED" in result.report_text


def test_engine_family_comes_from_registry(media, tmp_path, monkeypatch):
    """加引擎不该再写第二份白名单：未知 key 直接拒绝，而不是静默退回 Whisper。"""
    _patch_dirs(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        pipeline.run_transcription(
            pipeline.TranscribeRequest(media_path=media, engine_key="sensevoice-pro"),
            output_dir=tmp_path,
        )


def test_separate_vocals_routes_engine_to_cached_vocals(media, tmp_path, monkeypatch):
    """高级档（to_asr）：引擎拿到的是区间 vocals，时间轴仍按原片绝对时间。"""
    _patch_dirs(monkeypatch, tmp_path)
    from core import audio_cache, separate

    vocals = tmp_path / "vocals.wav"
    vocals.write_bytes(b"RIFF" + b"x" * 100)
    seen: dict = {}

    def fake_ensure(media_path, *, start, end, separator, cancel_event=None, progress_cb=None):
        seen.update(start=start, end=end)
        if progress_cb:
            progress_cb(0.5, "fake sep")
        return vocals

    monkeypatch.setattr(audio_cache, "ensure_vocals_wav", fake_ensure)
    monkeypatch.setattr(separate, "available", lambda: True)

    engine = _FakeEngine()
    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(
            media_path=media,
            start_s=10.0,
            end_s=20.0,
            separate_vocals=True,
            separate_mode="to_asr",
        ),
        output_dir=tmp_path,
        engine=engine,
    )

    assert seen == {"start": 10.0, "end": 20.0}
    assert engine.media_path == vocals
    assert engine.received["start_time_s"] is None
    assert engine.received["end_time_s"] is None
    assert engine.received["time_offset"] == 10.0
    assert result.out_filename.startswith("episode_00m10s-00m20s")


def test_separate_vocals_vad_only_keeps_original_audio(media, tmp_path, monkeypatch):
    """默认档（vad_only）：ASR 仍读原声与原区间，只有 VAD 拿分离人声。"""
    _patch_dirs(monkeypatch, tmp_path)
    from core import audio_cache, separate

    vocals = tmp_path / "vocals.wav"
    vocals.write_bytes(b"RIFF" + b"x" * 100)
    seen: dict = {}

    def fake_ensure(media_path, *, start, end, separator, cancel_event=None, progress_cb=None):
        seen.update(start=start, end=end)
        return vocals

    monkeypatch.setattr(audio_cache, "ensure_vocals_wav", fake_ensure)
    monkeypatch.setattr(separate, "available", lambda: True)

    engine = _FakeEngine()
    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(
            media_path=media,
            start_s=10.0,
            end_s=20.0,
            separate_vocals=True,
        ),
        output_dir=tmp_path,
        engine=engine,
    )

    assert seen == {"start": 10.0, "end": 20.0}
    # 识别音频 = 原片 + 原区间（与未开分离逐字节同一条解码路径）。
    assert engine.media_path == media
    assert engine.received["start_time_s"] == 10.0
    assert engine.received["end_time_s"] == 20.0
    # 干净人声只作为 VAD 参考传进去。
    assert engine.received["vad_audio_path"] == vocals
    assert engine.received["vad_audio_path"] != engine.media_path
    assert engine.received["time_offset"] == 10.0
    assert result.out_filename.startswith("episode_00m10s-00m20s")


def test_separate_mode_defaults_to_vad_only():
    from core.pipeline import SEPARATE_MODE_VAD_ONLY, TranscribeRequest

    assert TranscribeRequest(media_path=Path("x.mkv")).separate_mode == SEPARATE_MODE_VAD_ONLY


def test_separate_mode_rejects_unknown_value(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    from core import audio_cache, separate

    monkeypatch.setattr(separate, "available", lambda: True)
    monkeypatch.setattr(
        audio_cache,
        "ensure_vocals_wav",
        lambda *a, **k: tmp_path / "vocals.wav",
    )
    with pytest.raises(ValueError, match="未知的人声分离用途"):
        pipeline.run_transcription(
            pipeline.TranscribeRequest(
                media_path=media,
                start_s=1.0,
                end_s=2.0,
                separate_vocals=True,
                separate_mode="both",
            ),
            output_dir=tmp_path,
            engine=_FakeEngine(),
        )


def test_plain_transcribe_never_passes_vad_audio(media, tmp_path, monkeypatch):
    """未开分离时不多传参数：外部引擎替身/旧调用方签名不受影响。"""
    _patch_dirs(monkeypatch, tmp_path)
    engine = _FakeEngine()
    pipeline.run_transcription(
        pipeline.TranscribeRequest(media_path=media),
        output_dir=tmp_path,
        engine=engine,
    )
    assert "vad_audio_path" not in engine.received


def test_separate_vocals_full_film_uses_whole_duration(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    from core import audio_cache, separate

    vocals = tmp_path / "vocals.wav"
    vocals.write_bytes(b"RIFF")
    seen = {}

    def fake_ensure(media_path, *, start, end, separator, cancel_event=None, progress_cb=None):
        seen.update(start=start, end=end)
        return vocals

    monkeypatch.setattr(audio_cache, "ensure_vocals_wav", fake_ensure)
    monkeypatch.setattr(separate, "available", lambda: True)

    engine = _FakeEngine()
    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(
            media_path=media,
            media_duration_s=123.5,
            separate_vocals=True,
            separate_mode="to_asr",
        ),
        output_dir=tmp_path,
        engine=engine,
    )

    assert seen == {"start": 0.0, "end": 123.5}
    assert engine.media_path == vocals
    # 整片仍然是「整片」：引擎不传切片、文件名不带区间后缀
    assert engine.received["start_time_s"] is None
    assert engine.received["end_time_s"] is None
    assert engine.received["time_offset"] == 0.0
    assert result.slice_tag == ""
    assert result.out_filename == "episode.AnimeWhisper.srt"


def test_separation_range_fills_missing_edges_from_duration():
    from core.pipeline import TranscribeRequest, separation_range

    def req(**kw):
        return TranscribeRequest(media_path=Path("episode.mkv"), **kw)

    assert separation_range(req(media_duration_s=100.0)) == (0.0, 100.0)
    assert separation_range(req(media_duration_s=100.0, start_s=10.0)) == (10.0, 100.0)
    assert separation_range(req(media_duration_s=100.0, end_s=20.0)) == (0.0, 20.0)
    assert separation_range(req(start_s=10.0, end_s=20.0)) == (10.0, 20.0)
    # 用户填的尾部超过影片时长：夹到片尾
    assert separation_range(req(media_duration_s=100.0, start_s=10.0, end_s=999.0)) == (
        10.0,
        100.0,
    )


def test_separate_vocals_full_film_without_duration_asks_for_range(
    media, tmp_path, monkeypatch
):
    _patch_dirs(monkeypatch, tmp_path)
    from core import proxy

    monkeypatch.setattr(proxy, "probe_duration", lambda _path: 0.0)
    with pytest.raises(ValueError, match="无法确定影片总时长"):
        pipeline.run_transcription(
            pipeline.TranscribeRequest(media_path=media, separate_vocals=True),
            output_dir=tmp_path,
            engine=_FakeEngine(),
        )


# ---------------------------------------------------------------------------
# 短选区轻声兜底：只作用于核对台 replace_range（人工短选区），整片不动
# ---------------------------------------------------------------------------


class _QuietSelectionEngine(_FakeEngine):
    """默认阈值切不出语音；阈值降到 0.05 才「听得见」。"""

    def __init__(self, *, whole_clip_text: str = "", hit_on_low: bool = True) -> None:
        super().__init__()
        self.whole_clip_text = whole_clip_text
        self.hit_on_low = hit_on_low
        self.configs: list = []

    def transcribe_file(self, media_path, **kwargs):
        self.media_path = media_path
        self.received = kwargs
        config = kwargs.get("config")
        self.configs.append(getattr(config, "threshold", None))
        if (
            self.hit_on_low
            and config is not None
            and float(getattr(config, "threshold", 1.0)) <= 0.05
        ):
            return [SubtitleCue(10.0, 11.0, "轻声台词")]
        return []

    def transcribe_window(self, audio, **kwargs):
        return self.whole_clip_text


def test_short_clip_falls_back_to_low_threshold(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    from core.transcribe import WhisperVadConfig

    engine = _QuietSelectionEngine()
    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(
            media_path=media,
            start_s=10.0,
            end_s=14.0,
            short_clip_fallback=True,
            whisper_config=WhisperVadConfig(),
        ),
        output_dir=tmp_path,
        engine=engine,
    )
    assert [cue.text for cue in result.cues] == ["轻声台词"]
    # 第一次是用户当前参数（产品默认，不是兜底值），只有重试才降到 0.05
    assert engine.configs[0] == WhisperVadConfig().threshold
    assert 0.05 in engine.configs


def test_whole_transcription_never_uses_short_clip_fallback(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    from core.transcribe import WhisperVadConfig

    engine = _QuietSelectionEngine(whole_clip_text="整段送模不该发生")
    with pytest.raises(RuntimeError, match="未检测到有效语音"):
        pipeline.run_transcription(
            pipeline.TranscribeRequest(
                media_path=media,
                start_s=10.0,
                end_s=14.0,
                # 默认 False：整片 / 追加任务的口径
                whisper_config=WhisperVadConfig(),
            ),
            output_dir=tmp_path,
            engine=engine,
        )
    # 只跑了一次原参数，没有降阈值重试
    assert engine.configs == [WhisperVadConfig().threshold]


def test_short_clip_whole_clip_fallback_returns_one_cue(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    from core import short_clip
    from core.transcribe import WhisperVadConfig

    monkeypatch.setattr(
        short_clip, "read_whole_clip", lambda *a, **k: "整段识别到的台词"
    )
    engine = _QuietSelectionEngine(hit_on_low=False)
    result = pipeline.run_transcription(
        pipeline.TranscribeRequest(
            media_path=media,
            start_s=20.0,
            end_s=24.5,
            short_clip_fallback=True,
            whisper_config=WhisperVadConfig(),
        ),
        output_dir=tmp_path,
        engine=engine,
    )
    assert len(result.cues) == 1
    assert result.cues[0].start == 20.0
    assert result.cues[0].end == 24.5
    assert result.cues[0].text == "整段识别到的台词"


def test_short_clip_does_not_whole_clip_selection_longer_than_12s(media, tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    from core import short_clip
    from core.transcribe import WhisperVadConfig

    monkeypatch.setattr(short_clip, "read_whole_clip", lambda *a, **k: "不该发生")
    with pytest.raises(RuntimeError, match="未检测到有效语音"):
        pipeline.run_transcription(
            pipeline.TranscribeRequest(
                media_path=media,
                start_s=0.0,
                end_s=18.0,  # > 12s：只降阈值，不整段送模
                short_clip_fallback=True,
                whisper_config=WhisperVadConfig(),
            ),
            output_dir=tmp_path,
            engine=_QuietSelectionEngine(whole_clip_text="整段送模不该发生", hit_on_low=False),
        )
