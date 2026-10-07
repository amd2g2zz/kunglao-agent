# -*- coding: utf-8 -*-
"""tests/test_ws2_tiebreaker_545.py — the #548 UNFAIR verdict's fix, riding
the WS2 consumption switch. The censored-review data (PR #549): censored
acts moved Φ +0.079 while clean failures moved −0.009, yet both bank ≈0.5
credit — the punishment does not track state work. The tiebreaker: the
credit read applies PHI_TIEBREAK_WEIGHT · phi_delta BEFORE the [0,1] clamp,
so at equal banked credit the row that moved the state forward folds
stronger. r_incr stays the recorded raw material; Φ is the honest signal
(the cost term must not masquerade as signal — the #549 ruling), so the
one carried field is phi_delta.

Pins:

  1. fold: at equal banked credit, phi_delta separates the masses —
     censored-with-facts folds stronger than a clean failure.
  2. rows without phi_delta are bit-identical to the pre-change fold
     (the determinism wall).
  3. the clamp: a large positive phi_delta never pushes credit past 1.0.
  4. the store row carries phi_delta, and the warm-pool masses apply the
     same adjustment (both consumption faces move together).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr import q_cells  # noqa: E402
from rlvr import strategy_store  # noqa: E402


def _row(sig, credit, phi_delta=None):
    return {"schema": q_cells.OBS_SCHEMA, "ts": "2026-10-07T00:00:00Z",
            "source": "settlement", "signature_hash": sig,
            "method_family": "hypothesis-falsification", "claim": None,
            "agent": None, "credit": credit, "arm_key": None,
            "phi_delta": phi_delta}


def test_equal_credit_rows_separated_by_phi_delta():
    """The #548 shape: censored-with-facts (+Φ) vs clean failure (−Φ) at
    the same banked credit — the fold must rank the state-moving row
    stronger."""
    sig = "aaaa0000aaaa"
    censored = _row(sig, 0.5, phi_delta=0.2)   # moved the state forward
    clean = _row(sig, 0.5, phi_delta=-0.05)    # moved it backward
    view = q_cells.fold(q_cells.InMemoryStore([clean, censored]))
    cell = view.cells[(sig, "hypothesis-falsification")]
    w_tb = q_cells.PHI_TIEBREAK_WEIGHT
    assert cell.success == pytest.approx(0.5 + w_tb * 0.2 + 0.5 - w_tb * 0.05)
    assert cell.failure == pytest.approx(2.0 - cell.success)
    # and the same two rows WITHOUT phi_delta fold as a plain tie
    plain = q_cells.fold(q_cells.InMemoryStore(
        [_row(sig, 0.5), _row(sig, 0.5)])).cells[(sig, "hypothesis-falsification")]
    assert plain.success == pytest.approx(1.0)
    assert cell.success > plain.success, \
        "the phi_delta tiebreaker must break the equal-credit tie upward " \
        "for the state-moving row"


def test_rows_without_phi_delta_are_bit_identical():
    sig = "bbbb0000bbbb"
    rows = [_row(sig, 1.0), _row(sig, 0.0), _row(sig, 0.5)]
    view = q_cells.fold(q_cells.InMemoryStore(rows))
    cell = view.cells[(sig, "hypothesis-falsification")]
    assert cell.success == 1.5 and cell.failure == 1.5, \
        "absent phi_delta: the fold is byte-identical to the pre-change " \
        "kernel (x + W·0.0 must never leave a residue)"


def test_tiebreaker_never_pushes_credit_past_the_rail():
    sig = "cccc0000cccc"
    view = q_cells.fold(q_cells.InMemoryStore([_row(sig, 1.0, 0.9)]))
    cell = view.cells[(sig, "hypothesis-falsification")]
    assert cell.success == 1.0 and cell.failure == 0.0, \
        "the clamp holds: effective credit stays in [0, 1]"


def test_non_numeric_phi_delta_fails_open_to_zero(tmp_path):
    sig = "dddd0000dddd"
    view = q_cells.fold(q_cells.InMemoryStore(
        [_row(sig, 0.5, phi_delta="bogus")]))
    cell = view.cells[(sig, "hypothesis-falsification")]
    assert cell.success == 0.5 and cell.failure == 0.5


def test_store_rows_carry_phi_delta_and_pools_apply_it(
        tmp_path, monkeypatch):
    """Both consumption faces move together: the store row records
    phi_delta and the warm-pool masses use the tiebroken credit."""
    root = tmp_path / "store"
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(root))
    strategy_store.append_row({
        "schema": strategy_store.STORE_SCHEMA,
        "ts": "2026-10-07T00:00:00Z",
        "workspace_id": "ws-donor",
        "arm_key": "kdf-chain-reconstruction|facts_snapshot|none|1",
        "method_family": "kdf-chain-reconstruction",
        "feature_key": "none",
        "fingerprint": "fp",
        "status": "TIMEOUT",
        "credit": 0.5,
        "censored": True,
        "facts_citing": 2,
        "propensity": 1.0,
        "phi_delta": 0.2,
        "provenance": {"dispatch_id": "C-004"},
    })
    rows = strategy_store.load_rows(ws=None)
    assert rows[0]["phi_delta"] == 0.2
    pools = strategy_store.warm_pools(tmp_path / "ws", [
        "kdf-chain-reconstruction"])
    pool = pools["kdf-chain-reconstruction"]
    from rlvr import meta_arms  # noqa: PLC0415
    lam = meta_arms.LAMBDA
    eff = min(1.0, 0.5 + q_cells.PHI_TIEBREAK_WEIGHT * 0.2)
    assert pool.success == pytest.approx(lam * eff)
    assert pool.failure == pytest.approx(lam * (1.0 - eff))
    assert pool.rows == 1
