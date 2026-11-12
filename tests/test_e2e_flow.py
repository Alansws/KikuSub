"""端到端：导入媒体 → 起转写 → 改一条 → 撤销 → 导出 SRT → 重新导入。

为什么单独一份：其余用例都按"层"切（`core/` 的纯计算、`server/` 的单个 handler），
每层单独绿并不等于连起来能跑通——接口字段改名、会话写回顺序、导出目录解析这类问题，
只有在**一整条链**上才会露出来。这就是方法论里"最兜底的业务连通性"那一层。

口径：
- 只走**公开 HTTP 接口**（`TestClient`），不 import 内部函数，避免测成"实现镜像"；
- 用替身引擎（不加载模型，整套约 0.1 秒），所以能进日常 `pytest -q` 而不拖慢回环；
- 断言只盯用户能感知的事实：字幕条数、文本、时间码、导出文件内容、撤销后的复原。

与 `tests/test_server_jobs.py` 的分工：那边测任务生命周期与 WS 帧，这边测"人都以为能跑通"的
那条主链路。两者共用一个替身引擎的写法，但不共享 fixture——测试文件保持自包含，
改一个文件不会意外影响另一个。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("torch")

from fastapi.testclient import TestClient  # noqa: E402

from core.pipeline import TranscribeResult  # noqa: E402
from core.subtitles import format_srt_timestamp  # noqa: E402
from core.transcribe import SubtitleCue  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402
from server.jobs import JobManager  # noqa: E402

TOKEN = "e2e-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

# 三条足够覆盖"改中间一条、前后两条不动"；小数点刻意不是整秒，防止时间码被取整。
CUES = [
    SubtitleCue(0.0, 1.5, "おはよう"),
    SubtitleCue(2.0, 3.5, "またね"),
    SubtitleCue(4.0, 5.25, "テストです"),
]


class _FakeEngine:
    """替身引擎：发一帧进度就返回固定字幕，并写一份 SRT（真实引擎也这么做）。"""

    def __call__(self, request, *, on_progress, cancel_event, output_dir):
        on_progress(0.5, "转写中")
        out = Path(output_dir) / "episode.srt"
        out.parent.mkdir(parents=True, exist_ok=True)
        from core.subtitles import cues_to_srt

        out.write_text(cues_to_srt(CUES), encoding="utf-8")
        return TranscribeResult(
            cues=list(CUES),
            out_path=out,
            out_filename=out.name,
            elapsed=0.3,
            char_count=sum(len(c.text) for c in CUES),
            interrupted=False,
            report_text="报告",
            audit_payload="{}",
            pending_qa=0,
            status_summary="✅ 转写完成",
            final_progress="✅ 转录完成！",
            preview="",
            table=[[i + 1, "", "", c.text] for i, c in enumerate(CUES)],
        )


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    config = ServerConfig(
        token=TOKEN,
        output_dir=tmp_path,
        settings_path=tmp_path / "settings.json",
    )
    app = create_app(config)
    app.state.jobs = JobManager(tmp_path, runner=_FakeEngine())
    return TestClient(app)


def _import_media(client: TestClient, tmp_path: Path) -> str:
    media = tmp_path / "episode.mkv"
    media.write_bytes(b"not-a-real-video")
    resp = client.post("/api/media", headers=AUTH, json={"path": str(media)})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _run_transcription(client: TestClient, tmp_path: Path) -> None:
    media_id = _import_media(client, tmp_path)
    created = client.post("/api/jobs", headers=AUTH, json={"media_id": media_id})
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    deadline = time.time() + 10
    while time.time() < deadline:
        snapshot = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
        if snapshot["status"] in {"done", "error"}:
            break
        time.sleep(0.02)
    assert snapshot["status"] == "done", snapshot


def _cues(client: TestClient) -> list[dict]:
    resp = client.get("/api/cues", headers=AUTH)
    assert resp.status_code == 200, resp.text
    return resp.json()["cues"]


def _spans(cues: list[dict]) -> list[tuple[float, float]]:
    return [(c["start"], c["end"]) for c in cues]


EXPECTED_SPANS = [(c.start, c.end) for c in CUES]


def test_full_flow_transcribe_edit_undo_export_and_reimport(client, tmp_path):
    """一条链走完：转写 → 改一条 → ⌘Z 复原 → 再改 → 导出 → 重新导入仍一致。"""

    # ① 导入媒体 + 转写：核对台拿到 3 条
    _run_transcription(client, tmp_path)
    cues = _cues(client)
    assert [c["text"] for c in cues] == [c.text for c in CUES]
    assert _spans(cues) == EXPECTED_SPANS

    # ② 改中间一条：只动文本，时间码一分不动
    patched = client.patch("/api/cues/1", headers=AUTH, json={"text": "またね！"})
    assert patched.status_code == 200, patched.text
    cues = _cues(client)
    assert cues[1]["text"] == "またね！"
    assert _spans(cues) == EXPECTED_SPANS, "改文本不许动时间码"

    # ③ 一次撤销退回原状（A4：应用/编辑 = 一次历史）
    undone = client.post("/api/cues/undo", headers=AUTH)
    assert undone.status_code == 200, undone.text
    cues = _cues(client)
    assert [c["text"] for c in cues] == [c.text for c in CUES], "撤销必须一条退回改之前的文本"

    # ④ 再改一次并导出 SRT
    assert client.patch("/api/cues/1", headers=AUTH, json={"text": "またね！"}).status_code == 200
    exported = client.post(
        "/api/cues/export",
        headers=AUTH,
        json={"format": "SRT", "track": "source"},
    )
    assert exported.status_code == 200, exported.text
    body = exported.json()
    out_path = Path(body["path"])
    assert out_path.is_file(), f"导出接口说成功但文件不在：{out_path}"
    assert body["count"] == len(CUES)

    text = out_path.read_text(encoding="utf-8")
    # 时间码必须是 cue 的精确值（不是取整、不是重排）——这是"时间轴绝对不变"的对外证据
    second_line = f"{format_srt_timestamp(2.0)} --> {format_srt_timestamp(3.5)}"
    assert second_line in text, text
    assert "またね！" in text
    assert "おはよう" in text, "其余两条也必须保留"

    # ⑤ 导出的文件重新导入：条数、文本、时间码全部一致（剪贴板闭环）
    imported = client.post("/api/cues/import", headers=AUTH, json={"path": str(out_path)})
    assert imported.status_code == 200, imported.text
    again = _cues(client)
    assert [c["text"] for c in again] == [cues[0]["text"], "またね！", cues[2]["text"]]
    assert _spans(again) == _spans(cues), "重新导入后时间码必须逐条相等"


def test_export_without_translation_is_rejected(client, tmp_path):
    """导出译文但还没有译文轨时必须 409——而不是悄悄导出一份空文件。

    这条是"业务连通性"的反面：主链路能跑通还不够，**错误路径也不能把坏数据写出去**。
    """
    _run_transcription(client, tmp_path)

    resp = client.post(
        "/api/cues/export",
        headers=AUTH,
        json={"format": "SRT", "track": "target", "lang": "zh-Hans"},
    )
    assert resp.status_code == 409, resp.text
    assert "译文" in resp.json()["detail"]
