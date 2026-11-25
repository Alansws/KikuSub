"""用户报障路径回归：主稿存在时用 Anime Whisper 转录第二版（2026-11-26 真机事故）。

真机操作顺序：先用 Qwen3-ASR 整片转出 246 条主稿 → 转写页把产出切到
「第二版（对照）」→ 引擎选 Anime Whisper → 生成第二版 → 转录跑完即将落盘时
底部报 `! 转写失败 'NoneType' object is not callable`。

根因不在第二版逻辑，而在 ASR 空闲卸载：`kikusub-asr-idle` 线程按「最后一次
touch」判空闲（默认 180s），而整片任务运行期间没有任何 touch，于是它把**正在
解码的** Anime Whisper 权重卸了，`core/transcribe.py:1708` 的 `self._pipe(...)`
变成 `'NoneType' object is not callable`。租约（`EngineIdleReleaser.hold`）的
单元级回归见 `tests/test_engine_idle_lease.py`；本文件钉住服务端完整路径。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("torch")

pytestmark = pytest.mark.integration

from fastapi.testclient import TestClient  # noqa: E402

from core.engine_idle import EngineIdleReleaser  # noqa: E402
from core.pipeline import TranscribeResult  # noqa: E402
from core.transcribe import SubtitleCue  # noqa: E402
from server.app import create_app  # noqa: E402
from server.config import ServerConfig  # noqa: E402
from server.jobs import JobManager  # noqa: E402

TOKEN = "idle-lease-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PRIMARY = [
    {"start": 0.0, "end": 1.0, "text": "おはよう"},
    {"start": 1.0, "end": 2.0, "text": "今日は雨だ"},
]
SECOND = [
    {"start": 0.0, "end": 1.0, "text": "おはよう"},
    {"start": 1.0, "end": 2.0, "text": "今日は飴だ"},
]


class _FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakeWhisper:
    """模仿 `AnimeWhisperEngine`：`release()` 把 `_pipe` 置 None，之后调用即崩。"""

    def __init__(self) -> None:
        self._pipe = self.decode
        self.released = 0
        self.decodes = 0

    def decode(self, *_a, **_k) -> str:
        self.decodes += 1
        return f"第{self.decodes}段"

    def release(self) -> None:
        self._pipe = None
        self.released += 1

    def transcribe(self) -> str:
        # 与 core/transcribe.py:1708 同一形态：None 被当函数调用。
        return self._pipe({"array": b"", "sampling_rate": 16000})


class _AltRunner:
    """模拟整片 Anime Whisper 第二版：一段一段解码，段间时间在流逝。

    每次进度推进都顺手调一次 `jobs.idle.sweep()`——这正是 `kikusub-asr-idle`
    后台线程在做的事，只是把「等 5 秒」换成「直接喊巡检」，让复现确定而非偶然。
    """

    def __init__(self, idle, clock: _FakeClock, engine: _FakeWhisper, tmp_path: Path):
        self.idle = idle
        self.clock = clock
        self.engine = engine
        self.tmp_path = tmp_path
        self.sweeps: list[list[str]] = []

    def __call__(self, request, *, on_progress, cancel_event, output_dir):
        assert request.alt_review is True  # 第二版路径，不是覆盖主稿
        for index in range(1, 5):
            self.clock.advance(70)  # 4 段共 280s，跨过 180s 空闲阈值
            self.sweeps.append(self.idle.sweep())
            self.engine.transcribe()  # 权重若被卸，这里抛 NoneType
            on_progress(index / 4, f"第 {index}/4 段")
        out = self.tmp_path / "episode.alt.srt"
        out.write_text("", encoding="utf-8")
        return TranscribeResult(
            cues=[SubtitleCue(item["start"], item["end"], item["text"]) for item in SECOND],
            out_path=out,
            out_filename=out.name,
            elapsed=1.0,
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


def test_alt_review_second_pass_with_primary_present(tmp_path: Path):
    clock = _FakeClock()
    engine = _FakeWhisper()
    released: list[str] = []

    def release(key: str) -> bool:
        # 真实现里 release_engine("qwen") 卸的是 Qwen 的权重，不是 Whisper 的。
        released.append(key)
        if key == "whisper":
            engine.release()
        return True

    idle = EngineIdleReleaser(
        idle_seconds=180.0, clock=clock, release=release, autostart=False
    )
    runner = _AltRunner(idle, clock, engine, tmp_path)

    app = create_app(ServerConfig(token=TOKEN, output_dir=tmp_path))
    app.state.jobs = JobManager(tmp_path, runner=runner, idle_releaser=idle)
    client = TestClient(app)

    media = tmp_path / "episode.mkv"
    media.write_bytes(b"x")
    media_id = client.post(
        "/api/media", headers=AUTH, json={"path": str(media)}
    ).json()["id"]
    client.post("/api/session/bind", headers=AUTH, json={"media_id": media_id})
    seeded = client.post("/api/cues", headers=AUTH, json={"cues": PRIMARY})
    assert seeded.status_code == 200, seeded.text

    # 真机现场：主稿引擎（qwen）在这之前被「用过」，正在空闲表里；
    # 而 whisper 之所以会被巡检盯上，是因为**更早的一次「另一引擎复核」**结束时
    # touch 了它（日志 00:33:07），从那以后整片任务期间再没有 touch 落地。
    idle.touch("qwen")
    idle.touch("whisper")

    created = client.post(
        "/api/jobs",
        headers=AUTH,
        json={"media_id": media_id, "alt_review": True, "engine": "whisper"},
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]
    deadline = time.time() + 20
    snap = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()
    while snap["status"] not in {"done", "error", "cancelled"} and time.time() < deadline:
        time.sleep(0.02)
        snap = client.get(f"/api/jobs/{job_id}", headers=AUTH).json()

    assert snap["status"] == "done", snap
    assert "NoneType" not in str(snap.get("error") or "")
    assert snap["result"]["applied"] == "alt_review"
    # 巡检全程没有卸过 whisper；qwen 在任务开始时按设计让路
    assert "whisper" not in released
    assert engine.released == 0
    assert engine.decodes == 4
    assert runner.sweeps == [[]] * len(runner.sweeps), runner.sweeps

    # 第二版落进「第二列」，主稿一句没动
    alt = client.get("/api/alt-review", headers=AUTH).json()
    assert alt["exists"] is True
    assert [c["text"] for c in alt["cues"]] == [item["text"] for item in SECOND]
    primary = client.get("/api/cues", headers=AUTH).json()["cues"]
    assert [c["text"] for c in primary] == [item["text"] for item in PRIMARY]
