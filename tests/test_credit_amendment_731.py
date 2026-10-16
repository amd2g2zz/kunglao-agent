# -*- coding: utf-8 -*-
"""tests/test_credit_amendment_731.py — the learning signal tracks the
ledger (issue 731).

`scalar.settle_round_credit` banks a dispatch's ladder credit into the
Q-cell store ONCE — at the first settlement. Every later correction of
the ledger value (the issue 433 late-cite amendment, evidence repair that
shifts `r`) refined the LEDGER only: the posterior carried the old
wrong credit forever, and a bank that failed on the first pass stayed
failed.

The fix, pinned here:

  1. a `credit_amendment` SIGNED kind rides the issue 712 verbatim-delta
     fold branch (no band, no tiebreak, no γ-EMA feeding, admitted to
     the posterior);
  2. `amend_settlement` moves banked mass to a target exactly once and
     is a no-op when already current;
  3. amendment rows carry `source: "credit-amendment"` so every
     settlement-keyed ad-hoc reader stays blind;
  4. the settle pass reconciles every already-settled row: corrected
     ledger → one amendment; missed bank → first bank via the q-cell
     faces DIRECTLY (the strategy store / L1 legs must not
     double-write); pure replay → nothing.

Harness-audit defensive pins (2026-10-16 three-agent sweep): the OPE
propensity Beta parameters are floored (a clawback stream can no
longer crash `betavariate`), and `cell_count` does not count a
correction as a new observation.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import settle_round_credit as src  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import meta_arms  # noqa: E402
from rlvr import q_cells as qc  # noqa: E402
from rlvr import strategy_store as ss  # noqa: E402

FAM = "static-symbolic"


# ---------- fixtures --------------------------------------------------------

def _ws(tmp_path: Path, claims: list[dict] | None = None) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims or []}), encoding="utf-8")
    return ws


def _dispatch(ws: Path, claim: str) -> None:
    qc.record_dispatch_observation(
        ws, "dispatch envelope",
        envelope_meta={"method_family": FAM}, claim=claim)


def _rows(ws: Path) -> list[dict]:
    return qc.JSONLQStore(ws).observations()


def _amendment_rows(ws: Path) -> list[dict]:
    return [r for r in _rows(ws)
            if r.get("credit_kind") == "credit_amendment"]


class _RecordingSchedule:
    """A γ schedule that records what the fold feeds it (the EMA pin)."""

    def __init__(self) -> None:
        self.observed: list[float] = []

    def gamma(self) -> float:
        return 0.9

    def observe(self, outcome) -> None:
        self.observed.append(float(outcome))


def _cell(ws: Path, gamma=1.0):
    return qc.fold(qc.JSONLQStore(ws), gamma=gamma)


def _cell_at(ws: Path, sig: str, gamma=1.0):
    """The ONE cell whose signature matches (the action-key half of the
    fold's key is the row's arm_key — the test pins mass, not keys)."""
    cells = [(k, c) for k, c in _cell(ws, gamma=gamma).cells.items()
             if k[0] == str(sig)]
    assert len(cells) == 1, cells
    return cells[0][1]


# ---------- 1. the fold: verbatim signed mass -------------------------------

def test_amendment_row_folds_verbatim(tmp_path):
    """A signed amendment row applies Δsuccess/Δfailure verbatim —
    outside the band, the tiebreak, and the [0,1] clamp: a clawback
    from 0.8 to 0.2 lands the cell on (0.2, 0.8)."""
    ws = _ws(tmp_path)
    qc.append_observation(ws, "sig", FAM, 0.8, source="settlement",
                          claim="C-1", dispatch_id="C-1")
    qc.append_observation(ws, "sig", FAM, -0.6, source="credit-amendment",
                          credit_kind=qc.CREDIT_KIND_CREDIT_AMENDMENT,
                          failure_delta=0.6, claim="C-1",
                          dispatch_id="C-1")
    cell = _cell(ws).cells[("sig", FAM)]
    assert cell.success == pytest.approx(0.2)
    assert cell.failure == pytest.approx(0.8)


def test_amendment_excluded_from_gamma_ema(tmp_path):
    """The γ schedule never observes a signed row — a clawback must not
    drag the schedule's adaptive state off its declared range."""
    ws = _ws(tmp_path)
    qc.append_observation(ws, "sig", FAM, 0.6, source="settlement",
                          claim="C-1", dispatch_id="C-1")
    qc.append_observation(ws, "sig", FAM, -0.4,
                          source="credit-amendment",
                          credit_kind=qc.CREDIT_KIND_CREDIT_AMENDMENT,
                          failure_delta=0.4, claim="C-1",
                          dispatch_id="C-1")
    sched = _RecordingSchedule()
    _cell(ws, gamma=sched)
    assert sched.observed == [0.6]


