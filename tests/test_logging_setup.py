"""日志落盘与 handler 去重测试（无第三方依赖）。"""

from __future__ import annotations

import logging

from core.logging_setup import setup_logging


def _kikusub_handlers() -> list[logging.Handler]:
    return [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "_kikusub_handler", False)
    ]


def test_writes_to_rotating_file(tmp_path):
    path = setup_logging(tmp_path, force=True)
    logger = logging.getLogger("kikusub.test")
    logger.info("hello-log")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.exception("with-traceback")
    for handler in _kikusub_handlers():
        handler.flush()

    text = path.read_text(encoding="utf-8")
    assert "hello-log" in text
    assert "with-traceback" in text
    assert "RuntimeError: boom" in text


def test_repeated_setup_does_not_duplicate_handlers(tmp_path):
    setup_logging(tmp_path, force=True)
    setup_logging(tmp_path)
    setup_logging(tmp_path)
    handlers = _kikusub_handlers()
    assert len(handlers) == 2  # 一个文件 + 一个控制台


def test_force_repoints_to_new_directory(tmp_path):
    first = setup_logging(tmp_path / "a", force=True)
    second = setup_logging(tmp_path / "b", force=True)
    logging.getLogger("kikusub.test").warning("second-dir")
    for handler in _kikusub_handlers():
        handler.flush()

    assert first.exists()
    assert second.exists()
    assert "second-dir" in second.read_text(encoding="utf-8")


def test_tokens_are_redacted_in_log_file(tmp_path):
    path = setup_logging(tmp_path, force=True)
    logging.getLogger("uvicorn.error").info(
        'WebSocket /ws/jobs/x?token=SECRET123 [accepted] Authorization: Bearer abc.def'
    )
    for handler in _kikusub_handlers():
        handler.flush()

    text = path.read_text(encoding="utf-8")
    assert "SECRET123" not in text
    assert "abc.def" not in text
    assert "token=***" in text
    assert "Bearer ***" in text


# ---------------------------------------------------------------------------
# 保留策略：日志不能无限堆
# ---------------------------------------------------------------------------


def test_prune_removes_expired_backups_and_keeps_active(tmp_path):
    import os
    import time

    from core.logging_setup import prune_logs

    active = tmp_path / "kikusub.log"
    active.write_text("active", encoding="utf-8")
    old = tmp_path / "kikusub.log.3"
    old.write_text("old", encoding="utf-8")
    fresh = tmp_path / "main.log.1"
    fresh.write_text("fresh", encoding="utf-8")
    stale = time.time() - 30 * 24 * 3600
    os.utime(old, (stale, stale))

    result = prune_logs(tmp_path, max_age_days=14)

    assert result["removed"] == 1
    assert not old.exists()
    assert active.exists()  # 正在写的活动日志永远不删
    assert fresh.exists()  # 没过期的备份保留


def test_prune_enforces_total_size_budget(tmp_path):
    import os
    import time

    from core.logging_setup import prune_logs

    active = tmp_path / "kikusub.log"
    active.write_bytes(b"a" * 10)
    now = time.time()
    for index in range(1, 5):
        backup = tmp_path / f"kikusub.log.{index}"
        backup.write_bytes(b"b" * 20)
        stamp = now - (10 - index) * 3600
        os.utime(backup, (stamp, stamp))

    result = prune_logs(tmp_path, max_total_bytes=45)

    assert active.exists()
    assert result["total_bytes"] <= 45
    # 最旧的先删，最新的备份留着
    assert not (tmp_path / "kikusub.log.1").exists()
    assert (tmp_path / "kikusub.log.4").exists()


def test_setup_logging_runs_retention_at_startup(tmp_path):
    import os
    import time

    old = tmp_path / "kikusub.log.3"
    old.write_text("old", encoding="utf-8")
    stale = time.time() - 30 * 24 * 3600
    os.utime(old, (stale, stale))

    setup_logging(tmp_path, force=True)

    assert not old.exists()
    assert (tmp_path / "kikusub.log").exists()
