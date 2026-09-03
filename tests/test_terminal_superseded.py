# -*- coding: utf-8 -*-
"""RED tests for #59 — SUPERSEDED MUST be a terminal status.

Status quo (bug): SUPERSEDED is not in status_defs.TERMINAL, so
convergence_check._open_claims treats a superseded claim as OPEN. The
convergence loop then DISPATCHes on already-closed claims
(a2b5e25c C-019: status SUPERSEDED, superseded_by C-037/C-038/C-039).

GREEN = add "SUPERSEDED" to status_defs.TERMINAL; the convergence tests flip.
Dispatch-queue exclusion of SUPERSEDED (the former priority.rank_claims
tests, removed with the #916 compat zombie) now lives in
scripts/priority_ratio.py (is_open filtering). The OPEN-sanity test guards
against over-exclusion.
"""
from __future__ import annotations

from convergence_check import _open_claims


# --- REQ-001: SUPERSEDED membership in TERMINAL ---
# The 8-valued TERMINAL equality is pinned in tests/test_status_defs.py
# (test_terminal_is_8_valued_with_superseded_and_dead); SUPERSEDED membership
# is a redundant re-derivation of that pin.

# --- REQ-002: convergence_check._open_claims excludes SUPERSEDED ---

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
