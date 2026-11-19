# -*- coding: utf-8 -*-
"""tests/test_signal_topology.py — the S12 signal-topology mock suite.

Every learning/credit signal face gets one mock test that drives the
PRODUCER face against a synthetic workspace, asserts the CARRIER row
(schema, attribution, dedupe), then runs the CONSUMER face and asserts
the DECISION DELTA — so each face carries the three-column verdict
(正常 = written/read without corruption, 完整 = both ends covered,
实用 = the signal reaches a decision point). The matrix below is the
machine-readable deliverable; the gap rows are evidence, not to-do.

Chain tests apply the L11 pattern to the learning signals: 5 rounds,
seeded-random fault interspersion (faults land on a seeded draw, normal
rounds always present), every round's receipt traceable to the banked
rows. Deterministic: every draw rides an explicit seed, decisions never
read a wall clock (the fold decays by append-order age, the recipe and
planner seeds hash their inputs), and the seal round-trips whether the
learning channel is armed (rows seal at write) or not (pass-through).
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

import oracle_runner as orun  # noqa: E402
import priority_ratio as pr  # noqa: E402
from rlvr import reward  # noqa: E402
from rlvr import scalar  # noqa: E402
import settle_round_credit as src_credit  # noqa: E402
import cost_input_capture as cost_capture  # noqa: E402 (hooks/)
from rlvr import disposition_measure  # noqa: E402
from rlvr import episode_pool  # noqa: E402
from rlvr import episode_schema  # noqa: E402
from rlvr import episode_settle  # noqa: E402
import hypothesis_bridge as hb  # noqa: E402
import hypothesis_store as hstore  # noqa: E402
from posteriors_case import PosteriorLedger  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import incremental_reward as ir  # noqa: E402
from rlvr import l1_planner  # noqa: E402
from rlvr import l1_value as l1  # noqa: E402
from rlvr import learning_seal  # noqa: E402
from rlvr import phi_tree  # noqa: E402
from rlvr import q_cells as qc  # noqa: E402
from rlvr import recipe_arms as ra  # noqa: E402
from rlvr import reward_signal  # noqa: E402
from rlvr import rollout_timer as rt  # noqa: E402
from rlvr import rollout_timer_host as rth  # noqa: E402
from rlvr import source_reliability as sr  # noqa: E402
from rlvr import step_credit as sc  # noqa: E402

SIG = "0123456789ab"          # the 12-hex dispatch-time state signature
FAM_GOOD = "static-decompile"  # both families carry registered recipe arms
FAM_BAD = "dynamic-trace"
RECIPE = "facts_snapshot"
SEED = 20261120


# ----------------------------------------------------------------- fixtures

def _ws(tmp_path, name="ws"):
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    (ws / "oracle" / "cases").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": []}, allow_unicode=True), encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"primary_questions": {}}, allow_unicode=True),
        encoding="utf-8")
    return ws


def _register(ws, claims):
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True),
        encoding="utf-8")


def _claim(cid, status="OPEN", pq=None):
    c = {"id": cid, "status": status, "evidence_tier_attempted": 0,
         "promotion_attempts": 0, "statement": cid}
    if pq:
        c["answers_question"] = pq
    return c


def _oracle_case(ws, case_id, target_pq):
    (ws / "oracle" / "cases" / f"{case_id}.yaml").write_text(
        yaml.safe_dump({"id": case_id, "target_pq": target_pq}),
        encoding="utf-8")


def _dispatch(ws, claim, family, did):
    meta = {"method_family": family, "context_recipe": RECIPE,
            "verification_mode": "none", "tier": 0}
    out = qc.record_dispatch_observation(
        ws, "mock dispatch prompt", envelope_meta=meta, claim=claim,
        dispatch_id=did, fingerprint=f"fp-{did}", signature=SIG)
    assert out["appended"] is True, out
    return out


def _settle(ws, claim, credit, **kw):
    out = qc.observe_settlement(ws, claim, credit, **kw)
    assert out["appended"] is True, out
    return out


def _dispatched_credit(ws, claim, family, did, credit):
    """One full open-and-bank lap: the pending dispatch row, then the
    settled credit banked into the arm the dispatch opened."""
    _dispatch(ws, claim, family, did)
    return _settle(ws, claim, credit)


def _qrows(ws):
    return cl.read(ws, "experience", schema_prefix="q-cell-obs")


def _fold(ws, gamma=None):
    return qc.fold(qc.JSONLQStore(ws), gamma=gamma)


def _posterior(fold_view, family):
    return qc.cell_posterior(fold_view, SIG, family)


def _sample(ws, rng):
    return qc.sample_method_family(
        SIG, {FAM_GOOD: 0.5, FAM_BAD: 0.5}, qc.JSONLQStore(ws), rng=rng)


def _oracle_report(status):
    return {"cases": {"case-1": {"status": status, "pending_entries": 0,
                                 "instrumented": True}},
            "counts": {"cases": 1}}


# =========================================================================
# F1 — dispatch observation → q_cells pending row → sampling decision
# =========================================================================

def test_f1_dispatch_pending_row_carrier(tmp_path):
    """The dispatch ALLOW tail records the pending (s, a) row; the carrier
    row carries the schema stamp, the 4-dim arm key, the signature and
    the recipe triple; the fold counts it as pending mass."""
    ws = _ws(tmp_path)
    _dispatch(ws, "C-1", FAM_GOOD, "d1")
    rows = _qrows(ws)
    assert len(rows) == 1
    row = rows[0]
    assert row["schema"] == "q-cell-obs/1"
    assert row["source"] == "dispatch" and row["credit"] is None
    assert row["signature_hash"] == SIG and row["method_family"] == FAM_GOOD
    assert row["arm_key"] == qc.arm_key(FAM_GOOD, RECIPE, "none", 0)
    assert row["recipe_source"] in ("sampled", "declared", "none")
    cell = _fold(ws).cells.get((SIG, row["arm_key"]))
    assert cell is not None
    assert cell.success == 0.0 and cell.failure == 0.0
    assert cell.n_pending == 1, "pending mass counts, never enters the Beta"


def test_f1_sampling_decision_delta(tmp_path):
    """Banked credit moves the sampler: a fresh store draws from the wide
    prior; after two wins banked on the good family and two losses on
    the bad one, the posterior means reorder and the receipt's chosen
    family flips to the good arm (decision = the next dispatch's
    method family)."""
    ws_fresh = _ws(tmp_path, "fresh")
    fresh = _sample(ws_fresh, random.Random(SEED))
    fa, fb = fresh["candidates"][FAM_GOOD], fresh["candidates"][FAM_BAD]
    assert fa["alpha"] == pytest.approx(fb["alpha"])
    assert fresh["family"] in (FAM_GOOD, FAM_BAD)  # prior-dominated draw

    ws = _ws(tmp_path, "learned")
    _dispatched_credit(ws, "C-1", FAM_GOOD, "d1", 1.0)
    _dispatched_credit(ws, "C-2", FAM_GOOD, "d2", 1.0)
    _dispatched_credit(ws, "C-3", FAM_BAD, "d3", 0.0)
    _dispatched_credit(ws, "C-4", FAM_BAD, "d4", 0.0)
    learned = _sample(ws, random.Random(SEED))
    ga, gb = learned["candidates"][FAM_GOOD], learned["candidates"][FAM_BAD]
    assert ga["alpha"] > ga["beta"], "wins must bank success mass"
    assert gb["beta"] > gb["alpha"], "losses must bank failure mass"
    assert ga["alpha"] / (ga["alpha"] + ga["beta"]) \
        > gb["alpha"] / (gb["alpha"] + gb["beta"])
    assert learned["family"] == FAM_GOOD, (
        "the settled credit must move the sampled method family")
    assert learned["gamma"] > 0.0  # the receipt reports its schedule


def test_chain_f1_dispatch_settle_sample_5rounds(tmp_path):
    """The L11 pattern on the dispatch→settle→q-cell→sample chain: five
    rounds, receipt checks seeded-omitted on fault rounds (normal rounds
    always present). The data stream is fixed truth — the good family
    wins and the bad family loses every round — so the learner must
    converge: the final posterior orders the good family first and the
    final receipt names it."""
    rng = random.Random(SEED)
    faults = {i for i in range(5) if rng.random() < 0.35}
    assert faults and len(faults) < 5, "seeded plan needs both shapes"
    ws = _ws(tmp_path)
    g = b = None
    for i in range(5):
        receipt = _sample(ws, random.Random(f"{SEED}/{i}"))
        if i >= 1 and i not in faults:
            assert receipt["family"] == FAM_GOOD, (
                f"round {i}: with GOOD wins and BAD losses banked, the "
                "receipt must name the good family")
        _dispatched_credit(ws, f"C-{i}", FAM_GOOD, f"d{i}", 1.0)
        _dispatched_credit(ws, f"D-{i}", FAM_BAD, f"e{i}", 0.0)
        view = _fold(ws)
        g = _posterior(view, FAM_GOOD)
        b = _posterior(view, FAM_BAD)
        assert g[0] > 1.0 and b[1] > 1.0, (
            f"round {i}: GOOD's win and BAD's loss must both bank")
    assert g[0] / (g[0] + g[1]) > b[0] / (b[0] + b[1]), (
        "the final posterior must order the good family first")
    final = _sample(ws, random.Random(f"{SEED}/final"))
    assert final["family"] == FAM_GOOD


# =========================================================================
# F2 — settlement credit → q_cells banking (attribution + dedupe faces)
# =========================================================================

def test_f2_settlement_banks_attribution(tmp_path):
    """The banked credit rides the DISPATCH-recorded attribution: same
    signature/family/arm_key/claim, the recipe triple copied from the
    pending row, and the reward/band columns only when supplied."""
    ws = _ws(tmp_path)
    _dispatch(ws, "C-1", FAM_GOOD, "d1")
    out = _settle(ws, "C-1", 0.8, phi_delta=0.1, reward=0.42,
                  confidence_band="GREEN", reason="mock-settle")
    assert out["matched"] is True and out["beta_updated"] is True
    assert out["method_family"] == FAM_GOOD
    settle_row = [r for r in _qrows(ws) if r["source"] == "settlement"][-1]
    assert settle_row["schema"] == "q-cell-obs/1"
    assert settle_row["credit"] == pytest.approx(0.8)
    assert settle_row["arm_key"] == qc.arm_key(FAM_GOOD, RECIPE, "none", 0)
    assert settle_row["claim"] == "C-1"
    assert settle_row["dispatch_id"] == "C-1", (
        "the settle identity rides the matched dispatch row's claim id")
    assert settle_row["recipe_id"] is not None or \
        settle_row["recipe_source"] == "none"
    assert settle_row["reward"] == pytest.approx(0.42)
    assert settle_row["confidence_band"] == "GREEN"
    assert settle_row["reason"] == "mock-settle"


def test_f2_unmatched_settlement_honest_gap(tmp_path):
    """A settlement with no pending dispatch row banks NOTHING — the
    loud counted gap, never a fabricated bucket."""
    ws = _ws(tmp_path)
    out = qc.observe_settlement(ws, "C-GHOST", 0.5)
    assert out["appended"] is False and out["matched"] is False
    assert out["reason"] == "unmatched"
    assert _qrows(ws) == []


def test_f2_verification_credit_inadmissible(tmp_path):
    """Verification credit is recorded but never moves the Beta: the
    exact-γ fold mass is unchanged by its presence."""
    ws = _ws(tmp_path)
    _dispatched_credit(ws, "C-1", FAM_GOOD, "d1", 0.7)
    before = _fold(ws, gamma=1.0)
    cell_before = before.cells[(SIG, qc.arm_key(FAM_GOOD, RECIPE, "none", 0))]
    _dispatch(ws, "C-2", FAM_GOOD, "d2")
    _settle(ws, "C-2", 0.9, credit_kind="verification")
    after = _fold(ws, gamma=1.0)
    cell_after = after.cells[(SIG, qc.arm_key(FAM_GOOD, RECIPE, "none", 0))]
    assert cell_after.success == pytest.approx(cell_before.success)
    assert cell_after.failure == pytest.approx(cell_before.failure)
    kinds = {str(r.get("credit_kind") or "")
             for r in _qrows(ws) if r["source"] == "settlement"}
    assert "verification" in kinds, "the row is recorded, just not folded"


# =========================================================================
# F3 — step outcomes → step_credit → step rows → terminal calibration
# =========================================================================

def test_f3_step_credit_classes(tmp_path):
    """The evidence-quality ladder: cross-validated 1.0, unverified 0.3,
    refuted 0.0 — the mean over the step's evidence window."""
    ws = _ws(tmp_path)
    items = [{"status": "PROVEN", "verify_status": "passes"},
             {"status": "OPEN", "verify_status": ""},
             {"status": "REFUTED", "verify_status": ""}]
    value = sc.step_credit(items, ws=ws)
    assert value == pytest.approx(round((1.0 + 0.3 + 0.0) / 3, 6))
    assert sc.step_credit([], ws=ws) == sc.CREDIT_BY_CLASS[sc.UNVERIFIED]


