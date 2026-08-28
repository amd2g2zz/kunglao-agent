#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_tokens.py — token/wall-clock collector (B3, #823 AB-VALUE).

The ONLY new metering piece the bench adds. Reads a Claude Code session
transcript JSONL and reduces it to one receipt dict:

  total_in / total_out      sum of message.usage input/output tokens
  cache_creation / cache_read   the cache token faces
  grand_total               all four summed (the experiment's cost unit)
  wall_s                    last timestamp − first timestamp
  user_turn_count           GENUINE human turns (tool_result user rows
                            excluded — they are the harness talking)
  usage_incomplete          any assistant row without usage → True;
                            present rows still count (partial truth beats
                            no truth)

user_turn_count > 1 is the mechanical human-intervention signal feeding
the z_self label (channel 4) and the contamination rule (AB-DESIGN §7).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


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


def collect(transcript_path: Path) -> dict:
    out = {"total_in": 0, "total_out": 0, "cache_creation": 0,
           "cache_read": 0, "grand_total": 0, "wall_s": 0,
           "user_turn_count": 0, "usage_incomplete": False}
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    try:
        text = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        out["error"] = str(exc)
        out["usage_incomplete"] = True
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if _is_genuine_user_turn(row):
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
            first_ts = first_ts or ts
            last_ts = ts
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
