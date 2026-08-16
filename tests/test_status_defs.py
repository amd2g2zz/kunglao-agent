# -*- coding: utf-8 -*-
"""Tests for status_defs.py — single source of truth for claim status sets.

RED phase of the status-defs-safety-net change (GitHub #34). These tests
pin the contract:
- TERMINAL is 8-valued (incl. STALE, SUPERSEDED, DEAD)
- PARTIAL_STATUSES / IN_PROGRESS_STATUSES match the pre-existing semantics
- LedgerLineType distinguishes snapshot (default) from outcome rows
- No consumer script may redefine these sets
"""
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent  # repo root (kunglao-agent/)
SCRIPTS = REPO / "scripts"
HOOKS = REPO / "hooks"

sys.path.insert(0, str(SCRIPTS))
import status_defs  # noqa: E402


# ---------- TERMINAL ----------

def test_terminal_is_8_valued_with_superseded_and_dead():
    assert status_defs.TERMINAL == {
        "PROVEN", "VERIFIED", "NEGATIVE", "REFUTED", "DEFERRED", "STALE",
        "SUPERSEDED", "DEAD",
    }


# ---------- auxiliary sets ----------

def test_partial_statuses_match_existing_semantics():
    assert status_defs.PARTIAL_STATUSES == {
        "PARTIALLY-VERIFIED", "PARTIAL", "PARTIALLY_VERIFIED",
    }


def test_in_progress_statuses_cover_existing_usage():
    # exclusion semantics: IN_PROGRESS = already dispatched, NOT dispatchable
    assert "IN_PROGRESS" in status_defs.IN_PROGRESS_STATUSES
    assert "OPEN" not in status_defs.IN_PROGRESS_STATUSES
    # inclusion semantics: ACTIVE_STATUSES covers claim_expiry's ("OPEN","IN_PROGRESS")
    assert status_defs.ACTIVE_STATUSES == {"OPEN", "IN_PROGRESS"}


# ---------- ledger line types ----------

def test_ledger_line_type_constants():
    assert status_defs.LedgerLineType.SNAPSHOT == "snapshot"
    assert status_defs.LedgerLineType.OUTCOME == "outcome"


def test_snapshot_is_default():
    assert status_defs.ledger_line_type({"ts": "2026-08-11T00:00:00Z", "decision": "DISPATCH"}) == "snapshot"


def test_outcome_row_is_outcome():
    row = {"type": "outcome", "ts": "2026-08-11T00:00:00Z", "claim_id": "C-001", "checker": "verify-note"}
    assert status_defs.ledger_line_type(row) == "outcome"


# ---------- no hardcoded redefinitions ----------

CONSUMERS = [
    "convergence_check.py",
    "priority.py",
    "priority_ratio.py",
    "failure_analysis_gate.py",
    "stale_blocker_prune.py",
    "plan_drift_detector.py",
    "kunglao_record.py",
    "progress_report.py",
]

HOOK_CONSUMERS = [
    "worker_budget.py",
    "state_anchor.py",
]

# Build (path, fname) tuples so parametrize can resolve scripts/ vs hooks/
ALL_CONSUMERS = [(SCRIPTS, f) for f in CONSUMERS] + [(HOOKS, f) for f in HOOK_CONSUMERS]


@pytest.mark.parametrize("dirpath,fname", ALL_CONSUMERS)
def test_consumer_uses_shared_status_module(dirpath, fname):
    """Consumer scripts must import status_defs and must NOT redefine the
    status sets themselves (single source of truth, #34)."""
    text = (dirpath / fname).read_text(encoding="utf-8")
    assert "TERMINAL_STATUS = {" not in text, f"{fname} still defines TERMINAL_STATUS"
    assert "TERMINAL = {" not in text, f"{fname} still defines TERMINAL"
    assert "PARTIAL_STATUSES = {" not in text, f"{fname} still defines PARTIAL_STATUSES"
    assert "status_defs" in text, f"{fname} does not import status_defs"
    assert "from status_defs import" in text, f"{fname} does not use 'from status_defs import'"


# ---------- module compiles & docstring has the operating manual ----------

def test_module_compiles():
    importlib.reload(status_defs)
    assert status_defs.TERMINAL


def test_docstring_has_dead_procedure():
    doc = status_defs.__doc__ or ""
    assert "DEAD" in doc
    assert "TERMINAL" in doc
