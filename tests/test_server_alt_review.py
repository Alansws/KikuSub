"""第二版本（双引擎复核）服务端：不覆盖主稿、按媒体恢复、删除、整列替换。

用替身 runner 驱动转写，不加载模型。第二版不进入 50 步历史；整列替换才压一步。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from core.pipeline import TranscribeResult  # noqa: E402
from core.subtitles import SubtitleCue  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402
from server.jobs import JobManager  # noqa: E402
from server.sessions import Session  # noqa: E402

TOKEN = "alt-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PRIMARY = [
    {"start": 0.0, "end": 1.0, "text": "おはよう"},
    {"start": 1.0, "end": 2.0, "text": "今日は雨だ"},
]
SECOND = [
    {"start": 0.0, "end": 1.0, "text": "おはよう"},
    {"start": 1.0, "end": 2.0, "text": "今日は飴だ"},
    {"start": 2.0, "end": 3.0, "text": "追加の一句"},
]


class _Runner:
    def __init__(self, cues: list[SubtitleCue], tmp_path: Path) -> None:
        self.cues = cues
        self.tmp_path = tmp_path
        self.last_request = None

    def __call__(self, request, *, on_progress, cancel_event, output_dir):
        self.last_request = request
        out = self.tmp_path / "episode.srt"
        out.write_text("", encoding="utf-8")
        on_progress(1.0, "完成")
        return TranscribeResult(
            cues=list(self.cues),
            out_path=out,
            out_filename=out.name,
            elapsed=0.1,
            char_count=1,
            interrupted=False,
            report_text="",
            audit_payload="{}",
            pending_qa=0,
            status_summary="",
            final_progress="",
            preview="",
            table=[],
        )


@pytest.fixture()
def make_client(tmp_path: Path):
    def _factory(cues: list[SubtitleCue] | None = None) -> TestClient:
        app = create_app(ServerConfig(token=TOKEN, output_dir=tmp_path))
        app.state.jobs = JobManager(tmp_path, runner=_Runner(cues or [], tmp_path))
        return TestClient(app)

    return _factory


def _new_media(client: TestClient, tmp_path: Path, name: str = "episode.mkv") -> str:
    media = tmp_path / name
    media.write_bytes(b"x")
    resp = client.post("/api/media", headers=AUTH, json={"path": str(media)})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _bind(client: TestClient, media_id: str) -> dict:
    resp = client.post("/api/session/bind", headers=AUTH, json={"media_id": media_id})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed_primary(client: TestClient) -> None:
    resp = client.post("/api/cues", headers=AUTH, json={"cues": PRIMARY})
    assert resp.status_code == 200, resp.text


def _run_alt_job(client: TestClient, media_id: str) -> dict:
    created = client.post(
        "/api/jobs",
        headers=AUTH,
        json={"media_id": media_id, "alt_review": True},
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]
    # 任务在 worker 线程里跑，创建后立刻 GET 可能还在 running；轮询到终态，
    # 否则全量套件在高负载下会偶发「status != done」的假红。
    deadline = time.time() + 10
    snap = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
    while snap["status"] not in {"done", "error", "cancelled"} and time.time() < deadline:
        time.sleep(0.02)
        snap = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
    return snap


def test_alt_review_does_not_touch_primary(make_client, tmp_path):
    client = make_client([SubtitleCue(0, 1, "おはよう"), SubtitleCue(1, 2, "今日は飴だ")])
    media_id = _new_media(client, tmp_path)
    _bind(client, media_id)
    _seed_primary(client)

    snapshot = _run_alt_job(client, media_id)
    assert snapshot["status"] == "done"
    assert snapshot["result"]["alt_review"] is True
    assert snapshot["result"]["alt_count"] == 2

    cues = client.get("/api/cues", headers=AUTH).json()
    assert [c["text"] for c in cues["cues"]] == ["おはよう", "今日は雨だ"]
    alt = client.get("/api/alt-review", headers=AUTH).json()
    assert alt["exists"] is True
    assert alt["count"] == 2
    assert [c["text"] for c in alt["cues"]] == ["おはよう", "今日は飴だ"]


def test_alt_review_is_restored_per_media(make_client, tmp_path):
    client = make_client([SubtitleCue(0, 1, "B 版")])
    first = _new_media(client, tmp_path, "first.mkv")
    second = _new_media(client, tmp_path, "second.mkv")
    _bind(client, first)
    _seed_primary(client)
    _run_alt_job(client, first)
    assert client.get("/api/alt-review", headers=AUTH).json()["exists"] is True

    # 切到另一部片：内存必须清空，不能串台
    _bind(client, second)
    assert client.get("/api/alt-review", headers=AUTH).json()["exists"] is False

    # 切回来：从边车自动恢复
    _bind(client, first)
    restored = client.get("/api/alt-review", headers=AUTH).json()
    assert restored["exists"] is True
    assert [c["text"] for c in restored["cues"]] == ["B 版"]


def test_delete_alt_review_clears_memory_and_disk(make_client, tmp_path):
    client = make_client([SubtitleCue(0, 1, "B 版")])
    media_id = _new_media(client, tmp_path)
    _bind(client, media_id)
    _seed_primary(client)
    _run_alt_job(client, media_id)

    removed = client.delete("/api/alt-review", headers=AUTH)
    assert removed.status_code == 200, removed.text
    assert removed.json()["removed"] is True
    assert client.get("/api/alt-review", headers=AUTH).json()["exists"] is False

    other = _new_media(client, tmp_path, "other.mkv")
    _bind(client, other)
    _bind(client, media_id)
    assert client.get("/api/alt-review", headers=AUTH).json()["exists"] is False


def test_replace_primary_is_single_undo(make_client, tmp_path):
    client = make_client([SubtitleCue(0, 1, "おはよう"), SubtitleCue(1, 2, "今日は飴だ")])
    media_id = _new_media(client, tmp_path)
    _bind(client, media_id)
    _seed_primary(client)
    _run_alt_job(client, media_id)
    before = client.get("/api/cues", headers=AUTH).json()
    history_before = len(client.get("/api/cues/history", headers=AUTH).json()["items"])

    replaced = client.post("/api/alt-review/replace-primary", headers=AUTH, json={})
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["replaced"] == 2
    assert replaced.json()["alt_cleared"] is True
    cues = client.get("/api/cues", headers=AUTH).json()
    assert [c["text"] for c in cues["cues"]] == ["おはよう", "今日は飴だ"]
    assert len(client.get("/api/cues/history", headers=AUTH).json()["items"]) == history_before + 1
    assert client.get("/api/alt-review", headers=AUTH).json()["exists"] is False

    undone = client.post("/api/cues/undo", headers=AUTH)
    assert undone.status_code == 200, undone.text
    restored = client.get("/api/cues", headers=AUTH).json()
    assert [c["text"] for c in restored["cues"]] == [c["text"] for c in before["cues"]]


def test_alt_review_diff_is_computed_live(make_client, tmp_path):
    client = make_client(
        [SubtitleCue(0, 1, "おはよう"), SubtitleCue(1, 2, "今日は飴だ"), SubtitleCue(2, 3, "追加")]
    )
    media_id = _new_media(client, tmp_path)
    _bind(client, media_id)
    _seed_primary(client)
    _run_alt_job(client, media_id)

    data = client.get("/api/alt-review?diff=1", headers=AUTH).json()
    assert data["stats"]["a_count"] == 2
    assert data["stats"]["b_count"] == 3
    assert data["stats"]["diff"] == 1
    assert data["stats"]["badge"] == 1
    assert data["stats"]["only_b"] == 1
    assert any(row["kind"] == "diff" and row["char_ops"] for row in data["rows"])


def test_dual_prompt_contains_both_scripts_and_range(make_client, tmp_path):
    client = make_client([SubtitleCue(0, 1, "おはよう"), SubtitleCue(1, 2, "今日は飴だ")])
    media_id = _new_media(client, tmp_path)
    _bind(client, media_id)
    _seed_primary(client)
    _run_alt_job(client, media_id)

    full = client.get("/api/ai/prompt?kind=polish&mode=dual", headers=AUTH)
    assert full.status_code == 200, full.text
    body = full.json()
    assert body["mode"] == "dual"
    assert body["category"] == "polish_dual"
    assert "おはよう" in body["prompt"]
    assert "今日は飴だ" in body["prompt"]  # B 的文本
    assert "SRT_A" not in body["prompt"]
    assert "SRT_B" not in body["prompt"]

    segment = client.get(
        "/api/ai/prompt?kind=polish&mode=dual&from_index=2&to_index=2", headers=AUTH
    )
    assert segment.status_code == 200, segment.text
    seg = segment.json()
    assert (seg["from"], seg["to"], seg["count"]) == (2, 2, 1)
    assert "第 2–2 条" in seg["prompt"]
    assert "今日は雨だ" in seg["prompt"]  # A 片段内的主稿
    assert "今日は飴だ" in seg["prompt"]  # B 的上下文（时间窗 ±2s）
    assert seg["prompt"].count("今日は雨だ") >= 1


def test_from_srt_can_fill_a_segment(make_client, tmp_path):
    client = make_client([SubtitleCue(0, 1, "おはよう"), SubtitleCue(1, 2, "今日は飴だ")])
    media_id = _new_media(client, tmp_path)
    _bind(client, media_id)
    _seed_primary(client)
    _run_alt_job(client, media_id)

    pasted = "1\n00:00:01,000 --> 00:00:02,000\n今日は飴だ\n"
    res = client.post(
        "/api/ai/from-srt",
        headers=AUTH,
        json={"kind": "polish", "mode": "dual", "text": pasted, "from_index": 2, "to_index": 2},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["from"], body["to"], body["expected"]) == (2, 2, 1)
    assert [it["after"] for it in body["proposal"]["items"]] == ["おはよう", "今日は飴だ"]
    assert body["proposal"]["source"]["digest_b"]


def test_apply_dual_proposal_rejects_changed_b_digest(make_client, tmp_path):
    client = make_client([SubtitleCue(0, 1, "おはよう"), SubtitleCue(1, 2, "今日は飴だ")])
    media_id = _new_media(client, tmp_path)
    _bind(client, media_id)
    _seed_primary(client)
    _run_alt_job(client, media_id)

    from core import ai_proposal

    alt = client.get("/api/alt-review", headers=AUTH).json()
    texts_a = [c["text"] for c in client.get("/api/cues", headers=AUTH).json()["cues"]]
    texts_b = [c["text"] for c in alt["cues"]]
    data = ai_proposal.build_proposal(
        kind="polish",
        src_lang="ja",
        texts=texts_a,
        texts_b=texts_b,
        items=[
            {"i": i + 1, "before": texts_a[i], "after": texts_b[i]}
            for i in range(len(texts_a))
        ],
    )
    data["source"]["digest_b"] = "0" * 64
    res = client.post("/api/ai/apply", headers=AUTH, json={"kind": "polish", "proposal": data})
    assert res.status_code == 409, res.text
    assert [c["text"] for c in client.get("/api/cues", headers=AUTH).json()["cues"]] == texts_a


def test_alt_review_stats_reflect_cue_edits(make_client, tmp_path):
    client = make_client(
        [SubtitleCue(0, 1, "おはよう"), SubtitleCue(1, 2, "今日は飴だ"), SubtitleCue(2, 3, "追加")]
    )
    media_id = _new_media(client, tmp_path)
    _bind(client, media_id)
    _seed_primary(client)
    _run_alt_job(client, media_id)
    assert client.get("/api/alt-review", headers=AUTH).json()["stats"]["diff"] == 1

    # 在核对台把这一句改成与 B 相同：复核页下一次读取必须实时反映，而不是用旧下标
    patched = client.patch("/api/cues/1", headers=AUTH, json={"text": "今日は飴だ"})
    assert patched.status_code == 200, patched.text
    stats = client.get("/api/alt-review", headers=AUTH).json()["stats"]
    assert stats["diff"] == 0
    assert stats["badge"] == 0


def test_dual_polish_allows_a83_b89(make_client, tmp_path):
    """B 比 A 多 6 条时：复核统计不合并行，双源提示词/粘贴解析也不要求条数相等。"""
    from core.subtitles import SubtitleCue as Cue, cues_to_srt

    a_cues = [Cue(i * 2.0, i * 2.0 + 1.4, f"A{i + 1}") for i in range(83)]
    b_cues = [Cue(i * 1.8, i * 1.8 + 1.2, f"A{i + 1}") for i in range(83)]
    b_cues[10] = Cue(18.0, 19.2, "B 改听")
    b_cues += [Cue(160.0 + i, 161.0 + i, f"B 额外{i + 1}") for i in range(6)]
    b_cues.sort(key=lambda cue: cue.start)

    client = make_client([])
    sid_headers = {**AUTH, "x-kikusub-session": "alt-83-89"}
    media = tmp_path / "long.mkv"
    media.write_bytes(b"x")
    media_id = client.post("/api/media", headers=sid_headers, json={"path": str(media)}).json()["id"]
    bind = client.post("/api/session/bind", headers=sid_headers, json={"media_id": media_id})
    assert bind.status_code == 200, bind.text
    seeded = client.post(
        "/api/cues",
        headers=sid_headers,
        json={"cues": [{"start": c.start, "end": c.end, "text": c.text} for c in a_cues]},
    )
    assert seeded.status_code == 200, seeded.text

    session = client.app.state.sessions.peek("alt-83-89")
    assert session is not None
    session.set_alt_review(
        engine="qwen",
        cues=b_cues,
        source={"kind": "transcription", "engine": "qwen"},
        media_path=str(media),
        output_dir=tmp_path,
    )

    review = client.get("/api/alt-review?diff=1", headers=sid_headers)
    assert review.status_code == 200, review.text
    stats = review.json()["stats"]
    assert (stats["a_count"], stats["b_count"]) == (83, 89)
    assert stats["a_count"] == stats["paired"] + stats["only_a"]
    assert stats["b_count"] == stats["paired"] + stats["only_b"]
    assert stats["paired"] + stats["only_b"] - (stats["paired"] + stats["only_a"]) == 6
    assert all(len(row["a_indices"]) <= 1 and len(row["b_indices"]) <= 1 for row in review.json()["rows"])

    prompt = client.get("/api/ai/prompt?kind=polish&mode=dual", headers=sid_headers)
    assert prompt.status_code == 200, prompt.text
    assert "B 改听" in prompt.json()["prompt"]

    pasted = cues_to_srt(a_cues)
    parsed = client.post(
        "/api/ai/from-srt",
        headers=sid_headers,
        json={"kind": "polish", "mode": "dual", "text": pasted},
    )
    assert parsed.status_code == 200, parsed.text
    body = parsed.json()
    assert len(body["proposal"]["items"]) == 83
    assert body["proposal"]["source"]["count_b"] == 89
    assert body["proposal"]["source"]["digest_b"]


def test_separate_vocals_full_film_is_not_rejected(make_client, tmp_path):
    """整片勾「人声分离」不再 422：2026-11-15 起由 pipeline 按 0..总时长分段分离。"""
    client = make_client([])
    media_id = _new_media(client, tmp_path)

    created = client.post(
        "/api/jobs",
        headers=AUTH,
        json={"media_id": media_id, "separate_vocals": True},
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]
    for _ in range(200):
        snapshot = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if snapshot["status"] in {"done", "error", "cancelled"}:
            break
        import time

        time.sleep(0.01)
    assert snapshot["status"] == "done", snapshot
    request = client.app.state.jobs._runner.last_request
    assert request.separate_vocals is True
    # P3 默认：分离人声只做 VAD，识别仍听原声。
    assert request.separate_mode == "vad_only"
    assert request.start_s is None and request.end_s is None
    # 服务层把 ffprobe 到的总时长带给 pipeline（1 字节假媒体探不到 → 0，pipeline 会报错让填区间）
    assert request.media_duration_s == 0.0


def test_separate_vocals_range_reaches_pipeline(make_client, tmp_path):
    client = make_client([])
    media_id = _new_media(client, tmp_path)

    created = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "start": 1.0,
            "end": 2.0,
            "separate_vocals": True,
        },
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]
    for _ in range(200):
        snapshot = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if snapshot["status"] in {"done", "error", "cancelled"}:
            break
        import time

        time.sleep(0.01)
    assert snapshot["status"] == "done", snapshot
    assert client.app.state.jobs._runner.last_request.separate_vocals is True
    assert client.app.state.jobs._runner.last_request.separate_mode == "vad_only"


def test_separate_mode_to_asr_reaches_pipeline(make_client, tmp_path):
    """高级档显式选择「分离人声后送识别」，服务层不得静默改回默认。"""
    client = make_client([])
    media_id = _new_media(client, tmp_path)

    created = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "start": 1.0,
            "end": 2.0,
            "separate_vocals": True,
            "separate_mode": "to_asr",
        },
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]
    for _ in range(200):
        snapshot = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if snapshot["status"] in {"done", "error", "cancelled"}:
            break
        import time

        time.sleep(0.01)
    assert snapshot["status"] == "done", snapshot
    assert client.app.state.jobs._runner.last_request.separate_mode == "to_asr"


def test_separate_mode_rejects_unknown_value_at_request_layer(make_client, tmp_path):
    client = make_client([])
    media_id = _new_media(client, tmp_path)
    resp = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "separate_vocals": True,
            "separate_mode": "both",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 导入第二版（与转写产出的 B 版同构）
# ---------------------------------------------------------------------------


def _write_srt(path: Path, cues: list[tuple[float, float, str]]) -> Path:
    blocks = []
    for index, (start, end, text) in enumerate(cues, start=1):
        def stamp(sec: float) -> str:
            hours = int(sec // 3600)
            minutes = int((sec % 3600) // 60)
            seconds = int(sec % 60)
            millis = int(round((sec - int(sec)) * 1000))
            return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

        blocks.append(f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}\n")
    path.write_text("\n".join(blocks) + "\n", encoding="utf-8")
    return path


def test_import_alt_review_from_srt_behaves_like_transcribed_b(make_client, tmp_path):
    client = make_client()
    media_id = _new_media(client, tmp_path)
    _bind(client, media_id)
    _seed_primary(client)
    srt = _write_srt(
        tmp_path / "episode.whisper.reviewed.srt",
        [(0.0, 1.0, "おはよう"), (1.0, 2.0, "今日は飴だ"), (2.0, 3.0, "追加の一句")],
    )

    imported = client.post("/api/alt-review/import", headers=AUTH, json={"path": str(srt)})
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["count"] == 3
    assert body["engine"] == "whisper"  # 历史标签也要识别
    assert body["warning"] == ""

    alt = client.get("/api/alt-review?diff=1", headers=AUTH).json()
    assert alt["exists"] is True
    assert alt["source"]["kind"] == "import"
    assert alt["source"]["name"] == srt.name
    assert alt["stats"]["a_count"] == 2
    assert alt["stats"]["b_count"] == 3
    assert alt["stats"]["only_b"] == 1
    # 核对台一个字都没动
    assert [c["text"] for c in client.get("/api/cues", headers=AUTH).json()["cues"]] == [
        "おはよう",
        "今日は雨だ",
    ]
    # 边车按媒体身份落盘（切媒体恢复由现有 sync 逻辑负责）
    assert list(tmp_path.glob("*.autosave_draft.alt.json"))

    # 下游链路把导入稿当普通 B 版用：双源润色与断句重排的提示词都能拿到 B 文本
    polish = client.get("/api/ai/prompt?kind=polish&mode=dual", headers=AUTH)
    assert polish.status_code == 200, polish.text
    assert "追加の一句" in polish.json()["prompt"]
    reshape = client.get("/api/ai/reshape/prompt?mode=dual", headers=AUTH)
    assert reshape.status_code == 200, reshape.text
    assert "追加の一句" in reshape.json()["prompt"]

    # 切媒体再切回：导入稿与转写稿一样从边车恢复（source.kind 仍是 import）
    other = _new_media(client, tmp_path, "other.mkv")
    _bind(client, other)
    assert client.get("/api/alt-review", headers=AUTH).json()["exists"] is False
    _bind(client, media_id)
    restored = client.get("/api/alt-review", headers=AUTH).json()
    assert restored["exists"] is True
    assert restored["source"]["kind"] == "import"
    assert restored["count"] == 3


def test_import_alt_review_keeps_import_source_after_replace_and_undo(make_client, tmp_path):
    client = make_client()
    media_id = _new_media(client, tmp_path)
    _bind(client, media_id)

    # A 先由一份导入稿建立来源（kind=import + 文件名）
    a_srt = _write_srt(
        tmp_path / "episode.AnimeWhisper.srt", [(0.0, 1.0, "おはよう"), (1.0, 2.0, "今日は雨だ")]
    )
    assert client.post("/api/cues/import", headers=AUTH, json={"path": str(a_srt)}).status_code == 200
    a_source = client.get("/api/cues", headers=AUTH).json()["review_source"]
    assert a_source["kind"] == "import"

    b_srt = _write_srt(
        tmp_path / "episode.Qwen3-ASR.reviewed.srt",
        [(0.0, 1.0, "おはよう"), (1.0, 2.0, "今日は飴だ")],
    )
    assert client.post("/api/alt-review/import", headers=AUTH, json={"path": str(b_srt)}).status_code == 200

    replaced = client.post("/api/alt-review/replace-primary", headers=AUTH, json={})
    assert replaced.status_code == 200, replaced.text
    snapshot = replaced.json()
    assert [c["text"] for c in snapshot["cues"]] == ["おはよう", "今日は飴だ"]
    # 覆盖后来源仍是「导入稿」，检查器不会去找一份不存在的转写报告
    assert snapshot["review_source"]["kind"] == "import"
    assert snapshot["review_source"]["name"] == b_srt.name

    undone = client.post("/api/cues/undo", headers=AUTH)
    assert undone.status_code == 200, undone.text
    restored = client.get("/api/cues", headers=AUTH).json()
    assert [c["text"] for c in restored["cues"]] == ["おはよう", "今日は雨だ"]
    # ⌘Z 必须把 source 一起退回 A 的来源（不能只回字幕）
    assert restored["review_source"]["kind"] == "import"
    assert restored["review_source"]["name"] == a_srt.name


def test_import_alt_review_rejections(make_client, tmp_path):
    client = make_client()
    # 没有绑定媒体：第二版按影片身份落盘，必须先有片
    no_media = tmp_path / "episode.whisper.srt"
    _write_srt(no_media, [(0.0, 1.0, "x")])
    assert (
        client.post("/api/alt-review/import", headers=AUTH, json={"path": str(no_media)}).status_code
        == 409
    )

    media_id = _new_media(client, tmp_path)
    _bind(client, media_id)
    missing = client.post(
        "/api/alt-review/import", headers=AUTH, json={"path": str(tmp_path / "nope.srt")}
    )
    assert missing.status_code == 404

    bilingual = _write_srt(tmp_path / "episode.bilingual.srt", [(0.0, 1.0, "x")])
    assert (
        client.post(
            "/api/alt-review/import", headers=AUTH, json={"path": str(bilingual)}
        ).status_code
        == 422
    )

    txt = tmp_path / "episode.txt"
    txt.write_text("x", encoding="utf-8")
    assert (
        client.post("/api/alt-review/import", headers=AUTH, json={"path": str(txt)}).status_code
        == 422
    )


def test_alt_review_range_only_replaces_inside_window(tmp_path):
    session = Session(id="alt-range")
    session.set_alt_review(
        engine="whisper",
        cues=[SubtitleCue(0.0, 1.0, "前"), SubtitleCue(10.0, 11.0, "後")],
        media_path="",
        output_dir=tmp_path,
    )
    session.set_alt_review(
        engine="whisper",
        cues=[SubtitleCue(5.0, 6.0, "区间内新稿")],
        media_path="",
        output_dir=tmp_path,
        replace_range=(4.0, 7.0),
    )
    assert [(cue.start, cue.text) for cue in session.alt_review.cues] == [
        (0.0, "前"),
        (5.0, "区间内新稿"),
        (10.0, "後"),
    ]


def test_alt_review_diff_ignores_punctuation_by_default(make_client, tmp_path):
    """默认 ignore_punct：只有标点 / 空白不同的行不算差异，徽标跟着降。

    2026-11-21 界面重构 Step 2：`?ignore_punct=0` 必须能还原严格比对
    （用户要能看见「到底哪里标点不同」）。
    """
    client = make_client([SubtitleCue(0, 1, "おはよう。"), SubtitleCue(1, 2, "今日は、雨だ")])
    media_id = _new_media(client, tmp_path)
    _bind(client, media_id)
    _seed_primary(client)
    assert _run_alt_job(client, media_id)["status"] == "done"

    loose = client.get("/api/alt-review?diff=1", headers=AUTH).json()
    assert loose["ignore_punct"] is True
    assert loose["stats"]["diff"] == 0
    assert loose["stats"]["badge"] == 0
    assert loose["stats"]["punct_only"] == 2
    assert [row["kind"] for row in loose["rows"]] == ["same", "same"]

    strict = client.get("/api/alt-review?diff=1&ignore_punct=0", headers=AUTH).json()
    assert strict["ignore_punct"] is False
    assert strict["stats"]["diff"] == 2
    assert strict["stats"]["badge"] == 2
    assert strict["stats"]["punct_only"] == 0
    assert [row["kind"] for row in strict["rows"]] == ["diff", "diff"]


def test_patch_cue_keeps_custom_history_label(make_client, tmp_path):
    """「采用 B 句」走 PATCH /api/cues/{i} 时，历史标签必须是它自己那句话。

    复核页不新增写接口（避免两套可编辑字幕），单句采纳就是这条带 label 的 PATCH；
    ⌘Z 的提示与历史列表直接读这个 label。
    """
    client = make_client([SubtitleCue(0, 1, "おはよう")])
    media_id = _new_media(client, tmp_path)
    _bind(client, media_id)
    _seed_primary(client)

    resp = client.patch(
        "/api/cues/0",
        headers=AUTH,
        json={"text": "おはよう、元気？", "label": "采用第二版：第 1 条"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["undo_label"] == "采用第二版：第 1 条"
    assert resp.json()["cues"][0]["text"] == "おはよう、元気？"

    # 历史按时间正序返回（工具栏再 reverse 显示）：最新一步在末尾。
    items = client.get("/api/cues/history", headers=AUTH).json()["items"]
    assert items[-1]["label"] == "采用第二版：第 1 条"

    # 不传 label 的普通编辑仍回落到旧文案（别的调用方零改动）
    plain = client.patch("/api/cues/0", headers=AUTH, json={"text": "おはよう"})
    assert plain.status_code == 200, plain.text
    assert plain.json()["undo_label"] == "修改第 1 条文本"
