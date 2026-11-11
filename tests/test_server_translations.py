"""译文平行轨的接口：应用 / 撤销 / 删除 / 过期 / 三态导出 / 暂存（开发文档 §6）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from core import ai_proposal as proposals  # noqa: E402
from core.subtitles import srt_to_cues  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402

TOKEN = "tr-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

CUES = [
    {"start": 0.0, "end": 1.0, "text": "おはよう"},
    {"start": 1.0, "end": 2.0, "text": "今日は雨だ"},
    {"start": 2.0, "end": 3.0, "text": "またね"},
]
TEXTS = [c["text"] for c in CUES]
ZH = ["早上好", "今天下雨", "再见"]


def translate_proposal(after=None, texts=None, dst_lang="zh-Hans"):
    texts = list(TEXTS if texts is None else texts)
    after = list(ZH if after is None else after)
    items = [
        {"i": idx, "before": texts[idx - 1], "after": after[idx - 1], "note": ""}
        for idx in range(1, len(texts) + 1)
    ]
    return proposals.build_proposal(
        kind="translate", src_lang="ja", dst_lang=dst_lang, texts=texts, items=items
    )


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
    media_id = client.post("/api/media", headers=AUTH, json={"path": str(media)}).json()["id"]
    client.post("/api/session/bind", headers=AUTH, json={"media_id": media_id})
    assert client.post("/api/cues", headers=AUTH, json={"cues": CUES}).status_code == 200
    return client, tmp_path


# --------------------------------------------------------------------------- 读写


def test_apply_texts_then_read_back(ctx):
    client, _ = ctx
    res = client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["exists"] is True and body["count"] == 3
    assert body["stale"] == []

    listed = client.get("/api/translations", headers=AUTH).json()
    assert listed["count"] == 1
    assert listed["items"][0]["texts"] == ZH


def test_apply_from_proposal_checks_digest(ctx):
    client, _ = ctx
    ok = client.post(
        "/api/translations",
        headers=AUTH,
        json={"lang": "zh-Hans", "proposal": translate_proposal()},
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["texts"] == ZH

    bad = translate_proposal(texts=["别", "的", "字幕"])
    res = client.post(
        "/api/translations", headers=AUTH, json={"lang": "zh-Hans", "proposal": bad}
    )
    assert res.status_code == 409


def test_apply_rejects_count_mismatch(ctx):
    client, _ = ctx
    res = client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ["只有一条"]})
    assert res.status_code == 422
    assert client.get("/api/translations", headers=AUTH).json()["count"] == 0


def test_apply_rejects_polish_proposal(ctx):
    client, _ = ctx
    polish = proposals.build_proposal(
        kind="polish",
        src_lang="ja",
        texts=TEXTS,
        items=[
            {"i": i, "before": t, "after": t, "note": ""}
            for i, t in enumerate(TEXTS, start=1)
        ],
    )
    res = client.post(
        "/api/translations", headers=AUTH, json={"lang": "zh-Hans", "proposal": polish}
    )
    assert res.status_code == 422


def test_apply_requires_existing_cues(tmp_path: Path):
    app = create_app(
        ServerConfig(token=TOKEN, output_dir=tmp_path, settings_path=tmp_path / "s.json")
    )
    client = TestClient(app)
    media = tmp_path / "e.mkv"
    media.write_bytes(b"x")
    mid = client.post("/api/media", headers=AUTH, json={"path": str(media)}).json()["id"]
    client.post("/api/session/bind", headers=AUTH, json={"media_id": mid})
    res = client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": []})
    assert res.status_code == 409


# --------------------------------------------------------------------------- 过期


def test_stale_flags_after_source_edit(ctx):
    client, _ = ctx
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH})
    client.patch("/api/cues/1", headers=AUTH, json={"text": "今日は雪だ"})

    track = client.get("/api/translations", headers=AUTH).json()["items"][0]
    assert track["stale"] == [1]
    # 摘要里也要能看到，避免前端还得再拉一次全量
    summary = client.get("/api/cues", headers=AUTH).json()["translations"]["zh-Hans"]
    assert summary["stale"] == [1]


def test_stale_flags_when_cues_shrink(ctx):
    client, _ = ctx
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH})
    client.delete("/api/cues/1", headers=AUTH)
    track = client.get("/api/translations", headers=AUTH).json()["items"][0]
    assert 1 in track["stale"]


# --------------------------------------------------------------------------- 撤销 / 删除


def test_undo_restores_previous_track(ctx):
    client, _ = ctx
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH})
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ["A", "B", "C"]})

    undone = client.post("/api/translations/undo", headers=AUTH, json={"lang": "zh-Hans"}).json()
    assert undone["undone"] is True
    assert undone["texts"] == ZH


def test_undo_without_history_is_noop(ctx):
    client, _ = ctx
    res = client.post("/api/translations/undo", headers=AUTH, json={"lang": "zh-Hans"})
    assert res.status_code == 200
    assert res.json()["undone"] is False


def test_delete_track(ctx):
    client, _ = ctx
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH})
    res = client.delete("/api/translations/zh-Hans", headers=AUTH)
    assert res.json()["removed"] is True
    assert client.get("/api/translations", headers=AUTH).json()["count"] == 0


# --------------------------------------------------------------------------- 导出


def test_export_source_is_unchanged(ctx):
    client, _ = ctx
    data = client.post("/api/cues/export", headers=AUTH, json={"format": "SRT"}).json()
    assert data["track"] == "source"
    assert "おはよう" in Path(data["path"]).read_text(encoding="utf-8")
    assert "早上好" not in Path(data["path"]).read_text(encoding="utf-8")


def test_export_target_only_translation(ctx):
    client, _ = ctx
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH})
    res = client.post(
        "/api/cues/export", headers=AUTH, json={"format": "SRT", "track": "target", "lang": "zh-Hans"}
    )
    assert res.status_code == 200, res.text
    path = Path(res.json()["path"])
    assert path.name.endswith(".zh-Hans.srt")
    text = path.read_text(encoding="utf-8")
    assert "早上好" in text and "おはよう" not in text


def test_export_bilingual_writes_one_cue_per_language(ctx):
    client, _ = ctx
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH})
    res = client.post(
        "/api/cues/export", headers=AUTH, json={"format": "SRT", "track": "both", "lang": "zh-Hans"}
    )
    path = Path(res.json()["path"])
    assert path.name.endswith(".bilingual.srt")

    cues = srt_to_cues(path.read_text(encoding="utf-8"))
    # 每条 cue 只有一行：原文一条、译文一条，共享同一时间轴（官方双语 SRT 的写法）
    assert len(cues) == 6
    assert [c.text for c in cues] == ["おはよう", "早上好", "今日は雨だ", "今天下雨", "またね", "再见"]
    assert all("\n" not in c.text for c in cues)
    assert [(c.start, c.end) for c in cues] == [
        (0.0, 1.0),
        (0.0, 1.0),
        (1.0, 2.0),
        (1.0, 2.0),
        (2.0, 3.0),
        (2.0, 3.0),
    ]


def test_reimport_bilingual_export_has_single_line_cues(ctx):
    """回归：`.bilingual.srt` 重新导入核对台不能把两种语言挤成一行。"""
    client, _ = ctx
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH})
    exported = client.post(
        "/api/cues/export", headers=AUTH, json={"format": "SRT", "track": "both", "lang": "zh-Hans"}
    ).json()
    imported = client.post("/api/cues/import", headers=AUTH, json={"path": exported["path"]})
    assert imported.status_code == 200, imported.text
    cues = imported.json()["cues"]
    assert len(cues) == 6
    assert all("\n" not in cue["text"] for cue in cues)
    assert cues[0]["text"] == "おはよう" and cues[1]["text"] == "早上好"


def test_import_legacy_bilingual_two_line_cue_is_split(ctx, tmp_path):
    """旧版导出把两种语言写在一条 cue 的两行里；导入时按行拆开。"""
    client, tmp_path = ctx
    legacy = tmp_path / "episode.bilingual.srt"
    legacy.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nおはよう\n早上好\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nまたね\n",
        encoding="utf-8",
    )
    res = client.post("/api/cues/import", headers=AUTH, json={"path": str(legacy)})
    assert res.status_code == 200, res.text
    cues = res.json()["cues"]
    assert [c["text"] for c in cues] == ["おはよう", "早上好", "またね"]


def test_import_plain_multiline_srt_keeps_lines(ctx, tmp_path):
    """普通 SRT 的多行 cue 不做拆分：只有 .bilingual 文件名才按双语处理。"""
    client, tmp_path = ctx
    plain = tmp_path / "episode.srt"
    plain.write_text("1\n00:00:00,000 --> 00:00:01,000\n長い行\n折り返し\n", encoding="utf-8")
    res = client.post("/api/cues/import", headers=AUTH, json={"path": str(plain)})
    assert res.status_code == 200, res.text
    assert [c["text"] for c in res.json()["cues"]] == ["長い行\n折り返し"]


def test_export_target_without_track_is_409(ctx):
    client, _ = ctx
    res = client.post(
        "/api/cues/export", headers=AUTH, json={"format": "SRT", "track": "target", "lang": "zh-Hans"}
    )
    assert res.status_code == 409


def test_export_target_requires_lang(ctx):
    client, _ = ctx
    res = client.post("/api/cues/export", headers=AUTH, json={"format": "SRT", "track": "target"})
    assert res.status_code == 422


def test_export_unknown_track_is_422(ctx):
    client, _ = ctx
    res = client.post("/api/cues/export", headers=AUTH, json={"format": "SRT", "track": "sideways"})
    assert res.status_code == 422


# --------------------------------------------------------------------------- 暂存


def test_draft_roundtrip_keeps_translations(ctx):
    client, tmp_path = ctx
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH})

    client.post("/api/cues/draft", headers=AUTH)
    i18n = tmp_path / "episode.autosave_draft.i18n.json"
    assert i18n.exists()
    saved = json.loads(i18n.read_text(encoding="utf-8"))
    assert saved["tracks"]["zh-Hans"]["texts"] == ZH

    # 清空会话，再从草稿恢复
    client.post("/api/cues/clear", headers=AUTH)
    restored = client.post("/api/cues/draft/restore", headers=AUTH).json()
    assert "zh-Hans" in restored["translations"]
    track = client.get("/api/translations", headers=AUTH).json()["items"][0]
    assert track["texts"] == ZH


def test_draft_restore_ignores_mismatched_track(ctx):
    """草稿里的译文条数与字幕对不上时必须丢弃，而不是给一份错位的轨。"""
    client, tmp_path = ctx
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH})
    client.post("/api/cues/draft", headers=AUTH)
    # 手动把草稿改小：恢复时应当忽略译文轨
    (tmp_path / "episode.autosave_draft.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nおはよう\n", encoding="utf-8"
    )
    restored = client.post("/api/cues/draft/restore", headers=AUTH).json()
    assert restored["translations"] == []
    assert client.get("/api/translations", headers=AUTH).json()["count"] == 0


# --------------------------------------------------------------------------- 逐条改译文


def test_patch_single_translation(ctx):
    client, _ = ctx
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH})

    res = client.patch("/api/translations/zh-Hans/1", headers=AUTH, json={"text": "今天下雪"})
    assert res.status_code == 200, res.text
    assert res.json()["texts"] == ["早上好", "今天下雪", "再见"]
    # 原文与时间轴不动
    cues = client.get("/api/cues", headers=AUTH).json()["cues"]
    assert [c["text"] for c in cues] == TEXTS


def test_patch_is_undoable(ctx):
    client, _ = ctx
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH})
    client.patch("/api/translations/zh-Hans/0", headers=AUTH, json={"text": "早安"})

    undone = client.post("/api/translations/undo", headers=AUTH, json={"lang": "zh-Hans"}).json()
    assert undone["texts"] == ZH


def test_patch_rejects_missing_track_or_index(ctx):
    client, _ = ctx
    assert client.patch("/api/translations/ja/0", headers=AUTH, json={"text": "x"}).status_code == 404

    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH})
    assert client.patch("/api/translations/zh-Hans/9", headers=AUTH, json={"text": "x"}).status_code == 404


def test_patch_does_not_touch_other_languages(ctx):
    client, _ = ctx
    client.post("/api/translations", headers=AUTH, json={"lang": "zh-Hans", "texts": ZH})
    client.post("/api/translations", headers=AUTH, json={"lang": "en", "texts": ["a", "b", "c"]})
    client.patch("/api/translations/zh-Hans/0", headers=AUTH, json={"text": "早安"})

    items = {t["lang"]: t for t in client.get("/api/translations", headers=AUTH).json()["items"]}
    assert items["en"]["texts"] == ["a", "b", "c"]
    assert items["zh-Hans"]["texts"][0] == "早安"
