"""片段导出：FFmpeg 真裁 + 字幕 / 章节归零平移（ffprobe 回读验证）。

用户验收口径：只导出 `[2s, 12s]` 这一段，成片时长必须是 10 秒，字幕从
`00:00:00,000` 起，章节里的「发射点」在**片段内**是 `7.5s`（原片 9.5s）。
只看 ffmpeg 退出码不够，所以这里一律用 `ffprobe` / `ffmpeg -f srt` 读回真实产物。

三条路都覆盖：软字幕（帧级重编码）、仅封装（关键帧切片，允许 ±1s 误差）、
字幕单独导出（只出平移后的 SRT）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "export-clip-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

DURATION = 14.0
CLIP_START = 2.0
CLIP_END = 12.0
CLIP_LENGTH = CLIP_END - CLIP_START

# 第 1 条跨过片段起点（平移到 0）；最后一条在片段外（必须被丢掉）。
CUES = [
    {"start": 1.5, "end": 2.5, "text": "跨界句"},
    {"start": 3.0, "end": 4.0, "text": "第二句"},
    {"start": 6.0, "end": 7.0, "text": "第三句"},
    {"start": 10.0, "end": 12.0, "text": "尾部句"},
    {"start": 13.0, "end": 14.0, "text": "片段之后"},
]
# 章节 [0 → 9.5] + 时刻点 9.5（首尾相接，MP4 章节文本轨不会产生空档歧义）。
# 裁剪后：章节1 = 0 → 7.5；发射点 = 7.5 → 10（片段内）。
MARKS = [
    {"id": "scene-1", "start": 0.0, "end": 9.5, "title": "章节1"},
    {"id": "point-1", "start": 9.5, "end": None, "title": "发射点"},
    {"id": "outside", "start": 13.0, "end": None, "title": "片段之后"},
]


def _ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _cjk_font_available() -> bool:
    try:
        from core import video_export

        ok, _ = video_export.font_status()
        return ok
    except Exception:  # noqa: BLE001
        return False


pytestmark = [
    pytest.mark.needs_ffmpeg,
    pytest.mark.skipif(not _ffmpeg_available(), reason="需要 ffmpeg/ffprobe"),
]


@pytest.fixture()
def ctx(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=0x203040:size=640x360:rate=24:duration={DURATION}",
            "-f", "lavfi", "-i", f"sine=frequency=300:duration={DURATION}",
            # 关键帧每 0.5s 一个：仅封装切片才不会偏出一个 GOP（默认 250 帧）。
            "-g", "12", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest", str(video),
        ],
        check=True,
    )
    client = TestClient(
        create_app(
            ServerConfig(
                token=TOKEN,
                output_dir=tmp_path,
                settings_path=tmp_path / "settings.json",
            )
        )
    )
    media = client.post("/api/media", headers=AUTH, json={"path": str(video)}).json()
    client.post("/api/session/bind", headers=AUTH, json={"media_id": media["id"]})
    assert client.post("/api/cues", headers=AUTH, json={"cues": CUES}).status_code == 200
    assert (
        client.post(
            "/api/chapters", headers=AUTH, json={"marks": MARKS, "label": "建章节"}
        ).status_code
        == 200
    )
    return client, media, tmp_path


def _wait(client: TestClient, job_id: str, timeout: float = 90) -> dict:
    import time

    deadline = time.time() + timeout
    snap: dict = {}
    while time.time() < deadline:
        snap = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if snap["status"] in {"done", "error", "cancelled"}:
            return snap
        time.sleep(0.05)
    raise AssertionError(f"导出任务超时：{snap}")


def _probe(path: str, what: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", what, "-of", "json", path],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out or "{}")


def _chapters(path: str) -> list[dict]:
    return _probe(path, "-show_chapters").get("chapters", [])


def _subtitles(path: str) -> str:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-map", "0:s:0", "-f", "srt", "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out


def _export(client: TestClient, media: dict, mode: str, **extra) -> dict:
    body = {
        "media_id": media["id"],
        "mode": mode,
        "track": "source",
        "resolution": "480p",
        "preset": "small",
        "export_srt": False,
        **extra,
    }
    created = client.post("/api/export", headers=AUTH, json=body)
    assert created.status_code == 201, created.text
    snap = _wait(client, created.json()["id"])
    assert snap["status"] == "done", snap
    return snap["result"]


def _assert_clip_chapters(result: dict) -> None:
    chapters = _chapters(result["path"])
    assert [c["tags"]["title"] for c in chapters] == ["章节1", "发射点"], chapters
    first, second = chapters
    assert float(first["start_time"]) == pytest.approx(0.0, abs=0.02)
    assert float(first["end_time"]) == pytest.approx(7.5, abs=0.02)
    # 22:55 → 22:45 的同一条规则：原片 9.5s 在片段里是 7.5s
    assert float(second["start_time"]) == pytest.approx(7.5, abs=0.02)
    assert float(second["end_time"]) == pytest.approx(CLIP_LENGTH, abs=0.1)
    assert result["clip"]["start"] == pytest.approx(CLIP_START)
    assert result["clip"]["end"] == pytest.approx(CLIP_END)


def test_soft_export_clip_is_frame_exact(ctx) -> None:
    client, media, _ = ctx
    result = _export(
        client,
        media,
        "soft",
        clip_start=CLIP_START,
        clip_end=CLIP_END,
        clip_label="章节1",
    )
    info = _probe(result["path"], "-show_format")
    assert float(info["format"]["duration"]) == pytest.approx(CLIP_LENGTH, abs=0.15)
    _assert_clip_chapters(result)
    # 字幕已平移归零：跨界句从 0 起，最后一句在 8–10
    subs = _subtitles(result["path"])
    assert "00:00:00,000 --> 00:00:00,500" in subs
    assert "00:00:08,000 --> 00:00:10,000" in subs
    assert "片段之后" not in subs
    assert "章节1" in Path(result["path"]).name
    assert result["subtitle_count"] == 4


@pytest.mark.skipif(not _cjk_font_available(), reason="需要 macOS 中文字体（硬字幕烧录）")
def test_burn_export_clip_is_frame_exact(ctx) -> None:
    client, media, _ = ctx
    result = _export(
        client,
        media,
        "burn",
        clip_start=CLIP_START,
        clip_end=CLIP_END,
        clip_label="章节1",
    )
    info = _probe(result["path"], "-show_format")
    assert float(info["format"]["duration"]) == pytest.approx(CLIP_LENGTH, abs=0.2)
    _assert_clip_chapters(result)


def test_copy_export_clip_stays_playable(ctx) -> None:
    """仅封装按关键帧切片：时长允许 ±1s，但必须能读、章节已归零。"""
    client, media, _ = ctx
    result = _export(client, media, "copy", clip_start=CLIP_START, clip_end=CLIP_END)
    info = _probe(result["path"], "-show_format")
    assert float(info["format"]["duration"]) == pytest.approx(CLIP_LENGTH, abs=1.2)
    streams = _probe(result["path"], "-show_streams")["streams"]
    assert any(s["codec_type"] == "video" for s in streams)
    assert any(s["codec_type"] == "subtitle" for s in streams)
    _assert_clip_chapters(result)


def test_plan_reports_clip_and_keyframe_warning(ctx) -> None:
    client, media, _ = ctx
    res = client.post(
        "/api/export/plan",
        headers=AUTH,
        json={
            "media_id": media["id"],
            "mode": "copy",
            "track": "source",
            "resolution": "1080p",
            "preset": "balanced",
            "clip_start": CLIP_START,
            "clip_end": CLIP_END,
            "write_chapters": True,
        },
    )
    assert res.status_code == 200, res.text
    plan = res.json()["plan"]
    assert plan["duration"] == pytest.approx(CLIP_LENGTH)
    assert plan["clip"]["start"] == pytest.approx(CLIP_START)
    assert plan["clip"]["label"]
    assert [(c["start"], c["end"]) for c in plan["chapters"]] == [(0.0, 7.5), (7.5, CLIP_LENGTH)]
    assert any("关键帧" in warning for warning in plan["warnings"])
    assert any("片段导出" in warning for warning in plan["warnings"])


def test_subtitle_only_export_is_shifted_and_tagged(ctx) -> None:
    client, media, tmp_path = ctx
    full = client.post(
        "/api/cues/export", headers=AUTH, json={"format": "SRT", "track": "source"}
    )
    assert full.status_code == 200, full.text
    assert full.json()["count"] == len(CUES)

    clipped = client.post(
        "/api/cues/export",
        headers=AUTH,
        json={
            "format": "SRT",
            "track": "source",
            "clip_start": CLIP_START,
            "clip_end": CLIP_END,
            "clip_label": "章节1",
        },
    )
    assert clipped.status_code == 200, clipped.text
    body = clipped.json()
    assert body["count"] == 4
    assert body["clip"] and "章节1" in body["clip"]
    assert "章节1" in body["name"]
    text = body["text"]
    assert "00:00:00,000 --> 00:00:00,500" in text
    assert "00:00:08,000 --> 00:00:10,000" in text
    assert "片段之后" not in text
    assert Path(body["path"]).exists()


def test_subtitle_export_rejects_empty_clip(ctx) -> None:
    client, media, _ = ctx
    res = client.post(
        "/api/cues/export",
        headers=AUTH,
        json={"format": "SRT", "clip_start": 12.2, "clip_end": 12.9},
    )
    assert res.status_code == 409, res.text


def test_bilingual_clip_keeps_alignment(ctx) -> None:
    client, media, _ = ctx
    texts = [f"译文{i}" for i in range(len(CUES))]
    assert (
        client.post(
            "/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": texts}
        ).status_code
        == 201
    )
    res = client.post(
        "/api/cues/export",
        headers=AUTH,
        json={
            "format": "SRT",
            "track": "both",
            "lang": "zh-Hans",
            "clip_start": CLIP_START,
            "clip_end": CLIP_END,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # 4 条命中 × 双语各一条 = 8 条 cue；范围外那一条的译文不能混进来
    assert body["count"] == 8
    assert "译文4" not in body["text"]
    assert "译文0" in body["text"]
