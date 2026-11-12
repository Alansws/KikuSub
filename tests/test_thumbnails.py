"""最近打开封面：首帧优先，纯黑首帧才挑代表帧。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from core.thumbnails import _frame_has_signal, thumbnail_for

pytestmark = [
    pytest.mark.needs_ffmpeg,
    pytest.mark.skipif(not shutil.which("ffmpeg"), reason="需要 ffmpeg"),
]


def make_clip(path: Path) -> Path:
    """1 秒纯黑 + 2 秒彩条：模拟「黑场淡入视频内容」。"""
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostdin", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=320x180:d=1",
            "-f", "lavfi", "-i", "testsrc=s=320x180:d=2",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
            "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return path


def test_thumbnail_skips_black_first_frame(tmp_path: Path) -> None:
    clip = make_clip(tmp_path / "clip.mp4")
    thumb = thumbnail_for(clip, tmp_path / "thumbs", width=320)
    assert thumb.is_file() and thumb.stat().st_size > 0
    # 首帧是纯黑，必须挑到有画面的代表帧
    assert _frame_has_signal(thumb) is True


def test_thumbnail_is_cached(tmp_path: Path) -> None:
    clip = make_clip(tmp_path / "clip.mp4")
    cache = tmp_path / "thumbs"
    first = thumbnail_for(clip, cache, width=320)
    second = thumbnail_for(clip, cache, width=320)
    assert first == second
    assert len(list(cache.glob("*.jpg"))) == 1
