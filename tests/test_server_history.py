"""可回溯历史（20 步）与撤销/重做标签的回归。

用户要的是「历史列表能看出每一步做了什么，并能点任意一步跳回去」，不是只有
can_undo/can_redo 两个布尔值。这里守住时间线的语义：

- 每次编辑记一条带说明的状态，撤销返回被撤回的说明；
- 从历史中间点回去后，后面步骤仍可重做；
- 最多保留 20 步操作（外加「起始状态」）；
- 没有实际变化的 PATCH 不压历史。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "history-token"


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    config = ServerConfig(
        token=TOKEN,
        output_dir=tmp_path,
        settings_path=tmp_path / "settings.json",
    )
    return TestClient(create_app(config))


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


BASE_CUES = [
    {"start": 0.0, "end": 1.0, "text": "一"},
    {"start": 1.0, "end": 2.0, "text": "二"},
]


def test_history_labels_undo_redo_and_jump(client: TestClient) -> None:
    client.post("/api/cues", headers=auth(), json={"cues": BASE_CUES, "label": "导入字幕（2 条）"})
    client.patch("/api/cues/0", headers=auth(), json={"text": "改过"})
    client.post("/api/cues/1/insert", headers=auth(), json={"index": 0, "start": 2.0, "end": 2.5, "text": "新"})

    history = client.get("/api/cues/history", headers=auth()).json()
    labels = [item["label"] for item in history["items"]]
    assert labels[0] == "起始状态"
    assert "导入字幕（2 条）" in labels
    assert "修改第 1 条文本" in labels
    assert "插入第 1 条" in labels
    assert history["cursor"] == len(history["items"]) - 1
    assert history["items"][-1]["state"] == "current"

    # 撤回：返回的说明就是被撤回的那一步；再重做也返回同一个说明
    undone = client.post("/api/cues/undo", headers=auth()).json()
    assert undone["undone"] == "插入第 1 条"
    assert undone["can_redo"] is True
    assert undone["redo_label"] == "插入第 1 条"
    redone = client.post("/api/cues/redo", headers=auth()).json()
    assert redone["redone"] == "插入第 1 条"

    # 点历史里的「导入字幕」一步：直接回到两条字幕的状态
    import_id = next(
        item["id"] for item in history["items"] if item["label"] == "导入字幕（2 条）"
    )
    jumped = client.post(
        "/api/cues/history/jump", headers=auth(), json={"index": import_id}
    ).json()
    assert [c["text"] for c in jumped["cues"]] == ["一", "二"]
    assert jumped["can_undo"] is True
    assert jumped["can_redo"] is True, "跳到中间后后面的步骤必须还能重做"

    after = client.get("/api/cues/history", headers=auth()).json()
    assert after["cursor"] == import_id
    assert after["items"][-1]["state"] == "undone"


def test_history_caps_at_twenty_operations(client: TestClient) -> None:
    client.post("/api/cues", headers=auth(), json={"cues": BASE_CUES})
    for i in range(25):
        client.patch("/api/cues/0", headers=auth(), json={"text": f"v{i}"})

    history = client.get("/api/cues/history", headers=auth()).json()
    assert len(history["items"]) == 21, "最多 20 步操作 + 一条起始状态"
    assert history["cursor"] == 20
    # 最早的操作已经被挤出窗口，最新一步仍在
    assert history["items"][-1]["label"] == "修改第 1 条文本"
    assert history["items"][0]["label"] == "修改第 1 条文本"

    # 仍可连续撤回 20 步
    for _ in range(20):
        assert client.post("/api/cues/undo", headers=auth()).status_code == 200
    assert client.post("/api/cues/undo", headers=auth()).status_code == 409


def test_noop_patch_does_not_push_history(client: TestClient) -> None:
    client.post("/api/cues", headers=auth(), json={"cues": BASE_CUES})
    before = client.get("/api/cues/history", headers=auth()).json()["items"]
    client.patch("/api/cues/0", headers=auth(), json={"text": "一"})
    after = client.get("/api/cues/history", headers=auth()).json()["items"]
    assert len(after) == len(before)


def test_snapshot_exposes_step_timestamps_for_global_undo(client: TestClient) -> None:
    """渲染层的全局 ⌘Z 要按时间先后决定撤回字幕还是导出设置。"""
    no_media = client.get("/api/cues", headers=auth()).json()
    assert no_media["undo_at"] == 0.0 and no_media["redo_at"] == 0.0

    client.post("/api/cues", headers=auth(), json={"cues": BASE_CUES})
    patched = client.patch("/api/cues/0", headers=auth(), json={"text": "改过"}).json()
    history = client.get("/api/cues/history", headers=auth()).json()
    step = history["items"][history["cursor"]]
    assert patched["undo_at"] == pytest.approx(step["at"])
    assert patched["redo_at"] == 0.0

    undone = client.post("/api/cues/undo", headers=auth()).json()
    assert undone["undo_at"] < patched["undo_at"]
    assert undone["redo_at"] == pytest.approx(step["at"])


def test_jump_out_of_range_is_422(client: TestClient) -> None:
    client.post("/api/cues", headers=auth(), json={"cues": BASE_CUES})
    resp = client.post("/api/cues/history/jump", headers=auth(), json={"index": 99})
    assert resp.status_code == 422
