# -*- coding: utf-8 -*-
"""Contract + integration tests for #36 — DEAD status + dead-letter quarantine.

Contract (mirrors tests/test_terminal_superseded.py style):
  - DEAD is a member of status_defs.TERMINAL and not partial / in-progress.
  - convergence_check._open_claims excludes DEAD claims (loop can CONVERGE).

Dispatch-queue exclusion of DEAD claims (the former priority.rank_claims
tests, removed with the #916 compat zombie) now lives in
scripts/priority_ratio.py (is_open filtering).

Integration:
  - worker_pulse._build_pulse surfaces a `quarantined=N` flag on a workspace
    with DEAD claims, and omits it when there are none.

The dead_letter.py module API (mark_dead / scan / detect_dirty_statuses /
count_dead) is covered by tests/test_dead_letter.py.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from status_defs import PARTIAL_STATUSES, IN_PROGRESS_STATUSES
from convergence_check import _open_claims


# --- REQ-001: DEAD membership in TERMINAL ---
# The 8-valued TERMINAL equality is pinned in tests/test_status_defs.py
# (test_terminal_is_8_valued_with_superseded_and_dead); DEAD membership is a
# redundant re-derivation of that pin.

def test_dead_not_partial_not_in_progress():
    assert "DEAD" not in PARTIAL_STATUSES
    assert "DEAD" not in IN_PROGRESS_STATUSES


# --- REQ-002: convergence_check._open_claims excludes DEAD ---

def test_convergence_excludes_dead():
    reg = {"claims": [{"id": "C-036", "status": "DEAD"}]}
    assert _open_claims(reg) == [], (
        f"DEAD counted as open (#36 regression): {_open_claims(reg)}"
    )


# --- REQ-003: worker_pulse quarantined flag ---

def _write_reg(ws: Path, claims: list) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_worker_pulse_shows_quarantined_flag(tmp_path):
    """A workspace with a DEAD claim surfaces quarantined=1 in the pulse."""
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
    import worker_pulse as wp

    ws = tmp_path / "ws-clean"
    ws.mkdir()
    _write_reg(ws, [{"id": "C-099", "status": "PROVEN"}])

    pulse, decision = wp._build_pulse(ws)
    assert "quarantined=" not in pulse, (
        f"pulse must NOT carry a quarantined flag when no DEAD claim; got:\n{pulse}"
    )
