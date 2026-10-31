# -*- coding: utf-8 -*-
"""tests/test_rl_v2_reward_base_932.py — the measured reward base (#932).

The reward base moves from the fixed conjunctive lookup to MEASURED
progress: a gate-passing dispatch's credit is the posterior-mass change
the step actually produced (the PAV-style measured ΔP of the #898
evidence ladder, arXiv 2410.08146), scale-normalized to the ladder's
per-success mass. RED-first pins:

  1. the normalization constant is the ladder-floor offset relation
     derived FROM step_credit's own table (never a mirrored number):
     LADDER_SPAN = w(cross_validated) − w(unverified) = 1.0 − 0.3 = 0.7
     — a full floor→top climb banks exactly PASS_CREDIT, so per-success
     banked mass stays at the BASE scale (battery M3's diagnosed
     mass-scale effect);
  2. the measured pricing face: credit = clamp(ΔP / LADDER_SPAN, 0,
     PASS_CREDIT) on a passing gate; any failing layer still banks 0.0
     (the #884 conjunctive gate is UNTOUCHED);
  3. cold-start prior: a workspace with NO ladder measurements yet (no
     state-progress transition rows) prices the fixed ladder — the
     conjunctive gate's PASS_CREDIT/0.0 — until measurements exist; the
     transition is pinned at the first recorded transition row;
  4. measured mode at settlement: once any transition row exists, a
     gate-passing dispatch with no transition of its own banks 0.0 (the
     measured no-progress face), a full-climb dispatch banks
     PASS_CREDIT, a clawback (VERIFIED→REFUTED) clamps at 0.0;
  5. potential-based shaping invariance (the normalization's
     optimality discipline): the per-step credits telescope — a
     non-clamped trajectory's credit total equals the ENDPOINT mass
     delta over the span — and the ladder's floor offset cancels, so
     the fixed prior's scale is a positive factor and the optimal
     policy is unchanged;
  6. fail-closed walls: a poisoned transition fingerprint raises at
     the read face (a tampered row must never silently price), a
     non-finite progress_delta raises at the pricing face;
  7. determinism: the same ledger state re-prices byte-identically
     (the settled draft row round-trips exactly), and the #884 draft
     row shape is unchanged (schema ``settlement-draft/1``, the same
     required fields).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) in sys.path:
        continue
    sys.path.insert(0, str(_p))

from rlvr import consolidated_ledger as _cl  # noqa: E402
from rlvr import q_cells  # noqa: E402
from rlvr.step_credit import CREDIT_BY_CLASS, CROSS_VALIDATED, UNVERIFIED  # noqa: E402
from settlement import draft_commit, per_dispatch  # noqa: E402
from state import progress as progress_face  # noqa: E402

ALL_PASS = {"mechanical": True, "scope_verifier": True, "redteam": True}
ALL_FAIL = {"mechanical": False, "scope_verifier": True, "redteam": True}


def _sub(gid: str, status: str, *refs: str) -> progress_face.Subgoal:
    return progress_face.Subgoal(gid, status, evidence_refs=refs)


def _record(ws, before, after, *, dispatch_id: str) -> dict:
    return progress_face.record_transition(ws, before=before, after=after,
                                           dispatch_id=dispatch_id)


# ------------------------------------------- 1. the normalization constant

def test_ladder_span_is_the_floor_offset_relation():
    """LADDER_SPAN derives FROM step_credit's table (one authority — a
    mirror would drift under the #887 calibration): the full climb's
    measured mass w(top) − w(floor) = 0.7, so a full floor→top climb
    normalizes onto exactly PASS_CREDIT — per-success banked mass
    matches the BASE ladder's scale (the M3 fix)."""
    expected = (CREDIT_BY_CLASS[CROSS_VALIDATED]
                - CREDIT_BY_CLASS[UNVERIFIED])
    assert per_dispatch.LADDER_SPAN == pytest.approx(expected)
    assert per_dispatch.LADDER_SPAN == pytest.approx(0.7)
    assert per_dispatch.PASS_CREDIT == pytest.approx(1.0)


