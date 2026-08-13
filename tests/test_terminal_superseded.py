# -*- coding: utf-8 -*-
"""RED tests for #59 — SUPERSEDED MUST be a terminal status.

Status quo (bug): SUPERSEDED is not in status_defs.TERMINAL, so both
priority.rank_claims and convergence_check._open_claims treat a superseded
claim as OPEN. The convergence loop then DISPATCHes on already-closed claims
(a2b5e25c C-019: status SUPERSEDED, superseded_by C-037/C-038/C-039).

GREEN = add "SUPERSEDED" to status_defs.TERMINAL; all three core tests flip.
The two OPEN-sanity tests guard against over-exclusion.
"""
from __future__ import annotations

from status_defs import TERMINAL
from priority import rank_claims, DEFAULT_WEIGHTS
from convergence_check import _open_claims


# --- REQ-001: SUPERSEDED membership in TERMINAL ---

def test_superseded_in_terminal():
    assert "SUPERSEDED" in TERMINAL, (
        f"SUPERSEDED missing from TERMINAL (#59 regression); "
        f"current TERMINAL={sorted(TERMINAL)}"
    )


# --- REQ-002: priority.rank_claims excludes SUPERSEDED ---

def test_priority_skips_superseded():
    reg = {"claims": [{"id": "C-019", "status": "SUPERSEDED",
                       "promotion_attempts": 0,
                       "evidence_tier_attempted": 0}]}
    deps = {"depends_on": {}}
    rows = rank_claims(reg, deps, DEFAULT_WEIGHTS, leverage_v2=False)
    assert rows == [], (
        f"SUPERSEDED claim ranked as dispatchable (#59 regression): {rows}"
    )


def test_priority_still_ranks_open():
    """Sanity: a genuinely OPEN claim IS ranked (no over-exclusion)."""
    reg = {"claims": [{"id": "C-099", "status": "OPEN",
                       "promotion_attempts": 0,
                       "evidence_tier_attempted": 0}]}
    deps = {"depends_on": {}}
    rows = rank_claims(reg, deps, DEFAULT_WEIGHTS, leverage_v2=False)
    assert len(rows) == 1 and rows[0]["id"] == "C-099"


# --- REQ-003: convergence_check._open_claims excludes SUPERSEDED ---

def test_convergence_excludes_superseded():
    reg = {"claims": [{"id": "C-019", "status": "SUPERSEDED"}]}
    assert _open_claims(reg) == [], (
        f"SUPERSEDED counted as open (#59 regression): {_open_claims(reg)}"
    )


def test_convergence_still_includes_open():
    """Sanity: a genuinely OPEN claim IS counted (no over-exclusion)."""
    reg = {"claims": [{"id": "C-099", "status": "OPEN"}]}
    open_claims = _open_claims(reg)
    assert len(open_claims) == 1 and open_claims[0]["id"] == "C-099"
