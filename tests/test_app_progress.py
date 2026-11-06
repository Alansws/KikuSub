"""同名不同片源的校对断点不能互相恢复。"""

from __future__ import annotations

import pytest

pytest.importorskip("gradio")

import app  # noqa: E402
from transcribe import SubtitleCue  # noqa: E402


def test_progress_rejects_other_media_with_same_stem(tmp_path, monkeypatch):
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    monkeypatch.setattr(app, "OUTPUT_DIR", output_dir)

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    media_a = dir_a / "EP01.mkv"
    media_b = dir_b / "EP01.mkv"
    media_a.write_bytes(b"a")
    media_b.write_bytes(b"b")

    app._save_draft_and_progress(
        str(media_a),
        [SubtitleCue(1.0, 2.0, "a")],
        reviewed_idx=1,
        start_str="00:00:01,000",
        end_str="00:00:02,000",
        text="a",
    )
    assert app._load_review_progress(media_file=str(media_a)) is not None
    assert app._load_review_progress(media_file=str(media_b)) is None


def test_legacy_progress_without_path_still_loads(tmp_path, monkeypatch):
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    monkeypatch.setattr(app, "OUTPUT_DIR", output_dir)
    legacy = output_dir / "EP01.progress.json"
    legacy.write_text('{"last_reviewed_idx": 3}', encoding="utf-8")
    data = app._load_review_progress(media_file=str(tmp_path / "EP01.mkv"))
    assert data and data["last_reviewed_idx"] == 3