def test_full_climb_banks_exactly_pass_credit():
    """The scale normalization's target property: the ladder's
    UNVERIFIED→VERIFIED measured delta (0.7) prices at the SAME
    per-success mass the fixed ladder paid (1.0) — M3 goes GO by
    construction, not by patching the metric."""
    delta = progress_face.delta_P([_sub("g1", "UNVERIFIED")],
                                  [_sub("g1", "VERIFIED", "E-1")])
    assert delta == pytest.approx(0.7)
    assert per_dispatch.measured_credit(delta, gate_pass=True) \
        == pytest.approx(per_dispatch.PASS_CREDIT)


# ------------------------------------------- 2. the measured pricing face

def test_measured_credit_scales_and_clamps():
    """credit = clamp(ΔP / span, 0, PASS_CREDIT): partial climbs scale
    linearly, zero progress banks zero, a negative clawback clamps at
    the floor (the rail direction — a removal never mints reward)."""
    assert per_dispatch.measured_credit(0.35, gate_pass=True) \
        == pytest.approx(0.5)
    assert per_dispatch.measured_credit(0.0, gate_pass=True) \
        == pytest.approx(0.0)
    assert per_dispatch.measured_credit(-1.0, gate_pass=True) \
        == pytest.approx(0.0)
    assert per_dispatch.measured_credit(7.0, gate_pass=True) \
        == pytest.approx(1.0)


def test_conjunctive_gate_still_prices_failures_at_zero():
    """The #884 three-verdict gate is UNTOUCHED: any failing layer
    banks 0.0 regardless of the measured delta — the measured face
    only replaces the +PASS_CREDIT magnitude for gate-PASSING
    dispatches, never re-litigates a verdict."""
    assert per_dispatch.measured_credit(0.7, gate_pass=False) \
        == pytest.approx(0.0)
    row = per_dispatch.price_dispatch("ro-1", "d-1", 0.1, ALL_FAIL,
                                      progress_delta=0.7)
    assert row["credit"] == pytest.approx(0.0)


def test_price_dispatch_prior_is_the_fixed_ladder():
    """``progress_delta=None`` is the cold-start prior — the exact #884
    contract (all #884 pins ride this path unchanged)."""
    assert per_dispatch.price_dispatch(
        "ro-1", "d-1", 0.1, ALL_PASS)["credit"] == pytest.approx(1.0)
    assert per_dispatch.price_dispatch(
        "ro-1", "d-1", 0.1, ALL_FAIL)["credit"] == pytest.approx(0.0)


def test_price_dispatch_measured_mode_is_distinct_from_prior():
    """A gate-passing dispatch that MEASURED no progress banks 0.0 in
    measured mode (the hack-denial face) where the prior paid 1.0 —
    the two modes must never blur."""
    prior = per_dispatch.price_dispatch("ro-1", "d-1", 0.1, ALL_PASS)
    measured = per_dispatch.price_dispatch("ro-1", "d-1", 0.1, ALL_PASS,
                                           progress_delta=0.0)
    assert prior["credit"] == pytest.approx(1.0)
    assert measured["credit"] == pytest.approx(0.0)
    climbed = per_dispatch.price_dispatch("ro-1", "d-1", 0.1, ALL_PASS,
                                          progress_delta=0.7)
    assert climbed["credit"] == pytest.approx(1.0)


# ------------------------------------------------- 3+4. the cold start

