"""断句重排：SRT 解析、体检、按索引区间覆盖、digest 守卫。

这条车道和润色提案的区别只有一个，但很关键：**条数与时间码都可以变**。
所以这里冻结的是：
- 只收标准 SRT，纯文本一律拒绝（不做「按原稿重算时间轴」）；
- 时间码用模型给的，体检只标注问题、不改数；
- 覆盖锚点是原稿的条目索引区间，不是模型的时间边界（分段时不能误伤邻段）；
- 解析之后原稿被改过，digest 对不上就必须拒绝应用。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import reshape
from core.subtitles import SubtitleCue
from server.sessions import Session, TranslationTrack

Cue = SubtitleCue

SRT = """1
00:00:01,000 --> 00:00:02,000
おはよう

2
00:00:02,000 --> 00:00:03,500
今日は雨だ
"""


# --------------------------------------------------------------------------- 解析


def test_parse_keeps_model_timestamps_exactly() -> None:
    cues = reshape.parse_draft(SRT)
    assert [(cue.start, cue.end) for cue in cues] == [(1.0, 2.0), (2.0, 3.5)]
    assert [cue.text for cue in cues] == ["おはよう", "今日は雨だ"]


def test_parse_strips_markdown_fence() -> None:
    assert len(reshape.parse_draft("```srt\n" + SRT + "\n```")) == 2


def test_parse_rejects_plain_text_without_timecode() -> None:
    with pytest.raises(reshape.ReshapeError) as excinfo:
        reshape.parse_draft("1\n你好\n\n2\n世界")
    assert "缺少时间码" in str(excinfo.value)


def test_parse_rejects_reversed_timecode() -> None:
    with pytest.raises(reshape.ReshapeError) as excinfo:
        reshape.parse_draft("1\n00:00:05,000 --> 00:00:01,000\n坏掉的一条\n")
    assert "结束时间早于开始时间" in str(excinfo.value)


def test_parse_rejects_empty() -> None:
    with pytest.raises(reshape.ReshapeError):
        reshape.parse_draft("   ")


# --------------------------------------------------------------------------- 体检


def test_diagnose_flags_overlap_length_and_range() -> None:
    block = [
        Cue(0.0, 1.0, "一句"),
        Cue(0.5, 2.0, "和二句重叠"),  # 与上一条重叠 0.5s
        Cue(2.5, 12.0, "长" * 30),  # 9.5s + 30 字，且结尾越出本段
        Cue(2.0, 2.4, "倒序"),  # 开始早于上一条
    ]
    diag = reshape.diagnose(block, before_texts=["一句"], range_start=0.0, range_end=5.0)
    assert diag.totals["overlap"] == 1
    assert diag.totals["out_of_order"] == 1
    assert diag.totals["too_long"] == 1  # 同一条的字数与时长合并成一条
    assert diag.totals["out_of_range"] == 1  # 第 3 条结尾 12s 超出本段 5s
    kinds = {issue.kind for issue in diag.issues}
    assert {"overlap", "out_of_order", "too_long"} <= kinds


def test_diagnose_does_not_block_style_problems() -> None:
    """体检只是标注：重叠、偏长都不该让 validate_block 抛错。"""
    block = [Cue(0.0, 1.0, "a"), Cue(0.5, 2.0, "b")]
    reshape.validate_block(block)  # 不抛


def test_diagnose_detects_identical_draft() -> None:
    block = [Cue(1.0, 2.0, "おはよう"), Cue(2.0, 3.0, "今日は雨だ")]
    diag = reshape.diagnose(block, before_texts=["おはよう", "今日は雨だ"])
    assert diag.identical is True
    assert any("模型没改" in note["text"] for note in reshape.summary_notes(diag))


def test_summary_notes_are_compact() -> None:
    diag = reshape.diagnose([Cue(1.0, 2.0, "a")], before_texts=["x", "y", "z"])
    texts = [note["text"] for note in reshape.summary_notes(diag)]
    assert texts[0] == "1 条（原 3 条，-2）"
    assert texts[1] == "00:01.00–00:02.00"
    assert not any("模型没改" in text for text in texts)


# --------------------------------------------------------------------------- 区间覆盖


def _seeded_session(count: int = 5) -> Session:
    session = Session(id="reshape-unit")
    session.replace_review([Cue(float(i), float(i + 1), f"S{i + 1}") for i in range(count)])
    return session


def test_replace_range_is_index_anchored() -> None:
    """第 2–3 条被换掉，前后两条原样保留——时间漂移不该吃掉邻段。"""
    session = _seeded_session()
    result = session.replace_range(
        2, 3, [Cue(9.0, 10.0, "N1"), Cue(10.0, 11.0, "N2"), Cue(11.0, 12.0, "N3")]
    )
    assert [cue.text for cue in session.review_cues] == ["S1", "N1", "N2", "N3", "S4", "S5"]
    assert result["replaced"] == 2
    assert result["inserted"] == 3
    assert result["count"] == 6


def test_replace_range_records_one_history_step() -> None:
    session = _seeded_session()
    before = len(session.history)
    session.replace_range(1, 5, [Cue(0.0, 1.0, "全新")])
    assert len(session.history) == before + 1
    assert session.history[-1].label.startswith("断句重排")
    assert len(session.review_cues) == 1


def test_replace_range_drops_translations_when_count_changes() -> None:
    session = _seeded_session()
    session.translations["zh-Hans"] = TranslationTrack(
        lang="zh-Hans", texts=["a", "b", "c", "d", "e"], base=["a", "b", "c", "d", "e"]
    )
    result = session.replace_range(1, 5, [Cue(0.0, 1.0, "只剩一条")])
    assert result["dropped_translations"] == ["zh-Hans"]
    assert "zh-Hans" not in session.translations


def test_replace_range_keeps_translation_when_count_matches() -> None:
    session = _seeded_session()
    session.translations["zh-Hans"] = TranslationTrack(
        lang="zh-Hans", texts=["a", "b", "c", "d", "e"], base=["a", "b", "c", "d", "e"]
    )
    result = session.replace_range(2, 3, [Cue(1.0, 1.5, "新2"), Cue(1.5, 2.0, "新3")])
    assert result["dropped_translations"] == []
    assert "zh-Hans" in session.translations


def test_replace_range_unchanged_does_not_add_history() -> None:
    session = _seeded_session()
    before = len(session.history)
    same = [Cue(1.0, 2.0, "S2"), Cue(2.0, 3.0, "S3")]
    result = session.replace_range(2, 3, same)
    assert result["changed"] is False
    assert len(session.history) == before


def test_replace_range_rejects_bad_span() -> None:
    session = _seeded_session()
    with pytest.raises(ValueError):
        session.replace_range(4, 2, [Cue(0.0, 1.0, "x")])


# --------------------------------------------------------------------------- HTTP


fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402
from server.sessions import AltReview  # noqa: E402

TOKEN = "reshape-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SID = "reshape-test"
HEADERS = {**AUTH, "x-kikusub-session": SID}

CUES = [
    {"start": 1.0, "end": 2.0, "text": "おはよう"},
    {"start": 2.0, "end": 3.0, "text": "今日は雨だ"},
    {"start": 3.0, "end": 4.0, "text": "傘を忘れた"},
]


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        ServerConfig(token=TOKEN, output_dir=tmp_path, settings_path=tmp_path / "settings.json")
    )
    http = TestClient(app)
    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    media_id = http.post("/api/media", headers=HEADERS, json={"path": str(media)}).json()["id"]
    http.post("/api/session/bind", headers=HEADERS, json={"media_id": media_id})
    seeded = http.post("/api/cues", headers=HEADERS, json={"cues": CUES})
    assert seeded.status_code == 200, seeded.text
    return http


def test_prompt_uses_reshape_category(client: TestClient) -> None:
    res = client.get("/api/ai/reshape/prompt?mode=single", headers=HEADERS)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["category"] == "reshape_single"
    assert data["count"] == 3
    assert "おはよう" in data["prompt"]
    # 断句重排的提示词不能再出现「严格保留序号与时间戳」这种 1:1 约束
    assert "严格保留原 SRT 的序号和时间戳" not in data["prompt"]
    assert "不要逐条对齐" in data["prompt"]


def test_prompt_dual_requires_alt_review(client: TestClient) -> None:
    res = client.get("/api/ai/reshape/prompt?mode=dual", headers=HEADERS)
    assert res.status_code == 409


def test_prompt_dual_includes_reference_b(client: TestClient) -> None:
    session = client.app.state.sessions.peek(SID)
    session.alt_review = AltReview(
        engine="firered",
        cues=[Cue(1.0, 2.0, "おはよう"), Cue(2.0, 3.0, "今日は飴だ")],
    )
    res = client.get("/api/ai/reshape/prompt?mode=dual", headers=HEADERS)
    assert res.status_code == 200, res.text
    assert "今日は飴だ" in res.json()["prompt"]


def test_from_text_returns_diagnostics_and_digest(client: TestClient) -> None:
    res = client.post(
        "/api/ai/reshape/from-text",
        headers=HEADERS,
        json={"text": SRT, "from_index": 1},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["format"] == "srt"
    assert data["diagnostics"]["count"] == 2
    assert len(data["digest"]) == 64
    assert data["range"]["from"] == 1 and data["range"]["to"] == 3
    assert data["notes"][0]["text"].startswith("2 条")


def test_from_text_rejects_plain_text(client: TestClient) -> None:
    res = client.post(
        "/api/ai/reshape/from-text", headers=HEADERS, json={"text": "1\n你好\n\n2\n世界"}
    )
    assert res.status_code == 422
    assert "缺少时间码" in res.json()["detail"]


def test_apply_replaces_whole_table(client: TestClient) -> None:
    parsed = client.post(
        "/api/ai/reshape/from-text", headers=HEADERS, json={"text": SRT, "from_index": 1}
    ).json()
    res = client.post(
        "/api/ai/reshape/apply",
        headers=HEADERS,
        json={
            "cues": parsed["cues"],
            "from_index": 1,
            "to_index": 3,
            "digest": parsed["digest"],
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["count"] == 2
    assert [cue["text"] for cue in data["cues"]] == ["おはよう", "今日は雨だ"]
    assert data["replace"]["replaced"] == 3
    assert data["can_undo"] is True
    assert "断句重排" in data["undo_label"]


def test_apply_rejects_stale_digest(client: TestClient) -> None:
    res = client.post(
        "/api/ai/reshape/apply",
        headers=HEADERS,
        json={
            "cues": [{"start": 0.0, "end": 1.0, "text": "x"}],
            "from_index": 1,
            "to_index": 3,
            "digest": "0" * 64,
        },
    )
    assert res.status_code == 409
    assert "重新粘贴" in res.json()["detail"]


def test_apply_only_touches_the_given_range(client: TestClient) -> None:
    parsed = client.post(
        "/api/ai/reshape/from-text",
        headers=HEADERS,
        json={"text": SRT, "from_index": 2, "to_index": 3},
    ).json()
    res = client.post(
        "/api/ai/reshape/apply",
        headers=HEADERS,
        json={
            "cues": parsed["cues"],
            "from_index": 2,
            "to_index": 3,
            "digest": parsed["digest"],
        },
    )
    assert res.status_code == 200, res.text
    texts = [cue["text"] for cue in res.json()["cues"]]
    assert texts[0] == "おはよう"  # 段外第一句没被动过
    assert texts[-1] == "今日は雨だ"
    assert len(texts) == 3