def test_amendment_admitted_to_posterior(tmp_path):
    """Unlike issue 705 verification rows, a correction is outcome data: it
    moves the posterior while the verification row beside it stays
    inert (that is the whole point of the correction)."""
    ws = _ws(tmp_path)
    qc.append_observation(ws, "sig", FAM, 0.8, source="settlement",
                          claim="C-1", dispatch_id="C-1")
    qc.append_observation(ws, "sig", FAM, 0.8, source="settlement",
                          credit_kind="verification", claim="C-1",
                          dispatch_id="C-1")
    before = _cell_at(ws, "sig")
    assert before.success == pytest.approx(0.8)   # verification inert
    qc.append_observation(ws, "sig", FAM, -0.3,
                          source="credit-amendment",
                          credit_kind=qc.CREDIT_KIND_CREDIT_AMENDMENT,
                          failure_delta=0.3, claim="C-1",
                          dispatch_id="C-1")
    after = _cell_at(ws, "sig")
    assert after.success == pytest.approx(before.success - 0.3)
    assert after.failure == pytest.approx(before.failure + 0.3)


# ---------- 2. the append boundary takes the signed credit ------------------

def test_boundary_takes_signed_amendment(tmp_path):
    ws = _ws(tmp_path)
    out = qc.append_observation(ws, "sig", FAM, -0.4,
                                source="credit-amendment",
                                credit_kind=qc.CREDIT_KIND_CREDIT_AMENDMENT,
                                failure_delta=0.4, claim="C-1",
                                dispatch_id="C-1", reason="ledger-x")
    row = out["row"]
    assert row["credit"] == -0.4          # NOT clamped
    assert row["failure_delta"] == 0.4
    assert row["reason"] == "ledger-x"
    assert row["source"] == "credit-amendment"


def test_solve_rows_keep_their_clamp_and_shape(tmp_path):
    """Byte-identity wall: a solve row keeps the [0,1] clamp and grows
    neither a kind column nor a reason column."""
    ws = _ws(tmp_path)
    out = qc.append_observation(ws, "sig", FAM, -0.4,
                                source="settlement", claim="C-1",
                                dispatch_id="C-1")
    row = out["row"]
    assert row["credit"] == 0.0           # clamped, as always
    assert "credit_kind" not in row
    assert "reason" not in row
    assert "failure_delta" not in row


# ---------- 3. amend_settlement: move mass to a target ----------------------

def test_amend_settlement_moves_mass_once(tmp_path):
    ws = _ws(tmp_path)
    _dispatch(ws, "C-1")
    qc.observe_settlement(ws, "C-1", 0.2)
    out = qc.amend_settlement(ws, "C-1", 0.8, reason="ledger-amendment")
    assert out["appended"] is True
    rows = _amendment_rows(ws)
    assert len(rows) == 1
    assert rows[0]["source"] == "credit-amendment"
    assert rows[0]["reason"] == "ledger-amendment"
    cell = _cell_at(ws, rows[0]["signature_hash"])
    assert cell.success == pytest.approx(0.8)
    assert cell.failure == pytest.approx(0.2)


