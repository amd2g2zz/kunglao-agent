#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""signal_guard.py — the learning-signal degeneracy breaker (#773 Gate C).

Contract: docs/architecture/rl-signal-contract.md §3. Five consecutive
identical settlement credits = a dead signal: freeze the posterior-moving
legs and raise the ``signal_degenerate`` blocker. Recovery is manual —
learning on a dead signal must not resume by itself (resuming on noise
is learning on noise).

Since #1004 the credit series rides the knowledge family's consolidated
file (``knowledge-store.jsonl`` under the guarded root): the rows carry
``workspace_id`` (the shared posterior-store/1 builder), and
``recent_credits`` filters to the CALLING workspace — the per-workspace
series semantics survive the family merge.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from rlvr import consolidated_ledger as _cl  # #1004: the family faces

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
    """The most recent settled credits of THIS workspace's credit series
    (chronologic, oldest first), for the degeneracy check. The series
    rides the knowledge family's consolidated file (#1004); rows are
    keyed to their workspace by ``workspace_id`` (the credit-series
    builder's column) and belong to the SERIES by ``credit_kind`` (the
    workspace-credit face's marker) — so another workspace's store rows
    AND this workspace's cross-task bank rows never leak into the
    degeneracy series (the pre-#1004 series was the workspace-local
    file; the family merge keeps it exactly that series)."""
    mine = Path(ws).name
    vals: list[float] = []
    for rec in _cl.read(ws, "knowledge",
                        schema_prefix="posterior-store/1"):
        if str(rec.get("workspace_id") or "") != mine:
            continue
        if not rec.get("credit_kind"):
            continue  # the cross-task bank's rows are not series rows
        c = rec.get("credit")
        if isinstance(c, (int, float)) and not isinstance(c, bool):
            vals.append(float(c))
    return vals[-n:]


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
