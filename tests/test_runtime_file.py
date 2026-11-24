"""运行期握手文件：CLI 靠它发现端口/token，权限必须是 0600。"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from server.runtime_file import RuntimeFile, read_runtime


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_write_is_private_and_atomic(tmp_path: Path):
    runtime = RuntimeFile(tmp_path / "runtime.json")
    runtime.write(port=51234, token="secret-token", version="0.6.0", output_dir=tmp_path)

    data = read_runtime(tmp_path / "runtime.json")
    assert data is not None
    assert data["port"] == 51234
    assert data["token"] == "secret-token"
    assert data["pid"] == os.getpid()
    assert data["session_id"] == ""
    assert _mode(tmp_path / "runtime.json") == 0o600
    # 原子写不留下临时文件
    assert list(tmp_path.glob("*.tmp")) == []


def test_note_session_only_rewrites_on_change(tmp_path: Path):
    path = tmp_path / "runtime.json"
    runtime = RuntimeFile(path)
    runtime.write(port=1, token="t", version="v", output_dir=tmp_path)
    first = path.stat().st_mtime_ns

    runtime.note_session("")
    assert path.stat().st_mtime_ns == first

    runtime.note_session("abc")
    assert read_runtime(path)["session_id"] == "abc"
    second = path.stat().st_mtime_ns
    assert second >= first

    runtime.note_session("abc")  # 同一个 id 不再落盘
    assert path.stat().st_mtime_ns == second

    runtime.note_session("def")
    assert read_runtime(path)["session_id"] == "def"


def test_clear_does_not_delete_another_process_file(tmp_path: Path):
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({"pid": os.getpid() + 1}), "utf-8")
    RuntimeFile(path).clear()
    assert path.exists()


def test_clear_removes_own_file(tmp_path: Path):
    path = tmp_path / "runtime.json"
    runtime = RuntimeFile(path)
    runtime.write(port=1, token="t", version="v", output_dir=tmp_path)
    runtime.clear()
    assert not path.exists()


def test_read_runtime_tolerates_missing_and_corrupt(tmp_path: Path):
    assert read_runtime(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", "utf-8")
    assert read_runtime(bad) is None
