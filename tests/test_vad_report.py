"""VAD 切分器在任务报告里的显式回退提示。"""

from __future__ import annotations

from core import report


def test_report_shows_fallback_reason():
    text = report._vad_backend_summary({
        "vad_backend": {
            "requested": "whisperseg",
            "used": "silero",
            "fallback": True,
            "reason": "下载失败：断网",
        }
    })
    assert "回退 Silero 20s" in text
    assert "断网" in text


def test_report_shows_normal_backends():
    assert report._vad_backend_summary(
        {"vad_backend": {"requested": "whisperseg", "used": "whisperseg", "fallback": False}}
    ) == "WhisperSeg（推荐）"
    assert report._vad_backend_summary(
        {"vad_backend": {"requested": "silero", "used": "silero", "fallback": False}}
    ) == "Silero 20s（兼容）"
    assert report._vad_backend_summary({}) == "Silero 20s（本引擎固定）"
