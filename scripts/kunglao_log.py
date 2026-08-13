#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao_log — structured JSONL event log (#287 observability).

One JSON object per line, appended to runs/logs/kunglao-<YYYY-MM-DD>.jsonl
under the workspace. Worker, orchestrator, and hook events share ONE schema:

  ts          ISO8601 UTC timestamp (auto, Z suffix)
  actor       who did it (worker / orchestrator / hook / ...)
  action      what happened (dispatch / tool_call / artifact_written / verify / ...)
  claim       claim id the event concerns (or null)
  tool        tool name for tool events (or null)
  artifact    artifact id / path written or read (or null)
  duration_ms integer milliseconds the action took (or null)
  exit        integer exit / verdict code (or null)
  detail      free-text detail (or null)

Design contract:
  - stdlib only (json / os / sys / datetime / pathlib).
  - deterministic output: sort_keys + compact separators + ensure_ascii=False.
  - NEVER raises on write failure — emit degrades to a stderr warning and
    returns; logging must never break analysis.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def log_path(ws: Path) -> Path:
    """runs/logs/kunglao-<date>.jsonl — one file per UTC day."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Path(ws) / "runs" / "logs" / f"kunglao-{day}.jsonl"


def _utc_now() -> str:
    """ISO8601 UTC with Z suffix — same convention as kunglao_record.utc_now."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def emit(ws, actor: str, action: str, *, claim: str | None = None,
         tool: str | None = None, artifact: str | None = None,
         duration_ms: int | None = None, exit: int | None = None,
         detail: str | None = None) -> None:
    """Append one structured event line. Never raises — write failure degrades
    to a stderr warning so logging can never break analysis."""
    event = {
        "ts": _utc_now(),
        "actor": actor,
        "action": action,
        "claim": str(claim) if claim is not None else None,
        "tool": str(tool) if tool is not None else None,
        "artifact": str(artifact) if artifact is not None else None,
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
        "exit": int(exit) if exit is not None else None,
        "detail": str(detail) if detail is not None else None,
    }
    line = json.dumps(event, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False) + "\n"
    p = log_path(ws)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as exc:
        print(f"[kunglao_log] warning: cannot write {p}: {exc}", file=sys.stderr)