def test_f3_step_bank_and_calibration_signed(tmp_path):
    """The dense bank at SubagentStop (credit_kind step), then the
    claim-terminal residual applied VERBATIM under γ=1: a negative
    residual claws the success mass back and Δfailure lands on the
    failure side — the step-less endpoint."""
    ws = _ws(tmp_path)
    key = (SIG, qc.arm_key(FAM_GOOD, RECIPE, "none", 0))
    _dispatch(ws, "C-1", FAM_GOOD, "d1")
    banked = qc.observe_step_credit(ws, "C-1", 0.9, step_ref="s1")
    assert banked["appended"] is True and banked["matched"] is True
    cell = _fold(ws, gamma=1.0).cells[key]
    assert cell.success == pytest.approx(0.9)
    assert cell.failure == pytest.approx(0.1)
    totals = qc.step_credit_totals(ws, "C-1")
    assert totals[0] == pytest.approx(0.9) and totals[1] == 1
    cal = qc.observe_step_calibration(ws, "C-1", -0.4, failure_delta=0.4,
                                      reason="mock-terminal")
    assert cal["appended"] is True
    row = [r for r in _qrows(ws)
           if r.get("credit_kind") == "step_calibration"][-1]
    assert row["credit"] == pytest.approx(-0.4)
    assert row["failure_delta"] == pytest.approx(0.4)
    cell = _fold(ws, gamma=1.0).cells[key]
    assert cell.success == pytest.approx(0.5)
    assert cell.failure == pytest.approx(0.5)


