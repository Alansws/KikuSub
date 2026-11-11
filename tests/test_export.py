"""成片导出：规划、任务与硬字幕/软字幕产物。"""

from __future__ import annotations

import io
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("PIL")

from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "export-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


pytestmark = pytest.mark.skipif(not _ffmpeg_available(), reason="需要 ffmpeg/ffprobe")


@pytest.fixture()
def ctx(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=0x203040:size=640x360:rate=24:duration=3",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", str(video),
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
    cues = [
        {"start": 0.4, "end": 1.6, "text": "你好，世界！"},
        {"start": 1.8, "end": 2.8, "text": "第二句字幕"},
    ]
    assert client.post("/api/cues", headers=AUTH, json={"cues": cues}).status_code == 200
    return client, media, tmp_path


def _wait(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 30
    snap: dict = {}
    while time.time() < deadline:
        snap = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if snap["status"] in {"done", "error", "cancelled"}:
            return snap
        time.sleep(0.05)
    raise AssertionError(f"导出任务超时：{snap}")


def test_plan_reports_dimensions_and_warnings(ctx) -> None:
    client, media, _ = ctx
    res = client.post(
        "/api/export/plan",
        headers=AUTH,
        json={
            "media_id": media["id"],
            "mode": "burn",
            "track": "source",
            "resolution": "1080p",
            "preset": "balanced",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    plan = body["plan"]
    assert plan["height"] == 360
    assert plan["width"] == 640
    assert plan["video_bitrate"] > 0
    assert any("没有音轨" in w for w in plan["warnings"])


def test_burn_export_writes_bright_subtitle_pixels(ctx) -> None:
    from PIL import Image

    client, media, tmp_path = ctx
    created = client.post(
        "/api/export",
        headers=AUTH,
        json={
            "media_id": media["id"],
            "mode": "burn",
            "track": "source",
            "resolution": "480p",
            "preset": "small",
            "export_srt": True,
        },
    )
    assert created.status_code == 201, created.text
    snap = _wait(client, created.json()["id"])
    assert snap["status"] == "done", snap
    result = snap["result"]
    out = Path(result["path"])
    assert out.exists() and out.stat().st_size > 1024
    assert Path(result["srt_path"]).exists()

    frame = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "1.0", "-i", str(out), "-frames:v", "1", str(frame)],
        check=True,
    )
    image = Image.open(frame).convert("RGB")
    w, h = image.size
    bright = 0
    for y in range(int(h * 0.7), h):
        for x in range(w):
            r, g, b = image.getpixel((x, y))
            if r > 225 and g > 225 and b > 225:
                bright += 1
    assert bright > 80, f"底部的字幕像素太少：{bright}"


def test_soft_export_has_subtitle_stream(ctx) -> None:
    client, media, _ = ctx
    created = client.post(
        "/api/export",
        headers=AUTH,
        json={
            "media_id": media["id"],
            "mode": "soft",
            "track": "source",
            "resolution": "480p",
            "preset": "small",
            "export_srt": False,
        },
    )
    assert created.status_code == 201, created.text
    snap = _wait(client, created.json()["id"])
    assert snap["status"] == "done", snap
    result = snap["result"]
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
            "-of", "json", result["path"],
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "subtitle" in probe.stdout


def test_copy_export_does_not_reencode(ctx) -> None:
    client, media, _ = ctx
    created = client.post(
        "/api/export",
        headers=AUTH,
        json={
            "media_id": media["id"],
            "mode": "copy",
            "track": "source",
            "resolution": "1080p",
            "preset": "balanced",
            "export_srt": False,
        },
    )
    assert created.status_code == 201, created.text
    snap = _wait(client, created.json()["id"])
    assert snap["status"] == "done", snap
    result = snap["result"]
    assert result["mode"] == "copy"
    assert result["width"] == 640
    assert result["height"] == 360


def test_export_target_track_uses_translation(ctx) -> None:
    client, media, _ = ctx
    texts = ["你好，世界！", "第二句字幕"]
    res = client.post(
        "/api/translations",
        headers=AUTH,
        json={"lang": "zh-Hans", "texts": texts},
    )
    assert res.status_code in (200, 201), res.text

    created = client.post(
        "/api/export",
        headers=AUTH,
        json={
            "media_id": media["id"],
            "mode": "burn",
            "track": "target",
            "lang": "zh-Hans",
            "resolution": "480p",
            "preset": "small",
            "export_srt": False,
        },
    )
    assert created.status_code == 201, created.text
    snap = _wait(client, created.json()["id"])
    assert snap["status"] == "done", snap
    assert snap["result"]["track"] == "target"
    assert snap["result"]["lang"] == "zh-Hans"
    assert "." + "zh-Hans" in Path(snap["result"]["path"]).name


def test_bilingual_copied_srt_has_one_cue_per_language(ctx) -> None:
    """成片附带的 .bilingual.srt 也必须是「每语种一条」，否则重新导入会挤成一行。"""
    from core.subtitles import srt_to_cues

    client, media, _ = ctx
    client.post(
        "/api/translations",
        headers=AUTH,
        json={"lang": "zh-Hans", "texts": ["第一行译文", "第二行译文"]},
    )
    created = client.post(
        "/api/export",
        headers=AUTH,
        json={
            "media_id": media["id"],
            "mode": "copy",
            "track": "both",
            "lang": "zh-Hans",
            "export_srt": True,
        },
    )
    assert created.status_code == 201, created.text
    snap = _wait(client, created.json()["id"])
    assert snap["status"] == "done", snap
    srt_path = Path(snap["result"]["srt_path"])
    assert srt_path.name.endswith(".bilingual.srt")
    cues = srt_to_cues(srt_path.read_text(encoding="utf-8"))
    assert [c.text for c in cues] == [
        "你好，世界！",
        "第一行译文",
        "第二句字幕",
        "第二行译文",
    ]
    assert all("\n" not in c.text for c in cues)
    # 源与译文交替出现，时间轴逐对相同
    assert cues[0].start == cues[1].start and cues[0].end == cues[1].end


def test_copy_export_requires_translation_track(ctx) -> None:
    client, media, _ = ctx
    res = client.post(
        "/api/export",
        headers=AUTH,
        json={
            "media_id": media["id"],
            "mode": "burn",
            "track": "target",
            "lang": "zh-Hans",
            "resolution": "480p",
            "preset": "balanced",
        },
    )
    assert res.status_code == 409


# --------------------------------------------------------------------------- 进度 / 取消


def _realtime_cmd(seconds: float = 4.0) -> list[str]:
    # -re 让 ffmpeg 按真实时间产出，才能在秒级测试里观察到中间进度与取消响应
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-nostats",
        "-progress", "pipe:1", "-re",
        "-f", "lavfi", "-i", "testsrc=size=320x180:rate=12",
        "-t", str(seconds), "-f", "null", "-",
    ]


def test_progress_reader_reports_intermediate_progress() -> None:
    from core import video_export

    events: list[tuple[float, int | None]] = []
    started = time.monotonic()
    returncode, _ = video_export._progress_reader(
        _realtime_cmd(4.0), 4.0, lambda out_s, pct, extra: events.append((out_s, pct)), None
    )
    assert returncode == 0
    assert time.monotonic() - started < 8.0
    # 这正是旧实现的 bug：没有 -progress 时事件数为 0，界面永远停在 0%
    assert events, "进度回调一次都没有触发"
    assert any(pct is not None and 0 < pct < 100 for _, pct in events)


def test_progress_reader_cancels_without_waiting_for_ffmpeg() -> None:
    from core import video_export
    from core.procutil import CommandCancelled, active_processes

    cancel = threading.Event()
    threading.Timer(0.6, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(CommandCancelled):
        video_export._progress_reader(_realtime_cmd(4.0), 4.0, lambda *a: None, cancel)
    # 旧实现要等 ffmpeg 自己跑完 4 秒；新实现应该在一个轮询周期内退出
    assert time.monotonic() - started < 3.0
    assert active_processes() == []


# --------------------------------------------------------------------------- 样式


def test_export_styles_lists_presets_and_fonts(ctx) -> None:
    client, _, _ = ctx
    res = client.get("/api/export/styles", headers=AUTH)
    assert res.status_code == 200, res.text
    body = res.json()
    keys = [preset["key"] for preset in body["presets"]]
    assert "fansub" in keys and "fansub-heavy" in keys
    assert isinstance(body["fonts"], list) and body["fonts"]
    assert body["default"]["font"] and body["default"]["weight"] == "bold"
    assert set(body["ranges"]) == {"size", "outline", "margin"}


def test_style_preview_returns_png(ctx) -> None:
    from PIL import Image

    client, media, _ = ctx
    res = client.post(
        "/api/export/style-preview",
        headers=AUTH,
        json={
            "media_id": media["id"],
            "text": "预览：粗黑描边字幕",
            "width": 640,
            "height": 360,
            "style": {"font": "pingfang", "weight": "bold", "outline": 1.2, "shadow": True},
        },
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("image/png")
    assert res.content.startswith(b"\x89PNG")
    image = Image.open(io.BytesIO(res.content))
    assert image.size == (640, 360)


def test_plan_rejects_unknown_font(ctx) -> None:
    client, media, _ = ctx
    res = client.post(
        "/api/export/plan",
        headers=AUTH,
        json={
            "media_id": media["id"],
            "mode": "burn",
            "resolution": "480p",
            "style": {"font": "definitely-not-a-font"},
        },
    )
    assert res.status_code == 422


def test_burn_export_honours_style_font_and_position(ctx) -> None:
    from PIL import Image

    client, media, tmp_path = ctx
    created = client.post(
        "/api/export",
        headers=AUTH,
        json={
            "media_id": media["id"],
            "mode": "burn",
            "track": "source",
            "resolution": "480p",
            "preset": "small",
            "export_srt": False,
            "style": {
                "font": "lantinghei",
                "weight": "bold",
                "size": 1.3,
                "outline": 1.5,
                "shadow": True,
                "position": "top",
                "margin": 6,
            },
        },
    )
    assert created.status_code == 201, created.text
    snap = _wait(client, created.json()["id"])
    assert snap["status"] == "done", snap
    result = snap["result"]
    assert result["style"]["font"] == "lantinghei"
    assert result["style"]["position"] == "top"

    out = Path(result["path"])
    frame = tmp_path / "styled-frame.png"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "1.0", "-i", str(out),
         "-frames:v", "1", str(frame)],
        check=True,
    )
    image = Image.open(frame).convert("RGB")
    width, height = image.size

    def bright_pixels(box) -> int:
        gray = image.crop(box).convert("L")
        return sum(count for value, count in enumerate(gray.histogram()) if value > 235)

    # 字幕在顶部时，上半部分要出现明显更多的近白像素
    top_bright = bright_pixels((0, 0, width, int(height * 0.35)))
    bottom_bright = bright_pixels((0, int(height * 0.7), width, height))
    assert top_bright > 40, f"顶部字幕像素太少：{top_bright}"
    assert bottom_bright < top_bright, f"字幕不应同时出现在底部：{bottom_bright}"


def test_style_preview_bilingual_and_zoom(ctx) -> None:
    from PIL import Image

    client, media, _ = ctx
    texts = ["你好，世界！", "第二句字幕"]
    applied = client.post(
        "/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": texts}
    )
    assert applied.status_code in (200, 201), applied.text

    full = client.post(
        "/api/export/style-preview",
        headers=AUTH,
        json={
            "media_id": media["id"],
            "track": "both",
            "lang": "zh-Hans",
            "width": 640,
            "height": 360,
        },
    )
    assert full.status_code == 200, full.text
    assert Image.open(io.BytesIO(full.content)).size == (640, 360)

    zoom = client.post(
        "/api/export/style-preview",
        headers=AUTH,
        json={"media_id": media["id"], "zoom": True, "width": 640, "height": 360},
    )
    assert zoom.status_code == 200, zoom.text
    cropped = Image.open(io.BytesIO(zoom.content))
    assert cropped.width <= 640
    assert cropped.height < 360
