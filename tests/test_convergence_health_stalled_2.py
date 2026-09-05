# -*- coding: utf-8 -*-
"""Issue #2: never-dispatched claims must not trip the STALLED gate.

Root cause chain (all on dev):
  convergence_check._open_claims feeds the whole dispatchable frontier
  (pure OPEN = never dispatched included) into ledger snapshot open_ids;
  convergence_health._stuck_claims flags any id present in open_ids for
  3+ trailing snapshots as "stuck" regardless of dispatch history;
  assess() -> STALLED -> exit 1; the dispatch gate (hooks/
  worker_budget_core.check_convergence_health) blocks ALL dispatch on
  rc=1. A workspace whose claims are all OPEN is therefore deadlocked:
  "stuck" is stamped, dispatch is the only escape, and dispatch is
  exactly what the gate blocks.

Fix contract: "stuck" = dispatched AND flat, never "queued".
  Writer side: convergence_check._append_ledger adds `dispatched_ids`
  (claims in flight IN_PROGRESS or with promotion_attempts >= 1 — a
  recorded worker attempt) to each new snapshot row. Reader side:
  _stuck_claims requires membership in that evidence set. Old-format
  rows (no field) keep today's behavior — conservative fallback.

Covers:
  RED1: all-OPEN ledger (no dispatch ever, new-format rows) -> HEALTHY,
        queued_claims surfaced (was: STALLED deadlock)
  RED2: dispatched-flat claim -> STALLED still fires (detection NOT weakened)
  RED3: mixed queue + dispatched-flat -> STALLED names only the dispatched
        claim; action distinguishes stuck vs queued
  RED4: writer contract — _append_ledger stamps dispatched_ids
  GUARD1: old-format rows (no dispatched_ids) keep current STALLED behavior
  GUARD2: old-format output shape unchanged (no queued_claims key)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from convergence_health import (  # noqa: E402
    EXIT_HEALTHY,
    EXIT_STALLED,
    assess,
)
import convergence_check as cc  # noqa: E402


BASE = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)


def _snap(i: int, open_count: int, open_ids: list[str],
          dispatched_ids: list[str] | None = None, facts_total: int = 5) -> dict:
    """One ledger snapshot row, mirroring convergence_check._append_ledger.

    dispatched_ids=None models an OLD-format row (pre-#2 writer); a list
    models a NEW-format row."""
    row = {
        "ts": (BASE + timedelta(seconds=60 * i)).isoformat(),
        "decision": "DISPATCH",
        "open_count": open_count,
        "open_ids": open_ids,
        "partial_count": 0,
        "active_workers": 1,
        "blockers": [],
        "facts_total": facts_total,
    }
    if dispatched_ids is not None:
        row["dispatched_ids"] = dispatched_ids
    return row


# =====================================================================
# RED1: all claims OPEN, never dispatched -> HEALTHY, queue surfaced
# =====================================================================

def test_all_queued_never_dispatched_not_stalled():
    """Pure frontier queue (open_ids == all claims, no dispatch evidence on
    any row) sitting 4 snapshots -> NOT STALLED. Before the fix the stuck
    branch fired at 3 consecutive snapshots and deadlocked dispatch."""
    ledger = [
        _snap(0, 3, ["C-1", "C-2", "C-3"], dispatched_ids=[]),
        _snap(1, 3, ["C-1", "C-2", "C-3"], dispatched_ids=[]),
        _snap(2, 3, ["C-1", "C-2", "C-3"], dispatched_ids=[]),
        _snap(3, 3, ["C-1", "C-2", "C-3"], dispatched_ids=[]),
    ]
    r = assess(ledger)  # STALLED before the fix (stuck branch, flatline only 4)
    assert r["verdict"] != "STALLED", \
        f"a never-dispatched queue is frontier, not stuck; got {r['verdict']}"
    assert r["verdict"] == "HEALTHY", f"expected HEALTHY, got {r['verdict']}"
    assert r["exit_code"] == EXIT_HEALTHY
    assert r.get("queued_claims") == 3, \
        f"queued (never-dispatched) count must be surfaced, got {r.get('queued_claims')}"


# =====================================================================
# RED2: dispatched-then-flat claim -> STALLED still fires
# =====================================================================

def test_dispatched_flat_claim_still_stalls():
    """A claim with dispatch evidence sitting in open_ids for 3+ trailing
    snapshots is STILL stuck -> STALLED, exit 1. Guard against weakening
    detection while fixing the queue deadlock."""
    ledger = [
        _snap(0, 1, ["C-2"], dispatched_ids=["C-2"]),
        _snap(1, 1, ["C-2"], dispatched_ids=["C-2"]),
        _snap(2, 1, ["C-2"], dispatched_ids=["C-2"]),
        _snap(3, 1, ["C-2"], dispatched_ids=["C-2"]),
    ]
    r = assess(ledger)
    assert r["verdict"] == "STALLED", \
        f"dispatched-flat claim must still trip STALLED, got {r['verdict']}"
    assert r["exit_code"] == EXIT_STALLED
    named = [s["claim"] for s in r["stuck_claims"]]
    assert named == ["C-2"], f"expected C-2 named stuck, got {named}"


# =====================================================================
# RED3: mixed queue + dispatched-flat -> only the dispatched one named
# =====================================================================

def test_mixed_queue_names_only_dispatched_claim():
    """One queued claim (C-1, never dispatched) + one dispatched-flat claim
    (C-2): STALLED fires on C-2 only, and the action message distinguishes
    stuck (dispatched but flat) from queued (never dispatched)."""
    ledger = [
        _snap(0, 2, ["C-1", "C-2"], dispatched_ids=["C-2"]),
        _snap(1, 2, ["C-1", "C-2"], dispatched_ids=["C-2"]),
        _snap(2, 2, ["C-1", "C-2"], dispatched_ids=["C-2"]),
        _snap(3, 2, ["C-1", "C-2"], dispatched_ids=["C-2"]),
    ]
    r = assess(ledger)
    assert r["verdict"] == "STALLED"
    named = [s["claim"] for s in r["stuck_claims"]]
    assert named == ["C-2"], \
        f"queued C-1 must not be named stuck; got {named}"
    assert r.get("queued_claims") == 1
    action = r["action"]
    assert "never dispatched" in action, \
        f"STALLED action must distinguish queued claims, got: {action}"
    assert "dispatched but flat" in action, \
        f"STALLED action must label stuck claims as dispatched-flat, got: {action}"


# =====================================================================
# RED4: writer contract — _append_ledger stamps dispatched_ids
# =====================================================================

def test_append_ledger_writes_dispatched_ids(tmp_path):
    """dispatched_ids = live claims that are IN_PROGRESS (in flight) or
    carry promotion_attempts >= 1 (recorded worker attempt). Terminal and
    PARK claims are excluded; a missing register degrades to []."""
    reg = tmp_path / "claim-register.yaml"
    reg.write_text(
        "claims:\n"
        "  - id: C-1\n"
        "    status: OPEN\n"
        "    promotion_attempts: 0\n"
        "  - id: C-2\n"
        "    status: IN_PROGRESS\n"
        "    promotion_attempts: 0\n"
        "  - id: C-3\n"
        "    status: OPEN\n"
        "    promotion_attempts: 2\n"
        "  - id: C-4\n"
        "    status: PROVEN\n"
        "    promotion_attempts: 1\n",
        encoding="utf-8")
    d = {"decision": "DISPATCH", "open_count": 2,
         "open_claims": [{"id": "C-1", "status": "OPEN", "blocked": False},
                         {"id": "C-3", "status": "OPEN", "blocked": False}],
         "partial_count": 0, "active_workers": 0, "active_blockers": [],
         "facts_total": 1}
    cc._append_ledger(tmp_path, d)
    rows = [json.loads(l) for l in
            (tmp_path / ".convergence_ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows, "ledger row must be written"
    # before the fix the key is absent (KeyError below)
    assert rows[0]["dispatched_ids"] == ["C-2", "C-3"], \
        f"dispatch evidence must be stamped, got {rows[0].get('dispatched_ids')}"


# =====================================================================
# GUARD1: old-format rows keep current behavior
# =====================================================================

def test_old_format_rows_keep_current_stalled_behavior():
    """Rows without dispatched_ids (pre-#2 ledgers) must keep today's
    behavior: presence in open_ids for 3+ snapshots is stuck -> STALLED."""
    ledger = [
        _snap(0, 1, ["C-2"]),
        _snap(1, 1, ["C-2"]),
        _snap(2, 1, ["C-2"]),
        _snap(3, 1, ["C-2"]),
    ]
    r = assess(ledger)
    assert r["verdict"] == "STALLED", \
        f"old-format rows must keep current STALLED behavior, got {r['verdict']}"
    assert r["exit_code"] == EXIT_STALLED


# =====================================================================
# GUARD2: old-format output shape unchanged
# =====================================================================

def test_old_format_rows_have_no_queued_claims_key():
    """queued_claims is surfaced only when the trailing snapshot carries
    dispatch evidence; old-format ledgers keep their exact prior shape."""
    ledger = [
        _snap(0, 2, ["C-1", "C-2"]),
        _snap(1, 1, ["C-1"]),
        _snap(2, 1, ["C-1"]),
        _snap(3, 1, ["C-1"]),
    ]
    r = assess(ledger)
    assert "queued_claims" not in r, \
        "old-format trailing row must not gain a queued_claims key"