def test_f3_observation_band_and_zero(tmp_path):
    """The D-678.4a band: a settled step credit in (0, 0.05] banks no
    mass (an observation, not a verdict); a genuine 0.0 trains failure."""
    ws = _ws(tmp_path)
    key = (SIG, qc.arm_key(FAM_GOOD, RECIPE, "none", 0))
    _dispatched_credit(ws, "C-1", FAM_GOOD, "d1", 0.03)
    cell = _fold(ws, gamma=1.0).cells[key]
    assert cell.success == 0.0 and cell.failure == 0.0
    _dispatched_credit(ws, "C-2", FAM_GOOD, "d2", 0.0)
    cell = _fold(ws, gamma=1.0).cells[key]
    assert cell.failure == pytest.approx(1.0)


# =========================================================================
# F4 — rollout outcomes → deadline timer → learn → next budget (LIVE loop)
# =========================================================================

def test_f4_coefficient_table_pins(tmp_path):
    """The bounded outcome table: timeout ×1.25 (fired + incomplete),
    early ×0.9, on-time ×0.98, infra/aborted never move it, clamps at
    [0.5, 4.0]."""
    assert rt.next_coefficient(1.0, actual_min=30, budget_min=30,
                               completed=False, outcome="timeout",
                               deadline_fired=True)["coeff_after"] == 1.25
    assert rt.next_coefficient(1.0, actual_min=10, budget_min=30,
                               completed=True, outcome="early")[
                                   "coeff_after"] == 0.9
    assert rt.next_coefficient(1.0, actual_min=25, budget_min=30,
                               completed=True, outcome="on_time")[
                                   "coeff_after"] == 0.98
    for word in ("infra", "aborted"):
        v = rt.next_coefficient(1.7, actual_min=0, budget_min=30,
                                completed=False, outcome=word)
        assert v["coeff_after"] == 1.7 and v["updated"] is False
    assert rt.next_coefficient(3.9, actual_min=30, budget_min=30,
                               completed=False, outcome="timeout",
                               deadline_fired=True)["coeff_after"] == 4.0
    assert rt.next_coefficient(0.51, actual_min=10, budget_min=30,
                               completed=True, outcome="early")[
                                   "coeff_after"] == 0.5


def _armed(ws, rid, now):
    out = rt.arm(ws, rid, claim="C-1", kind="task", difficulty="medium",
                 now=now, base_estimate_min=30.0)
    assert out["idempotent"] is False
    return out["row"]


def test_f4_learn_moves_next_budget(tmp_path):
    """The LIVE loop: the first arm rides the default 1.0 coefficient; a
    deadline wake (fire → deadline stop → cancel → learn timeout) moves
    the coefficient; the NEXT arm prices its budget from the learned
    value."""
    ws = _ws(tmp_path)
    t0 = datetime(2026, 11, 20, tzinfo=timezone.utc)
    row1 = _armed(ws, "r1", t0)
    assert row1["coeff"] == 1.0 and row1["budget_min"] == pytest.approx(30.0)
    wake = rth.deadline_wake_face(ws, "r1", now=t0 + timedelta(minutes=31))
    assert wake is not None and wake["learned"] is True
    assert wake["stop"]["stop_reason"] == "deadline"
    assert wake["stop"]["excluded_from_strategy_learning"] is True
    row2 = _armed(ws, "r2", t0 + timedelta(minutes=60))
    assert row2["coeff"] == pytest.approx(1.25)
    assert row2["budget_min"] == pytest.approx(37.5)


def test_chain_f4_deadline_5rounds(tmp_path):
    """Five rollout rounds with the seeded fault plan (timeout rounds are
    the faults; early/on-time rounds normal): the coefficient walks the
    bounded table exactly and each round's armed budget reflects every
    prior lesson."""
    rng = random.Random(SEED + 1)
    plan = []
    for _ in range(5):
        roll = rng.random()
        plan.append("timeout" if roll < 0.35
                    else ("early" if roll < 0.65 else "on_time"))
    assert "timeout" in plan and set(plan) != {"timeout"}
    ws = _ws(tmp_path)
    t = datetime(2026, 11, 20, tzinfo=timezone.utc)
    for i, word in enumerate(plan):
        rid = f"r{i}"
        row = _armed(ws, rid, t)
        assert row["coeff"] == pytest.approx(rt._current_coefficient(ws))
        assert row["budget_min"] == pytest.approx(
            min(max(30.0 * row["coeff"], 15.0), 480.0))
        deadline = datetime.fromisoformat(row["deadline_ts"])
        if word == "timeout":
            wake = rth.deadline_wake_face(ws, rid,
                                          now=deadline + timedelta(seconds=1))
            assert wake["learned"] is True
        else:
            rt.cancel(ws, rid, now=t, reason="rollout finished")
            actual = 30.0 * (0.5 if word == "early" else 0.8)
            learned = rt.learn(ws, rid, actual_min=actual, completed=True,
                               outcome=word)
            assert learned["updated"] is True
        factor = {"timeout": 1.25, "early": 0.9, "on_time": 0.98}[word]
        expected = min(max(round(row["coeff"] * factor, 6),
                           rt.MIN_COEFF), rt.MAX_COEFF)
        assert rt._current_coefficient(ws) == pytest.approx(expected)
    assert rt._current_coefficient(ws) != rt.DEFAULT_COEFF, (
        "the loop moved off the default coefficient")


# =========================================================================
# F5 — case observations → posteriors → priority_ratio ranking
# =========================================================================

def _ranked_top(ws, claims):
    ranked = pr.priority_ratio(claims, {"depends_on": {}},
                               pr.EvidenceView.from_workspace(ws))
    return ranked[0].claim_id


def test_f5_settlement_observation_moves_rank(tmp_path):
    """The ranker's live posterior leg: record_case_settlements writes
    one Bernoulli observation per linked case; the green case's claim
    ranks above the unobserved one (score = posterior mean)."""
    ws = _ws(tmp_path)
    _register(ws, [_claim("C-1", "PROVEN", "q1"), _claim("C-2x", "PROVEN", "q2"),
                   _claim("C-1a", "OPEN", "q1"), _claim("C-2a", "OPEN", "q2")])
    _oracle_case(ws, "case-1", "q1")
    _oracle_case(ws, "case-2", "q2")
    out = src_credit.record_case_settlements(ws, ["C-1"])
    assert out["case_observations"] == 1
    led = PosteriorLedger.load(ws)
    assert led.cases["case-1"].alpha == pytest.approx(2.0)
    assert led.cases["case-1"].beta == pytest.approx(1.0)
    obs_rows = cl.read(ws, "experience", schema_prefix="case-observation")
    assert len(obs_rows) == 1
    top = _ranked_top(ws, [_claim("C-1a", "OPEN", "q1"),
                           _claim("C-2a", "OPEN", "q2")])
    assert top == "C-1a", "the green case's question must rank first"


