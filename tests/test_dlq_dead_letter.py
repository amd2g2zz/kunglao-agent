# -*- coding: utf-8 -*-
"""Contract + integration tests for #36 — DEAD status + dead-letter quarantine.

Contract (mirrors tests/test_terminal_superseded.py style):
  - DEAD is a member of status_defs.TERMINAL and not partial / in-progress.
  - priority.rank_claims excludes DEAD claims (dispatch never spins on poison).
  - convergence_check._open_claims excludes DEAD claims (loop can CONVERGE).

Integration:
  - worker_pulse._build_pulse surfaces a `quarantined=N` flag on a workspace
    with DEAD claims, and omits it when there are none.

The dead_letter.py module API (mark_dead / scan / detect_dirty_statuses /
count_dead) is covered by scripts/test_dead_letter.py.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from status_defs import TERMINAL, PARTIAL_STATUSES, IN_PROGRESS_STATUSES
from priority import rank_claims, DEFAULT_WEIGHTS
from convergence_check import _open_claims


# --- REQ-001: DEAD membership in TERMINAL ---

def test_dead_in_terminal():
    assert "DEAD" in TERMINAL, (
        f"DEAD missing from TERMINAL (#36 regression); "
        f"current TERMINAL={sorted(TERMINAL)}"
    )


def test_terminal_is_8_valued_with_dead():
    assert TERMINAL == {
        "PROVEN", "VERIFIED", "NEGATIVE", "REFUTED", "DEFERRED",
        "STALE", "SUPERSEDED", "DEAD",
    }


def test_dead_not_partial_not_in_progress():
    assert "DEAD" not in PARTIAL_STATUSES
    assert "DEAD" not in IN_PROGRESS_STATUSES


# --- REQ-002: priority.rank_claims excludes DEAD ---

def test_priority_skips_dead():
    reg = {"claims": [{"id": "C-036", "status": "DEAD",
                       "promotion_attempts": 5,
                       "evidence_tier_attempted": 0}]}
    deps = {"depends_on": {}}
    rows = rank_claims(reg, deps, DEFAULT_WEIGHTS, leverage_v2=False)
    assert rows == [], (
        f"DEAD claim ranked as dispatchable (#36 regression): {rows}"
    )


def test_priority_still_ranks_open():
    """Sanity: a genuinely OPEN claim IS ranked (no over-exclusion)."""
    reg = {"claims": [{"id": "C-099", "status": "OPEN",
                       "promotion_attempts": 0,
                       "evidence_tier_attempted": 0}]}
    deps = {"depends_on": {}}
    rows = rank_claims(reg, deps, DEFAULT_WEIGHTS, leverage_v2=False)
    assert len(rows) == 1 and rows[0]["id"] == "C-099"


# --- REQ-003: convergence_check._open_claims excludes DEAD ---

def test_convergence_excludes_dead():
    reg = {"claims": [{"id": "C-036", "status": "DEAD"}]}
    assert _open_claims(reg) == [], (
        f"DEAD counted as open (#36 regression): {_open_claims(reg)}"
    )


def test_convergence_still_includes_open():
    """Sanity: a genuinely OPEN claim IS counted (no over-exclusion)."""
    reg = {"claims": [{"id": "C-099", "status": "OPEN"}]}
    open_claims = _open_claims(reg)
    assert len(open_claims) == 1 and open_claims[0]["id"] == "C-099"


# --- REQ-004: worker_pulse quarantined flag ---

def _write_reg(ws: Path, claims: list) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_worker_pulse_shows_quarantined_flag(tmp_path):
    """A workspace with a DEAD claim surfaces quarantined=1 in the pulse."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
    import worker_pulse as wp

    ws = tmp_path / "ws-dead"
    ws.mkdir()
    _write_reg(ws, [{"id": "C-036", "status": "DEAD", "promotion_attempts": 5}])

    pulse, decision = wp._build_pulse(ws)
    assert "quarantined=1" in pulse, (
        f"pulse must flag quarantined=1 for a DEAD claim; got:\n{pulse}"
    )


def test_worker_pulse_omits_quarantined_when_clean(tmp_path):
    """A workspace with no DEAD claim omits the quarantined flag."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
    import worker_pulse as wp

    ws = tmp_path / "ws-clean"
    ws.mkdir()
    _write_reg(ws, [{"id": "C-099", "status": "PROVEN"}])

    pulse, decision = wp._build_pulse(ws)
    assert "quarantined=" not in pulse, (
        f"pulse must NOT carry a quarantined flag when no DEAD claim; got:\n{pulse}"
    )
