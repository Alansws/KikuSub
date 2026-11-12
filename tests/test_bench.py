"""性能基线 CLI 的冒烟测试：它得能在 CI 里跑通（不依赖 torch / 模型）。"""

from __future__ import annotations

import json

from core import bench


def test_bench_quick_runs_and_reports_all_workloads(tmp_path, capsys):
    out = tmp_path / "bench.json"
    assert bench.main(["--quick", "--json", str(out)]) == 0

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["cues"] == bench.DEFAULT_CUES // 10
    assert set(payload["ms"]) == {
        "srt_to_cues",
        "cues_to_srt",
        "align_translation_texts",
        "cues_from_subtitle_file",
    }
    assert all(v >= 0 for v in payload["ms"].values())
    assert "内核基线" in capsys.readouterr().out


def test_bench_accepts_explicit_cue_count(tmp_path):
    out = tmp_path / "b.json"
    assert bench.main(["--cues", "50", "--json", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["cues"] == 50
