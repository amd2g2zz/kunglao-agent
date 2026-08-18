#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""log_setup.py — stdlib logging dual-output facade (#454, #459).

Single entry point: `setup(ws, name)` returns a `logging.Logger` already
wired with a FileHandler (under `<ws>/runs/logs/<name>-<date>.log`) and a
StreamHandler (to stderr). Callers `import logging; logging.getLogger(name)`
and `logger.info(...)` — the facade just guarantees uniform format and
idempotent setup.

Design choices:
  * stdlib `logging` only (no extra deps).
  * Idempotent: calling `setup` twice for the same logger name returns the
    already-configured logger without re-adding handlers.
  * Format is fixed: `%(asctime)s %(levelname)s %(name)s | %(message)s`
    — operators can `tail -f` the file or watch the live stderr stream.
  * File path uses UTC date so multi-machine operators see a stable cutover
    (operator-local dates can drift across timezones).
  * `also_stderr=True` by default; CI/headless callers can pass False.

This module is NOT the structured JSONL event log (that's `kunglao_log.py`,
#287). Two distinct observability surfaces:
  - `kunglao_log.emit()` — structured events for tooling (machine parse).
  - `log_setup.setup()` — human-readable records (operator tail).
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def setup(ws: Path, name: str, *, level: int = logging.INFO,
          also_stderr: bool = True) -> logging.Logger:
    """Idempotent dual-output: FileHandler + (optional) StreamHandler.

    Args:
      ws: workspace path; logs land under `<ws>/runs/logs/`.
      name: logger name (dot-separated, e.g. "kunglao.init").
      level: logger level (default INFO).
      also_stderr: when True (default), mirror to stderr for live tail.

    Returns:
      The configured `logging.Logger`. Subsequent calls with the same
      `name` return the same logger without re-adding handlers.
    """
    logger = logging.getLogger(name)
    if logger.handlers:  # already configured — keep idempotent
        return logger
    log_dir = ws / "runs" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    day = datetime.now(timezone.utc).date().isoformat()
    safe_name = name.replace(".", "_")
    fh = logging.FileHandler(log_dir / f"{safe_name}-{day}.log",
                             encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    if also_stderr:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    logger.setLevel(level)
    return logger
