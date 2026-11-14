"""结构建议的 HTTP 契约：解析落盘 / 预览 / 原子应用 / 冲突与译文保护。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402
from core.subtitles import SubtitleCue  # noqa: E402
from server.sessions import TranslationTrack  # noqa: E402

TOKEN = "structure-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SID = "structure-test"
HEADERS = {**AUTH, "x-kikusub-session": SID}

CUES = [
    {"start": 1.0, "end": 2.0, "text": "あ"},
    {"start": 2.0, "end": 3.0, "text": "い"},
    {"start": 3.0, "end": 4.0, "text": "う"},
    {"start": 4.0, "end": 5.0, "text": "え"},
]


@pytest.fixture()
def ctx(tmp_path: Path):
    app = create_app(
        ServerConfig(
            token=TOKEN,
            output_dir=tmp_path,
            settings_path=tmp_path / "settings.json",
        )
    )
    client = TestClient(app)
    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    media_id = client.post("/api/media", headers=HEADERS, json={"path": str(media)}).json()["id"]
    client.post("/api/session/bind", headers=HEADERS, json={"media_id": media_id})
    seeded = client.post("/api/cues", headers=HEADERS, json={"cues": CUES})
    assert seeded.status_code == 200, seeded.text
    return client, tmp_path


def _ops(client: TestClient, ops: list[dict]):
    return client.post(
        "/api/ai/structure/from-json",
        headers=HEADERS,
        json={"text": json.dumps({"ops": ops}, ensure_ascii=False)},
    )


def _texts(client: TestClient) -> list[str]:
    return [cue["text"] for cue in client.get("/api/cues", headers=HEADERS).json()["cues"]]


def test_from_json_saves_and_previews(ctx):
    client, root = ctx
    res = _ops(
        client,
        [
            {"op": "merge", "from": 1, "to": 2, "text": "あい"},
            {"op": "replace_text", "i": 3, "after": "うう"},
            {"op": "insert", "after": 0, "start": 0.1, "end": 0.9, "text": "前"},
        ],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["exists"] is True
    assert body["revision"]
    assert body["source"]["digest"]
    assert body["summary"]["conflicts"] == 0
    assert [op["op"] for op in body["ops"]] == ["merge", "replace_text", "insert"]
    assert (root / "episode.ai-structure.json").exists()

    loaded = client.get("/api/ai/structure", headers=HEADERS)
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["revision"] == body["revision"]


def test_from_json_rejects_unknown_op(ctx):
    client, root = ctx
    res = _ops(client, [{"op": "split", "i": 1}])
    assert res.status_code == 422
    assert "不支持" in res.json()["detail"]
    assert not (root / "episode.ai-structure.json").exists()


def test_apply_is_atomic_and_undoable(ctx):
    client, _ = ctx
    parsed = _ops(
        client,
        [
            {"op": "merge", "from": 1, "to": 2, "text": "あい"},
            {"op": "retime", "i": 3, "start": 3.1, "end": 3.9},
            {"op": "insert", "after": 0, "start": 0.1, "end": 0.9, "text": "前"},
        ],
    ).json()
    res = client.post(
        "/api/ai/structure/apply",
        headers=HEADERS,
        json={"accept": [0, 1, 2], "revision": parsed["revision"]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["applied"] == 3
    assert body["changed"] == 1
    assert [(c["text"], c["start"], c["end"]) for c in body["cues"]] == [
        ("前", 0.1, 0.9),
        ("あい", 1.0, 3.0),
        ("う", 3.1, 3.9),
        ("え", 4.0, 5.0),
    ]
    # 应用后文件丢弃，剩余 ops 的旧下标不再可信
    assert client.get("/api/ai/structure", headers=HEADERS).status_code == 409

    undone = client.post("/api/cues/undo", headers=HEADERS)
    assert undone.status_code == 200, undone.text
    assert _texts(client) == ["あ", "い", "う", "え"]


def test_apply_rejects_stale_digest(ctx):
    client, _ = ctx
    parsed = _ops(client, [{"op": "delete", "i": 1}]).json()
    patched = client.patch("/api/cues/0", headers=HEADERS, json={"text": "ああ"})
    assert patched.status_code == 200, patched.text
    res = client.post(
        "/api/ai/structure/apply",
        headers=HEADERS,
        json={"accept": [0], "revision": parsed["revision"]},
    )
    assert res.status_code == 409
    assert "字幕已变化" in res.json()["detail"]
    assert _texts(client) == ["ああ", "い", "う", "え"]


def test_apply_conflict_returns_409_without_changing_cues(ctx):
    client, _ = ctx
    parsed = _ops(
        client,
        [{"op": "merge", "from": 1, "to": 2}, {"op": "delete", "i": 1}],
    ).json()
    res = client.post(
        "/api/ai/structure/apply",
        headers=HEADERS,
        json={"accept": [0, 1], "revision": parsed["revision"]},
    )
    assert res.status_code == 409
    assert _texts(client) == ["あ", "い", "う", "え"]


def test_apply_selected_subset_and_revision_guard(ctx):
    client, _ = ctx
    parsed = _ops(
        client,
        [
            {"op": "replace_text", "i": 1, "after": "ああ"},
            {"op": "delete", "i": 4},
        ],
    ).json()

    wrong = client.post(
        "/api/ai/structure/apply",
        headers=HEADERS,
        json={"accept": [0], "revision": "old-revision"},
    )
    assert wrong.status_code == 409

    res = client.post(
        "/api/ai/structure/apply",
        headers=HEADERS,
        json={"accept": [0], "revision": parsed["revision"]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["applied"] == 1
    assert _texts(client) == ["ああ", "い", "う", "え"]  # delete 不在选中集里


def test_apply_requires_a_selection(ctx):
    client, _ = ctx
    parsed = _ops(client, [{"op": "delete", "i": 1}]).json()
    res = client.post(
        "/api/ai/structure/apply",
        headers=HEADERS,
        json={"accept": [], "revision": parsed["revision"]},
    )
    assert res.status_code == 422


def test_translation_guard_blocks_count_changing_ops(ctx):
    client, _ = ctx
    session = client.app.state.sessions.peek(SID)
    assert session is not None
    session.set_translation(
        TranslationTrack(lang="zh-Hans", texts=["甲", "乙", "丙", "丁"], base=["あ", "い", "う", "え"]),
        record=False,
    )
    parsed = _ops(
        client,
        [
            {"op": "merge", "from": 1, "to": 2},
            {"op": "replace_text", "i": 3, "after": "うう"},
        ],
    ).json()
    assert parsed["ops"][0]["conflict"]
    assert not parsed["ops"][1]["conflict"]

    blocked = client.post(
        "/api/ai/structure/apply",
        headers=HEADERS,
        json={"accept": [0], "revision": parsed["revision"]},
    )
    assert blocked.status_code == 409
    assert "已有译文轨" in blocked.json()["detail"]

    allowed = client.post(
        "/api/ai/structure/apply",
        headers=HEADERS,
        json={"accept": [1], "revision": parsed["revision"]},
    )
    assert allowed.status_code == 200, allowed.text
    assert _texts(client) == ["あ", "い", "うう", "え"]


def test_prompt_endpoint_has_ops_contract(ctx):
    client, root = ctx
    res = client.get("/api/ai/structure/prompt", headers=HEADERS)
    assert res.status_code == 200, res.text
    prompt = res.json()["prompt"]
    assert '"ops"' in prompt
    assert "digest" not in prompt
    assert "version" not in prompt
    assert "あ" in prompt
    # 没有第二版时 dual 模式应明确拒绝，而不是静默退化成单源
    dual = client.get("/api/ai/structure/prompt?mode=dual", headers=HEADERS)
    assert dual.status_code == 409

    session = client.app.state.sessions.peek(SID)
    assert session is not None
    session.set_alt_review(
        engine="qwen",
        cues=[SubtitleCue(1.0, 2.0, "B 参考台词")],
        source={"kind": "transcription"},
        media_path=session.media_path or str(root / "episode.mkv"),
        output_dir=root,
    )
    dual = client.get("/api/ai/structure/prompt?mode=dual", headers=HEADERS)
    assert dual.status_code == 200, dual.text
    assert "B 参考台词" in dual.json()["prompt"]


def test_empty_ops_clears_previous_proposal(ctx):
    client, root = ctx
    assert _ops(client, [{"op": "delete", "i": 1}]).status_code == 200
    path = root / "episode.ai-structure.json"
    assert path.exists()
    res = _ops(client, [])
    assert res.status_code == 200, res.text
    assert res.json()["exists"] is False
    assert not path.exists()