def test_f5_double_record_idempotent(tmp_path):
    """The pair-level dedupe: a re-run over the same banked set observes
    nothing twice — the posterior moves exactly once."""
    ws = _ws(tmp_path)
    _register(ws, [_claim("C-1", "PROVEN", "q1")])
    _oracle_case(ws, "case-1", "q1")
    assert src_credit.record_case_settlements(ws, ["C-1"])[
        "case_observations"] == 1
    second = src_credit.record_case_settlements(ws, ["C-1"])
    assert second["case_observations"] == 0
    led = PosteriorLedger.load(ws)
    assert led.cases["case-1"].alpha == pytest.approx(2.0)


# =========================================================================
# F6 — case amendments (the S10 transactional correction face)
# =========================================================================

def test_f6_amendment_flips_posterior_and_idempotent(tmp_path):
    """A decisive-status flip lands ONE case-amendment row FIRST, then
    the floored ±1 posterior flip; a re-run is a read-scan no-op."""
    ws = _ws(tmp_path)
    _register(ws, [_claim("C-1", "PROVEN", "q1")])
    _oracle_case(ws, "case-1", "q1")
    src_credit.record_case_settlements(ws, ["C-1"])
    _register(ws, [_claim("C-1", "REFUTED", "q1")])
    out = src_credit.reconcile_case_settlements(ws)
    assert out["case_amendments"] == 1
    assert out.get("case_amendments_error") is None
    led = PosteriorLedger.load(ws)
    assert led.cases["case-1"].alpha == pytest.approx(1.0), (
        "the flip is floored at the Beta(1,1) support")
    amend_rows = cl.read(ws, "experience", schema_prefix="case-amendment")
    assert len(amend_rows) == 1
    again = src_credit.reconcile_case_settlements(ws)
    assert again["case_amendments"] == 0, "the fold idempotence face"


def test_f6_skip_set_never_observes(tmp_path):
    """Censored/pending outcomes are not observations: the skip set
    leaves both the posterior and the amendment trail untouched."""
    ws = _ws(tmp_path)
    _register(ws, [_claim("C-1", "PROVEN", "q1")])
    _oracle_case(ws, "case-1", "q1")
    src_credit.record_case_settlements(ws, ["C-1"])
    _register(ws, [_claim("C-1", "REFUTED", "q1")])
    out = src_credit.reconcile_case_settlements(ws, skip={"C-1"})
    assert out["case_amendments"] == 0
    assert PosteriorLedger.load(ws).cases["case-1"].alpha == pytest.approx(2.0)
    assert cl.read(ws, "experience", schema_prefix="case-amendment") == []


# =========================================================================
# F7 — oracle status → ground-truth consumers (verdict face + reward lock)
# =========================================================================

def test_f7_write_status_carrier_and_verdict(tmp_path):
    """write_status is the canonical writer of runs/oracle-status.json;
    the reward face reads it into the machine verdict and the settlement
    signal list."""
    ws = _ws(tmp_path)
    assert reward._oracle_verdict(ws) is None  # no file → no signal
    orun.write_status(ws, _oracle_report("pass"))
    assert reward._oracle_verdict(ws) == "pass"
    orun.write_status(ws, _oracle_report("fail"))
    assert reward._oracle_verdict(ws) == "fail"
    signals = reward.task_signals(ws, "C-1", "PROVEN")
    assert any(s["type"] == "oracle_verdict" and s["value"] == "fail"
               for s in signals)
    orun.write_status(ws, _oracle_report("pending"))
    assert reward._oracle_verdict(ws) is None, (
        "pending-only is an unmeasured claim, never a signal")
    assert (ws / "runs" / "oracle-status.json").is_file()


def test_f7_oracle_lock_decision_delta(tmp_path):
    """The lock faces: pass locks the reward at 1.0, fail caps it below
    the pass band, no verdict passes the clamped scalar through."""
    locked = scalar.oracle_lock("pass", 0.4, False)
    assert locked["locked"] is True and locked["reward"] == 1.0
    capped = scalar.oracle_lock("fail", 0.95, False)
    assert capped["capped"] is True and capped["reward"] < 1.0
    passthrough = scalar.oracle_lock(None, 0.4, False)
    assert passthrough["reward"] == pytest.approx(scalar.clamp_credit(0.4))


def test_f7_phi_oracle_dim(tmp_path):
    """Φ's oracle dim reads the sealed status file: no file → Φ 0.0; all
    cases pass → Φ 1.0 (the single present dim renormalizes)."""
    ws = _ws(tmp_path)
    assert ir.potential(ws) == 0.0
    orun.write_status(ws, _oracle_report("pass"))
    assert ir.potential(ws) == pytest.approx(1.0)


# =========================================================================
# F8 — Φ → r_incr transition → l1 rollout return → planner advisory
# =========================================================================

def test_chain_f8_phi_to_r_incr_to_l1_planner(tmp_path):
    """The full value chain over real faces: launch stash → oracle move →
    transition row (r_incr = ALPHA·ΔΦ − cost) → terminal rollout return
    into runs/l1-value-log.jsonl → the l1 fold banks the cell → the
    planner advisory surface OPENS for the rank path."""
    ws = _ws(tmp_path)
    sig0 = l1.state_signature_of(ws)
    launch = ir.record_launch(ws, "C-1", FAM_GOOD, s_hash=sig0)
    assert launch is not None and launch["attempt_id"]
    assert ir.potential(ws) == 0.0
    orun.write_status(ws, _oracle_report("pass"))
    assert ir.potential(ws) == pytest.approx(1.0)
    row = ir.append_transition(ws, "C-1", "completed", done=True)
    assert row is not None
    assert row["schema"] == "transition/1"
    assert row["r_incr"] == pytest.approx(1.0), "ALPHA·ΔΦ with zero cost"
    assert row["phi_delta"] == pytest.approx(1.0)
    assert row["claim_ref"] == "C-1" and row["action_key"] == FAM_GOOD
    assert not (ws / "runs" / "dispatch-launch-C-1.json").exists(), (
        "the stash is consumed by its settle")
    # the consumer face fires with nothing to reconcile (no resolution
    # rows exist — the G1 gap): a silent no-op, never a crash
    assert phi_tree.reconcile_claim(ws, "C-1") is None
    transitions = [r for r in ir.read_transitions(ws)
                   if str(r.get("dispatch_id")) == "C-1"]
    assert len(transitions) == 1
    # before the value row exists the rank path's advisory is {} (the
    # byte-identity contract); after it, the surface is live
    assert l1_planner.advisory_factors(ws, [("C-1", 1.0)]) == {}
    out = l1.record_terminal_return(ws, "C-1", 1.0, signature=sig0)
    assert out["recorded"] is True and out["steps"] == 1
    assert out["return"] == pytest.approx(2.0), "r_incr + terminal credit"
    log_rows = [json.loads(line)
                for line in (ws / "runs" / "l1-value-log.jsonl")
                .read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(log_rows) == 1
    assert log_rows[0]["return"] == pytest.approx(2.0)
    factors = l1_planner.advisory_factors(ws, [("C-1", 1.0)])
    assert factors and 0.0 < factors["C-1"] <= 1.0
    view = l1.fold(l1.default_store(ws))
    cell = view.cell(sig0, "dispatch")
    assert cell.success == pytest.approx(2.0)


def test_f8_no_launch_stash_banks_nothing(tmp_path):
    """1-F1: a settle without a recorded launch banks nothing rather than
    inventing a before-state."""
    ws = _ws(tmp_path)
    assert ir.append_transition(ws, "C-404", "completed") is None
    assert ir.read_transitions(ws) == []


# =========================================================================
# F9 — hypothesis confirmations → family ledger sync (status flip face)
# =========================================================================

def _family(ws, hid="H-001", arms=("AES", "ChaCha")):
    store = hstore.HypothesisStore(ws / "hypotheses")
    store.create(hstore.Hypothesis(
        id=hid, claim_id="C-PENDING", competitor_group=hb.family_group(hid),
        candidates=[], status="open", body=f"test family {hid}\n"))
    _register(ws, [{"id": "C-BASE", "status": "OPEN", "statement": "base"}])
    mint = hb.mint_family_arms(ws, hid, list(arms))
    assert mint["refused"] is None
    return mint


def _arms(ws, hid="H-001"):
    return [c for c in src_credit._register_claims(ws)
            if c.get("competitor_group") == f"hyp-{hid}"]


def test_f9_family_sync_confirm_supersedes_peers(tmp_path):
    """One arm PROVEN → the family flips confirmed with
    confirming_fact_id = the WINNING ARM id, losing open arms retire —
    a decided question stops drawing TS budget."""
    ws = _ws(tmp_path)
    _family(ws)
    arms = _arms(ws)
    assert len(arms) == 2
    winner = arms[0]["id"]
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(
        encoding="utf-8"))
    for c in reg["claims"]:
        if c["id"] == winner:
            c["status"] = "PROVEN"
    _register(ws, reg["claims"])
    report = hb.sync_family_ledger(ws)
    assert report["confirmed"] == ["H-001"]
    hyp = hstore.HypothesisStore(ws / "hypotheses").get("H-001")
    assert hyp.status == "confirmed"
    assert hyp.confirming_fact_id == winner
    assert report["refuted"] == []
    retired = {c["id"]: c["status"] for c in src_credit._register_claims(ws)}
    assert retired[arms[1]["id"]] == "SUPERSEDED"


