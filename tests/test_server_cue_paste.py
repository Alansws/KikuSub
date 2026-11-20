"""「复制 / 粘贴字幕」的服务端契约（2026-11-17）。

用户场景：气声字幕局部转写常常空结果，偶尔转出来一条正确的，就想把它复制到
另一个播放头位置。前端负责算时间；服务端这里守住三件事：

- 粘贴一条带译文的字幕只压**一步**统一历史，⌘Z 一次把原文与译文一起退回；
- 剪贴板跨片时可能带着目标片不存在的语种：直接忽略，不报错、不新建残缺轨；
- 译文生成时的 ``base`` 原样保留，原来过期的译文在新句上仍然显示过期。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "cue-paste-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

BASE_CUES = [
    {"start": 0.0, "end": 1.0, "text": "一"},
    {"start": 1.0, "end": 2.0, "text": "二"},
]


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    config = ServerConfig(
        token=TOKEN,
        output_dir=tmp_path,
        settings_path=tmp_path / "settings.json",
    )
    return TestClient(create_app(config))


def _cues(client: TestClient) -> list[dict]:
    return client.get("/api/cues", headers=AUTH).json()["cues"]


def _zh_track(client: TestClient) -> dict:
    items = client.get("/api/translations", headers=AUTH).json()["items"]
    return next(item for item in items if item["lang"] == "zh-Hans")


def test_paste_with_translation_is_one_history_step(client: TestClient) -> None:
    client.post("/api/cues", headers=AUTH, json={"cues": BASE_CUES, "label": "导入字幕"})
    client.post(
        "/api/translations",
        headers=AUTH,
        json={"lang": "zh-Hans", "texts": ["一译", "二译"]},
    )

    res = client.post(
        "/api/cues/1/insert",
        headers=AUTH,
        json={
            "index": 1,
            "start": 5.0,
            "end": 5.5,
            "text": "一",
            "label": "粘贴字幕到 00:05.000",
            "translations": {"zh-Hans": {"text": "一译", "base": "一"}},
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["index"] == 1

    assert [cue["text"] for cue in _cues(client)] == ["一", "一", "二"]
    track = _zh_track(client)
    assert track["texts"] == ["一译", "一译", "二译"]
    assert track["base"] == ["一", "一", "二"]
    assert track["stale"] == []

    history = client.get("/api/cues/history", headers=AUTH).json()
    assert history["items"][-1]["label"] == "粘贴字幕到 00:05.000"

    # 一次撤回：原文与译文在同一份历史快照里，必须一起回到粘贴前
    undone = client.post("/api/cues/undo", headers=AUTH)
    assert undone.status_code == 200, undone.text
    assert undone.json()["undone"] == "粘贴字幕到 00:05.000"
    assert [cue["text"] for cue in _cues(client)] == ["一", "二"]
    assert _zh_track(client)["texts"] == ["一译", "二译"]


def test_paste_ignores_translation_langs_missing_from_current_media(
    client: TestClient,
) -> None:
    """剪贴板来自另一部片：目标片没有 en 轨时静默忽略，不新建残缺轨。"""
    client.post("/api/cues", headers=AUTH, json={"cues": BASE_CUES})

    res = client.post(
        "/api/cues/0/insert",
        headers=AUTH,
        json={
            "index": 0,
            "start": 5.0,
            "end": 5.5,
            "text": "一",
            "label": "粘贴字幕到 00:05.000",
            "translations": {"en": {"text": "one", "base": "一"}},
        },
    )
    assert res.status_code == 200, res.text
    assert [cue["text"] for cue in _cues(client)] == ["一", "一", "二"]
    assert client.get("/api/translations", headers=AUTH).json()["items"] == []


def test_paste_keeps_stale_translation_base(client: TestClient) -> None:
    """复制一条已经过期的译文，粘到新位置后仍然是过期状态。"""
    client.post("/api/cues", headers=AUTH, json={"cues": BASE_CUES})
    client.post(
        "/api/translations",
        headers=AUTH,
        json={"lang": "zh-Hans", "texts": ["一译", "二译"]},
    )
    client.patch("/api/cues/0", headers=AUTH, json={"text": "改过"})
    assert _zh_track(client)["stale"] == [0]

    res = client.post(
        "/api/cues/1/insert",
        headers=AUTH,
        json={
            "index": 1,
            "start": 5.0,
            "end": 5.5,
            "text": "改过",
            "label": "粘贴字幕到 00:05.000",
            # 前端带的是译文轨里原来的 base（「一」），不是当前原文「改过」
            "translations": {"zh-Hans": {"text": "一译", "base": "一"}},
        },
    )
    assert res.status_code == 200, res.text
    track = _zh_track(client)
    assert track["base"] == ["一", "一", "二"]
    assert track["stale"] == [0, 1]
