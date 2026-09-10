# -*- coding: utf-8 -*-
"""rank_face.py — THE Thompson rank face, single source (issue 218).

The ranker (scripts/priority_ratio.py, issue 107) writes ONE ``rank_feeds``
event per run into the workspace ledger (issue 157): per-claim Thompson
samples, scores, ranked order and the replay fingerprint. That event used to
be FILE-ONLY — the statusline carried derived entropy but never the sampling
itself. This module owns the reading of that event so both faces read THE
SAME computed values (the issue 142 dual-use display principle, the same
shape as scripts/entropy_face.py):

  - display face   — scripts/statusline_snapshot.py ships ``rank`` /
    ``rank_log`` inside the snapshot; statusline_render.mjs only renders it;
  - decision face  — scripts/heartbeat_tick.py carries the same two fields
    in its report (runs/.heartbeat-tick.json).

Emit-failure marker: ``priority_ratio._emit_rank_feeds`` stays SILENT
fail-open (the issue 569 contract — a crash never reaches the ranking
result), but a failed attempt now leaves ``runs/.rank-emit-fail.json``
{ts, error class}; a later success clears it, so the marker means "the LAST
emit attempt failed" and the health bit recovers by itself. Neither the
ranking result nor the rank_feeds payload is touched by the marker.

Fail-open everywhere: a missing/unreadable ledger or marker degrades to the
absent face, never an exception. The ledger read is bounded (last 64KB of
the newest day file — the issue 883 read budget).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# One marker file, one reader (no twin): the writer in priority_ratio.py and
# both display faces import these constants from here.
MARKER_REL = Path("runs") / ".rank-emit-fail.json"
LOG_DIR_REL = Path("runs") / "logs"
TAIL_BYTES = 65_536
RANK_ACTION = "rank_feeds"
# A rank older than this is displayed as stall-suspect: the ranker runs on
# every DECIDE / dispatch-gate pass, so half an hour without one is not a
# "current" ranking (it is still shown — aged, never hidden).
RANK_STALE_MINUTES = 30


def _epoch(value) -> float | None:
    """ISO8601 Z -> epoch seconds; None on anything unparseable (fail-open)."""
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OSError):
        return None


def _now_z() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def write_fail_marker(ws, error) -> None:
    """Record ONE failed rank_feeds emit (timestamp + error class).

    `error` is an exception (its class name is recorded) or a short label
    string for a failure that has no exception object — e.g. the writer
    reporting a failed write with False.

    Best-effort by contract: the marker is observability, never a ranking
    dependency, so it must not be able to raise into the ranker's fail-open
    path."""
    try:
        p = Path(ws) / MARKER_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"ts": _now_z(),
                                 "error": (error if isinstance(error, str)
                                           else type(error).__name__)},
                                ensure_ascii=False) + "\n",
                     encoding="utf-8")
    except Exception:  # noqa: BLE001 — the marker never breaks its caller
        pass


def clear_fail_marker(ws) -> None:
    """A successful emit clears the marker (last-attempt semantics)."""
    try:
        (Path(ws) / MARKER_REL).unlink()
    except OSError:
        pass


def emit_health(ws) -> dict:
    """The emit-path health bit: {"ok", "error", "ts"}.

    No marker -> ok (the clean face). A present-but-unreadable marker is
    still fault evidence (its existence IS the signal) -> ok False."""
    p = Path(ws) / MARKER_REL
    if not p.exists():
        return {"ok": True, "error": None, "ts": None}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": "unreadable", "ts": None}
    if not isinstance(doc, dict):
        return {"ok": False, "error": "unreadable", "ts": None}
    err = doc.get("error")
    ts = doc.get("ts")
    return {"ok": False, "error": str(err) if err else "unknown",
            "ts": ts if isinstance(ts, str) else None}


def _tail_rows(ws) -> list[dict]:
    """Parsed rows from the last 64KB of the newest day file (bounded read;
    a possibly-partial first line is dropped ONLY when the window actually
    starts mid-file — a complete first line in a small file survives).
    [] on any read failure."""
    logs = Path(ws) / LOG_DIR_REL
    start = 0
    try:
        latest = max((p for p in logs.glob("kunglao-*.jsonl") if p.is_file()),
                     key=lambda p: p.stat().st_mtime, default=None)
        if latest is None:
            return []
        with latest.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - TAIL_BYTES)
            f.seek(start)
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = tail.splitlines()
    if start > 0:
        # the window began mid-file, so line 1 is possibly partial
        lines = lines[1:]
    rows: list[dict] = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _payload(row: dict) -> dict:
    """The rank_feeds payload from a row's detail JSON; {} when unreadable."""
    detail = row.get("detail")
    if not isinstance(detail, str):
        return {}
    try:
        doc = json.loads(detail)
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


def latest_rank(ws, now: datetime | None = None) -> dict:
    """The latest rank_feeds run: the top action's claim id + sampled score +
    age/staleness. No run at all -> the absent face (claim None, stale True),
    never an exception."""
    now = now or datetime.now(timezone.utc)
    for row in reversed(_tail_rows(ws)):
        if row.get("action") != RANK_ACTION:
            continue
        payload = _payload(row)
        order = payload.get("ranked_order")
        top = order[0] if isinstance(order, list) and order else None
        scores = payload.get("scores")
        score = None
        if isinstance(scores, dict) and isinstance(top, str):
            raw = scores.get(top)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                score = float(raw)
        ts = row.get("ts")
        ts_epoch = _epoch(ts)
        age_s = (round(max(0.0, now.timestamp() - ts_epoch), 1)
                 if ts_epoch is not None else None)
        return {"claim": top if isinstance(top, str) else None,
                "score": score,
                "ts": ts if isinstance(ts, str) else None,
                "age_s": age_s,
                "stale": age_s is None or age_s > RANK_STALE_MINUTES * 60}
    return {"claim": None, "score": None, "ts": None, "age_s": None,
            "stale": True}


def face(ws, now: datetime | None = None) -> dict:
    """THE single-source face: ``{"rank", "rank_log"}``.

    ``rank``     — the latest rank_feeds run (claim / score / ts / age_s /
                   stale), the absent face when none exists.
    ``rank_log`` — the emit-path health bit ({ok, error, ts}): ok False means
                   the LAST emit attempt crashed, so the displayed rank is
                   only as fresh as the last successful emit.
    """
    return {"rank": latest_rank(ws, now=now), "rank_log": emit_health(ws)}