def test_f9_family_sync_refute(tmp_path):
    """All arms terminal, none positive → refuted with refuting_fact_id =
    the first NEGATIVE arm in claim-id order (never a winning id)."""
    ws = _ws(tmp_path)
    _family(ws)
    arms = sorted(_arms(ws), key=lambda c: c["id"])
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(
        encoding="utf-8"))
    for c in reg["claims"]:
        if c["id"] in {a["id"] for a in arms}:
            c["status"] = "NEGATIVE"
    _register(ws, reg["claims"])
    report = hb.sync_family_ledger(ws)
    assert report["refuted"] == ["H-001"]
    hyp = hstore.HypothesisStore(ws / "hypotheses").get("H-001")
    assert hyp.status == "refuted"
    assert hyp.refuting_fact_id == arms[0]["id"]


# =========================================================================
# F10 — source reliability events → theta discount → step credit
# =========================================================================

def test_f10_reliability_moves_discount(tmp_path):
    """The teacher face writes invalidation events; the fold prices the
    source class; the step credit discounts a labeled item by a Thompson
    draw from that posterior while an unlabeled item rides 1.0."""
    ws = _ws(tmp_path)
    labeled = {"status": "PROVEN", "verify_status": "passes",
               "source": "floss", "reference_class": "raw"}
    for _ in range(3):
        out = sr.record_confirmation(ws, labeled, confirmed_by="F-9")
        assert out["recorded"] is True
    out = sr.record_refutation(ws, labeled, refuted_by="F-10")
    assert out["recorded"] is True
    rows = sr._read_events(ws)
    assert len(rows) == 4 and rows[0]["schema"] == sr.SCHEMA
    assert rows[0]["source_class"] == "floss|raw"
    view = sr.fold(ws=ws)
    post = view.posterior(labeled)
    assert post["n"] == 4.0
    assert post["alpha"] == pytest.approx(4.0) and \
        post["beta"] == pytest.approx(2.0), (
        "the fold seeds each cell with the Beta(1,1) prior: "
        "(1+3 wins, 1+1 losses)")
    assert post["mean"] == pytest.approx(4.0 / 6.0)
    base = sc.weighted_step_credit(
        [{"status": "PROVEN", "verify_status": "passes"}], ws=ws)
    assert base == pytest.approx(1.0)
    discounted = sc.weighted_step_credit([labeled], ws=ws,
                                         rng=random.Random(SEED))
    assert 0.0 < discounted < 1.0, (
        "the learned posterior must discount the labeled item")
    plain = sc.weighted_step_credit(
        [dict(labeled, source="", reference_class="")], ws=ws,
        rng=random.Random(SEED))
    assert plain == pytest.approx(base), "unlabeled rides the neutral weight"


# =========================================================================
# F11 — recipe arms: sampling weights, propensity carrier, credit loop
# =========================================================================

def test_f11_recipe_weights_move_and_propensity_carrier(tmp_path):
    """The recipe loop: the sampler draws one registered arm with its
    propensity; banked solve credit lands in that arm's fold counts; the
    dispatch row carries the {recipe_id, propensity, source} triple and
    the settlement row copies it (credit banks against the
    DISPATCH-recorded recipe)."""
    family = FAM_GOOD
    arm_ids = ra.arm_ids_for(family)
    assert arm_ids, "the mock family must have registered arms"
    ws_fresh = _ws(tmp_path, "fresh")
    weights_before = ra.arm_weights(ws_fresh, family)
    receipt = ra.sample_recipe(ws_fresh, family)
    assert receipt is not None
    assert receipt["recipe_id"] in arm_ids
    assert 0.0 < receipt["propensity"] <= 1.0
    ws = _ws(tmp_path, "learned")
    _dispatch(ws, "C-1", family, "d1")
    dispatch_row = [r for r in _qrows(ws) if r["source"] == "dispatch"][-1]
    assert dispatch_row["recipe_source"] in ("sampled", "declared", "none")
    assert dispatch_row["recipe_propensity"] is None or \
        0.0 <= dispatch_row["recipe_propensity"] <= 1.0
    credited_arm = receipt["recipe_id"]
    _settle(ws, "C-1", 1.0)
    settle_row = [r for r in _qrows(ws) if r["source"] == "settlement"][-1]
    assert settle_row["recipe_id"] == dispatch_row["recipe_id"]
    assert dispatch_row["recipe_id"] in arm_ids, (
        "the sampler's draw must name a registered arm")
    fold_after = ra.arm_fold(ws)
    assert fold_after[credited_arm]["rows"] == 1, (
        "the settled credit must land in the credited arm's fold counts")
    assert fold_after[credited_arm]["success"] == pytest.approx(1.0), (
        "a 1.0 solve credit banks as the arm's success mass")
    weights_after = ra.arm_weights(ws, family)
    assert set(weights_after) == set(weights_before)
    assert weights_after[credited_arm] > weights_before[credited_arm], (
        "banked success must raise the arm's sampling weight "
        "(prior·(1+1)/(2+1) > prior·1/2)")
    assert all(w > 0.0 for w in weights_after.values()), (
        "floored, never deleted")


