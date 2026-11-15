"""交付文件命名与引擎标签识别（纯函数，无模型 / 无服务层）。

守住三件事：
1. 引擎文件名标签只在 `core/engines.py` 登记，且四种引擎互不重复；
2. 交付稿一定是 `{stem}.{version}.reviewed{track}{ext}`，不同引擎不会撞名；
3. 从旧文件反推引擎时既认新标签也认历史标签，且不会把媒体名里的关键字误当引擎。
"""

from __future__ import annotations

from pathlib import Path

from core import engines
from core.export_naming import engine_from_filename, reviewed_filename, review_version
from core.textio import next_available_path


def test_engine_file_tags_are_registered_and_unique():
    tags = [engines.file_tag_of(spec.key) for spec in engines.ENGINES]
    assert all(tags), "每个引擎都必须登记 file_tag"
    assert len({tag.lower() for tag in tags}) == len(tags), f"文件名标签重复：{tags}"


def test_reviewed_filename_distinguishes_engines():
    whisper = reviewed_filename(
        "言叶之庭", {"kind": "transcription", "engine": "whisper"}
    )
    qwen = reviewed_filename("言叶之庭", {"kind": "transcription", "engine": "qwen"})
    assert whisper == "言叶之庭.AnimeWhisper.reviewed.srt"
    assert qwen == "言叶之庭.Qwen3-ASR.reviewed.srt"
    assert whisper != qwen


def test_reviewed_filename_keeps_track_suffix():
    source = {"kind": "transcription", "engine": "qwen"}
    assert (
        reviewed_filename("剧集", source, track_suffix=".zh-Hans")
        == "剧集.Qwen3-ASR.reviewed.zh-Hans.srt"
    )
    assert (
        reviewed_filename("剧集", source, track_suffix=".bilingual", ext=".vtt")
        == "剧集.Qwen3-ASR.reviewed.bilingual.vtt"
    )


def test_reviewed_filename_falls_back_to_source_kind():
    assert (
        reviewed_filename("剧集", {"kind": "import", "name": "我的字幕.srt"})
        == "剧集.import.reviewed.srt"
    )
    assert (
        reviewed_filename("剧集", {"kind": "draft"}) == "剧集.draft.reviewed.srt"
    )
    # 来源未知时不硬塞假引擎名，但仍保留 .reviewed，避免和原始转写同名
    assert reviewed_filename("剧集", {}) == "剧集.reviewed.srt"


def test_engine_inference_accepts_new_and_legacy_tags():
    assert engine_from_filename("episode.AnimeWhisper.srt") == "whisper"
    assert engine_from_filename("episode.whisper.srt") == "whisper"
    assert engine_from_filename("episode.Qwen3-ASR.srt") == "qwen"
    assert engine_from_filename("episode.qwen.srt") == "qwen"
    assert engine_from_filename("episode_00m10s-01m05s.qwen.srt") == "qwen"
    assert engine_from_filename("episode.SenseVoice-Small.reviewed.srt") == "sensevoice"
    assert engine_from_filename("episode.firered.srt") == "firered"
    assert engine_from_filename("episode.srt") == ""


def test_engine_inference_strips_media_stem_first():
    # 影片名本身带 whisper 关键字：不能把这条字幕当成 Whisper 引擎产物
    assert engine_from_filename("MyWhisperFilm.srt", "MyWhisperFilm") == ""
    assert (
        engine_from_filename("MyWhisperFilm.zh-Hans.srt", "MyWhisperFilm") == ""
    )
    # 媒体前缀之后的真正标签仍要认
    assert (
        engine_from_filename("MyWhisperFilm.AnimeWhisper.reviewed.srt", "MyWhisperFilm")
        == "whisper"
    )


def test_engine_inference_requires_dot_tag():
    # 点分标签才算数：文件名中间的关键字不误判
    assert engine_from_filename("whisper_notes_episode.srt") == ""
    assert engine_from_filename("my.qwen.draft.srt") == "qwen"


def test_review_version_prefers_session_source_engine():
    assert review_version({"kind": "import", "engine": "whisper"}) == "AnimeWhisper"
    assert (
        review_version(
            {"kind": "import", "name": "别的片.Qwen3-ASR.reviewed.srt"},
            media_stem="言叶之庭",
        )
        == "Qwen3-ASR"
    )


def test_next_available_path_uses_numbered_suffix(tmp_path: Path):
    target = tmp_path / "剧集.AnimeWhisper.reviewed.srt"
    assert next_available_path(target) == target
    target.write_text("v1", encoding="utf-8")
    second = next_available_path(target)
    assert second.name == "剧集.AnimeWhisper.reviewed (2).srt"
    second.write_text("v2", encoding="utf-8")
    third = next_available_path(target)
    assert third.name == "剧集.AnimeWhisper.reviewed (3).srt"
