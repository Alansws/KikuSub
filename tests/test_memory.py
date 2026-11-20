"""双引擎预检的内存口径：8GB 拒绝、16GB 放行、探测失败不误拦。"""

from __future__ import annotations

from core import memory


def test_low_memory_is_rejected(monkeypatch):
    monkeypatch.setattr(memory, "total_ram_gb", lambda: 8.0)
    assert "12GB" in memory.dual_memory_error()


def test_16gb_is_allowed(monkeypatch):
    monkeypatch.setattr(memory, "total_ram_gb", lambda: 16.0)
    assert memory.dual_memory_error() == ""


def test_unknown_memory_does_not_block(monkeypatch):
    monkeypatch.setattr(memory, "total_ram_gb", lambda: 0.0)
    assert memory.dual_memory_error() == ""