# =========================================================================
# F12 — cost events → spend window / workspace spend face
# =========================================================================

def _cost_row(ws, amount, tool="Bash", word="WARNING"):
    out = cost_capture.process_event({
        "tool_response": f"COST {word}: session total ~${amount}",
        "cwd": str(ws), "tool_name": tool})
    assert out == 0  # the recorder is a fail-open face, never a block


def test_f12_cost_event_producer_row(tmp_path):
    """The capture hook parses the COST WARNING/CRITICAL text into one
    cost-event/1 row in the settlement family file; foreign text writes
    nothing. The DECLARED 口径 boundary: the amount is the session
    CUMULATIVE total — Claude Code exposes no per-call billing."""
    ws = _ws(tmp_path)
    _cost_row(ws, "1.50")
    _cost_row(ws, "2.25", word="CRITICAL")
    rows = cl.read(ws, "settlement", schema_prefix="cost-event")
    assert [r["amount"] for r in rows] == pytest.approx([1.50, 2.25])
    assert rows[0]["schema"] == "cost-event/1"
    assert rows[0]["source"] == "Bash"
    foreign = cost_capture.process_event({
        "tool_response": "no cost line here", "cwd": str(ws)})
    assert foreign == 0
    assert len(cl.read(ws, "settlement",
                       schema_prefix="cost-event")) == 2


def test_f12_spend_window_high_water_diff(tmp_path):
    """The settlement-granularity cost delta EXISTS: each mission window
    sums only the rows past the previous settle's high-water mark. The
    mark rides a hand-written episode fixture (the pool's write gate is
    the trust spine's face, not this test's subject)."""
    ws = _ws(tmp_path)
    _cost_row(ws, "1.50")
    _cost_row(ws, "2.25")
    doc1 = episode_settle._build_episode(
        ws, "C-1", [{"id": "C-1", "status": "PROVEN"}])
    assert doc1["cost"]["spend_usd"] == pytest.approx(3.75)
    assert doc1["cost"]["event_rows"] == {"runs/settlement.jsonl": 2}
    path = episode_pool.episode_path(ws, "C-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        + yaml.safe_dump(doc1, allow_unicode=True, sort_keys=True)
        + "---\n",
        encoding="utf-8")
    _cost_row(ws, "2.25")  # the session total climbs; one more row lands
    doc2 = episode_settle._build_episode(
        ws, "C-1b", [{"id": "C-1b", "status": "PROVEN"}])
    assert doc2["cost"]["spend_usd"] == pytest.approx(2.25), (
        "the second window reads only rows past the stamped mark")
    assert doc2["cost"]["event_rows"]["runs/settlement.jsonl"] == 3


def test_f12_disposition_spend_face(tmp_path):
    """The workspace spend face totals the same carrier rows."""
    ws = _ws(tmp_path)
    _cost_row(ws, "1.50")
    _cost_row(ws, "0.75")
    spend = disposition_measure._cost_workspace(ws)
    assert spend["amount"] == pytest.approx(2.25)
    assert spend["events"] == 2


def test_f12_cost_term_linear_pin(tmp_path):
    """The −λ·cost term, pinned mechanically: ΔΦ 1.0 at 10k tokens nets
    0.0 — a linear cost penalty (G5: this shape contradicts the owner's
    2026-11-19 quadrant ruling)."""
    assert ir.incremental_reward(0.0, 1.0) == pytest.approx(1.0)
    assert ir.incremental_reward(0.0, 1.0, tokens=10_000.0) == 0.0
    assert ir.incremental_reward(0.0, 1.0, tokens=20_000.0) == pytest.approx(-1.0)
    assert reward_signal.COST_TOKENS_NORM == pytest.approx(10_000.0)


def test_f12_normalization_stability_invariant(tmp_path):
    """Owner-approved invariant: adding an extreme observation must not
    change any previously recorded historical credit. The carrier rows
    are append-only (history survives as a byte prefix), a settled cost
    window keeps its booked value (the high-water mark excludes later
    rows — a min-max normalizer would have rescaled it to 0, the
    retrospectively-invalidating anti-pattern), and the reward cost term
    divides by the FIXED 10k-token divisor, never a rescaled form."""
    ws = _ws(tmp_path)
    _cost_row(ws, "1.50")
    _cost_row(ws, "2.25")
    rel = ws / "runs" / "settlement.jsonl"
    history = rel.read_bytes()
    base = ir.incremental_reward(0.0, 1.0, tokens=10_000.0)
    doc1 = episode_settle._build_episode(
        ws, "C-1", [{"id": "C-1", "status": "PROVEN"}])
    assert doc1["cost"]["spend_usd"] == pytest.approx(3.75)
    path = episode_pool.episode_path(ws, "C-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n" + yaml.safe_dump(doc1, allow_unicode=True, sort_keys=True)
        + "---\n", encoding="utf-8")
    # the extreme outlier lands (a 5,000,000-token cost event at the
    # $1==10k-tokens convention)
    _cost_row(ws, "500.00")
    assert rel.read_bytes().startswith(history), (
        "the carrier is append-only: historical rows are byte-unchanged")
    assert ir.incremental_reward(0.0, 1.0, tokens=10_000.0) == base, (
        "a fixed-divisor term cannot be moved by store state")
    assert ir.incremental_reward(0.0, 1.0, tokens=5_000_000.0) == \
        pytest.approx(1.0 - 5_000_000.0 / 10_000.0), (
        "the outlier prices through the FIXED divisor tokens/10000")
    # the SETTLED episode file keeps its booked value: the settle is
    # idempotent (a settled episode is never rebuilt), so min-max
    # rescaling could never touch it — the landed document still says 3.75
    landed, _body = episode_schema.read_episode_file(
        episode_pool.episode_path(ws, "C-1"))
    assert landed["cost"]["spend_usd"] == pytest.approx(3.75), (
        "historical credit byte-stable — min-max rescaling would have "
        "zeroed it (the retrospectively-invalidating shape)")
    # the outlier belongs to the NEXT window only (rows past the mark)
    doc2 = episode_settle._build_episode(
        ws, "C-1b", [{"id": "C-1b", "status": "PROVEN"}])
    assert doc2["cost"]["spend_usd"] == pytest.approx(500.0)


# =========================================================================
# the topology matrix — the machine-readable deliverable
# =========================================================================