def test_cold_start_prior_until_measurements_exist(tmp_path):
    """The transition, pinned end-to-end: a fresh workspace (no
    state-progress transition rows anywhere) prices the fixed ladder
    through the REAL settlement entry; the FIRST recorded transition
    row flips the workspace into measured mode."""
    ws = tmp_path / "ws"
    assert progress_face.has_measurements(ws) is False
    landed = draft_commit.ensure_draft(ws, "ro-1", "d-1", 0.4, ALL_PASS)
    assert landed["appended"] is True
    drafts = _cl.read(ws, "settlement", schema_prefix="settlement-draft")
    assert drafts[0]["credit"] == pytest.approx(1.0)     # the prior

    # the ladder's first measurement flips the pricing face
    _record(ws, [_sub("g1", "UNVERIFIED")],
            [_sub("g1", "VERIFIED", "E-1")], dispatch_id="d-1")
    assert progress_face.has_measurements(ws) is True
    after = draft_commit.ensure_draft(ws, "ro-1", "d-2", 0.4, ALL_PASS)
    assert after["appended"] is True
    drafts = _cl.read(ws, "settlement", schema_prefix="settlement-draft")
    assert drafts[1]["credit"] == pytest.approx(0.0)     # measured


def test_measured_mode_prices_the_dispatchs_own_delta(tmp_path):
    """In measured mode the settled credit is the dispatch's OWN ΣΔP:
    a full climb banks PASS_CREDIT, a no-progress pass banks 0.0, a
    REFUTED clawback clamps at 0.0 — each through the real
    ensure_draft settlement entry."""
    ws = tmp_path / "ws"
    _record(ws, [_sub("g1", "UNVERIFIED")],
            [_sub("g1", "VERIFIED", "E-1")], dispatch_id="d-climb")
    _record(ws, [_sub("g2", "UNVERIFIED")],
            [_sub("g2", "UNVERIFIED")], dispatch_id="d-flat")
    _record(ws, [_sub("g3", "VERIFIED", "E-3")],
            [_sub("g3", "REFUTED")], dispatch_id="d-claw")
    assert progress_face.dispatch_delta(ws, "d-climb") \
        == pytest.approx(0.7)
    assert progress_face.dispatch_delta(ws, "d-flat") \
        == pytest.approx(0.0)
    assert progress_face.dispatch_delta(ws, "d-claw") \
        == pytest.approx(-1.0)
    for did in ("d-climb", "d-flat", "d-claw"):
        draft_commit.ensure_draft(ws, "ro-1", did, 0.1, ALL_PASS)
    drafts = _cl.read(ws, "settlement", schema_prefix="settlement-draft")
    got = {d["dispatch_id"]: d["credit"] for d in drafts}
    assert got["d-climb"] == pytest.approx(1.0)   # the pass-credit scale
    assert got["d-flat"] == pytest.approx(0.0)
    assert got["d-claw"] == pytest.approx(0.0)


def test_multi_step_delta_sums_across_transition_rows(tmp_path):
    """One dispatch may advance SEVERAL subgoals (several transition
    rows carry its dispatch_id) — the settled delta is the Σ, never
    the last row's."""
    ws = tmp_path / "ws"
    _record(ws, [_sub("g1", "UNVERIFIED")],
            [_sub("g1", "VERIFIED", "E-1")], dispatch_id="d-1")
    _record(ws, [_sub("g2", "UNVERIFIED")],
            [_sub("g2", "NEGATIVE", "E-2")], dispatch_id="d-1")
    assert progress_face.dispatch_delta(ws, "d-1") == pytest.approx(1.4)
    draft_commit.ensure_draft(ws, "ro-1", "d-1", 0.1, ALL_PASS)
    drafts = _cl.read(ws, "settlement", schema_prefix="settlement-draft")
    assert drafts[0]["credit"] == pytest.approx(1.0)     # rail clamp


# ------------------------------------- 5. the shaping-invariance discipline

