"""提示词模板库：默认值、持久化、渲染与手动通道。"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from core import prompts  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "prompt-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

CUES = [
    {"start": 0.5, "end": 1.5, "text": "おはよう"},
    {"start": 2.0, "end": 3.0, "text": "今日は雨だ"},
]


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            ServerConfig(
                token=TOKEN,
                output_dir=tmp_path,
                settings_path=tmp_path / "settings.json",
            )
        )
    )


def test_default_library_has_two_builtin_templates(tmp_path: Path) -> None:
    library = prompts.load_library(path=tmp_path / "prompts.json")
    assert [item["name"] for item in library["templates"]] == ["原有模板", "成熟汉化组"]
    assert library["selected"] == prompts.LEGACY_ID
    assert all(item["builtin"] for item in library["templates"])


def test_render_replaces_placeholders_and_appends_srt(tmp_path: Path) -> None:
    text = prompts.render_template(
        "翻译为{{LANG}}：\n{{SRT}}", "1\n00:00:00,000 --> 00:00:01,000\n你好", "简体中文"
    )
    assert "翻译为简体中文" in text
    assert "你好" in text
    assert "{{SRT}}" not in text

    appended = prompts.render_template("内容如下：", "SRT-BODY", "简体中文")
    assert appended.startswith("内容如下：")
    assert "<subtitles>" in appended
    assert "SRT-BODY" in appended


def test_update_select_and_builtin_reset(client: TestClient) -> None:
    created = client.post(
        "/api/prompts",
        headers=AUTH,
        json={"name": "测试模板", "description": "d", "content": "把 {{SRT}} 译成{{LANG}}"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created"].startswith("custom-")
    custom_id = body["created"]
    assert any(item["id"] == custom_id for item in body["templates"])

    patched = client.patch(
        f"/api/prompts/{custom_id}",
        headers=AUTH,
        json={"name": "改过的名字", "content": "新的 {{SRT}}"},
    )
    assert patched.status_code == 200, patched.text
    item = next(t for t in patched.json()["templates"] if t["id"] == custom_id)
    assert item["name"] == "改过的名字"
    assert item["content"] == "新的 {{SRT}}"

    selected = client.post(f"/api/prompts/{custom_id}/select", headers=AUTH)
    assert selected.status_code == 200, selected.text
    assert selected.json()["selected"] == custom_id

    # 内置模板被改后可以恢复出厂文案
    changed = client.patch(
        f"/api/prompts/{prompts.LOCALIZATION_ID}",
        headers=AUTH,
        json={"content": "临时内容"},
    )
    assert changed.status_code == 200
    reset = client.post(f"/api/prompts/{prompts.LOCALIZATION_ID}/reset", headers=AUTH)
    assert reset.status_code == 200, reset.text
    item = next(
        t for t in reset.json()["templates"] if t["id"] == prompts.LOCALIZATION_ID
    )
    assert "资深成熟汉化组" in item["content"]


def test_manual_prompt_uses_selected_template(client: TestClient, tmp_path: Path) -> None:
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"x")
    media_id = client.post("/api/media", headers=AUTH, json={"path": str(media)}).json()["id"]
    client.post("/api/session/bind", headers=AUTH, json={"media_id": media_id})
    assert client.post("/api/cues", headers=AUTH, json={"cues": CUES}).status_code == 200

    def prompt_for(template_id: str = "") -> dict:
        q = "?kind=translate&lang=zh-Hans"
        if template_id:
            q += f"&template_id={template_id}"
        res = client.get(f"/api/ai/prompt{q}", headers=AUTH)
        assert res.status_code == 200, res.text
        return res.json()

    legacy = prompt_for()
    assert legacy["template_id"] == prompts.LEGACY_ID
    assert "おはよう" in legacy["prompt"]
    assert "00:00:00,500" in legacy["prompt"]

    client.post(f"/api/prompts/{prompts.LOCALIZATION_ID}/select", headers=AUTH)
    chosen = prompt_for()
    assert chosen["template_id"] == prompts.LOCALIZATION_ID
    assert "资深成熟汉化组" in chosen["prompt"]
    assert "おはよう" in chosen["prompt"]


def test_library_file_is_written_next_to_settings(client: TestClient, tmp_path: Path) -> None:
    client.post("/api/prompts", headers=AUTH, json={"name": "x", "content": "y"})
    assert (tmp_path / "prompts.json").exists()