def test_amend_settlement_idempotent(tmp_path):
    ws = _ws(tmp_path)
    _dispatch(ws, "C-1")
    qc.observe_settlement(ws, "C-1", 0.2)
    assert qc.amend_settlement(ws, "C-1", 0.8,
                               reason="r")["appended"] is True
    n = len(_rows(ws))
    again = qc.amend_settlement(ws, "C-1", 0.8, reason="r")
    assert again["appended"] is False
    assert len(_rows(ws)) == n            # byte-identical no-op


def test_amend_half_grid_target_is_idempotent(tmp_path):
    """The review's non-idempotence class: a target on the 6-dp HALF
    grid (the ms-precision wall-overrun reward shape lands exactly
    there) must converge. The target is rounded onto the SAME 6-dp grid
    the banked read and the delta rounding live on — an unrounded
    target oscillated ±1e-6 and re-appended every pass forever."""
    ws = _ws(tmp_path)
    _dispatch(ws, "C-1")
    qc.observe_settlement(ws, "C-1", 0.9979325)
    # the SAME value as target: zero-rounded delta, no row, ever
    assert qc.amend_settlement(
        ws, "C-1", 0.9979325, reason="r")["appended"] is False
    # a half-grid correction: at most ONE row, then converged
    _dispatch(ws, "C-2")
    qc.append_observation(ws, "sig2", FAM, 0.123456, source="settlement",
                          claim="C-2", dispatch_id="C-2")
    qc.amend_settlement(ws, "C-2", 0.1234565, reason="r")
    n = len(_rows(ws))
    for _ in range(3):
        again = qc.amend_settlement(ws, "C-2", 0.1234565, reason="r")
        assert again["appended"] is False
    assert len(_rows(ws)) == n            # no oscillation, no growth


def test_banked_mass_skips_verification_rows(tmp_path):
    """banked_mass mirrors the fold's admission: a verification row is
    inadmissible to the posterior, so the operand must not count it —
    otherwise the amendment math lands the WRONG direction. All three
    rows share the dispatch row's cell (the production identity)."""
    ws = _ws(tmp_path)
    _dispatch(ws, "C-1")
    sig = str([r for r in _rows(ws)
               if r.get("source") == "dispatch"][0]["signature_hash"])
    qc.observe_settlement(ws, "C-1", 0.2)
    qc.append_observation(ws, sig, FAM, 0.8, source="settlement",
                          credit_kind="verification", claim="C-1",
                          dispatch_id="C-1")
    assert qc.banked_mass(ws, "C-1") == (0.2, 0.8, 1)
    out = qc.amend_settlement(ws, "C-1", 0.8, reason="r")
    assert out["appended"] is True
    row = _amendment_rows(ws)[0]
    cell = _cell_at(ws, row["signature_hash"])
    assert cell.success == pytest.approx(0.8)
    assert cell.failure == pytest.approx(0.2)


def test_amend_is_the_honest_gap_when_nothing_banked(tmp_path):
    """No pending dispatch row and no banked row → the correction has no
    cell to land in: nothing written, never a fabricated bucket."""
    ws = _ws(tmp_path)
    out = qc.amend_settlement(ws, "C-404", 0.9, reason="r")
    assert out["appended"] is False
    assert out["matched"] is False
    assert _rows(ws) == []


def test_amend_identity_fallback_through_the_banked_row(tmp_path):
    """A pruned dispatch row must not orphan a correction: the latest
    banked settlement row carries the cell identity itself."""
    ws = _ws(tmp_path)
    qc.append_observation(ws, "sig-banked", FAM, 0.5,
                          source="settlement", claim="C-1",
                          dispatch_id="C-1")
    out = qc.amend_settlement(ws, "C-1", 0.9, reason="r")
    assert out["appended"] is True
    row = _amendment_rows(ws)[0]
    assert row["signature_hash"] == "sig-banked"
    cell = _cell(ws).cells[("sig-banked", FAM)]
    assert cell.success == pytest.approx(0.9)
    assert cell.failure == pytest.approx(0.1)


