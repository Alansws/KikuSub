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
