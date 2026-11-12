"""可回溯历史（50 步）与撤销/重做标签的回归。

用户要的是「历史列表能看出每一步做了什么，并能点任意一步跳回去」，不是只有
can_undo/can_redo 两个布尔值。这里守住时间线的语义：

- 每次编辑记一条带说明的状态，撤销返回被撤回的说明；
- 从历史中间点回去后，后面步骤仍可重做；
- 最多保留 50 步操作（外加「起始状态」）；
- 没有实际变化的 PATCH 不压历史。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from core import audit  # noqa: E402
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


def test_history_caps_at_fifty_operations(client: TestClient) -> None:
    client.post("/api/cues", headers=auth(), json={"cues": BASE_CUES})
    for i in range(55):
        client.patch("/api/cues/0", headers=auth(), json={"text": f"v{i}"})

    history = client.get("/api/cues/history", headers=auth()).json()
    assert len(history["items"]) == 51, "最多 50 步操作 + 一条起始状态"
    assert history["cursor"] == 50
    # 最早的操作已经被挤出窗口，最新一步仍在
    assert history["items"][-1]["label"] == "修改第 1 条文本"
    assert history["items"][0]["label"] == "修改第 1 条文本"

    # 仍可连续撤回 50 步
    for _ in range(50):
        assert client.post("/api/cues/undo", headers=auth()).status_code == 200
    assert client.post("/api/cues/undo", headers=auth()).status_code == 409


def test_noop_patch_does_not_push_history(client: TestClient) -> None:
    client.post("/api/cues", headers=auth(), json={"cues": BASE_CUES})
    before = client.get("/api/cues/history", headers=auth()).json()["items"]
    client.patch("/api/cues/0", headers=auth(), json={"text": "一"})
    after = client.get("/api/cues/history", headers=auth()).json()["items"]
    assert len(after) == len(before)


def test_snapshot_exposes_step_timestamps(client: TestClient) -> None:
    """时间戳仍随快照返回（显示用），但客户端不再拿它做分域比较。"""
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


def test_translation_edits_share_the_unified_history(client: TestClient) -> None:
    client.post("/api/cues", headers=auth(), json={"cues": BASE_CUES})
    client.post(
        "/api/translations",
        headers=auth(),
        json={"lang": "zh-Hans", "texts": ["一译", "二译"]},
    )
    client.post(
        "/api/translations/zh-Hans/replace",
        headers=auth(),
        json={"texts": ["一译改", "二译"]},
    )

    labels = [item["label"] for item in client.get("/api/cues/history", headers=auth()).json()["items"]]
    assert "应用 zh-Hans 译文（2 条）" in labels
    assert "替换 zh-Hans 译文（1 处）" in labels

    # 一条时间线：⌘Z 先退回译文替换，再退回整版应用
    undone = client.post("/api/cues/undo", headers=auth()).json()
    assert undone["undone"] == "替换 zh-Hans 译文（1 处）"
    texts = client.get("/api/translations", headers=auth()).json()["items"][0]["texts"]
    assert texts == ["一译", "二译"]

    undone2 = client.post("/api/cues/undo", headers=auth()).json()
    assert undone2["undone"] == "应用 zh-Hans 译文（2 条）"
    assert client.get("/api/translations", headers=auth()).json()["count"] == 0

    redone = client.post("/api/cues/redo", headers=auth()).json()
    assert redone["redone"] == "应用 zh-Hans 译文（2 条）"
    assert client.get("/api/translations", headers=auth()).json()["items"][0]["texts"] == ["一译", "二译"]


def test_checkpoint_puts_export_ui_on_the_same_timeline(client: TestClient) -> None:
    client.post("/api/cues", headers=auth(), json={"cues": BASE_CUES})
    res = client.post(
        "/api/history/checkpoint",
        headers=auth(),
        json={"label": "导出：字号 42 → 44", "export_ui": {"mode": "soft", "style": {"size": 44}}},
    )
    assert res.status_code == 200, res.text
    assert res.json()["export_ui"]["mode"] == "soft"

    undone = client.post("/api/cues/undo", headers=auth()).json()
    assert undone["undone"] == "导出：字号 42 → 44"
    assert undone["export_ui"] == {}

    redone = client.post("/api/cues/redo", headers=auth()).json()
    assert redone["redone"] == "导出：字号 42 → 44"
    assert redone["export_ui"]["style"]["size"] == 44


def test_checkpoint_coalesces_consecutive_slider_changes(client: TestClient) -> None:
    client.post("/api/cues", headers=auth(), json={"cues": BASE_CUES})
    for size in (43, 44, 45):
        client.post(
            "/api/history/checkpoint",
            headers=auth(),
            json={
                "label": f"导出：字号 42 → {size}",
                "export_ui": {"style": {"size": size}},
                "coalesce": "style.size",
            },
        )
    labels = [item["label"] for item in client.get("/api/cues/history", headers=auth()).json()["items"]]
    assert labels.count("导出：字号 42 → 43") == 0
    assert labels[-1] == "导出：字号 42 → 45"
    assert len(labels) == 3  # 起始状态 + 导入 + 合并后的拖拽


def test_qa_status_actions_are_on_the_unified_timeline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(audit, "OUTPUT_DIR", tmp_path)
    config = ServerConfig(
        token=TOKEN,
        output_dir=tmp_path,
        settings_path=tmp_path / "settings.json",
    )
    client = TestClient(create_app(config))
    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    media_id = client.post("/api/media", headers=auth(), json={"path": str(media)}).json()["id"]
    client.post("/api/session/bind", headers=auth(), json={"media_id": media_id})
    client.post("/api/cues", headers=auth(), json={"cues": BASE_CUES})

    item = {
        "id": "suspect:1000:1500",
        "kind": "suspect",
        "start": 1.0,
        "end": 1.5,
        "dur": 0.5,
        "text": "二",
        "cues": [{"start": 1.0, "end": 2.0, "text": "二"}],
    }
    payload = audit.make_audit_payload("episode.mkv", [item], latest_cue_count=2)
    (tmp_path / "episode.qa.json").write_text(payload, encoding="utf-8")

    qa = client.get("/api/qa", headers=auth()).json()
    assert len(qa["items"]) == 1
    done = client.post(
        "/api/qa/action",
        headers=auth(),
        json={"id": item["id"], "action": "mark", "status": "done", "resolution": "kept"},
    )
    assert done.status_code == 200, done.text
    assert done.json()["qa"]["statuses"][item["id"]]["status"] == "done"

    labels = [entry["label"] for entry in client.get("/api/cues/history", headers=auth()).json()["items"]]
    assert labels[-1] == "质检：保留"

    undone = client.post("/api/cues/undo", headers=auth()).json()
    assert undone["undone"] == "质检：保留"
    # 状态也回滚：服务端必须把 .qa.json 写回动作之前的样子。
    assert client.get("/api/qa", headers=auth()).json()["statuses"] == {}

    redone = client.post("/api/cues/redo", headers=auth()).json()
    assert redone["redone"] == "质检：保留"
    assert client.get("/api/qa", headers=auth()).json()["statuses"][item["id"]]["status"] == "done"


def test_first_export_checkpoint_is_still_undoable(client: TestClient) -> None:
    """第一次动作就是导出设置时，基线必须落在改动之前。"""
    client.post(
        "/api/history/checkpoint",
        headers=auth(),
        json={"label": "导出：套用软字幕", "export_ui": {"mode": "soft"}},
    )
    labels = [item["label"] for item in client.get("/api/cues/history", headers=auth()).json()["items"]]
    assert labels == ["起始状态", "导出：套用软字幕"]
    undone = client.post("/api/cues/undo", headers=auth()).json()
    assert undone["undone"] == "导出：套用软字幕"
    assert undone["export_ui"] == {}


def test_replace_all_original_and_translation_is_one_history_step(client: TestClient) -> None:
    client.post("/api/cues", headers=auth(), json={"cues": BASE_CUES})
    client.post(
        "/api/translations",
        headers=auth(),
        json={"lang": "zh-Hans", "texts": ["一译", "二译"]},
    )
    before = len(client.get("/api/cues/history", headers=auth()).json()["items"])

    res = client.post(
        "/api/cues/replace-all",
        headers=auth(),
        json={
            "label": "查找替换（2 处）",
            "cues": [
                {"start": 0.0, "end": 1.0, "text": "一新"},
                {"start": 1.0, "end": 2.0, "text": "二新"},
            ],
            "lang": "zh-Hans",
            "texts": ["一译新", "二译新"],
        },
    )
    assert res.status_code == 200, res.text
    after = client.get("/api/cues/history", headers=auth()).json()["items"]
    assert len(after) == before + 1
    assert after[-1]["label"] == "查找替换（2 处）"

    undone = client.post("/api/cues/undo", headers=auth()).json()
    assert undone["undone"] == "查找替换（2 处）"
    assert [c["text"] for c in undone["cues"]] == ["一", "二"]
    assert client.get("/api/translations", headers=auth()).json()["items"][0]["texts"] == [
        "一译",
        "二译",
    ]

    redone = client.post("/api/cues/redo", headers=auth()).json()
    assert redone["redone"] == "查找替换（2 处）"
    assert [c["text"] for c in redone["cues"]] == ["一新", "二新"]
    assert client.get("/api/translations", headers=auth()).json()["items"][0]["texts"] == [
        "一译新",
        "二译新",
    ]
