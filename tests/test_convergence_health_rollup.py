# -*- coding: utf-8 -*-
"""Issue #1: convergence_health crashes with KeyError: 'open_count' on mixed ledgers.

The convergence ledger is shared: convergence_check._append_ledger writes
snapshot rows (no "type" key, carries open_count/open_ids), while
rollup.py and convergence_check.record_operator_action append
OPERATOR_ACTION rows (type="operator_action", NO open_count).
assess() assumed every row was a snapshot → KeyError on the first
non-snapshot row.

Covers:
  RED1: snapshots + rollup row + operator-action row → verdict, no crash,
        trajectory computed from snapshot rows only, count surfaced
  RED2: rollup row BETWEEN identical snapshots → flatline run not broken
        (verdict must stay STALLED, not degrade to HEALTHY)
  RED3: pure snapshot ledger → output shape unchanged (no extra keys)
  RED4: ledger with ONLY non-snapshot rows → NO_DATA, not a crash
  RED5: non-snapshot rows surfaced on the warming-up early-return path too
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from convergence_health import EXIT_NO_DATA, EXIT_STALLED, assess
from status_defs import LedgerLineType


BASE = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


def _snap(i: int, open_count: int, open_ids: list[str], facts_total: int = 5) -> dict:
    """One ledger snapshot row, mirroring convergence_check._append_ledger."""
    return {
        "ts": (BASE + timedelta(seconds=60 * i)).isoformat(),
        "decision": "DISPATCH",
        "open_count": open_count,
        "open_ids": open_ids,
        "partial_count": 0,
        "active_workers": 1,
        "blockers": [],
        "facts_total": facts_total,
    }


def _rollup(i: int, claim_id: str = "C-1") -> dict:
    """One rollup row, mirroring scripts/rollup.py's _append_ledger call."""
    return {
        "type": LedgerLineType.OPERATOR_ACTION,
        "action": "rollup",
        "actor": "orchestrator",
        "claim_id": claim_id,
        "terminal_status": "PROVEN",
        "captured_outcomes": {},
        "lessons_written": 1,
        "lessons_skipped": 0,
        "queue_added": 0,
        "checkpoint_commit": "abc1234",
        "ts": (BASE + timedelta(seconds=60 * i)).isoformat(),
    }


def _operator_action(i: int, action: str = "defer", claim_id: str = "C-2") -> dict:
    """One operator-action row, mirroring convergence_check.record_operator_action."""
    return {
        "type": LedgerLineType.OPERATOR_ACTION,
        "action": action,
        "actor": "orchestrator",
        "claim_id": claim_id,
        "reason": "hard target, waiting",
        "before": "OPEN",
        "after": "DEFERRED",
        "ts": (BASE + timedelta(seconds=60 * i)).isoformat(),
    }


# =====================================================================
# RED1: mixed ledger (snapshots + rollup + operator action) → no crash
# =====================================================================

def test_mixed_ledger_assess_no_keyerror(tmp_path):
    """Snapshots + one rollup row + one operator-action row: assess() must
    return a verdict (no KeyError), compute the trajectory from snapshot
    rows only, and surface the excluded-row count."""
    ledger = [
        _snap(0, 5, ["C-1", "C-2", "C-3", "C-4", "C-5"]),
        _rollup(1),                      # event, not a snapshot
        _snap(2, 4, ["C-3", "C-4", "C-5", "C-6"]),
        _operator_action(3),             # event, not a snapshot
        _snap(4, 3, ["C-6", "C-7", "C-8"]),
        _snap(5, 2, ["C-7", "C-8"]),
    ]
    r = assess(ledger)  # KeyError: 'open_count' before the fix
    assert r["verdict"] == "HEALTHY", f"converging snapshots → HEALTHY, got {r['verdict']}"
    # trajectory from snapshots ONLY (4 of them, 60s apart → no dedup collapse)
    assert r["rounds"] == 4, f"expected 4 snapshot rounds, got {r['rounds']}"
    assert r["first_open_count"] == 5
    assert r["last_open_count"] == 2
    assert r["open_delta"] == -3
    # observability: excluded rows are counted, not silently dropped
    assert r.get("non_snapshot_rows") == 2, \
        f"expected non_snapshot_rows=2, got {r.get('non_snapshot_rows')}"
    # last_snapshot must be a real snapshot row, never an event row
    assert "open_count" in r["last_snapshot"]
    assert r["last_snapshot"].get("type") is None


# =====================================================================
# RED2: rollup row BETWEEN identical snapshots must not break the run
# =====================================================================

def test_rollup_between_snapshots_does_not_break_flatline():
    """6 identical snapshots (60s apart) → STALLED via flatline >= 5.
    A rollup row interleaved mid-run must not split the run: counting it
    (or None-filling its open_count) would truncate the trailing run to 3
    and wrongly return HEALTHY."""
    ledger = [
        _snap(0, 3, ["C-1", "C-2", "C-3"]),
        _snap(1, 3, ["C-1", "C-2", "C-3"]),
        _snap(2, 3, ["C-1", "C-2", "C-3"]),
        _rollup(3),                      # event in the middle of the flatline
        _snap(4, 3, ["C-1", "C-2", "C-3"]),
        _snap(5, 3, ["C-1", "C-2", "C-3"]),
        _snap(6, 3, ["C-1", "C-2", "C-3"]),
    ]
    r = assess(ledger)  # KeyError: 'open_count' before the fix
    assert r["verdict"] == "STALLED", \
        f"flatline of 6 identical snapshots must stay STALLED across the " \
        f"rollup row, got {r['verdict']}"
    assert r["flatline_run"] == 6, \
        f"rollup row must not break the flatline run, got {r['flatline_run']}"
    assert r["exit_code"] == EXIT_STALLED


# =====================================================================
# RED3: pure snapshot ledger → behavior unchanged
# =====================================================================

def test_pure_snapshot_ledger_output_unchanged():
    """No non-snapshot rows → verdicts identical to today and NO extra key
    in the result (output stays byte-identical for pure ledgers)."""
    ledger = [
        _snap(0, 4, ["C-1", "C-2", "C-3", "C-4"], facts_total=4),
        _snap(1, 3, ["C-1", "C-2", "C-3"], facts_total=5),
        _snap(2, 2, ["C-1", "C-2"], facts_total=6),
        _snap(3, 0, [], facts_total=7),
    ]
    r = assess(ledger)
    assert r["verdict"] == "HEALTHY"  # last_open == 0 guard
    assert "non_snapshot_rows" not in r, \
        "pure snapshot ledger must not gain a non_snapshot_rows key"


# =====================================================================
# RED4: ledger with ONLY non-snapshot rows → NO_DATA, not a crash
# =====================================================================

def test_only_non_snapshot_rows_is_no_data():
    """A ledger of only rollup/operator rows has no trajectory to judge."""
    ledger = [_rollup(0), _operator_action(1, action="override_proven")]
    r = assess(ledger)
    assert r["verdict"] == "NO_DATA"
    assert r["exit_code"] == EXIT_NO_DATA
    assert r.get("non_snapshot_rows") == 2


# =====================================================================
# RED5: excluded rows surfaced on the warming-up path too
# =====================================================================

def test_warming_up_surfaces_non_snapshot_rows():
    """Fewer than 3 snapshots → warming-up verdict, but the excluded count
    must still be surfaced."""
    ledger = [_snap(0, 2, ["C-1", "C-2"]), _rollup(1), _snap(2, 1, ["C-1"])]
    r = assess(ledger)
    assert r["verdict"] == "HEALTHY"
    assert r["rounds"] == 2
    assert r.get("non_snapshot_rows") == 1
