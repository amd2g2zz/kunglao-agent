# -*- coding: utf-8 -*-
"""tc_journal.py — per-dispatch tool-call journal (issue 396, v0.1.6
RECORDING face; the cheapest possible recording surface).

One JSONL line per tool call in ``runs/tc-journal.jsonl``:

    {"schema": "tc-journal/1", "dispatch_id", "tool", "args_sha256",
     "status", "files", "ts", "actor"}

Written by RETURN-TIME AGGREGATION ONLY (worker exit / the loop runner at
worker-return) — never inside tool dispatch. Two write faces:

  record_call / record_calls  the direct append face (a worker exit path
                              that knows its calls writes these);
  harvest_from_log            the zero-instrumentation derivation face:
                              derive journal rows FROM THE EXISTING
                              kunglao_log tool_call events (action ==
                              "tool_call", the structured-log observability face)
                              at worker return. The log schema carries no
                              args, so derived rows carry
                              args_sha256=None — honest documented
                              absence, never a fabricated hash.

Identity dedupe (dispatch_id, actor, tool, ts, status, files) makes
re-harvest idempotent at any wall-clock distance: the journal grows only
when the logs grew (the settle_round_credit freeze-ts precedent — the
recording face must never churn).

ZERO DECISION POSTURE: pure appends, never imported by any dispatch,
gate, or settlement face (pinned by test_experience_freeze_396).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from kunglao_log import iter_jsonl

SCHEMA = "tc-journal/1"
JOURNAL_REL = "runs/tc-journal.jsonl"

_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    """Rate-limited stderr WARN (the issue 276 _zof_warn pattern)."""
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] tc_journal WARN (fail-open): "
          f"{op}: {reason}", file=sys.stderr)


def _now() -> str:
    from harness_common import utc_now_z
    return utc_now_z()


def _row(dispatch_id: str, tool: str, args_hash, status, files, ts,
         actor) -> dict:
    if isinstance(files, str):
        files = [files]
    return {"schema": SCHEMA,
            "dispatch_id": str(dispatch_id),
            "tool": str(tool),
            "args_sha256": (str(args_hash) if args_hash else None),
            "status": status,
            "files": [str(f) for f in files] if files else [],
            "ts": str(ts or _now()),
            "actor": str(actor) if actor else None}


def _append(ws, row: dict) -> bool:
    """O_APPEND single-write; never raises (fail-open telemetry)."""
    try:
        import os
        p = Path(ws) / JOURNAL_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return True
    except Exception as exc:  # noqa: BLE001 — recording never breaks callers
        warn("append", f"{type(exc).__name__}: {exc}")
        return False


def record_call(ws, dispatch_id: str, tool: str, args_hash=None,
                status=None, files=None, ts=None, actor=None) -> bool:
    """Append one tool-call journal line. Never raises."""
    try:
        return _append(ws, _row(dispatch_id, tool, args_hash, status,
                                files, ts, actor))
    except Exception as exc:  # noqa: BLE001 — fail-open
        warn("record_call", f"{type(exc).__name__}: {exc}")
        return False


def record_calls(ws, dispatch_id: str, calls, ts=None) -> int:
    """Append a batch of calls (each a mapping with tool / args_hash /
    status / files / actor keys); returns the appended count."""
    appended = 0
    for call in calls or []:
        if not isinstance(call, dict):
            continue
        if record_call(ws, dispatch_id,
                       tool=str(call.get("tool") or ""),
                       args_hash=call.get("args_hash"),
                       status=call.get("status"),
                       files=call.get("files"),
                       ts=ts,
                       actor=call.get("actor")):
            appended += 1
    return appended


def read(ws) -> list[dict]:
    """Tolerant journal read (missing/dirty -> skipped rows; never raises)."""
    p = Path(ws) / JOURNAL_REL
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [row for row in iter_jsonl(text.splitlines())
            if isinstance(row, dict)]


def _identity(row: dict) -> tuple:
    """The journal row identity (the dedupe key)."""
    return (str(row.get("dispatch_id") or ""),
            str(row.get("actor") or ""),
            str(row.get("tool") or ""),
            str(row.get("ts") or ""),
            json.dumps(row.get("status")),
            json.dumps(row.get("files"), sort_keys=True))


def from_kunglao_log(ws) -> list[dict]:
    """Derive journal rows from the EXISTING kunglao_log tool_call events
    (runs/logs/kunglao-*.jsonl, action == "tool_call"). The log schema
    carries no args: derived rows carry args_sha256=None (documented
    absence). dispatch_id falls back to the row's claim, then
    "unattributed" — the null-documentation posture (claims un-attributed, never guessed)."""
    logs_dir = Path(ws) / "runs" / "logs"
    out: list[dict] = []
    if not logs_dir.is_dir():
        return out
    for path in sorted(logs_dir.glob("kunglao-*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for row in iter_jsonl(text.splitlines()):
            if not isinstance(row, dict):
                continue
            if str(row.get("action") or "") != "tool_call":
                continue
            claim = str(row.get("claim") or "").strip()
            artifact = str(row.get("artifact") or "").strip()
            out.append(_row(dispatch_id=claim or "unattributed",
                            tool=str(row.get("tool") or ""),
                            args_hash=None,
                            status=row.get("exit"),
                            files=[artifact] if artifact else [],
                            ts=row.get("ts"),
                            actor=row.get("actor")))
    return out


def harvest_from_log(ws) -> int:
    """The worker-return face: journal every not-yet-journaled tool_call
    log row. Idempotent at any wall-clock distance (identity dedupe);
    returns the appended count. Never raises."""
    try:
        existing = {_identity(r) for r in read(ws)}
        appended = 0
        for row in from_kunglao_log(ws):
            if _identity(row) in existing:
                continue
            if _append(ws, row):
                existing.add(_identity(row))
                appended += 1
        return appended
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        warn("harvest_from_log", f"{type(exc).__name__}: {exc}")
        return 0


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
