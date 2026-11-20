"""章节写入成片：三种导出模式 + ffprobe -show_chapters 回归。

用户验收口径是「IINA 能直接读到并跳转」，所以这里不看 ffmpeg 的退出码，
而是用 `ffprobe -show_chapters` 读回容器里真实存在的章节，逐条核对
标题 / 起止时间 / 是否有序不重叠。硬字幕（burn）、软字幕（soft）、
仅封装（copy）三条路都要过——尤其是「仅封装」：几秒出片也必须带章节。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "export-chapters-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


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

DURATION = 6.0
# 两条标记首尾相接：MP4 的章节是一条文本轨，ffmpeg 会把「空档」并进上一章，
# 所以容器级回归用连续区间（空档语义由 tests/test_chapters.py 的纯函数用例覆盖）。
MARKS = [
    {"id": "scene-1", "start": 0.0, "end": 4.0, "title": "场景1 / 开场"},
    {"id": "point-1", "start": 4.0, "end": None, "title": "关键时刻; #倒计时"},
]


@pytest.fixture()
def ctx(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=0x203040:size=640x360:rate=24:duration={DURATION}",
            "-f", "lavfi", "-i", f"sine=frequency=300:duration={DURATION}",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
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
    cues = [
        {"start": 0.4, "end": 1.6, "text": "你好，世界！"},
        {"start": 2.0, "end": 2.4, "text": "第二句字幕"},
    ]
    assert client.post("/api/cues", headers=AUTH, json={"cues": cues}).status_code == 200
    assert (
        client.post(
            "/api/chapters", headers=AUTH, json={"marks": MARKS, "label": "新建章节"}
        ).status_code
        == 200
    )
    return client, media, tmp_path


def _wait(client: TestClient, job_id: str, timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    snap: dict = {}
    while time.time() < deadline:
        snap = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if snap["status"] in {"done", "error", "cancelled"}:
            return snap
        time.sleep(0.05)
    raise AssertionError(f"导出任务超时：{snap}")


def _chapters(path: str) -> list[dict]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_chapters", "-of", "json", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(probe.stdout or "{}").get("chapters", [])


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


def _assert_chapters(result: dict) -> None:
    chapters = _chapters(result["path"])
    assert len(chapters) == 2, chapters
    first, second = chapters
    assert first["tags"]["title"] == "场景1 / 开场"
    assert float(first["start_time"]) == pytest.approx(0.0, abs=0.01)
    assert float(first["end_time"]) == pytest.approx(4.0, abs=0.01)
    # 时刻点自动衔接到片尾（这里 4.0 → 6.0）
    assert second["tags"]["title"] == "关键时刻; #倒计时"
    assert float(second["start_time"]) == pytest.approx(4.0, abs=0.01)
    assert float(second["end_time"]) == pytest.approx(DURATION, abs=0.05)
    # 有序、不重叠（播放器跳转的前提）
    assert float(first["end_time"]) <= float(second["start_time"]) + 0.001
    assert result["chapters"] == 2


def test_copy_export_writes_chapters_fast(ctx) -> None:
    """仅封装：几秒出片，视频流原样复制，章节照样读得到。"""
    client, media, _ = ctx
    started = time.time()
    result = _export(client, media, "copy")
    elapsed = time.time() - started
    assert elapsed < 30, f"仅封装不该重编码：{elapsed:.1f}s"
    _assert_chapters(result)

    streams = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", result["path"]],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    codecs = json.loads(streams)["streams"]
    assert any(stream["codec_type"] == "video" and stream["codec_name"] == "h264" for stream in codecs)


def test_soft_export_writes_chapters(ctx) -> None:
    client, media, _ = ctx
    result = _export(client, media, "soft")
    _assert_chapters(result)


@pytest.mark.skipif(not _cjk_font_available(), reason="需要 macOS 中文字体（硬字幕烧录）")
def test_burn_export_writes_chapters(ctx) -> None:
    client, media, _ = ctx
    result = _export(client, media, "burn")
    _assert_chapters(result)


def test_write_chapters_switch_off(ctx) -> None:
    client, media, _ = ctx
    result = _export(client, media, "copy", write_chapters=False)
    assert _chapters(result["path"]) == []
    assert result["chapters"] == 0


def test_plan_previews_chapter_layout(ctx) -> None:
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
        },
    )
    assert res.status_code == 200, res.text
    plan = res.json()["plan"]
    assert [(c["start"], c["end"]) for c in plan["chapters"]] == [(0.0, 4.0), (4.0, DURATION)]


def test_chapter_undo_restores_list_and_disk(ctx, tmp_path: Path) -> None:
    client, media, _ = ctx
    assert (
        client.post(
            "/api/chapters",
            headers=AUTH,
            json={
                "marks": [{"id": "only", "start": 1.0, "end": 3.0, "title": "只剩一个"}],
                "label": "删除其余章节",
            },
        ).status_code
        == 200
    )
    assert len(client.get("/api/chapters", headers=AUTH).json()["marks"]) == 1

    undo = client.post("/api/cues/undo", headers=AUTH)
    assert undo.status_code == 200, undo.text
    marks = client.get("/api/chapters", headers=AUTH).json()["marks"]
    assert [m["title"] for m in marks] == ["场景1 / 开场", "关键时刻; #倒计时"]

    # 边车文件也要回到撤销后的版本（重启 / 换会话都能读到）
    from core import chapters as chapter_store

    stored = chapter_store.load_marks(tmp_path, media["path"])
    assert [m.title for m in stored] == ["场景1 / 开场", "关键时刻; #倒计时"]
