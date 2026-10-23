# -*- coding: utf-8 -*-
"""tests/test_log_setup_818.py — the #454/#459 dual-output logging facade.

Real-fixture behavior pins (issue #818 coverage climb): a real file lands
under <ws>/runs/logs/ with the documented name shape, the handler wiring
is the documented dual-output (file + optional stderr), the setup is
idempotent (a second call never re-adds handlers), and dot-separated
logger names are sanitized into the file name. No mocks: the assertions
read the logger object and the bytes on disk.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import log_setup as ls  # noqa: E402  (scripts/ on pytest path)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def test_setup_wires_file_and_stderr_handlers(tmp_path: Path) -> None:
    name = "kunglao.test.face"
    logger = ls.setup(tmp_path, name)
    try:
        assert logger.level == logging.INFO
        kinds = sorted(type(h).__name__ for h in logger.handlers)
        assert kinds == ["FileHandler", "StreamHandler"]
        expected = (tmp_path / "runs" / "logs"
                    / f"kunglao_test_face-{_today()}.log")
        assert logger.handlers[0].baseFilename == str(expected)
    finally:
        for h in logger.handlers:
            h.close()
            logging.getLogger(name).removeHandler(h)


def test_setup_is_idempotent_no_handler_duplication(
        tmp_path: Path) -> None:
    name = "kunglao.idempotent"
    first = ls.setup(tmp_path, name)
    n = len(first.handlers)
    assert n >= 1
    second = ls.setup(tmp_path, name)
    assert second is first
    assert len(second.handlers) == n
    # the log dir gained exactly one file for this name
    files = list((tmp_path / "runs" / "logs").glob("kunglao_idempotent*"))
    assert len(files) == 1
    for h in first.handlers:
        h.close()
        logging.getLogger(name).removeHandler(h)


def test_setup_stderr_optional(tmp_path: Path) -> None:
    name = "kunglao.quiet"
    logger = ls.setup(tmp_path, name, also_stderr=False)
    try:
        assert [type(h).__name__ for h in logger.handlers] == ["FileHandler"]
    finally:
        for h in logger.handlers:
            h.close()
            logging.getLogger(name).removeHandler(h)


def test_setup_log_record_format_and_content(tmp_path: Path) -> None:
    name = "kunglao.format"
    logger = ls.setup(tmp_path, name)
    try:
        logger.info("hello %s", "world")
        for h in logger.handlers:
            h.flush()
        log_file = (tmp_path / "runs" / "logs"
                    / f"kunglao_format-{_today()}.log")
        text = log_file.read_text(encoding="utf-8")
        assert "hello world" in text
        assert "kunglao.format" in text
        assert "INFO" in text
        # the documented fixed format: asctime LEVEL name | message
        assert " | " in text
    finally:
        for h in logger.handlers:
            h.close()
            logging.getLogger(name).removeHandler(h)


def test_setup_respects_custom_level(tmp_path: Path) -> None:
    name = "kunglao.level"
    logger = ls.setup(tmp_path, name, level=logging.WARNING)
    try:
        assert logger.level == logging.WARNING
        assert not logger.isEnabledFor(logging.INFO)
        assert logger.isEnabledFor(logging.WARNING)
    finally:
        for h in logger.handlers:
            h.close()
            logging.getLogger(name).removeHandler(h)