def test_credits_telescope_to_endpoint_mass_over_span(tmp_path):
    """Potential-based shaping (γ=1): a non-clamped trajectory's
    per-step credit total equals the ENDPOINT mass delta over the span
    — no step can mint more than the endpoints allow, so the reward
    ranks policies by terminal progress, exactly the unshaped
    ΔP-ranking up to the positive scale."""
    ws = tmp_path / "ws"
    start = [_sub("g1", "UNVERIFIED"), _sub("g2", "UNVERIFIED")]
    _record(ws, start, [_sub("g1", "VERIFIED", "E-1"),
                        _sub("g2", "UNVERIFIED")], dispatch_id="s1")
    _record(ws, [_sub("g1", "VERIFIED", "E-1"),
                 _sub("g2", "UNVERIFIED")],
            [_sub("g1", "VERIFIED", "E-1"),
             _sub("g2", "NEGATIVE", "E-2")], dispatch_id="s2")
    end = [_sub("g1", "VERIFIED", "E-1"), _sub("g2", "NEGATIVE", "E-2")]
    total = sum(per_dispatch.measured_credit(
        progress_face.dispatch_delta(ws, f"s{i}"), gate_pass=True)
        for i in (1, 2))
    endpoint = (progress_face.P(end) - progress_face.P(start)) \
        / per_dispatch.LADDER_SPAN
    assert total == pytest.approx(endpoint)


def test_floor_offset_cancels_the_policy_is_unchanged(tmp_path):
    """The floor-offset invariance: a constant floor mass present
    before AND after (a subgoal sitting at UNVERIFIED throughout)
    shifts P at both endpoints equally — the telescoped total, and
    with it every trajectory's ranking, is unchanged. The fixed
    ladder's scale is a positive factor on the shaped reward; the
    optimal policy is the same policy (Ng et al. 1999)."""
    ws = tmp_path / "ws"
    # the SAME two climbs, plus g3 parked at the floor throughout
    _record(ws, [_sub("g1", "UNVERIFIED"), _sub("g3", "UNVERIFIED")],
            [_sub("g1", "VERIFIED", "E-1"),
             _sub("g3", "UNVERIFIED")], dispatch_id="s1")
    _record(ws, [_sub("g2", "UNVERIFIED"), _sub("g3", "UNVERIFIED")],
            [_sub("g2", "NEGATIVE", "E-2"),
             _sub("g3", "UNVERIFIED")], dispatch_id="s2")
    total = sum(per_dispatch.measured_credit(
        progress_face.dispatch_delta(ws, f"s{i}"), gate_pass=True)
        for i in (1, 2))
    assert total == pytest.approx(2 * per_dispatch.PASS_CREDIT)
    # the ordering invariance holds in the CLAMP-FREE domain: within
    # (0, LADDER_SPAN] the normalization is a positive scale and ranks
    # are preserved. Outside it the clamp is a DESIGNED asymmetry (the
    # anti-hack rail): clawback deltas clamp to 0 instead of banking
    # negative, so credits over clawback trajectories deliberately do
    # not telescope — see the clamp-collapse pin below.
    raw_a = progress_face.delta_P([_sub("g1", "UNVERIFIED")],
                                  [_sub("g1", "VERIFIED", "E-1")])
    raw_b = progress_face.delta_P(
        [_sub("g1", "UNVERIFIED"), _sub("g2", "UNVERIFIED")],
        [_sub("g1", "VERIFIED", "E-1"), _sub("g2", "NEGATIVE", "E-2")])
    assert raw_b > raw_a
    # the old ordering pin was saturated (raw_b clamps to 1.0 == raw_a's
    # 1.0 — vacuous). Non-saturating ordering: two raw deltas strictly
    # inside the span must rank identically after normalization.
    raw_c = raw_a / 2
    assert 0 < raw_c < raw_a <= per_dispatch.LADDER_SPAN
    assert per_dispatch.measured_credit(raw_a, gate_pass=True) \
        > per_dispatch.measured_credit(raw_c, gate_pass=True)


def test_clamp_collapse_is_the_designed_asymmetry(tmp_path):
    """Clawback deltas clamp to 0.0 — the anti-hack rail, documented:
    over a clawback trajectory the credits do NOT telescope (the
    potential-based invariance holds only clamp-free). The collapse is
    deterministic and one-sided: negative measured credit is impossible
    (banked floors at 0), while ladder-priced clawbacks can bank the
    NEGATIVE class — the measured base is strictly harsher on regress."""
    neg = -per_dispatch.LADDER_SPAN
    assert per_dispatch.measured_credit(neg, gate_pass=True) == 0.0


