#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""signal_guard.py — the learning-signal degeneracy breaker (#773 Gate C).

Contract: docs/architecture/rl-signal-contract.md §3. Five consecutive
identical settlement credits = a dead signal: freeze the posterior-moving
legs and raise the ``signal_degenerate`` blocker. Recovery is manual —
learning on a dead signal must not resume by itself (resuming on noise
is learning on noise).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from rlvr import consolidated_ledger as _cl

DEGENERATE_WINDOW = 5


def check_degeneracy(credits: list[float],
                     window: int = DEGENERATE_WINDOW) -> dict:
    """The last ``window`` credits all identical -> degenerate. Numeric
    values only (non-numeric entries are ignored, never counted)."""
    vals = [float(c) for c in credits
            if isinstance(c, (int, float))][-window:]
    distinct = len(set(vals))
    degenerate = len(vals) >= window and distinct == 1
    return {"degenerate": degenerate, "distinct": distinct,
            "values": vals}


def recent_credits(ws: Path, n: int = DEGENERATE_WINDOW) -> list[float]:
    """The most recent settled credits from THIS workspace's credit
    series (chronologic, oldest first), for the degeneracy check.

    The series rides the knowledge family file (issue-1004 R2c) — the
    only face since the issue-1004 R3 schema cutover. Two filters keep
    the series exactly what the pre-move ws-local file held — the
    credit-series face's rows (``append_workspace_credit_row``, whose
    ``credit_kind`` column is the face's marker) of THIS workspace:

    - ``workspace_id`` — the family file is CROSS-task: a foreign
      workspace's credits must never enter this workspace's breaker
      series (its dead signal must not freeze this workspace's
      learning), the same isolation discipline as the store's
      leave-one-out warm faces;
    - ``credit_kind`` — the cross-task settlement rows (the scalar
      bank's ``append_store_row`` face) ride the same file since the
      move; they are the warm-pool evidence, never the breaker's dense
      credit series.

    The survivors then ride ``learning_seal.trusted_rows``: armed, a
    forged credit row naming this workspace is refused (the shared
    family file widened the forgery blast radius — the wall moves with
    it); unarmed, rows pass (the notice lives on the write face)."""
    from rlvr import learning_seal as _seal  # noqa: PLC0415 — lazy
    mine = Path(ws).name
    rows = [rec for rec in
            _cl.read(ws, "knowledge", schema_prefix="posterior-store")
            if isinstance(rec, dict)
            and str(rec.get("workspace_id") or "") == mine
            and rec.get("credit_kind")
            and isinstance(rec.get("credit"), (int, float))
            and not isinstance(rec.get("credit"), bool)]
    rows = _seal.trusted_rows(rows, op="signal_guard.recent_credits")
    return [float(r["credit"]) for r in rows][-n:]


def freeze_if_degenerate(ws: Path, credits: list[float],
                         window: int = DEGENERATE_WINDOW) -> bool:
    """True = the caller MUST skip the posterior-moving legs (the signal
    is dead). Raises the ``signal_degenerate`` blocker event when firing
    (kunglao_log; a telemetry failure prints, never raises)."""
    verdict = check_degeneracy(credits, window)
    if not verdict["degenerate"]:
        return False
    try:
        from kunglao_log import emit
        emit(Path(ws), "hook:signal_guard", "signal_degenerate",
             detail=json.dumps(verdict, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 — loud print, never raise
        print(f"signal_guard: blocker emit failed ({exc!r})",
              file=sys.stderr, flush=True)
    return True