def _matrix_rows():
    W = str(ROOT)
    return [
        {"face": "F1 dispatch observation → q_cells → sampling",
         "producer": f"{W}/hooks/worker_budget_sinks.py:798,821 → "
                     f"{W}/scripts/rlvr/q_cells.py:2267 "
                     "record_dispatch_observation",
         "carrier": f"{W}/scripts/rlvr/consolidated_ledger.py:58 "
                    "runs/experience.jsonl (q-cell-obs/1, pending credit=None)",
         "consumer": f"{W}/scripts/rlvr/q_cells.py:877 sample_method_family "
                     "(fold :564, cell_posterior :701, Thompson draw :967)",
         "decision": "the next dispatch's sampled method family",
         "tests": ["test_f1_dispatch_pending_row_carrier",
                   "test_f1_sampling_decision_delta",
                   "test_chain_f1_dispatch_settle_sample_5rounds"],
         "gap": None},
        {"face": "F2 settlement credit → q_cells banking",
         "producer": f"{W}/scripts/rlvr/scalar.py:1179 observe_settlement / "
                     f":1187 observe_step_calibration; "
                     f"{W}/scripts/rlvr/settlement_wire.py:546,542 (blind face)",
         "carrier": "runs/experience.jsonl q-cell-obs/1 settlement rows "
                    f"(match face {W}/scripts/rlvr/q_cells.py:1694)",
         "consumer": "q_cells.fold :564 banks the arm the dispatch opened; "
                     f"strategy_store method_sample {W}/scripts/rlvr/"
                     "strategy_store.py:751 rides the same fold",
         "decision": "sampling posterior + compose method_lead",
         "tests": ["test_f2_settlement_banks_attribution",
                   "test_f2_unmatched_settlement_honest_gap",
                   "test_f2_verification_credit_inadmissible"],
         "gap": None},
        {"face": "F3 step outcomes → step_credit / step_grain",
         "producer": f"{W}/hooks/round_closure.py:371 settle_step(blind=True) "
                     f"(def {W}/scripts/rlvr/step_grain.py:264; credit leg "
                     ":364-367 blind=False eval face)",
         "carrier": "runs/experience.jsonl step-record/2 + q-cell-obs/1 "
                    "credit_kind step|step_calibration",
         "consumer": f"q_cells.step_credit_totals {W}/scripts/rlvr/"
                     f"q_cells.py:2160 ← scalar.py:1177 (terminal residual); "
                     "parking.py:108 provisional_mass; fold :650 signed deltas",
         "decision": "claim-terminal calibration + PARK posture",
         "tests": ["test_f3_step_credit_classes",
                   "test_f3_step_bank_and_calibration_signed",
                   "test_f3_observation_band_and_zero"],
         "gap": None},
        {"face": "F4 rollout outcomes → deadline timer → learn",
         "producer": f"{W}/scripts/rlvr/rollout_timer_host.py:296 "
                     "deadline_wake_face (fire :308 → stop :315 → cancel :318 "
                     "→ learn :323); round_close_face :201 (cancel+learn :239)",
         "carrier": "runs/telemetry.jsonl rollout-timer/1 + rollout-budget/1 "
                    f"({W}/scripts/rlvr/rollout_timer.py:37,38)",
         "consumer": f"rollout_timer.arm :453 reads _current_coefficient :401 "
                     "at :493 and prices budget_minutes at :494",
         "decision": "the next rollout's budget_min / deadline_ts",
         "tests": ["test_f4_coefficient_table_pins",
                   "test_f4_learn_moves_next_budget",
                   "test_chain_f4_deadline_5rounds"],
         "gap": None},
        {"face": "F5 case observations → posteriors → priority ranking",
         "producer": f"{W}/scripts/settle_round_credit.py:607 "
                     "record_case_settlements (+ runner leg "
                     f"{W}/scripts/oracle_runner.py:1478 record_posteriors)",
         "carrier": f"runs/posteriors.yaml ({W}/scripts/posteriors_case.py:233 "
                    "PosteriorLedger.save, sealed) + case-observation/1 rows",
         "consumer": f"{W}/scripts/priority_ratio.py:400 priority_ratio "
                     "(ledger load :462, case_value mean :492, sort :604)",
         "decision": "the dispatch queue head (claim ranking)",
         "tests": ["test_f5_settlement_observation_moves_rank",
                   "test_f5_double_record_idempotent"],
         "gap": None},
        {"face": "F6 case amendments (S10 transactional correction)",
         "producer": f"{W}/scripts/settle_round_credit.py:438 "
                     "reconcile_case_settlements (row-first commit "
                     "_amend_pair_entries :392)",
         "carrier": "runs/experience.jsonl case-amendment/1 rows "
                    "(belief flip only after the row lands)",
         "consumer": "the corrected posterior re-enters priority_ratio "
                     "ranking at its :462 load face on the next DECIDE tick",
         "decision": "dispatch order correction (belief rollback)",
         "tests": ["test_f6_amendment_flips_posterior_and_idempotent",
                   "test_f6_skip_set_never_observes"],
         "gap": None},
        {"face": "F7 oracle status → ground-truth consumers",
         "producer": f"{W}/scripts/oracle_runner.py:1141 write_status "
                     "(carrier runs/oracle-status.json, sealed)",
         "carrier": "runs/oracle-status.json (oracle-status/1)",
         "consumer": f"{W}/scripts/rlvr/reward.py:313 _oracle_verdict → "
                     "task_signals :354; scalar.oracle_lock :1695; "
                     "convergence_check.py:1268 oracle_blocks; "
                     "mission_ledger.py:325 oracle_credit_gate",
         "decision": "settlement tier lock/cap + convergence block",
         "tests": ["test_f7_write_status_carrier_and_verdict",
                   "test_f7_oracle_lock_decision_delta",
                   "test_f7_phi_oracle_dim"],
         "gap": None},
        {"face": "F8 Φ progress → r_incr → l1 value → planner advisory",
         "producer": f"{W}/scripts/rlvr/incremental_reward.py:279 "
                     "append_transition (r_incr computed at :363, row :394)",
         "carrier": "runs/experience.jsonl transition/1 rows + "
                    f"runs/l1-value-log.jsonl ({W}/scripts/rlvr/l1_value.py:89)",
         "consumer": "l1_value.record_terminal_return :227 ← scalar.py:897,"
                     ":1219 and settlement_wire.py:573; "
                     "l1_planner.advisory_factors :494 → "
                     f"{W}/scripts/priority_ratio.py:577-597 rank drag",
         "decision": "claim-rank drag by the planner's dispatch share",
         "tests": ["test_chain_f8_phi_to_r_incr_to_l1_planner",
                   "test_f8_no_launch_stash_banks_nothing"],
         "gap": None},
        {"face": "F9 hypothesis confirmations → family ledger",
         "producer": f"{W}/scripts/kunglao_record.py:559-560 "
                     "sync_family_ledger call ← settlements",
         "carrier": f"{W}/scripts/hypothesis_store.py HypothesisStore files + "
                    "claim-register arm retirement",
         "consumer": "priority_ratio.is_open (retired arms leave the TS "
                     "pool); the hypothesis store state feeds the "
                     "hypothesis faces",
         "decision": "family question closed; arms stop drawing TS budget",
         "tests": ["test_f9_family_sync_confirm_supersedes_peers",
                   "test_f9_family_sync_refute"],
         "gap": "G3: the sync writes the STATUS flip + confirming/refuting "
                "fact ids only; the valuation fields (ΔΦ, step_ref, "
                "posterior) exist solely on phi_tree.settle_resolution — "
                "which has no production caller (see G1)"},
        {"face": "F10 source reliability → theta discount → step credit",
         "producer": f"{W}/scripts/rlvr/source_reliability.py:130 "
                     "record_outcome (+:173/:182 wrappers)",
         "carrier": "runs/source-reliability.jsonl (source-reliability/1)",
         "consumer": f"{W}/scripts/rlvr/step_credit.py:206-211 "
                     "weighted_step_credit folds _sr.reliability_weight",
         "decision": "the evidence-quality credit a step banks",
         "tests": ["test_f10_reliability_moves_discount"],
         "gap": "G2 (teacherless teacher): record_outcome has NO production "
                "caller — the read side is decision-wired (step_credit "
                ":209), the write side never fires outside tests"},
        {"face": "F11 recipe arms → sampling weights + propensity receipt",
         "producer": f"{W}/scripts/rlvr/q_cells.py:2222 _recipe_view → "
                     "recipe_arms.record_dispatch_recipe :378",
         "carrier": "the q-cell-obs row's recipe triple "
                    "(recipe_id/propensity/source)",
         "consumer": f"recipe_arms.arm_fold :231 → arm_weights :285 → "
                     "sample_recipe :323 (recommendation); SNIPS receipt "
                     "check incremental_reward.py:429",
         "decision": "recipe recommendation + propensity integrity gate "
                     "(no dispatch veto — the online switch is not wired)",
         "tests": ["test_f11_recipe_weights_move_and_propensity_carrier"],
         "gap": None},
        {"face": "G1 phi_tree settle_resolution / elimination_credit",
         "producer": f"{W}/scripts/rlvr/phi_tree.py:292 settle_resolution, "
                     ":372 elimination_credit",
         "carrier": "hypothesis-resolution rows in runs/experience.jsonl",
         "consumer": "phi_tree consumer face exists "
                     "(reconcile_claim fired from append_transition "
                     "done=True, incremental_reward.py:408-420) and is "
                     "starved: resolution rows never exist in production",
         "decision": "escrow release + calibration triples",
         "tests": ["test_chain_f8_phi_to_r_incr_to_l1_planner"],
         "gap": "producer without consumer: no production caller of "
                "settle_resolution/elimination_credit exists (grep across "
                "scripts/ hooks/ skills/ agents/) — the resolution rows "
                "never exist, so reconcile_claim is a starved no-op and "
                "tree Φ stays at its prior"},
        {"face": "F12 cost events → spend window / spend faces",
         "producer": f"{W}/hooks/cost_input_capture.py:232 process_event "
                     "(COST WARNING/CRITICAL parse → cost-event/1 row; the "
                     "DECLARED 口径 boundary: amount is the session "
                     "CUMULATIVE total, Claude Code exposes no per-call "
                     "billing)",
         "carrier": f"runs/settlement.jsonl cost-event/1 rows "
                    f"({W}/scripts/rlvr/consolidated_ledger.py settlement family)",
         "consumer": f"episode_settle._spend_window {W}/scripts/rlvr/"
                     "episode_settle.py:296 (high-water per-settle diff) → "
                     "doc cost block; disposition_measure._cost_workspace "
                     ":382 (workspace spend face); "
                     "incremental_reward −λ·cost term (formula :82-87,141-146)",
         "decision": "episode cost block (A1 cost term) + workspace spend "
                     "telemetry; NO credit consumer",
         "tests": ["test_f12_cost_event_producer_row",
                   "test_f12_spend_window_high_water_diff",
                   "test_f12_disposition_spend_face",
                   "test_f12_cost_term_linear_pin",
                   "test_f12_normalization_stability_invariant"],
         "gap": None,
         "note": "cost normalization is FIXED-DIVISOR (stable: "
                 "tokens/10000, $1==10k tokens; the settled window's "
                 "booked value survives extreme outliers) — NOT min-max, "
                 "which would be retrospectively invalidating (the "
                 "anti-pattern: a new extreme rescales historical credit "
                 "to 0); pinned by "
                 "test_f12_normalization_stability_invariant"},
        {"face": "G4 per-step increment cost",
         "producer": "NONE — the capture hook only sees the session "
                     "cumulative total (口径 boundary: no per-call billing "
                     "surface in Claude Code)",
         "carrier": "runs/settlement.jsonl cost-event/1 (cumulative rows only)",
         "consumer": "NONE on the credit side — the q_cells credit is a "
                     "cost-blind [0,1] outcome scalar: a family spending "
                     "$10 vs $2000 earns identical credit mass "
                     "(q_cells.append_observation credit clamp, "
                     "q_cells.py:1319)",
         "decision": "none — the arm choice never sees spend",
         "tests": ["test_f12_cost_event_producer_row",
                   "test_f12_cost_term_linear_pin"],
         "gap": "producer AND consumer missing (owner confirmed the change "
                "is required: 高成本低回报 is unacceptable — cost-blind "
                "credit lets exactly that quadrant survive selection)"},
        {"face": "G5 −λ·cost linear reward term",
         "producer": f"{W}/scripts/rlvr/incremental_reward.py:141-146 "
                     "incremental_reward (cost = tokens/10000 + seconds/3600)",
         "carrier": "the transition row's r_incr column",
         "consumer": "l1_value.compute_rollout_return :187 (the discounted "
                     "rollout return) → planner advisory → rank drag",
         "decision": "per-transition value estimate",
         "tests": ["test_f12_cost_term_linear_pin"],
         "gap": "contradicts the owner's 2026-11-19 quadrant ruling: the "
                "linear term penalizes high-cost-high-return rollouts "
                "instead of pruning high-cost-LOW-return ones — documented "
                "evidence for the post-suite wiring decision, not fixed "
                "here"},
    ]


