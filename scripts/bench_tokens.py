#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_tokens.py — token/wall-clock collector (B3, #823 AB-VALUE).

The ONLY new metering piece the bench adds. Reads a Claude Code SESSION
(the transcript it is handed plus the worker transcripts beside
it, enumerated by the ONE shared read-domain function in _common — the
main file alone never carried the worker rows) and reduces it to one
receipt dict:

  total_in / total_out      sum of message.usage input/output tokens
  cache_creation / cache_read   the cache token faces
  grand_total               all four summed (the experiment's cost unit —
                            now genuinely over the whole session, which
                            is what the declaration claims)
  wall_s                    min→max timestamp span across ALL the
                            session's transcripts (a worker can outlive
                            the main file's last row)
  user_turn_count           GENUINE human turns, MAIN transcript only
                            (tool_result user rows are the harness
                            talking; worker files' user rows are the
                            dispatch envelope — neither is a person)
  worker_transcripts /      how many worker files the fold saw / could
  worker_unread             not read (the loss is counted, never zero)
  usage_incomplete          any assistant row without usage, in any file
                            → True; present rows still count (partial
                            truth beats no truth)

user_turn_count > 1 is the mechanical human-intervention signal feeding
the z_self label (channel 4) and the contamination rule (AB-DESIGN §7).

Determinism: the token sums are in-order integer accumulation over the
canonical file order (main first, worker files sorted by name) — never a
reordered/pairwise reduction (the settlement axiom's input-order rule).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from kunglao_log import iter_jsonl  # noqa: E402  (#863 Family K single source)
from _common import session_transcript_files  # noqa: E402  (read domain)


def _parse_ts(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _usage_of(row: dict) -> dict | None:
    msg = row.get("message")
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    return usage if isinstance(usage, dict) else None


def _is_genuine_user_turn(row: dict) -> bool:
    """type=user rows carry BOTH human prompts and tool_result payloads;
    only the former count (a tool result is the harness speaking)."""
    if row.get("type") != "user":
        return False
    content = (row.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(not (isinstance(b, dict) and b.get("type") == "tool_result")
                   for b in content)
    return False


def _fold_rows_into(out: dict, text: str, *, is_main: bool
                    ) -> tuple[datetime | None, datetime | None]:
    """Fold ONE transcript's rows into the receipt dict, in file order
    (in-order integer accumulation — the determinism rule). Genuine user
    turns count only when the file is the main transcript (a worker
    file's user rows are the dispatch envelope). Returns this file's
    (min_ts, max_ts); the caller keeps the session-wide bounds."""
    lo: datetime | None = None
    hi: datetime | None = None
    for row in iter_jsonl(text.splitlines()):
        if not isinstance(row, dict):
            continue
        if is_main and _is_genuine_user_turn(row):
            out["user_turn_count"] += 1
        usage = _usage_of(row)
        if usage is None:
            if row.get("type") == "assistant":
                out["usage_incomplete"] = True
        else:
            out["total_in"] += int(usage.get("input_tokens") or 0)
            out["total_out"] += int(usage.get("output_tokens") or 0)
            out["cache_creation"] += int(
                usage.get("cache_creation_input_tokens") or 0)
            out["cache_read"] += int(
                usage.get("cache_read_input_tokens") or 0)
        ts = _parse_ts(row.get("timestamp"))
        if ts is not None:
            if lo is None or ts < lo:
                lo = ts
            if hi is None or ts > hi:
                hi = ts
    return lo, hi


def collect(transcript_path: Path) -> dict:
    """The session receipt: every transcript of session_transcript_files()
    (the main file first, then its worker files) folded in order.

    The main file keeps its short-circuit: unreadable → error +
    usage_incomplete, return. A worker file that cannot be read costs
    only its own contribution (worker_unread += 1, incomplete = True,
    fold continues). user_turn_count is counted from the main transcript
    alone (worker user rows are dispatch envelopes); the token faces,
    the timestamp bounds and usage_incomplete span the whole session."""
    out = {"total_in": 0, "total_out": 0, "cache_creation": 0,
           "cache_read": 0, "grand_total": 0, "wall_s": 0,
           "user_turn_count": 0, "usage_incomplete": False,
           "worker_transcripts": 0, "worker_unread": 0}
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    files = session_transcript_files(transcript_path)
    for index, path in enumerate(files):
        is_main = index == 0
        if not is_main:
            out["worker_transcripts"] += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            if is_main:
                out["error"] = str(exc)
                out["usage_incomplete"] = True
                return out
            out["worker_unread"] += 1
            out["usage_incomplete"] = True
            continue
        lo, hi = _fold_rows_into(out, text, is_main=is_main)
        if lo is not None and (first_ts is None or lo < first_ts):
            first_ts = lo
        if hi is not None and (last_ts is None or hi > last_ts):
            last_ts = hi
    if first_ts and last_ts:
        out["wall_s"] = int((last_ts - first_ts).total_seconds())
    out["grand_total"] = (out["total_in"] + out["total_out"]
                          + out["cache_creation"] + out["cache_read"])
    return out


def human_intervention(tokens: dict) -> bool:
    """z_self channel 4 / contamination signal: more than ONE human turn
    means the session was rescued (the opening prompt is turn 1)."""
    return int(tokens.get("user_turn_count") or 0) > 1


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
