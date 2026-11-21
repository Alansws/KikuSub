"""`kikusub` CLI：运行时发现、只读输出、提案提交与错误透传。

不起真实 sidecar：用 stdlib 的 ThreadingHTTPServer 演服务端，验证 CLI 的
HTTP 契约（Bearer / X-Kikusub-Session）与命令输出形状。
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tools.kikusub import kikusub

TOKEN = "cli-token"
SESSION = "cli-session"


class _Handler(BaseHTTPRequestHandler):
    routes: dict = {}

    def log_message(self, *args):  # noqa: D401 - 静音
        return

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length else None
        key = (method, self.path.split("?")[0])
        handler = self.routes.get(key)
        if handler is None:
            self._reply(404, {"detail": "not found"})
            return
        status, payload = handler(self.headers, body)
        self._reply(status, payload)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    _Handler.routes = {}
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()


def _runtime(tmp_path: Path, httpd: ThreadingHTTPServer, *, pid: int | None = None) -> Path:
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(
            {
                "app": "KikuSub",
                "port": httpd.server_address[1],
                "token": TOKEN,
                "pid": os.getpid() if pid is None else pid,
                "session_id": SESSION,
                "api_version": "9.9.9",
            }
        ),
        "utf-8",
    )
    return path


def _cues(count: int = 2):
    return {
        "count": count,
        "digest": "d" * 64,
        "cues": [
            {"start": 0.0, "end": 1.0, "text": "おはよう"},
            {"start": 2.0, "end": 3.0, "text": "今日は雨だ"},
        ],
        "review_source": {"engine": "AnimeWhisper", "name": "episode.AnimeWhisper.srt"},
    }


def _assert_auth(headers) -> None:
    assert headers.get("Authorization") == f"Bearer {TOKEN}"
    assert headers.get("X-Kikusub-Session") == SESSION


def test_project_json(server, tmp_path, capsys):
    _Handler.routes = {
        ("GET", "/api/health"): lambda h, b: (200, {"ok": True, "version": "9.9.9"}),
        ("GET", "/api/config"): lambda h, b: (
            200,
            {"version": "9.9.9", "output_dir": str(tmp_path), "export_dir": str(tmp_path)},
        ),
        ("GET", "/api/session"): lambda h, b: (
            200,
            {
                "media": {"id": "m1", "path": str(tmp_path / "episode.mkv"), "duration": 120.0},
                "review_source": {"engine": "AnimeWhisper"},
            },
        ),
        ("GET", "/api/cues"): lambda h, b: (200, _cues()),
        ("GET", "/api/proposals/status"): lambda h, b: (
            200,
            {"items": [{"kind": "polish", "lang": "", "path": "/x.ai-polish.json"}], "revision": "r1"},
        ),
    }
    path = _runtime(tmp_path, server)
    code = kikusub.main(["project", "--json", "--runtime", str(path)])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cues"]["count"] == 2
    assert out["cues"]["digest"] == "d" * 64
    assert out["app"]["version"] == "9.9.9"
    assert out["proposals"][0]["kind"] == "polish"


def test_cues_merges_metrics_and_b(server, tmp_path, capsys):
    def evidence(headers, body):
        _assert_auth(headers)
        return (
            200,
            {
                "vocals_cached": True,
                "items": [
                    {"i": 1, "raw_dbfs": -31.0, "vocals_dbfs": -33.0},
                    {"i": 2, "raw_dbfs": -85.2, "vocals_dbfs": -85.2},
                ],
            },
        )

    _Handler.routes = {
        ("GET", "/api/health"): lambda h, b: (200, {"ok": True}),
        ("GET", "/api/cues"): lambda h, b: (200, _cues()),
        ("GET", "/api/evidence/cues"): evidence,
        ("GET", "/api/alt-review"): lambda h, b: (
            200,
            {
                "rows": [
                    {"a_indices": [0], "b_indices": [0], "kind": "diff", "b_text": "おはようございます"}
                ]
            },
        ),
    }
    path = _runtime(tmp_path, server)
    code = kikusub.main(["cues", "--json", "--with-b", "--runtime", str(path)])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["items"][0]["raw_dbfs"] == -31.0
    assert out["items"][1]["vocals_dbfs"] == -85.2
    assert out["items"][0]["b_text"] == "おはようございます"
    assert out["vocals_cached"] is True


def test_listen_prints_current_and_result(server, tmp_path, capsys):
    state = {"posted": None, "polls": 0}

    def post_job(headers, body):
        _assert_auth(headers)
        state["posted"] = body
        return 201, {"id": "job-1", "status": "running"}

    def get_job(headers, body):
        state["polls"] += 1
        if state["polls"] < 2:
            return 200, {"status": "running", "stage": "正在用 Qwen 复核…"}
        return (
            200,
            {
                "status": "done",
                "result": {
                    "engine": "qwen",
                    "engine_name": "Qwen3-ASR",
                    "separate": True,
                    "elapsed": 12.5,
                    "texts": [{"index": 0, "text": "おはようございます"}],
                },
            },
        )

    _Handler.routes = {
        ("GET", "/api/health"): lambda h, b: (200, {"ok": True}),
        ("GET", "/api/session"): lambda h, b: (
            200,
            {"media": {"id": "m1"}, "review_source": {"engine": "AnimeWhisper"}},
        ),
        ("GET", "/api/cues"): lambda h, b: (200, _cues()),
        ("POST", "/api/jobs"): post_job,
        ("GET", "/api/jobs/job-1"): get_job,
    }
    path = _runtime(tmp_path, server)
    code = kikusub.main(
        ["listen", "1", "--engine", "qwen", "--separate", "--json", "--runtime", str(path)]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cue"]["text"] == "おはよう"
    assert out["listen"]["text"] == "おはようございます"
    assert out["listen"]["separate"] is True
    assert state["posted"]["separate_vocals"] is True
    assert state["posted"]["ranges"][0]["index"] == 0


def test_propose_polish_posts_and_prints(server, tmp_path, capsys):
    seen = {}

    def save(headers, body):
        _assert_auth(headers)
        seen["body"] = body
        return 201, {"path": "/out/episode.ai-polish.json", "count": 2, "warnings": []}

    _Handler.routes = {
        ("GET", "/api/health"): lambda h, b: (200, {"ok": True}),
        ("POST", "/api/ai/proposal"): save,
    }
    proposal = tmp_path / "p.json"
    proposal.write_text('{"version":1,"items":[{"i":1,"after":"x"}]}', "utf-8")
    path = _runtime(tmp_path, server)
    code = kikusub.main(["propose", "polish", "--file", str(proposal), "--json", "--runtime", str(path)])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["count"] == 2
    assert seen["body"]["kind"] == "polish"
    assert seen["body"]["proposal"]["items"][0]["i"] == 1


def test_propose_rejection_surfaces_errors(server, tmp_path, capsys):
    _Handler.routes = {
        ("GET", "/api/health"): lambda h, b: (200, {"ok": True}),
        ("POST", "/api/ai/proposal"): lambda h, b: (
            409,
            {"detail": "源指纹不一致", "errors": ["digest 不匹配"], "warnings": []},
        ),
    }
    proposal = tmp_path / "p.json"
    proposal.write_text("{}", "utf-8")
    path = _runtime(tmp_path, server)
    code = kikusub.main(["propose", "polish", "--file", str(proposal), "--runtime", str(path)])
    assert code == 2
    err = capsys.readouterr().err
    assert "源指纹不一致" in err
    assert "digest 不匹配" in err


def test_connect_rejects_dead_pid(tmp_path, capsys):
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({"port": 1, "token": "t", "pid": 999999, "session_id": "x"}), "utf-8")
    code = kikusub.main(["project", "--runtime", str(path)])
    assert code == 3
    assert "已退出" in capsys.readouterr().err


def test_runtime_candidates_put_explicit_first(tmp_path):
    candidates = kikusub.runtime_candidates(str(tmp_path / "x.json"))
    assert candidates[0] == tmp_path / "x.json"


def test_table_truncates_cjk_by_display_width():
    text = kikusub.table(["文本"], [["很长的中日文文本"]], max_widths=[8])
    assert "…" in text


def test_propose_structure_sends_text(server, tmp_path, capsys):
    seen = {}

    def parse(headers, body):
        seen["text"] = body["text"]
        return 201, {"path": "/out/episode.ai-structure.json", "ops": [], "summary": "无改动"}

    _Handler.routes = {
        ("GET", "/api/health"): lambda h, b: (200, {"ok": True}),
        ("POST", "/api/ai/structure/from-json"): parse,
    }
    ops = tmp_path / "ops.json"
    ops.write_text('{"ops":[{"op":"delete","i":2}]}', "utf-8")
    path = _runtime(tmp_path, server)
    assert kikusub.main(["propose", "structure", "--file", str(ops), "--runtime", str(path)]) == 0
    assert json.loads(seen["text"])["ops"][0]["op"] == "delete"
