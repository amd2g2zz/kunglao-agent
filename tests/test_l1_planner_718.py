# -*- coding: utf-8 -*-
"""tests/test_l1_planner_718.py — the L1 planner: value function +
planning algorithm; the rollout return's consumer.

The three-layer ruling (2026-10-16): the orchestration layer had NO
learner — claim selection / worker assignment / stopping were heuristics
+ LLM with zero credit attribution, and no rollout-level return was ever
computed, stored, or consumed. This card closes the gap:

  T2  the rollout return is computed and stored at claim terminal
      (`R(τ) = Σ γ^t·r_t` — the discounted SUM, terminal-dominated; the
      mean is a different objective and would flatten the sparse terminal
      reward);
  T3  the L1 value store keys (state_signature, action_kind) Beta cells
      fed by rollout returns (the q_cells DTS machinery, mirrored);
  T4  the planner chooses actions by the value/cost RATIO over DTS draws
      — a policy, never a trigger rule; the rank face consumes it
      additively and is byte-identical while the value store is empty;
  T5  `reuse` is an available action whenever the knowledge substrate
      (facts / register / cross-task store) says the claim is solved —
      re-attempt wins only on value/cost superiority.

Pins:
  1. `test_rollout_return_computed_at_terminal` — the return exists
     after the first claim-terminal settlement (today: nonexistent),
     equals the discounted sum of the claim's transition rewards plus
     the terminal ladder credit, telescopes over the Φ chain, and
     replays idempotently.
  2. `test_l1_value_updated_from_rollout_return` — terminal returns move
     the (state, action) Beta cells; positive returns bank success mass,
     negative returns failure mass; the cold cell stays Beta(1,1).
  3. `test_planner_consumes_value_plus_cost_plus_knowledge` — the action
     choice reads V (DTS draws), the cost model and the knowledge query;
     it is an argmax of value/cost, so a cheaper/better action wins and a
     prohibitive cost loses despite a high value.
  4. `test_solved_claim_reused_not_redispatched` — verified knowledge
     present: `reuse` wins (near-zero cost, known value); but the choice
     is COMPARATIVE — a re-attempt whose value/cost beats reuse's flips
     it, no rule firing anywhere.
  5. `test_step_credit_flows_to_l2_only` — the L1 return never reads the
     step-credit stream (L2's signal) and the L1 bank never writes the
     q-cell store: two stores, two signals, no mixing.
  6. `test_advisory_face_dormant_until_learned` — the rank-face
     consumption is absent while the value store is empty (byte
     identity) and drags exactly the solved claims once learning exists.

All arithmetic is explicit (fixture ts, γ=1 calibration reads, seeded
rng) — no wall-clock sleeps anywhere.
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (SCRIPTS, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from rlvr import l1_planner as lp  # noqa: E402
from rlvr import l1_value as lv  # noqa: E402
from rlvr import q_cells as qc  # noqa: E402
from rlvr import scalar  # noqa: E402
from rlvr import state as ssig  # noqa: E402

T0 = datetime(2026, 10, 16, 8, 0, 0, tzinfo=timezone.utc)
FAM = "static-symbolic"

CITED = {"id": "F718-cited", "status": "PROVEN", "verify_status": "passes",
         "cited_by_deliverable": True, "answers_question": False,
         "oracle_backed_refutation": False}


def _ws(tmp_path: Path, claims: list[dict]) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}), encoding="utf-8")
    return ws


def _dispatch(ws: Path, claim: str) -> dict:
    """The pending dispatch row the settlement faces match (it records
    the dispatch-time state signature the L1 row must key on)."""
    return qc.record_dispatch_observation(
        ws, "dispatch envelope",
        envelope_meta={"method_family": FAM, "action_type": "dispatch",
                       "context_recipe": "facts_snapshot",
                       "verification_mode": "none", "tier": 0},
        claim=claim)


def _transition(ws: Path, claim: str, *, r_incr: float,
                phi_delta: float = 0.0) -> None:
    """One closed transition row (the settle face's own shape; written
    directly so the numbers are exact). ``r_incr`` already embeds
    −cost (the production writer's ALPHA·ΔΦ − LAMBDA·cost), so the
    fixture picks r_incr = phi_delta − cost pairs explicitly — there is
    no cost column on a real row."""
    row = {"ts": T0.strftime("%Y-%m-%dT%H:%M:%SZ"), "dispatch_id": claim,
           "action_type": "dispatch", "s": "0" * 12, "a": FAM,
           "o": {"status": "ok", "class": "strategy", "facts": 1},
           "s_prime_phi": round(phi_delta, 6), "phi_before": 0.0,
           "phi_delta": round(phi_delta, 6), "claim_ref": claim,
           "action_key": FAM, "r_incr": r_incr, "r_settle": None,
           "done": False}
    p = ws / "runs" / "transitions.jsonl"
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _index_row(ws: Path, fact_id: str, status: str, claim: str) -> None:
    idx = ws / "facts" / "_INDEX.md"
    with idx.open("a", encoding="utf-8") as fh:
        fh.write(f"{fact_id} | {status} | {claim} | fixture conclusion\n")


def _l1_rows(ws: Path) -> list[dict]:
    p = ws / "runs" / "l1-value-log.jsonl"
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def _sig(ws: Path) -> str:
    return ssig.signature_hash(ssig.snapshot(ws))


def _settle(ws: Path, claim: str, artifacts: list[dict] | None = None) -> dict:
    return scalar.settle_round_credit(
        ws, [{"dispatch_id": claim, "round": 1}],
        [dict(CITED, id=f"{CITED['id']}-{claim}", creator=claim)]
        if artifacts is None else artifacts, [])


# ==========================================================================
# 1. the rollout return exists at claim terminal (today: nonexistent)
# ==========================================================================

def test_rollout_return_computed_at_terminal(tmp_path):
    """At the claim-terminal settlement (where settle_round_credit runs)
    the rollout return is computed and stored: the discounted SUM of the
    claim's transition rewards plus the terminal ladder settlement — NOT
    the mean — keyed to the dispatch-time state signature, and a replay
    adds no second row."""
    ws = _ws(tmp_path, [{"id": "C-718", "status": "IN_PROGRESS"}])
    disp = _dispatch(ws, "C-718")
    # r_incr = phi_delta − cost, the production writer's own arithmetic
    _transition(ws, "C-718", r_incr=0.4, phi_delta=0.55)   # cost 0.15
    _transition(ws, "C-718", r_incr=-0.1, phi_delta=-0.05)  # cost 0.05
    assert _l1_rows(ws) == [], (
        "no rollout return exists before the terminal settlement")
    # the workspace MOVES between dispatch and settle (one fact file
    # lands — the state signature advances): the return must still key
    # the DISPATCH-time state the action was chosen in, not the
    # post-terminal snapshot
    (ws / "facts" / "F718-late.md").write_text(
        "---\nid: F718-late\ntype: fact\nstatus: OPEN\n---\n\nbody\n",
        encoding="utf-8")
    assert _sig(ws) != disp["signature_hash"]

    res = _settle(ws, "C-718")
    assert res["banked"] == ["C-718"]
    rows = _l1_rows(ws)
    assert len(rows) == 1, "one return row per first settlement"
    row = rows[0]
    assert row["schema"] == "l1-value-obs/1"
    assert row["claim"] == "C-718"
    assert row["action_kind"] == "dispatch"
    # R = Σ r_t + terminal (γ = 1: the shipped calibration face)
    assert row["return"] == pytest.approx(0.4 - 0.1 + 1.0)
    assert row["components"]["transitions_sum"] == pytest.approx(0.3)
    assert row["components"]["terminal"] == pytest.approx(1.0)
    assert row["steps"] == 2
    # NOT the mean (#716): the mean would be 1.3 / 3 — a different
    # objective that flattens the sparse terminal reward
    assert row["return"] != pytest.approx(1.3 / 3)
    # the telescoped form (potential-based shaping at γ=1):
    # Σ r_incr == Σ Φ-delta − Σcost — and R == that chain + terminal
    phi = 0.55 - 0.05
    cost = 0.15 + 0.05
    assert row["components"]["transitions_sum"] == pytest.approx(phi - cost)
    # keyed to the DISPATCH-time state (the state the action was chosen
    # in) — the terminal-state snapshot would be the wrong cell
    assert row["state_signature"] == disp["signature_hash"]
    assert row["state_signature"] != _sig(ws)

    # replay idempotence: the first-settlement guard covers the L1 bank
    _settle(ws, "C-718")
    assert len(_l1_rows(ws)) == 1

    # the pure face: the discount face exists and the sum is the default
    assert lv.ROLLOUT_GAMMA == 1.0
    out = lv.compute_rollout_return(
        [{"r_incr": 1.0}, {"r_incr": 1.0}], 1.0, gamma=0.5)
    assert out["return"] == pytest.approx(1.0 + 0.5 * 1.0 + 0.25 * 1.0)


# ==========================================================================
# 2. terminal returns update V(state) — the L1 value function
# ==========================================================================

def test_l1_value_updated_from_rollout_return(tmp_path):
    """The value store is keyed (state_signature, action_kind): positive
    returns bank success mass, negative returns bank failure mass, the
    cold cell stays the wide Beta(1,1), and the terminal settlement path
    feeds it end to end."""
    ws = _ws(tmp_path, [{"id": "C-719", "status": "IN_PROGRESS"}])
    sig = _sig(ws)

    # cold: the wide prior, no cells
    cold = lv.fold(lv.InMemoryStore(), gamma=1.0)
    assert cold.cells == {}
    a0, b0 = lv.cell_posterior(cold, sig, "dispatch")
    assert (a0, b0) == (1.0, 1.0)

    # the pure store face: ± returns split into the two Beta masses
    lv.record_observation(ws, sig, "dispatch", 1.5, claim="C-719",
                          source="terminal")
    lv.record_observation(ws, sig, "dispatch", -0.5, claim="C-719",
                          source="terminal")
    lv.record_observation(ws, sig, "dispatch", 0.0, claim="C-719",
                          source="terminal")
    view = lv.fold(lv.default_store(ws), gamma=1.0)
    cell = view.cells[(sig, "dispatch")]
    assert cell.success == pytest.approx(1.5)
    assert cell.failure == pytest.approx(0.5)
    assert cell.n == 3
    alpha, beta = lv.cell_posterior(view, sig, "dispatch")
    assert alpha > 1.0 and beta > 1.0
    # the other action kind is untouched — the key carries the action
    assert (sig, "split") not in view.cells
    assert lv.cell_posterior(view, sig, "split") == (1.0, 1.0)

    # the terminal path feeds it: a full settle lands one observation
    ws2 = _ws(tmp_path / "terminal", [{"id": "C-720",
                                       "status": "IN_PROGRESS"}])
    sig2 = _sig(ws2)
    _dispatch(ws2, "C-720")
    _transition(ws2, "C-720", r_incr=0.25)
    _settle(ws2, "C-720")           # R = 0.25 + 1.0
    v2 = lv.fold(lv.default_store(ws2), gamma=1.0)
    assert v2.cells[(sig2, "dispatch")].success == pytest.approx(1.25)
    # and the sampled value follows the evidence: a store full of bad
    # dispatch returns draws low, a store full of good split returns high
    ws3 = _ws(tmp_path / "sampled", [{"id": "C-721", "status": "OPEN"}])
    sig3 = _sig(ws3)
    for _ in range(20):
        lv.record_observation(ws3, sig3, "dispatch", -1.0)
        lv.record_observation(ws3, sig3, "split", 1.0)
    v3 = lv.fold(lv.default_store(ws3), gamma=1.0)
    rng = random.Random(11)
    draws_d = [lv.sample_value(v3, sig3, "dispatch", rng) for _ in range(8)]
    draws_s = [lv.sample_value(v3, sig3, "split", rng) for _ in range(8)]
    assert max(draws_d) < 0.35 < 0.65 < min(draws_s)


# ==========================================================================
# 3. the planner consumes V + cost + knowledge (policy, not rule)
# ==========================================================================

def test_planner_consumes_value_plus_cost_plus_knowledge(tmp_path):
    """plan() samples DTS draws over the V cells and ranks by
    value/cost: learned evidence moves the choice, the cost model can
    overrule a high value, and the knowledge query feeds the reuse
    candidate's value."""
    ws = _ws(tmp_path, [{"id": "C-722", "status": "OPEN"}])
    sig = _sig(ws)
    for _ in range(20):
        lv.record_observation(ws, sig, "dispatch", -1.0)
        lv.record_observation(ws, sig, "split", 1.0)
    cands = [lp.candidate("dispatch", "C-722", cost=1.0),
             lp.candidate("split", "C-722", cost=1.0)]
    out = lp.plan(ws, cands, rng=random.Random(7))
    assert out["schema"] == "l1-plan/1"
    assert out["chosen"]["action_kind"] == "split", (
        "learned V must move the choice: dispatch draws low, split high")
    assert (out["candidates"]["dispatch/C-722"]["value"]
            < out["candidates"]["split/C-722"]["value"])
    assert (out["candidates"]["dispatch/C-722"]["ratio"]
            < out["candidates"]["split/C-722"]["ratio"])

    # the cost model overrules the value: value/cost, not value
    out2 = lp.plan(ws, [lp.candidate("dispatch", "C-722", cost=0.2),
                        lp.candidate("split", "C-722", cost=100.0)],
                   rng=random.Random(7))
    assert out2["chosen"]["action_kind"] == "dispatch"
    # no candidate with positive marginal value -> the do-nothing
    # baseline (park) is the honest choice; doing nothing costs 0
    out3 = lp.plan(ws, [lp.candidate("park", "C-722", cost=0.0)],
                   rng=random.Random(7))
    assert out3["chosen"]["action_kind"] == "park"
    assert out3["chosen"]["ratio"] == 0.0

    # the knowledge query feeds reuse: a solved claim plans to reuse
    _index_row(ws, "F722", "PROVEN", "C-722")
    kc = lp.knowledge_query(ws, "C-722")
    assert kc["solved"] is True
    assert kc["strength"] == pytest.approx(1.0)
    out4 = lp.plan_for_claim(ws, "C-722", dispatch_cost=3.0,
                             rng=random.Random(7))
    assert out4["candidates"]["reuse/C-722"]["value_hint"] == pytest.approx(
        1.0)
    assert out4["chosen"]["action_kind"] == "reuse"

    # the vocabulary is closed and validated at the boundary
    with pytest.raises(ValueError):
        lp.candidate("teleport", "C-722", cost=1.0)


# ==========================================================================
# 4. solved claims are reused, not re-dispatched (value/cost decides)
# ==========================================================================

def test_solved_claim_reused_not_redispatched(tmp_path):
    """Verified knowledge present -> the reuse action wins on value/cost
    (near-zero cost, known value). The flip side pins the mechanism: a
    re-attempt whose value/cost EXCEEDS reuse's flips the choice — no
    trigger rule anywhere, the comparison decides."""
    ws = _ws(tmp_path, [{"id": "C-723", "status": "OPEN"}])
    _index_row(ws, "F723", "PROVEN", "C-723")

    kc = lp.knowledge_query(ws, "C-723")
    assert kc["solved"] and kc["source"] == "facts_index"

    # A: the replay beats the re-attempt (certified knowledge, near-zero
    # reuse cost vs the dispatch's full cost)
    out = lp.plan_for_claim(ws, "C-723", dispatch_cost=3.0,
                            rng=random.Random(5))
    assert out["chosen"]["action_kind"] == "reuse"
    ratio_reuse = out["candidates"]["reuse/C-723"]["ratio"]
    ratio_disp = out["candidates"]["dispatch/C-723"]["ratio"]
    assert ratio_reuse > ratio_disp

    # B: weak knowledge (an unverified/refuted answer) + a re-attempt
    # carrying superior value/cost -> the re-attempt is chosen. Nothing
    # forbade it: a solved claim is re-dispatched exactly when its
    # marginal value/cost beat the existing answer's.
    weak = lp.knowledge_query(
        _weak_ws(tmp_path / "weak"), "C-724")
    assert weak["solved"] and weak["strength"] < 1.0
    out2 = lp.plan(
        _weak_ws(tmp_path / "weak2"),
        [lp.candidate("reuse", "C-724", cost=0.1,
                      value_hint=weak["strength"]),
         lp.candidate("dispatch", "C-724", cost=0.5, value_hint=2.0)],
        rng=random.Random(5))
    assert out2["chosen"]["action_kind"] == "dispatch"
    assert (out2["candidates"]["dispatch/C-724"]["ratio"]
            > out2["candidates"]["reuse/C-724"]["ratio"])

    # C: the register face also answers (a claim already closed elsewhere)
    ws3 = _ws(tmp_path / "closed", [{"id": "C-725", "status": "PROVEN"}])
    kc3 = lp.knowledge_query(ws3, "C-725")
    assert kc3["solved"] and kc3["source"] == "register"
    # ... but lifecycle is NOT an answer artifact: the rank-side drag
    # keys on the answer faces only (the rank frontier owns closure)
    assert kc3["answer_strength"] is None
    # D: nothing known -> no reuse action at all
    ws4 = _ws(tmp_path / "cold", [{"id": "C-726", "status": "OPEN"}])
    assert lp.knowledge_query(ws4, "C-726")["solved"] is False
    out4 = lp.plan_for_claim(ws4, "C-726", dispatch_cost=1.0,
                             rng=random.Random(5))
    assert "reuse/C-726" not in out4["candidates"]


def _weak_ws(tmp_path: Path) -> Path:
    ws = _ws(tmp_path, [{"id": "C-724", "status": "OPEN"}])
    _index_row(ws, "F724", "REFUTED", "C-724")
    return ws


# ==========================================================================
# 5. step credit flows to L2 only (no mixing)
# ==========================================================================

def test_step_credit_flows_to_l2_only(tmp_path):
    """The L1 rollout return reads the transition chain + the terminal
    ladder, never the step-credit stream (the L2 signal), and the L1
    bank never writes the q-cell store: two stores, two signals."""
    ws = _ws(tmp_path, [{"id": "C-727", "status": "IN_PROGRESS"}])
    sig = _sig(ws)
    _dispatch(ws, "C-727")
    # one L2 step credit banks at the step boundary (the #712 face)
    qc.observe_step_credit(ws, "C-727", 1.0)
    _transition(ws, "C-727", r_incr=0.2)
    _settle(ws, "C-727")

    row = _l1_rows(ws)[0]
    # the return saw the transition + terminal, NOT the step credit
    assert row["return"] == pytest.approx(0.2 + 1.0)
    assert row["steps"] == 1
    # no step-credit column rides the L1 row (the L2 vocabulary stays in
    # the q-cell log: source/credit_kind are L2 faces)
    assert "credit_kind" not in row and "step_ref" not in row
    assert row["source"] == "terminal"
    # the L1 fold holds only the L1 observation
    v = lv.fold(lv.default_store(ws), gamma=1.0)
    assert v.cells[(sig, "dispatch")].success == pytest.approx(1.2)
    assert v.cells[(sig, "dispatch")].n == 1
    # the L2 store was not written by the L1 bank: the q-cell log's
    # settlement rows are the #712 L2 kinds only (step + the terminal
    # residual calibration) — no L1-flavored kind exists there
    kinds = sorted(str(r.get("credit_kind") or "") for r in
                   qc.JSONLQStore(ws).observations() if r.get("source")
                   != "dispatch")
    assert kinds == ["step", "step_calibration"], (
        "the L1 bank must never write the q-cell (L2) store")
    # and the reverse: an L2-only workspace folds no L1 cells
    ws2 = _ws(tmp_path / "l2only", [{"id": "C-728", "status": "IN_PROGRESS"}])
    _dispatch(ws2, "C-728")
    qc.observe_step_credit(ws2, "C-728", 1.0)
    assert lv.fold(lv.default_store(ws2), gamma=1.0).cells == {}


# ==========================================================================
# 6. the rank-face consumption is dormant until learning exists
# ==========================================================================

def test_advisory_face_dormant_until_learned(tmp_path):
    """The advisory factor face returns {} while the value store is
    empty (the rank path stays byte-identical); once learned, a solved
    claim is dragged below 1.0 and an unsolved claim is left at exactly
    1.0 — the drag is the planner's dispatch share, not a rule."""
    ws = _ws(tmp_path, [{"id": "C-729", "status": "OPEN"},
                        {"id": "C-730", "status": "OPEN"}])
    _index_row(ws, "F729", "PROVEN", "C-729")
    assert lp.advisory_factors(ws, [("C-729", 3.0),
                                    ("C-730", 1.0)]) == {}, (
        "empty value store -> the advisory face is dormant (byte "
        "identity for the rank path)")
    sig = _sig(ws)
    lv.record_observation(ws, sig, "dispatch", 0.5, claim="C-730")
    factors = lp.advisory_factors(ws, [("C-729", 3.0), ("C-730", 1.0)],
                                 rng=random.Random(4))
    assert 0.0 < factors["C-729"] < 1.0, "solved claim: reuse dominates"
    assert factors["C-730"] == pytest.approx(1.0), (
        "unsolved claim: no reuse candidate -> the share is exactly 1.0")


# ==========================================================================
# integration: the additive rank consumption (empty store byte-identity)
# ==========================================================================

def test_rank_consumes_planner_additively(tmp_path):
    """priority_ratio applies the planner factors ONLY when the value
    store is non-empty: empty -> identical scores either way; learned +
    solved -> the claim's score is dragged and both the feed and the
    payload carry the planner signal."""
    from test_algorithm_event_log_157 import _rank_inputs, _rank_ws
    import priority_ratio as pr

    ws = _rank_ws(tmp_path)
    claims, deps, evidence = _rank_inputs(ws)
    base = pr.priority_ratio(claims, deps, evidence, rng=random.Random(9))
    assert lp.advisory_factors(evidence.ws, []) == {}
    # empty store: no planner feed anywhere
    assert all("planner" not in a.feeds for a in base)

    # learn something + solve one claim -> the advisory face wakes up
    sig = _sig(ws)
    lv.record_observation(ws, sig, "dispatch", 0.5, claim="C-1")
    solved = next(c["id"] for c in claims if c.get("status") == "OPEN")
    (ws / "facts" / "_INDEX.md").parent.mkdir(exist_ok=True)
    _index_row(ws, "F731", "PROVEN", solved)
    got = pr.priority_ratio(claims, deps, evidence, rng=random.Random(9))
    by_id = {a.claim_id: a for a in base}
    moved = [a for a in got if "planner" in a.feeds]
    assert [a.claim_id for a in moved] == [solved]
    assert moved[0].score < by_id[solved].score


def test_l1_seed_state_moves_with_the_store(tmp_path):
    """The planner's rng rides the f(store, round) seed contract: the
    same store replays the same seed, new evidence moves it (no wall
    clock anywhere)."""
    ws = _ws(tmp_path, [{"id": "C-732", "status": "OPEN"}])
    sig = _sig(ws)
    rng_a, round_a = lv.seed_state(ws)
    rng_b, round_b = lv.seed_state(ws)
    d_a, d_b = rng_a.getrandbits(64), rng_b.getrandbits(64)
    assert (d_a, round_a) == (d_b, round_b), (
        "same store + same round -> the same seed (deterministic replay)")
    lv.record_observation(ws, sig, "dispatch", 1.0, claim="C-732")
    rng_c, _ = lv.seed_state(ws)
    assert rng_c.getrandbits(64) != d_a, (
        "new evidence moves the seed (the #251 contract)")


def test_action_vocabulary_is_the_ruling_list():
    """The L1 action space is exactly the owner ruling's five actions."""
    assert lv.ACTION_KINDS == ("dispatch", "park", "split", "verify",
                               "reuse")
    assert lp.ACTION_KINDS == lv.ACTION_KINDS
    # park is the do-nothing baseline: zero cost, zero value, never a
    # cheapness winner
    assert lp.PARK_COST == 0.0
    assert lp.REUSE_COST > 0.0


def test_knowledge_query_reads_the_cross_task_store(tmp_path, monkeypatch):
    """The cross-task face (T5): a strategy_store row carrying THIS
    claim's identity from another workspace is knowledge (mid-strength),
    and the ws's own rows are never read (the store's leave-one-out
    read)."""
    from rlvr import strategy_store as st

    monkeypatch.setenv(st.STORE_ENV, str(tmp_path / "store"))
    other = tmp_path / "other-ws"
    other.mkdir()
    out = st.append_store_row(other, method_family="static-symbolic",
                              status="ROUND_CREDIT", credit=1.0,
                              dispatch_id="C-733", claim="C-733")
    assert out["appended"] is True
    ws = _ws(tmp_path, [{"id": "C-733", "status": "OPEN"}])
    kc = lp.knowledge_query(ws, "C-733")
    assert kc["solved"] and kc["source"] == "cross_task"
    assert kc["strength"] == pytest.approx(lp.CROSS_TASK_STRENGTH)
    # it IS an answer face: the rank-side drag may consume it
    assert kc["answer_strength"] == pytest.approx(lp.CROSS_TASK_STRENGTH)
    # a claim with no store row stays cold
    assert lp.knowledge_query(ws, "C-999")["solved"] is False
    # the store's leave-one-out read: a row written BY this workspace
    # never makes its own claim "solved elsewhere"
    out2 = st.append_store_row(ws, method_family="static-symbolic",
                               status="ROUND_CREDIT", credit=1.0,
                               dispatch_id="C-734", claim="C-734")
    assert out2["appended"] is True
    assert lp.knowledge_query(ws, "C-734")["solved"] is False, (
        "the ws's own store rows are never read (leave-one-out)")
