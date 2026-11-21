"""提案状态轮询 + 断句重排提案文件（CLI `propose reshape` 的落点）。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from core import ai_proposal  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "proposal-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
CUES = [
    {"start": 0.0, "end": 1.0, "text": "おはよう"},
    {"start": 2.0, "end": 3.0, "text": "今日は雨だ"},
]


@pytest.fixture()
def client(tmp_path: Path):
    app = create_app(
        ServerConfig(token=TOKEN, output_dir=tmp_path, settings_path=tmp_path / "settings.json")
    )
    client = TestClient(app)
    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    media_id = client.post("/api/media", headers=AUTH, json={"path": str(media)}).json()["id"]
    client.post("/api/session/bind", headers=AUTH, json={"media_id": media_id})
    client.post("/api/cues", headers=AUTH, json={"cues": CUES})
    return client, tmp_path


def test_status_lists_four_proposal_kinds(client):
    api, tmp_path = client
    (tmp_path / "episode.ai-polish.json").write_text("{}", "utf-8")
    (tmp_path / "episode.zh-Hans.ai-translate.json").write_text("{}", "utf-8")
    (tmp_path / "episode.ai-structure.json").write_text("{}", "utf-8")
    (tmp_path / "episode.ai-reshape.json").write_text("{}", "utf-8")

    body = api.get("/api/proposals/status", headers=AUTH).json()
    assert body["media_stem"] == "episode"
    kinds = {item["kind"] for item in body["items"]}
    assert kinds == {"polish", "translate", "structure", "reshape"}
    translate = [item for item in body["items"] if item["kind"] == "translate"][0]
    assert translate["lang"] == "zh-Hans"
    assert translate["mtime"] > 0


def test_status_revision_changes_when_file_changes(client):
    api, tmp_path = client
    path = tmp_path / "episode.ai-polish.json"
    path.write_text("{}", "utf-8")
    first = api.get("/api/proposals/status", headers=AUTH).json()["revision"]
    assert first

    time.sleep(0.02)
    path.write_text('{"items": []}', "utf-8")
    second = api.get("/api/proposals/status", headers=AUTH).json()["revision"]
    assert second != first

    assert api.get("/api/proposals/status", headers=AUTH).json()["revision"] == second


def test_status_is_empty_without_media(client, tmp_path):
    api, _ = client
    # 换一个没有媒体的新会话：状态应是空表而不是报错
    fresh = api.get("/api/proposals/status", headers={**AUTH, "X-Kikusub-Session": "nobody"})
    assert fresh.status_code == 200
    assert fresh.json()["items"] == []


RESHAPE = """1
00:00:00,000 --> 00:00:02,000
おはよう、今日は雨だ

2
00:00:02,500 --> 00:00:04,000
行ってきます
"""


def test_reshape_proposal_roundtrip_and_digest_guard(client):
    api, tmp_path = client
    saved = api.post(
        "/api/ai/reshape/proposal",
        headers=AUTH,
        json={"text": RESHAPE, "digest": ai_proposal.source_digest([c["text"] for c in CUES])},
    )
    assert saved.status_code == 201, saved.text
    path = Path(saved.json()["path"])
    assert path == tmp_path / "episode.ai-reshape.json"
    assert json.loads(path.read_text("utf-8"))["kind"] == "reshape"

    got = api.get("/api/ai/reshape/proposal", headers=AUTH)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["stale"] is False
    assert len(body["cues"]) == 2
    assert body["diagnostics"]["count"] == 2

    # 原稿变了：提案必须标 stale，应用会被 digest 拦住
    api.post(
        "/api/cues",
        headers=AUTH,
        json={"cues": [{"start": 0.0, "end": 1.0, "text": "変わった"}]},
    )
    stale = api.get("/api/ai/reshape/proposal", headers=AUTH).json()
    assert stale["stale"] is True

    rejected = api.post(
        "/api/ai/reshape/proposal",
        headers=AUTH,
        json={"text": RESHAPE, "digest": ai_proposal.source_digest(["おはよう", "今日は雨だ"])},
    )
    assert rejected.status_code == 409

    removed = api.delete("/api/ai/reshape/proposal", headers=AUTH)
    assert removed.json()["removed"] is True
    assert not path.exists()


def test_reshape_proposal_rejects_plain_text(client):
    api, _ = client
    res = api.post("/api/ai/reshape/proposal", headers=AUTH, json={"text": "只是文本"})
    assert res.status_code == 422
    assert "时间码" in res.json()["detail"]
