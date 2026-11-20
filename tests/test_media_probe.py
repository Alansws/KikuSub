"""媒体探测的帧率口径。

逐帧步进依赖服务端给出真实 fps：这里只测纯解析与 `_probe()` 的字段选择，
不调用 ffprobe、不依赖本机素材。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from server import media


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("24000/1001", 24000 / 1001),
        ("30000/1001", 30000 / 1001),
        ("25", 25.0),
        ("25/1", 25.0),
        ("0/0", 0.0),
        ("", 0.0),
        (None, 0.0),
        ("not-a-rate", 0.0),
        ("1000/1", 0.0),  # 超出合理范围，按未知处理
        ("1/1000", 0.0),
    ],
)
def test_parse_frame_rate(raw: object, expected: float) -> None:
    value = media._parse_frame_rate(raw)
    if expected:
        assert value == pytest.approx(expected, abs=1e-6)
    else:
        assert value == 0.0


def _probe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, streams: list[dict]) -> media.MediaInfo:
    monkeypatch.setattr(
        media,
        "_ffprobe_json",
        lambda path: {"format": {"duration": "10.0"}, "streams": streams},
    )
    info = media.MediaInfo(id="x", path=Path("x.mp4"), name="x.mp4", size=0)
    media.MediaStore(output_dir=tmp_path)._probe(info)
    return info


def test_video_fps_prefers_avg_frame_rate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    info = _probe(
        monkeypatch,
        tmp_path,
        [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "24000/1001",
                "r_frame_rate": "30/1",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    )
    assert info.has_video is True
    assert info.video_fps == pytest.approx(24000 / 1001, abs=1e-6)
    assert info.to_dict()["video_fps"] == pytest.approx(24000 / 1001, abs=1e-6)


def test_video_fps_falls_back_to_r_frame_rate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    info = _probe(
        monkeypatch,
        tmp_path,
        [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "avg_frame_rate": "0/0",
                "r_frame_rate": "25/1",
            }
        ],
    )
    assert info.video_fps == pytest.approx(25.0)


def test_audio_only_has_no_fps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    info = _probe(
        monkeypatch,
        tmp_path,
        [{"codec_type": "audio", "codec_name": "pcm_s16le"}],
    )
    assert info.has_video is False
    assert info.video_fps == 0.0
    assert info.to_dict()["video_fps"] == 0.0


def test_invalid_frame_rate_falls_back_to_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    info = _probe(
        monkeypatch,
        tmp_path,
        [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "avg_frame_rate": "garbage",
                "r_frame_rate": "0/0",
            }
        ],
    )
    assert info.video_fps == 0.0