def test_amend_accounts_step_mass(tmp_path):
    """The operand is the fold's full mass view: step rows + settlement
    rows. A corrected target lands the CUMULATIVE mass on the target —
    the issue 712 endpoint contract, now correction-safe. (The fixture rides
    the production residual path — a raw observe_settlement beside
    steps would be the unphysical state the bank never writes.)"""
    from rlvr import scalar as scalar_mod

    ws = _ws(tmp_path)
    _dispatch(ws, "C-1")
    qc.observe_step_credit(ws, "C-1", 0.3)
    d_s, d_f = scalar_mod._calibration_delta(
        0.7, 0.3, 1, band_ceil=qc.OBSERVATION_BAND_CEIL)
    qc.observe_step_calibration(ws, "C-1", d_s, failure_delta=d_f)
    assert _cell_at(ws, _rows(ws)[1]["signature_hash"]).success \
        == pytest.approx(0.7)
    # cumulative is already 0.7; amend to 0.9 → one Δ of +0.2
    out = qc.amend_settlement(ws, "C-1", 0.9, reason="r")
    assert out["appended"] is True
    row = _amendment_rows(ws)[0]
    cell = _cell_at(ws, row["signature_hash"])
    assert cell.success == pytest.approx(0.9)
    assert cell.failure == pytest.approx(0.1)


# ---------- 4. banked_mass mirrors the fold ---------------------------------

def test_banked_mass_mirrors_the_fold(tmp_path):
    ws = _ws(tmp_path)
    # band-valued solve row: existence, zero mass — but it IS a row
    qc.append_observation(ws, "sig", FAM, 0.05, source="settlement",
                          claim="C-1", dispatch_id="C-1")
    s, f, n = qc.banked_mass(ws, "C-1")
    assert (s, f, n) == (0.0, 0.0, 1)
    # tiebroken solve row: the tiebroken value is the mass
    qc.append_observation(ws, "sig", FAM, 0.5, source="settlement",
                          claim="C-1", dispatch_id="C-1",
                          phi_delta=1.0)
    s, f, n = qc.banked_mass(ws, "C-1")
    tb = qc.tiebroken_credit(0.5, 1.0)
    assert s == pytest.approx(tb)
    assert f == pytest.approx(1.0 - tb)
    # a signed amendment rides verbatim
    qc.append_observation(ws, "sig", FAM, -0.2,
                          source="credit-amendment",
                          credit_kind=qc.CREDIT_KIND_CREDIT_AMENDMENT,
                          failure_delta=0.2, claim="C-1",
                          dispatch_id="C-1")
    s, f, n = qc.banked_mass(ws, "C-1")
    assert s == pytest.approx(tb - 0.2)
    assert f == pytest.approx(1.0 - tb + 0.2)
    assert n == 3


# ---------- 5. the settle pass reconciles ------------------------------------

def test_settle_pass_reconciles_a_corrected_ledger(tmp_path):
    """The e2e face: pass 1 banks r(REFUTED); the evidence is corrected;
    pass 2 appends exactly one amendment and the mass lands on the new
    target; pass 3 is a no-op."""
    ws = _ws(tmp_path, claims=[{"id": "C-9", "status": "REFUTED"}])
    _dispatch(ws, "C-9")
    src.run(ws)
    s1, _, _ = qc.banked_mass(ws, "C-9")
    n1 = len(_rows(ws))
    # the correction: the evidence flips to a proven, verified fact
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-9", "status": "PROVEN"}]}),
        encoding="utf-8")
    (ws / "facts" / "F-1.md").write_text(
        "---\nid: F-1\ntype: fact\nstatus: PROVEN\n"
        "verify_status: passes\nclaim_id: C-9\ncreator: C-9\n"
        "---\n\nbody\n", encoding="utf-8")
    out2 = src.run(ws)
    assert out2.get("amended") == 1, out2
    s2, f2, _ = qc.banked_mass(ws, "C-9")
    assert (s2, f2) != (s1, 1.0 - s1)     # the mass moved (target changed)
    assert len(_amendment_rows(ws)) == 1
    # pass 3: converged
    n2 = len(_rows(ws))
    out3 = src.run(ws)
    assert out3.get("amended") == 0
    assert len(_rows(ws)) == n2
    assert n2 > n1


