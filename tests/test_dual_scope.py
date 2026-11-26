"""双引擎复核的**对照范围**（2026-11-26 真机报障回归）。

现场（v1.0.1）：第 1、2 章字幕已进核对台，第 3 章用「两版一起 + 替换选区」跑，
于是 A = 1–3 章 636 条（00:13–55:36）、B = 第 3 章 220 条（35:58–55:36）。
旧复核页按整片对齐：前两章 430 条全变成红色「仅 A」，统计与侧栏徽标失真，
而右上角还只有一个「整列覆盖」按钮——按下去前两章直接消失。

这里守三件事：

1. 纯函数 ``core.dual_scope`` 的范围解析 / 切片 / 替换窗口；
2. ``GET /api/alt-review`` 默认聚焦 B 所在章节，统计只算这一段；
3. ``POST /api/alt-review/replace-primary`` 的默认口径是**范围替换**，
   前两章一条不动；整列覆盖在 B 是局部稿时必须显式确认，否则 409。
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from core import dual_review, dual_scope  # noqa: E402
from core.subtitles import SubtitleCue  # noqa: E402

# 三章的时间轴（秒）：用户现场的 35:53.364–55:41.072 就是第三段。
CH1 = (13.0, 1_380.0)
CH2 = (1_380.0, 2_153.0)
CH3 = (2_153.364, 3_341.072)


def _cues(start: float, end: float, count: int, prefix: str) -> list[SubtitleCue]:
    """在 [start, end) 里均匀铺 count 条 1.5 秒的字幕。"""
    step = (end - start) / count
    return [
        SubtitleCue(round(start + i * step, 3), round(start + i * step + 1.5, 3), f"{prefix}{i}")
        for i in range(count)
    ]


def _same_timeline(cues: list[SubtitleCue], every: int = 7) -> list[SubtitleCue]:
    """同一段音频的**另一个引擎稿**：时间轴差一丝、断句基本一样、每 7 行一处听写分歧。

    真实双引擎就是这样：同一句的入出点差 0.1–0.5s，大部分行一致、少数专名听错。
    （时间轴完全错开 5 秒那种稿子不是双引擎，是两次不同的转录。）
    """
    out: list[SubtitleCue] = []
    for index, cue in enumerate(cues):
        base = cue.text.replace("a3-", "b3-", 1)
        text = base if index % every else f"{base}-聞き違い"
        out.append(
            SubtitleCue(
                round(cue.start + 0.12, 3),
                round(cue.end + 0.03, 3),
                text,
            )
        )
    return out


def _chapters() -> list[dict]:
    return [
        {"id": "ch-1", "title": "章节一", "start": CH1[0], "end": CH1[1]},
        {"id": "ch-2", "title": "章节二", "start": CH2[0], "end": CH2[1]},
        {"id": "ch-3", "title": "章节三", "start": CH3[0], "end": CH3[1]},
    ]


def _scene() -> tuple[list[SubtitleCue], list[SubtitleCue]]:
    """用户现场：A 累积 1–3 章 636 条，B 只有第 3 章的 220 条（35:58–55:36）。

    章节三铺 223 条，B 去掉首 2 条与末 1 条 → 220 条，与真机的 220 条同形。
    """
    ch3 = _cues(CH3[0], CH3[1], 223, "a3-")
    a = _cues(CH1[0], CH1[1], 200, "a1-") + _cues(CH2[0], CH2[1], 213, "a2-") + ch3
    b = _same_timeline(ch3[2:-1])
    return (a, b)


# --------------------------------------------------------------------------- 纯函数


def test_partial_b_detected_for_chapter_only_run():
    a, b = _scene()
    assert dual_scope.is_partial_b(a, b) is True
    # B 就是整片第二版：不算局部
    assert dual_scope.is_partial_b(a, _cues(CH1[0], CH3[1], 600, "full-")) is False


def test_default_focus_snaps_to_the_chapter_that_contains_b():
    a, b = _scene()
    focus = dual_scope.default_focus(a, b, _chapters())
    assert focus["key"] == "ch:ch-3"
    assert focus["label"] == "章节三"
    # 章节起点覆盖了 B 的 padding，但不会越过章节终点
    assert focus["start"] <= CH3[0]
    assert focus["end"] >= b[-1].end - 0.001


def test_default_focus_falls_back_to_b_span_without_chapters():
    a, b = _scene()
    focus = dual_scope.default_focus(a, b, [])
    assert focus["key"] == "b"
    assert focus["kind"] == "range"
    assert abs(focus["start"] - b[0].start) < 0.01
    assert abs(focus["end"] - b[-1].end) < 0.01


def test_default_focus_is_whole_film_when_b_covers_everything():
    a = _cues(CH1[0], CH1[1], 50, "a-")
    b = _cues(CH1[0], CH1[1], 50, "b-")
    focus = dual_scope.default_focus(a, b, _chapters())
    assert focus["key"] == "all"


def test_scope_options_list_b_then_chapters_then_all():
    a, b = _scene()
    options = dual_scope.scope_options(a, b, _chapters())
    assert options[0]["key"] == "ch:ch-3"
    assert options[0]["b_count"] == 220
    assert options[-1]["key"] == "all"
    keys = [opt["key"] for opt in options]
    assert keys.count("ch:ch-3") == 1, "B 所在章节不能重复一条"
    assert {"ch:ch-1", "ch:ch-2"} <= set(keys)
    # 全片口径：636 vs 220（这正是用户看到的两个数字）
    assert options[-1]["a_count"] == 636
    assert options[-1]["b_count"] == 220
    # 章节三区间：223 vs 220 —— 只有 3 条是真的只在 A（B 少听了首尾各一两条），
    # 不再是整片口径里那 416 条假差异。
    assert options[0]["a_count"] == 223


def test_badge_counts_only_the_focused_window():
    """侧栏徽标不许拿范围外的章节凑差异（用户看到 430 个假差异的根因）。"""
    a, b = _scene()
    chapter_scope = dual_scope.resolve_focus("ch:ch-3", a, b, _chapters())
    a_win, a_map = dual_scope.cues_in_window(a, chapter_scope["start"], chapter_scope["end"])
    b_win, b_map = dual_scope.cues_in_window(b, chapter_scope["start"], chapter_scope["end"])
    focused = dual_review.build_review(a_win, b_win, a_map=a_map, b_map=b_map)
    whole = dual_review.build_review(a, b)

    assert focused["stats"]["a_count"] == 223
    assert focused["stats"]["b_count"] == 220
    # 章节三区间里只剩 3 条真的「仅 A」（B 少听了首尾），不再是整片那 416 条假差异
    assert focused["stats"]["only_a"] <= 3
    assert whole["stats"]["only_a"] == 416, "整片口径下才有那 416 条假差异"
    # 徽标（文本差异数）在范围口径下只数这一段的真分歧
    assert whole["stats"]["badge"] == focused["stats"]["badge"]
    assert focused["stats"]["same"] + focused["stats"]["diff"] + focused["stats"]["only_a"] == 223


def test_focused_rows_point_back_into_the_full_table():
    """「采用 B」必须写回全片第 N 条，不能是切片里的第 n 条。"""
    a, b = _scene()
    focus = dual_scope.resolve_focus("ch:ch-3", a, b, _chapters())
    a_win, a_map = dual_scope.cues_in_window(a, focus["start"], focus["end"])
    b_win, b_map = dual_scope.cues_in_window(b, focus["start"], focus["end"])
    review = dual_review.build_review(a_win, b_win, a_map=a_map, b_map=b_map)
    indices = [row["a_indices"][0] for row in review["rows"] if row["a_indices"]]
    assert indices, "范围里应该有 A 行"
    assert min(indices) >= 413, f"章节三的第一条在全片里是第 414 条，实际 {min(indices)}"
    assert max(indices) < len(a)
    # 下标能回指到同一句文本
    for row in review["rows"][:20]:
        if row["a_indices"]:
            assert a[row["a_indices"][0]].text == row["a_text"]


def test_hidden_counts_explain_the_scoped_header():
    a, b = _scene()
    focus = dual_scope.resolve_focus("ch:ch-3", a, b, _chapters())
    hidden_a, hidden_b = dual_scope.hidden_counts(a, b, focus)
    assert hidden_a == 413, "章节一 200 + 章节二 213，全部隐去"
    assert hidden_b == 0


def test_replace_window_keeps_the_other_chapters():
    a, b = _scene()
    merged, removed, inserted = dual_scope.replace_window(
        a, b, CH3[0] - 1.0, CH3[1] + 1.0
    )
    assert inserted == 220
    assert removed == 223
    # 前两章 413 条原样保留，且顺序不变
    assert [cue.text for cue in merged[:413]] == [cue.text for cue in a[:413]]
    assert len(merged) == 413 + 220
    assert not any(cue.text.startswith("a3-") for cue in merged), "章节三的旧 A 必须被换掉"


def test_would_trim_counts_what_a_whole_table_overwrite_would_lose():
    a, b = _scene()
    # 416 = 前两章 413 条 + 章节三里 B 覆盖不到的那 3 条；
    # 它与「章节窗口隐去 413 条」是两个口径：前者是**真会丢掉**的条数。
    assert dual_scope.would_trim(a, b) == 416
    assert dual_scope.would_trim(a, _cues(CH1[0], CH3[1], 600, "full-")) == 0


def test_interval_chapters_ignore_markers_without_span():
    marks = [
        {"id": "ch-1", "title": "章节一", "start": 10.0, "end": 20.0},
        {"id": "point-1", "title": "发射点", "start": 15.0, "end": None},
        {"id": "zero", "title": "零长度", "start": 30.0, "end": 30.0},
    ]
    out = dual_scope.interval_chapters(marks)
    assert [item["id"] for item in out] == ["ch-1"]


def test_resolve_focus_unknown_key_falls_back_to_default():
    a, b = _scene()
    focus = dual_scope.resolve_focus("ch:nope", a, b, _chapters())
    assert focus["key"] == "ch:ch-3"


# --------------------------------------------------------------------------- HTTP


TOKEN = "scope-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.config import ServerConfig
    from server.jobs import JobManager

    app = create_app(ServerConfig(token=TOKEN, output_dir=tmp_path))
    app.state.jobs = JobManager(tmp_path, runner=lambda *a, **k: None)
    return TestClient(app)


def _open_media(client, tmp_path) -> str:
    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    resp = client.post("/api/media", headers=AUTH, json={"path": str(media)})
    assert resp.status_code == 200, resp.text
    media_id = resp.json()["id"]
    bound = client.post("/api/session/bind", headers=AUTH, json={"media_id": media_id})
    assert bound.status_code == 200, bound.text
    return media_id


def _import_b(client, tmp_path, b_cues: list[SubtitleCue]) -> None:
    """走真实导入链路把 B 写进第二列（不经模型）。"""
    from core.subtitles import cues_to_srt

    path = tmp_path / "chapter3.srt"
    path.write_text(cues_to_srt(b_cues), encoding="utf-8")
    resp = client.post("/api/alt-review/import", headers=AUTH, json={"path": str(path)})
    assert resp.status_code == 200, resp.text


def test_api_default_scope_focuses_the_partial_b(client, tmp_path):
    a, b = _scene()
    _open_media(client, tmp_path)
    assert client.post("/api/cues", headers=AUTH, json={"cues": [c.__dict__ for c in a]}).status_code == 200
    chapters = client.post(
        "/api/chapters",
        headers=AUTH,
        json={"marks": _chapters(), "label": "开发种子：章节"},
    )
    assert chapters.status_code == 200, chapters.text
    _import_b(client, tmp_path, b)

    payload = client.get("/api/alt-review?diff=1", headers=AUTH).json()
    scope = payload["scope"]
    assert scope["auto"] is True
    assert scope["partial_b"] is True
    assert scope["chapter_title"] == "章节三"
    assert scope["hidden_a"] == 413
    assert payload["stats"]["only_a"] <= 3, "默认口径不该再报「仅 A 416 条」"
    assert payload["total_a"] == 636
    assert payload["total_b"] == 220
    # 行仍然是范围里的 220 对 220
    assert len(payload["rows"]) >= 220

    # 显式切到全片：此时才该看到那 416 条「仅 A」
    whole = client.get("/api/alt-review?diff=1&scope=all", headers=AUTH).json()
    assert whole["scope"]["key"] == "all"
    assert whole["stats"]["only_a"] == 416
    assert whole["stats"]["a_count"] == 636


def test_api_scope_chapter_key_selects_explicit_chapter(client, tmp_path):
    a, b = _scene()
    _open_media(client, tmp_path)
    client.post("/api/cues", headers=AUTH, json={"cues": [c.__dict__ for c in a]})
    client.post("/api/chapters", headers=AUTH, json={"marks": _chapters(), "label": "章节"})
    _import_b(client, tmp_path, b)

    payload = client.get("/api/alt-review?scope=ch:ch-2", headers=AUTH).json()
    assert payload["scope"]["key"] == "ch:ch-2"
    assert payload["scope"]["label"] == "章节二"
    assert payload["stats"]["a_count"] == 213
    assert payload["stats"]["b_count"] == 0
    assert payload["stats"]["only_a"] == 213


def test_replace_range_keeps_the_first_two_chapters(client, tmp_path):
    """核心回归：范围替换只换章节三，前两章 416 条一条不少，且只压一步历史。"""
    a, b = _scene()
    _open_media(client, tmp_path)
    client.post("/api/cues", headers=AUTH, json={"cues": [c.__dict__ for c in a]})
    client.post("/api/chapters", headers=AUTH, json={"marks": _chapters(), "label": "章节"})
    _import_b(client, tmp_path, b)

    history_before = len(client.get("/api/cues/history", headers=AUTH).json()["items"])
    scope = client.get("/api/alt-review", headers=AUTH).json()["scope"]
    assert scope["replace_mode"] == "range"

    replaced = client.post(
        "/api/alt-review/replace-primary",
        headers=AUTH,
        json={"mode": "range", "start": scope["start"], "end": scope["end"]},
    )
    assert replaced.status_code == 200, replaced.text
    body = replaced.json()
    assert body["mode"] == "range"
    assert body["removed"] == 223
    assert body["replaced"] == 220
    assert body["alt_cleared"] is False, "范围替换不该把 B 一起丢掉"

    cues = client.get("/api/cues", headers=AUTH).json()["cues"]
    assert len(cues) == 633, "前两章必须原样保留，总数仍是 413 + 220"
    assert [c["text"] for c in cues[:413]] == [c.__dict__["text"] for c in a[:413]]
    assert not any(c["text"].startswith("a3-") for c in cues)
    assert sum(1 for c in cues if c["text"].startswith("b3-")) == 220

    history_after = len(client.get("/api/cues/history", headers=AUTH).json()["items"])
    assert history_after == history_before + 1, "一步统一历史"

    # ⌘Z 一次整批退回
    assert client.post("/api/cues/undo", headers=AUTH).status_code == 200
    restored = client.get("/api/cues", headers=AUTH).json()["cues"]
    assert [c["text"] for c in restored] == [c.__dict__["text"] for c in a]


def test_whole_table_overwrite_of_partial_b_is_refused(client, tmp_path):
    """最危险的那一步：B 是局部稿时整列覆盖必须 409，除非显式确认。"""
    a, b = _scene()
    _open_media(client, tmp_path)
    client.post("/api/cues", headers=AUTH, json={"cues": [c.__dict__ for c in a]})
    client.post("/api/chapters", headers=AUTH, json={"marks": _chapters(), "label": "章节"})
    _import_b(client, tmp_path, b)

    blocked = client.post(
        "/api/alt-review/replace-primary", headers=AUTH, json={"mode": "all"}
    )
    assert blocked.status_code == 409, blocked.text
    assert "416" in blocked.text
    assert len(client.get("/api/cues", headers=AUTH).json()["cues"]) == 636

    # 老客户端（只发 {}）同样被拦：auto → all，但闸门还在
    legacy = client.post("/api/alt-review/replace-primary", headers=AUTH, json={})
    assert legacy.status_code == 409, legacy.text

    confirmed = client.post(
        "/api/alt-review/replace-primary",
        headers=AUTH,
        json={"mode": "all", "confirm_trim": True, "clear_alt": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["removed"] == 416
    assert len(client.get("/api/cues", headers=AUTH).json()["cues"]) == 220


def test_whole_table_overwrite_is_fine_for_a_full_length_b(client, tmp_path):
    """B 盖住整片时整列覆盖是正常口径，不该被闸门误拦。"""
    a = _cues(CH1[0], CH1[1], 50, "a-")
    b = _cues(CH1[0], CH1[1], 50, "b-")
    _open_media(client, tmp_path)
    client.post("/api/cues", headers=AUTH, json={"cues": [c.__dict__ for c in a]})
    _import_b(client, tmp_path, b)

    payload = client.get("/api/alt-review", headers=AUTH).json()
    assert payload["scope"]["key"] == "all"
    assert payload["scope"]["would_trim"] == 0
    assert payload["scope"]["replace_mode"] == "all"

    ok = client.post("/api/alt-review/replace-primary", headers=AUTH, json={"mode": "all"})
    assert ok.status_code == 200, ok.text
    assert [c["text"] for c in ok.json()["cues"]] == [c.__dict__["text"] for c in b]
