"""双引擎顺序协同的 job 编排：主稿、第二列、ensemble 升级、B 取消保留 A。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("torch")

pytestmark = pytest.mark.integration

from fastapi.testclient import TestClient  # noqa: E402

from core import audit  # noqa: E402
from core.pipeline import TranscribeResult  # noqa: E402
from core.subtitles import SubtitleCue  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402
from server.jobs import JobManager  # noqa: E402

TOKEN = "dual-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
MEDIA = "episode.mkv"


def _result(tmp_path: Path, cues: list[SubtitleCue], payload: str, *, interrupted=False):
    out = tmp_path / f"out-{time.time_ns()}.srt"
    out.write_text("1\n00:00:00,000 --> 00:00:01,000\nテスト\n", encoding="utf-8")
    return TranscribeResult(
        cues=cues,
        out_path=out,
        out_filename=out.name,
        elapsed=1.0,
        char_count=3,
        interrupted=interrupted,
        report_text="报告",
        audit_payload=payload,
        pending_qa=0,
        status_summary="ok",
        final_progress="ok",
        preview="",
        table=[],
    )


class _DualRunner:
    def __init__(
        self,
        tmp_path: Path,
        *,
        cancel_secondary: bool = False,
        fail_secondary: bool = False,
    ) -> None:
        self.tmp_path = tmp_path
        self.cancel_secondary = cancel_secondary
        self.fail_secondary = fail_secondary
        self.calls: list[str] = []
        self.requests: list[object] = []

    def __call__(self, request, *, on_progress, cancel_event, output_dir):
        self.calls.append(request.engine_key)
        self.requests.append(request)
        on_progress(0.5, "半程")
        if request.engine_key == "qwen":
            a_cue = SubtitleCue(0.0, 1.0, "主稿の台詞")
            items = audit.build_audit_items(
                [{"start": 2.0, "end": 3.0, "dur": 1.0, "reason": "empty-after-retry", "peak": 0.4}],
                {},
                [a_cue],
            )
            payload = audit.make_audit_payload(
                MEDIA, items, {}, 1, engine="qwen", phase="done"
            )
            return _result(self.tmp_path, [a_cue], payload)
        if self.fail_secondary:
            raise RuntimeError("副引擎加载失败")
        if self.cancel_secondary:
            cancel_event.cancel()
            return _result(
                self.tmp_path,
                [SubtitleCue(2.0, 3.2, "副稿だけの台詞")],
                "{}",
                interrupted=True,
            )
        return _result(
            self.tmp_path,
            [SubtitleCue(2.0, 3.2, "副稿だけの台詞")],
            "{}",
        )


@pytest.fixture()
def make_client(tmp_path: Path):
    def _factory(runner) -> TestClient:
        app = create_app(ServerConfig(token=TOKEN, output_dir=tmp_path))
        app.state.jobs = JobManager(tmp_path, runner=runner)
        return TestClient(app)

    return _factory


def _import_media(client: TestClient, tmp_path: Path) -> str:
    media = tmp_path / MEDIA
    media.write_bytes(b"x")
    resp = client.post("/api/media", headers=AUTH, json={"path": str(media)})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _wait(client: TestClient, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if snapshot["status"] in {"done", "error", "cancelled"}:
            return snapshot
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def _start_dual(client: TestClient, media_id: str, **extra) -> dict:
    payload = {
        "media_id": media_id,
        "kind": "dual",
        "engine": "qwen",
        "secondary_engine": "whisper",
        "apply": "replace",
        **extra,
    }
    resp = client.post("/api/jobs", headers=AUTH, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_dual_writes_main_alt_and_ensemble(make_client, tmp_path):
    runner = _DualRunner(tmp_path)
    client = make_client(runner)
    media_id = _import_media(client, tmp_path)

    job = _start_dual(client, media_id)
    snapshot = _wait(client, job["id"])
    assert snapshot["status"] == "done", snapshot
    assert runner.calls == ["qwen", "whisper"]
    result = snapshot["result"]
    assert result["dual"] is True
    assert result["primary_engine"] == "qwen"
    assert result["secondary_engine"] == "whisper"
    assert result["primary_cues"] == 1
    assert result["secondary_cues"] == 1
    assert result["ensemble_count"] == 1
    assert "新增 1 条补漏建议" in result["summary"]

    main = client.get("/api/cues", headers=AUTH).json()
    assert [cue["text"] for cue in main["cues"]] == ["主稿の台詞"]

    alt = client.get("/api/alt-review", headers=AUTH).json()
    assert alt["engine"] == "whisper"
    assert [cue["text"] for cue in alt["cues"]] == ["副稿だけの台詞"]

    report = client.get(f"/api/report?job_id={job['id']}", headers=AUTH).json()
    dual = next(section for section in report["sections"] if section["id"] == "dual")
    assert dual["headline"].startswith("主稿 1 条 / 第二列 1 条")
    assert [row["text"] for row in dual["items"]] == ["副稿だけの台詞"]
    assert report["quality"]["ensemble"] == 1

    qa = client.get("/api/qa", headers=AUTH).json()
    kinds = [item["kind"] for item in qa["items"]]
    assert kinds == ["ensemble"]
    assert qa["items"][0]["text"] == "副稿だけの台詞"
    assert qa["counts"]["by_kind"]["ensemble"] == 1
    assert "missed" not in kinds


def test_dual_secondary_cancel_keeps_main_and_skips_alt(make_client, tmp_path):
    runner = _DualRunner(tmp_path, cancel_secondary=True)
    client = make_client(runner)
    media_id = _import_media(client, tmp_path)

    job = _start_dual(client, media_id)
    snapshot = _wait(client, job["id"])
    assert snapshot["status"] == "done", snapshot
    assert snapshot["result"]["secondary_cancelled"] is True
    assert "主稿已完整保留" in snapshot["result"]["summary"]

    main = client.get("/api/cues", headers=AUTH).json()
    assert [cue["text"] for cue in main["cues"]] == ["主稿の台詞"]
    alt = client.get("/api/alt-review", headers=AUTH).json()
    assert alt.get("exists") is False or alt.get("cues") == []


def test_dual_rejects_low_memory(make_client, tmp_path, monkeypatch):
    from core import memory

    monkeypatch.setattr(memory, "dual_memory_error", lambda: "内存不足，请只跑主引擎")
    client = make_client(_DualRunner(tmp_path))
    media_id = _import_media(client, tmp_path)
    resp = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "kind": "dual",
            "engine": "qwen",
            "secondary_engine": "whisper",
        },
    )
    assert resp.status_code == 422
    assert "内存不足" in resp.text


def test_dual_rejects_same_engine_and_append(make_client, tmp_path):
    client = make_client(_DualRunner(tmp_path))
    media_id = _import_media(client, tmp_path)
    same = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "kind": "dual",
            "engine": "qwen",
            "secondary_engine": "qwen",
        },
    )
    assert same.status_code == 422
    appended = client.post(
        "/api/jobs",
        headers=AUTH,
        json={
            "media_id": media_id,
            "kind": "dual",
            "engine": "qwen",
            "secondary_engine": "whisper",
            "apply": "append",
        },
    )
    assert appended.status_code == 422


def test_dual_secondary_failure_keeps_main(make_client, tmp_path):
    runner = _DualRunner(tmp_path, fail_secondary=True)
    client = make_client(runner)
    media_id = _import_media(client, tmp_path)

    job = _start_dual(client, media_id)
    snapshot = _wait(client, job["id"])
    assert snapshot["status"] == "done", snapshot
    assert "副引擎加载失败" in snapshot["result"]["secondary_error"]
    assert snapshot["result"]["primary_cues"] == 1

    main = client.get("/api/cues", headers=AUTH).json()
    assert [cue["text"] for cue in main["cues"]] == ["主稿の台詞"]
