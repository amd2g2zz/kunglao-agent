# -*- coding: utf-8 -*-
"""tests/test_decompat_804.py — #804 full-collapse de-compat pins.

Every pin here states the NEW loud gap where a compatibility fallback
used to serve the old behavior (mandate 2026-10-25: no compatibility,
migration = regeneration, old fallback -> new loud gap):

  1. q_cells fold: rows without an ``arm_key`` add NO posterior mass
     and NO pending count — they are counted in ``Fold.unkeyed`` (the
     un-attributed rate signal, mirroring kunglao_log's null-actor gap).
     The pre-#804 dual-write tolerance (fallback to the bare
     ``method_family`` cell) is retired.
  2. q_cells cell_posterior: the #539/#545 legacy tolerance (pooling the
     bare-family cell into a keyed local read) is retired — a keyed read
     sees ONLY its own cell as local mass.
  3. q_cells declared_family: the v0 prose marker fallback (``method-family:``
     in the prompt text) is retired — the envelope meta field is the only
     declaration face.
  4. kunglao_log actor vocabulary: LEGACY_ACTORS words whose emitters were
     migrated to strict shapes no longer validate bare (the adopted set
     only shrinks, #879 + #804).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rlvr import q_cells  # noqa: E402


def _row(sig: str, fam: str, credit, *, arm_key=None, source="settlement"):
    row = {"schema": q_cells.OBS_SCHEMA, "ts": "2026-10-25T00:00:00Z",
           "source": source, "signature_hash": sig, "method_family": fam,
           "credit": credit}
    if arm_key is not None:
        row["arm_key"] = arm_key
    return row


# ------------------------------------------------ 1. fold: unkeyed gap

def test_unkeyed_settled_row_banks_no_mass_and_counts_the_gap():
    """The old log tolerance is retired: a settled row without arm_key
    folds NOWHERE (no success/failure mass in any cell) and is counted
    in Fold.unkeyed — the loud un-attributed gap."""
    rows = [_row("aaaa00000000", "static-symbolic", 1.0)]
    fold = q_cells.fold(q_cells.InMemoryStore(rows), gamma=1.0)
    assert fold.cells == {} or all(
        c.success == 0.0 and c.failure == 0.0 for c in fold.cells.values())
    assert fold.unkeyed == 1


def test_unkeyed_pending_row_banks_no_pending_count():
    rows = [_row("bbbb00000000", "static-symbolic", None,
                 source="dispatch")]
    fold = q_cells.fold(q_cells.InMemoryStore(rows), gamma=1.0)
    assert all(c.n_pending == 0 for c in fold.cells.values())
    assert fold.unkeyed == 1


def test_keyed_row_still_folds_exactly():
    """Regression guard: the keyed (arm_key-carrying) consumption face is
    unchanged — the same row WITH the key banks full mass."""
    rows = [_row("cccc00000000", "static-symbolic", 1.0,
                 arm_key="static-symbolic|facts_snapshot|none|0")]
    fold = q_cells.fold(q_cells.InMemoryStore(rows), gamma=1.0)
    cell = fold.cells[("cccc00000000",
                       "static-symbolic|facts_snapshot|none|0")]
    assert cell.success == pytest.approx(1.0)
    assert cell.failure == pytest.approx(0.0)
    assert fold.unkeyed == 0


def test_unkeyed_rows_stay_in_the_gamma_chain():
    """The unkeyed row is a real outcome — the γ schedule must OBSERVE
    it (the adaptive γ after a success differs from after a failure),
    even though no cell mass banks. If the fold dropped unkeyed rows
    from the chain, both streams' keyed masses would be identical."""
    def _stream(unkeyed_credit):
        return [
            _row("dddd00000000", "fam", unkeyed_credit),      # unkeyed (first)
            _row("eeee00000000", "fam", 1.0,
                 arm_key="fam|facts_snapshot|none|0"),        # keyed
            _row("ffff00000000", "fam", 1.0,
                 arm_key="fam|facts_snapshot|none|0"),        # keyed (last)
        ]

    after_success = q_cells.fold(
        q_cells.InMemoryStore(_stream(1.0))).cells[
            ("eeee00000000", "fam|facts_snapshot|none|0")]
    after_failure = q_cells.fold(
        q_cells.InMemoryStore(_stream(0.0))).cells[
            ("eeee00000000", "fam|facts_snapshot|none|0")]
    # the γ after the unkeyed outcome decays the middle keyed row (< 1.0)
    assert after_success.success < 1.0
    # and the schedule FELT the unkeyed outcome (success vs failure move
    # the adaptive γ differently -> different decayed masses)
    assert after_success.success != after_failure.success


# --------------------------------- 2. cell_posterior: no legacy pooling

def test_keyed_local_read_never_pools_the_bare_family_cell():
    """The #539/#545 tolerance pooled the bare (sig, family) cell into a
    keyed local read. Retired: local mass = the keyed cell ONLY; the
    bare-family cell (wherever it came from) stays in the leave-one-out
    anchor, never in local."""
    bare = q_cells.CellCounts("aaaaaaaa0000", "fam",
                              success=10.0, failure=0.0)
    keyed = q_cells.CellCounts("aaaaaaaa0000", "fam|facts_snapshot|none|0",
                               success=2.0, failure=1.0)
    fold_view = q_cells.Fold(cells={
        ("aaaaaaaa0000", "fam"): bare,
        ("aaaaaaaa0000", "fam|facts_snapshot|none|0"): keyed,
    })
    # local = the keyed cell only (2,1); anchor = family mass (12,1)
    # minus local = (10,0); m = (1+10)/(2+10), w = min(8, 10) = 8.
    # Exact posterior under the retired-pooling law:
    a, b = q_cells.cell_posterior(
        fold_view, "aaaaaaaa0000", "fam",
        arm_key="fam|facts_snapshot|none|0")
    assert a == pytest.approx(1.0 + 8.0 * (11.0 / 12.0) + 2.0)
    assert b == pytest.approx(1.0 + 8.0 * (1.0 / 12.0) + 1.0)
    # the OLD pooling face returned (13.0, 2.0) — the bare cell rode local.
    assert (a, b) != (13.0, 2.0)


# --------------------------------- 3. declared_family: envelope only

def test_declared_family_envelope_field_is_the_only_face():
    assert q_cells.declared_family(
        {"method_family": "static-symbolic"}, "junk") == "static-symbolic"


def test_declared_family_prose_marker_is_no_longer_a_declaration():
    """The v0 prose marker (dead since #432 went universal) is retired:
    a prompt carrying `method-family: X` without the envelope field is
    the undeclared honest gap."""
    out = q_cells.declared_family(None, "do things\nmethod-family: ")
    assert out is None
    assert q_cells.declared_family(None, "x\nmethod-family: dynamic-tr\n") \
        is None


# --------------------------------- 4. observe(): the keyed bank face

def test_observe_accepts_an_explicit_arm_key(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    q_cells.observe(ws, "abcdabcdabcd", "static-symbolic", 0.5,
                    arm_key="static-symbolic|full_recall|none|0")
    rows = q_cells.JSONLQStore(ws).observations()
    assert rows[0]["arm_key"] == "static-symbolic|full_recall|none|0"