# --------------------------------------------------- 6. fail-closed walls

def test_poisoned_transition_fingerprint_raises_at_the_read(tmp_path):
    """A tampered transition row (a fingerprint that is not the state
    face's ``delta_p=<float>`` shape) must never silently price — the
    read face raises (the fail-closed ledger posture)."""
    ws = tmp_path / "ws"
    _cl.append(ws, "experience", {
        "schema": "q-cell-obs/1", "ts": "2026-01-01T00:00:00Z",
        "source": progress_face.SOURCE, "signature_hash": "x",
        "method_family": progress_face.METHOD_FAMILY_TRANSITION,
        "dispatch_id": "d-1", "fingerprint": "delta_p=garbage",
        "credit": None,
    })
    with pytest.raises(ValueError):
        progress_face.dispatch_delta(ws, "d-1")
    with pytest.raises(ValueError):
        draft_commit.ensure_draft(ws, "ro-1", "d-1", 0.1, ALL_PASS)


def test_non_finite_progress_delta_raises():
    """A NaN/inf measurement is a fabrication, never a price."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            per_dispatch.price_dispatch("ro-1", "d-1", 0.1, ALL_PASS,
                                        progress_delta=bad)
    with pytest.raises(ValueError):
        per_dispatch.measured_credit("0.7", gate_pass=True)  # type: ignore[arg-type]


# ------------------------------------- 7. determinism + the #884 row shape

def test_settlement_reprice_is_byte_identical(tmp_path):
    """The same ledger state re-prices to the SAME draft row (the
    crash-recovery replay contract, now over the measured face): the
    re-derived row equals the landed one field for field."""
    ws = tmp_path / "ws"
    _record(ws, [_sub("g1", "UNVERIFIED")],
            [_sub("g1", "VERIFIED", "E-1")], dispatch_id="d-1")
    first = draft_commit.ensure_draft(ws, "ro-1", "d-1", 0.7, ALL_PASS,
                                      ts="2026-01-01T00:00:00Z")
    assert first["appended"] is True
    replay = per_dispatch.price_dispatch(
        "ro-1", "d-1", 0.7, ALL_PASS, ts="2026-01-01T00:00:00Z",
        progress_delta=progress_face.dispatch_delta(ws, "d-1"))
    landed = _cl.read(ws, "settlement",
                      schema_prefix="settlement-draft")[0]
    assert replay == landed
    assert landed["schema"] == "settlement-draft/1"
    assert set(landed) == {"schema", "ts", "batch_id", "rollout_id",
                           "dispatch_id", "spend", "verdicts", "credit"}


def test_committed_aggregate_prices_the_measured_batch(tmp_path):
    """The rollout aggregate rides the measured drafts unchanged (the
    #884 Σ + terminal contract): two full-climb dispatches commit to
    the same total the fixed ladder would have paid for two
    successes — the normalization keeps the aggregate scale."""
    ws = tmp_path / "ws"
    _record(ws, [_sub("g1", "UNVERIFIED")],
            [_sub("g1", "VERIFIED", "E-1")], dispatch_id="d-1")
    _record(ws, [_sub("g2", "UNVERIFIED")],
            [_sub("g2", "NEGATIVE", "E-2")], dispatch_id="d-2")
    for did in ("d-1", "d-2"):
        draft_commit.ensure_draft(ws, "ro-1", did, 0.1, ALL_PASS)
    q_cells.append_action(ws, kind="terminate_rollout", rollout_id="ro-1",
                          target="C-1")
    marker = draft_commit.commit_batch(ws, "ro-1")
    assert marker["appended"] is True
    assert marker["total_credit"] == pytest.approx(2.0)
    view = draft_commit.committed_rollout(ws, "ro-1")
    assert view["committed"] is True
    assert view["credits_sum"] == pytest.approx(2.0)