def test_topology_matrix_is_complete_and_grounded():
    """Every face row carries both ends + a decision, every named test
    exists in this module, and every gap row stays loud — including the
    runtime pin that G1's producer face really has no production caller
    (the row flips the day one lands)."""
    import test_signal_topology as this_module  # noqa: PLC0415
    rows = _matrix_rows()
    assert len(rows) == 15
    assert len([r for r in rows if r["gap"]]) == 5, (
        "G1/G2/G3/G4/G5 must stay loud")
    named = {name for row in rows for name in row["tests"]}
    for name in sorted(named):
        assert callable(getattr(this_module, name, None)), name
    for row in rows:
        for cell in ("producer", "carrier", "consumer", "decision"):
            assert row[cell].strip(), (row["face"], cell)
    f12 = next(r for r in rows if r["face"].startswith("F12"))
    note = f12.get("note", "").lower()
    assert "fixed-divisor" in note and "min-max" in note, (
        "the cost face must document the stable normalization contract "
        "and the min-max anti-pattern")
    callers = []
    for base in (ROOT / "scripts", ROOT / "hooks"):
        for p in base.rglob("*.py"):
            text = p.read_text(encoding="utf-8", errors="replace")
            if "settle_resolution(" in text and p.name != "phi_tree.py":
                callers.append(str(p))
    assert not callers, f"settle_resolution grew a caller: {callers}"


def test_seal_round_trip_is_transparent():
    """The suite's determinism contract: whether the learning channel is
    armed (rows seal at write) or not (pass-through), module-face writes
    always read back through the learner's trusted-rows face."""
    armed = learning_seal.armed()
    row = {"schema": "probe/1", "v": 1}
    sealed = learning_seal.sign_row(row)
    kept = learning_seal.trusted_rows([sealed], op="tests.probe")
    assert len(kept) == 1
    assert armed is bool("seal" in sealed)