def test_settle_pass_repair_never_reenters_banked(tmp_path, monkeypatch):
    """A bank that failed on the first pass is repaired on the next one
    via the q-cell faces — and the repaired dispatch must NOT appear in
    `banked` (the case-posterior leg keys on that set; a Bernoulli
    re-observation would double-count). The refusal is simulated at the
    ledger append boundary (the dispatch row itself must survive, so a
    directory trick cannot be used — it lives in the same family)."""
    ws = _ws(tmp_path, claims=[{"id": "C-9", "status": "REFUTED"}])
    _dispatch(ws, "C-9")
    monkeypatch.setattr(cl, "append", lambda *a, **k: False)
    src.run(ws)                           # ledger settles; bank fails open
    monkeypatch.undo()
    out2 = src.run(ws)
    settlement_rows = [r for r in _rows(ws)
                       if r.get("source") == "settlement"]
    assert len(settlement_rows) == 1      # the repair landed
    assert out2.get("banked") == 0        # not re-reported as first-bank
    assert out2.get("amended") == 1


def test_repair_never_refires_the_store_and_l1_writers(tmp_path, monkeypatch):
    """The missed-bank repair rides the q-cell faces DIRECTLY: the
    strategy-store and L1 writers must never fire from a reconcile."""
    ws = _ws(tmp_path, claims=[{"id": "C-9", "status": "REFUTED"}])
    _dispatch(ws, "C-9")
    monkeypatch.setattr(cl, "append", lambda *a, **k: False)
    src.run(ws)
    monkeypatch.undo()

    from rlvr import scalar as scalar_mod

    def _boom(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("store/L1 writer re-fired from the repair")

    monkeypatch.setattr(scalar_mod, "_bank_strategy_store_row", _boom)
    monkeypatch.setattr(scalar_mod, "_bank_l1_rollout_return", _boom)
    out2 = src.run(ws)
    assert out2.get("amended") == 1


def test_replay_without_correction_is_a_byte_noop(tmp_path):
    ws = _ws(tmp_path, claims=[{"id": "C-9", "status": "REFUTED"}])
    _dispatch(ws, "C-9")
    src.run(ws)
    n1 = len(_rows(ws))
    out2 = src.run(ws)
    assert out2.get("amended") == 0
    assert len(_rows(ws)) == n1


# ---------- 6. defensive reader fixes (audit findings) ----------------------

def test_mc_propensity_survives_a_clawback_stream():
    """Accumulated negative credits once drove Beta(s+1, t−s+1) ≤ 0 →
    betavariate raised → the fail-open caller silently dropped the OPE
    propensity. The parameters are floored at the +1.0 prior."""
    rows = [{"credit": -0.8, "method_family": "a"},
            {"credit": -0.8, "method_family": "a"}]
    p = meta_arms.mc_propensity(rows, "a", ["a", "b"])
    assert 0.0 <= p <= 1.0


def test_cell_count_excludes_amendments(tmp_path):
    """A correction is not a new observation: the n_min evidence gate
    must not count amendment rows."""
    ws = _ws(tmp_path)
    store = ss.PosteriorStrategyStore(ws)
    qc.append_observation(ws, "sig", FAM, 0.7, source="settlement",
                          claim="C-1", dispatch_id="C-1")
    qc.append_observation(ws, "sig", FAM, -0.2,
                          source="credit-amendment",
                          credit_kind=qc.CREDIT_KIND_CREDIT_AMENDMENT,
                          failure_delta=0.2, claim="C-1",
                          dispatch_id="C-1")
    assert store.cell_count("sig") == 1
