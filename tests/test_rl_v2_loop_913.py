# -*- coding: utf-8 -*-
"""tests/test_rl_v2_loop_913.py — the unified decision loop (#913).

``experiments/learning-loop/loop.py`` is the #909 harness promoted to
the production loop face: the same protocol, with the carried pins
BUILT IN (not bolted on). The pins this suite drives:

  LAPS      N >= 5 laps of the full protocol with per-seam receipts
            (select/assign/execute/terminate/settle/credit/belief);
  PHASES    the phase-tag envelope — the closed vocab stamped on every
            dispatch receipt + action row, the goal-tree inference
            rule, the worker challenge channel;
  INTENT    the intent declaration — expected_output +
            eliminates_uncertainty on every dispatch, fail-closed;
  WALL      the belief evidence-wall — evidence_refs resolve into the
            fact base BEFORE apply_proposals banks (the loop's pinned
            duty from #898's review);
  CLOCK     the deterministic driver clock — no wall clock in any
            landed row, byte-identical ledgers modulo ts across
            identical runs;
  V-WIRE    P(s) -> credit/advantage values via progress.values_from;
  STAG      the stagnation advisory consumed — widen the assigner
            candidates + down-weight the current direction (advisory:
            the faces still decide);
  ARBITER   the rollback/rollup arbiter — ΔP's sign decides rollup
            (commit; the settled state carries) vs rollback (discard +
            negative advantage; the facts still bank);
  FAULTS    the #909 fault matrix re-run through the REAL loop — the
            observed responses hold.

Mock worker only; deterministic seeds; no wall clock in any assertion.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop",
           ROOT / "experiments" / "learning-loop" / "sim", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import loop as loop913  # noqa: E402
from loop_worker import mock_worker  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import learning_seal as seal  # noqa: E402
import method_families  # noqa: E402 — the closed vocabulary owner
from rlvr import q_cells  # noqa: E402
from settlement import draft_commit, per_dispatch  # noqa: E402
from state import belief, progress  # noqa: E402

CORE = loop913.CORE_TASK


@pytest.fixture(autouse=True)
def _unarmed_seal(monkeypatch, tmp_path):
    """The suite's default seal posture (the 903/887/909 posture): rows
    pass through unsigned; the unsealed-row pin re-arms locally."""
    monkeypatch.setattr(seal, "KEY_PATH", tmp_path / "absent.key")
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})


@pytest.fixture(autouse=True)
def _isolated_store_root(monkeypatch, tmp_path):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))


def _run(tmp_path, name: str = "ws", **kw: Any):
    ws = tmp_path / name
    ws.mkdir()
    # the suite's orchestrator choice, explicit in one place (spawn_slots
    # is a required, never-defaulted decision per the #924 policy)
    kw.setdefault("spawn_slots", 1)
    kw.setdefault("worker", mock_worker)
    run, ws2 = loop913.run_loop(ws, **kw)
    return run["report"], ws2


def _no_ts(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _no_ts(v) for k, v in value.items() if k != "ts"}
    if isinstance(value, list):
        return [_no_ts(v) for v in value]
    return value


def _idx(rows: list[dict], pred) -> list[int]:
    return [i for i, row in enumerate(rows) if pred(row)]


def _is_action(row: dict, kind: str, rid: str | None = None) -> bool:
    if row.get("schema") != q_cells.SCHEMA_ACTION_V2 \
            or row.get("kind") != kind:
        return False
    return rid is None or str(row.get("rollout_id") or "") == rid


def _is_result(row: dict, rid: str) -> bool:
    return row.get("schema") == q_cells.SCHEMA_RESULT_V2 \
        and str(row.get("rollout_id") or "") == rid


def _all_steps(report: dict) -> list[dict]:
    return [step for lap in report["per_lap"]
            for ro in lap["rollouts"] for step in ro["steps"]]


def _first_verified_rollout(report: dict) -> dict:
    for lap in report["per_lap"]:
        for ro in lap["rollouts"]:
            if ro["verified_dispatches"] > 0:
                return ro
    raise AssertionError("no rollout with a verified dispatch")


# ------------------------------------------------- laps + per-seam receipts

def test_five_laps_full_protocol_with_per_seam_receipts(tmp_path):
    """N=5 laps of the COMPLETE protocol: every seam's receipt rides
    the lap record, every seam landed its ledger row, and the loop
    never stops."""
    run, ws = _run(tmp_path, laps=5, seed=7)
    assert run["schema"] == loop913.SCHEMA
    assert run["chain_stopped_lap"] is None
    assert [lap["lap"] for lap in run["per_lap"]] == [1, 2, 3, 4, 5]
    rows = q_cells.trajectory_rows(ws)
    assert len(rows) > 0
    for lap in run["per_lap"]:
        rid = lap["rollouts"][0]["rollout_id"]
        assert lap["picks"][0]["receipt"]["schema"] == "task-select/1"
        assert _idx(rows, lambda r: _is_action(r, "select_task", rid))
        ro = lap["rollouts"][0]
        for step in ro["steps"]:
            assert step["assign"]["schema"] == "method-assign/1"
            assert step["spawn"]["schema"] == "spawn-receipt/1"
            assert step["brief"]["schema"] == "dispatch-brief/1"
            assert step["action_row"]["row"]["schema"] \
                == q_cells.SCHEMA_ACTION_V2
            assert step["result_row"]["row"]["schema"] \
                == q_cells.SCHEMA_RESULT_V2
            assert step["draft"]["schema"] == per_dispatch.DRAFT_SCHEMA
        assert lap["watchdog"]["deadline"]["schema"] \
            == "watchdog-deadline/1"
        assert lap["belief"]["snapshot"]["schema"] == belief.SCHEMA
        marker = [r for r in cl.read(ws, "settlement")
                  if r.get("schema") == draft_commit.COMMIT_SCHEMA
                  and r.get("rollout_id") == rid]
        discard = [r for r in cl.read(ws, "settlement")
                   if r.get("schema") == draft_commit.DISCARD_SCHEMA
                   and r.get("rollout_id") == rid]
        assert marker or discard, rid
    beliefs = _idx(rows, lambda r: r.get("reason") == belief.REASON_BELIEF)
    assert len(beliefs) == 5


def test_p_series_monotone_through_rollups(tmp_path):
    """P(s) only moves through the arbiter: a rollup carries the
    ladder's PROVEN mass, a rollback reverts — the series is monotone
    across the whole run."""
    run, _ws = _run(tmp_path, laps=5, seed=7)
    series = run["p_series"]
    assert len(series) >= 5
    assert all(b <= a for b, a in zip(series, series[1:]))
    assert any(ro["disposition"] == "rolled_up"
               for lap in run["per_lap"] for ro in lap["rollouts"])


# ------------------------------------------------------------- the pins

def test_phase_envelope_closed_vocab_and_inference_rule(tmp_path):
    """Every dispatch receipt + action row params carry a phase from
    the CLOSED vocab; the inference rule is the goal-tree position
    (the rollout's PROVEN rung indexes the phase ladder)."""
    run, ws = _run(tmp_path, laps=3, seed=7)
    rows = q_cells.trajectory_rows(ws)
    for step in _all_steps(run):
        assert step["phase"] in loop913.PHASES
        params = step["action_row"]["row"]["params"]
        assert params["phase"] == step["phase"]
    first = run["per_lap"][0]["rollouts"][0]["steps"][0]
    assert first["phase"] == "triage"      # nothing proven -> the base
    # the documented rule, unit-pinned: proven rung -> phase
    g = lambda s: progress.Subgoal(  # noqa: E731
        id=f"g-ro-x-{s}", status="UNVERIFIED")
    p = lambda s: progress.Subgoal(  # noqa: E731
        id=f"g-ro-x-{s}", status="PROVEN", evidence_refs=("F0101",))
    assert loop913.infer_phase([], "ro-x") == "triage"
    assert loop913.infer_phase([p("a")], "ro-x") == "understand"
    assert loop913.infer_phase([p("a"), p("b")], "ro-x") == "build-env"
    assert loop913.infer_phase([p("a"), p("b"), p("c"), p("d"), p("e"),
                                p("f")], "ro-x") == "verify"
    assert loop913.infer_phase([g("z")], "ro-x") == "triage"
    # another rollout's proven rungs never leak into this one's phase
    other = progress.Subgoal(id="g-ro-other-a", status="PROVEN",
                             evidence_refs=("F0101",))
    assert loop913.infer_phase([other], "ro-x") == "triage"
    # the ladder walks IN ORDER along a rollout's verified run
    for lap in run["per_lap"]:
        for ro in lap["rollouts"]:
            phases = [s["phase"] for s in ro["steps"]]
            rungs = [loop913.PHASES.index(ph) for ph in phases]
            assert rungs == sorted(rungs), phases
    # every landed action row's phase sits on the closed vocab too
    for row in rows:
        if _is_action(row, "assign_step"):
            assert row["params"]["phase"] in loop913.PHASES


def test_phase_challenge_channel(tmp_path):
    """The worker may challenge the inferred phase: a legal challenge
    is recorded on the dispatch receipt (the orchestrator's inference
    stays authoritative for the CURRENT dispatch); an off-vocab
    challenge is a caller bug — refused loudly."""
    seen: dict[str, Any] = {}

    def challenged_worker(situation: str, family: str):
        seen["called"] = True
        return {"verified": True, "tokens": loop913.RIGHT_TOKENS,
                "seconds": loop913.RIGHT_SECONDS,
                "phase_challenge": "understand"}

    run, _ws = _run(tmp_path, laps=1, seed=7, worker=challenged_worker)
    steps = run["per_lap"][0]["rollouts"][0]["steps"]
    assert seen["called"]
    challenged = [s for s in steps if s.get("phase_challenge")]
    assert challenged and challenged[0]["phase_challenge"] == "understand"

    def bad_worker(situation: str, family: str):
        return {"verified": False, "tokens": loop913.WRONG_TOKENS,
                "seconds": loop913.WRONG_SECONDS,
                "phase_challenge": "warp"}

    with pytest.raises(loop913.LoopError, match="phase"):
        _run(tmp_path, name="ws2", laps=1, seed=7, worker=bad_worker)


def test_intent_declaration_fail_closed(tmp_path):
    """Every dispatch declares intent (expected_output +
    eliminates_uncertainty) and the declaration rides the assign
    receipt + the action row; a dispatch without intent is structural —
    refused before anything lands."""
    run, ws = _run(tmp_path, laps=2, seed=7)
    for step in _all_steps(run):
        intent = step["intent"]
        assert intent["expected_output"].strip()
        assert intent["eliminates_uncertainty"].strip()
        assert step["action_row"]["row"]["params"]["intent"] == intent
        assert step["assign"]["intent"] == intent
    # the fail-closed face
    for bad in (None, {}, {"expected_output": "x"},
                {"expected_output": "x", "eliminates_uncertainty": "  "}):
        with pytest.raises(loop913.LoopError):
            loop913.require_intent(bad)
    for phase in loop913.PHASES:
        doc = loop913.declare_intent(phase, CORE)
        assert doc["expected_output"] and doc["eliminates_uncertainty"]


def test_evidence_wall_before_banking(tmp_path):
    """THE LOOP'S PINNED DUTY (#898 review): every evidence_ref in a
    banking proposal must resolve into the fact base BEFORE
    apply_proposals runs — a fabricated ref refuses, never banks."""
    run, ws = _run(tmp_path, laps=2, seed=7)
    stems = {p.stem for p in (ws / "facts").glob("F*.md")}
    assert stems, "the clean run landed facts"
    for step in _all_steps(run):
        if step.get("eval_doc"):
            refs = step["eval_doc"]["proposals"][0]["evidence_refs"]
            assert set(refs) <= stems
    # the wall itself: a fabricated ref refuses before banking
    doc = {"schema": "trajectory-evaluation/1", "new_facts": [],
           "validated_hypotheses": [], "rejected_hypotheses": [],
           "unresolved_questions": [], "possible_new_directions": [],
           "exploration_progress": 0.0, "redundancy": 0.0,
           "proposals": [{"subgoal_id": "g-x", "to_status": "PROVEN",
                          "evidence_refs": ("F9999",)}]}
    with pytest.raises(loop913.LoopError, match="F9999"):
        loop913.evidence_wall(ws, doc)
    # a resolving ref passes the wall
    fid = sorted(stems)[0]
    ok = dict(doc, proposals=[{"subgoal_id": "g-x", "to_status": "PROVEN",
                               "evidence_refs": (fid,)}])
    loop913.evidence_wall(ws, ok)          # no raise
    # and the wall precedes apply_proposals: with BOTH a bad ref and a
    # banking proposal, the wall raises before the tree moves
    tree = (progress.Subgoal(id="g-x", status="UNVERIFIED"),)
    with pytest.raises(loop913.LoopError):
        loop913.bank_evaluation(ws, tree, dict(doc))


def test_deterministic_driver_clock_no_wall_clock(tmp_path):
    """The loop owns the clock: every landed row (select and belief
    INCLUDED — the #909 threading) carries the counter stamp, and two
    identical runs land byte-identical ledgers modulo ts."""
    run_a, ws_a = _run(tmp_path, name="a", laps=3, seed=7)
    run_b, ws_b = _run(tmp_path, name="b", laps=3, seed=7)
    rows_a = q_cells.trajectory_rows(ws_a)
    rows_b = q_cells.trajectory_rows(ws_b)
    settle_a = cl.read(ws_a, "settlement")
    settle_b = cl.read(ws_b, "settlement")
    assert _no_ts(rows_a) == _no_ts(rows_b)
    assert _no_ts(settle_a) == _no_ts(settle_b)
    assert _no_ts(run_a) == _no_ts(run_b)
    for row in rows_a + settle_a:
        ts = str(row.get("ts") or "")
        assert ts.startswith("2026-01-01T"), ts
    # the two named faces carry the driver clock explicitly
    sel = next(r for r in rows_a if _is_action(r, "select_task"))
    bel = next(r for r in rows_a
               if r.get("reason") == belief.REASON_BELIEF)
    assert sel["ts"].startswith("2026-01-01T")
    assert bel["ts"].startswith("2026-01-01T")


def test_v_wiring_p_series_into_advantage(tmp_path):
    """V wiring: the per-step P ladder feeds credit/advantage through
    progress.values_from — a moving baseline subtracts (A != R), the
    flat cold start keeps the pinned A == R identity."""
    run, ws = _run(tmp_path, laps=4, seed=7)
    ro = _first_verified_rollout(run)
    assert ro["advantage_source"] == "values"
    rows = q_cells.trajectory_rows(ws)
    term = next(r for r in rows if _is_result(r, ro["rollout_id"])
                and str(r.get("step_id")) == f"{ro['rollout_id']}-terminal")
    assert term["A_t"] != term["R_t"]      # the baseline moved the A
    # the decision-time P values rode values_from: the rollout receipt
    # carries the exact series the advantage consumed
    assert ro["p_decisions"] == [pytest.approx(v) for v in
                                 ro["v_series_used"]]
    # a dead rollout STILL moves P (its subgoal births are real tree
    # states) — the baseline subtracts there too, and the COLD identity
    # (values_from -> None -> A == R) is pinned on the flat series
    dead_run, dead_ws = _run(tmp_path, name="dead", laps=2, seed=7,
                             situation="dead-1")
    dead = dead_run["per_lap"][0]["rollouts"][0]
    assert dead["advantage_source"] == "values"
    drows = q_cells.trajectory_rows(dead_ws)
    dterm = next(r for r in drows
                 if _is_result(r, dead["rollout_id"])
                 and str(r.get("step_id"))
                 == f"{dead['rollout_id']}-terminal")
    assert dterm["A_t"] != dterm["R_t"]
    flat = loop913.terminal_advantage(
        [0.0, 0.0], [0.5, 0.5], [3.0, 3.0])
    assert flat["source"] == "cold"
    assert flat["advantage"][-1] == flat["shaped"][-1]


def test_stagnation_advisory_widens_and_downweights(tmp_path):
    """The stagnation receipt is consumed at the data level: the next
    assign's candidate set widens to the full registry vocabulary and
    the current direction's planner rank is down-weighted; the receipt
    itself stays advisory (no terminate row, the faces still decide).
    A real ΔP move clears the posture."""
    registry = sorted(method_families.registered_tokens(None))
    run, ws = _run(tmp_path, laps=3, seed=7, situation="dead-1")
    advisories = [ro["stagnation"] for lap in run["per_lap"]
                  for ro in lap["rollouts"] if ro["stagnation"]]
    assert advisories, "two flat segments must advise"
    assert all(a["terminates"] is False for a in advisories)
    steps = _all_steps(run)
    widened = [s for s in steps
               if sorted(s["assign"]["candidates"]) == registry]
    assert widened, "the post-advice assigns must widen the candidates"
    direction = widened[0]["direction"]
    assert widened[0]["assign"]["candidates"][direction]["rank"] \
        == loop913.STAGNATION_RANK_PENALTY
    assert widened[0]["assign"]["candidates"][direction]["p_llm"] \
        == pytest.approx(1.0 / loop913.STAGNATION_RANK_PENALTY)
    # no terminate row out of the advisory (the β terminator decides)
    rows = q_cells.trajectory_rows(ws)
    for row in rows:
        if _is_action(row, "rollback"):
            assert row["params"].get("rule") != "stagnation"


def test_rollback_rollup_arbiter_delta_p_sign(tmp_path):
    """ΔP's sign decides the end-of-rollout disposition: positive ->
    rollup (the commit marker lands, the settled tree carries);
    non-positive -> rollback (the audited discard lands, the advantage
    is negative, the settled tree reverts — and the per-dispatch facts
    STILL bank)."""
    run, ws = _run(tmp_path, laps=5, seed=3)
    srows = cl.read(ws, "settlement")
    rolled_up = [ro for lap in run["per_lap"] for ro in lap["rollouts"]
                 if ro["disposition"] == "rolled_up"]
    rolled_back = [ro for lap in run["per_lap"] for ro in lap["rollouts"]
                   if ro["disposition"] == "rolled_back"]
    assert rolled_up and rolled_back
    for ro in rolled_up:
        assert ro["delta_p"] > 0
        assert ro["p_after"] > ro["p_before"]
        marker = [r for r in srows
                  if r.get("schema") == draft_commit.COMMIT_SCHEMA
                  and r.get("rollout_id") == ro["rollout_id"]]
        assert marker
    for ro in rolled_back:
        assert ro["delta_p"] <= 0
        assert ro["p_after"] == ro["p_before"]      # the tree reverts
        assert ro["terminal_r_t"] < 0               # negative advantage
        discard = [r for r in srows
                   if r.get("schema") == draft_commit.DISCARD_SCHEMA
                   and r.get("rollout_id") == ro["rollout_id"]]
        assert discard and "delta_p" in discard[0].get("reason", "")
        # the facts still banked: every settled step's fold obs landed
        for step in ro["steps"]:
            assert step["banked_credit"] is not None
    # the arbiter's disposition is the terminal the ledger records
    rows = q_cells.trajectory_rows(ws)
    for ro in rolled_up:
        assert _idx(rows, lambda r, rid=ro["rollout_id"]:
                    _is_action(r, "terminate_rollout", rid))
    for ro in rolled_back:
        assert _idx(rows, lambda r, rid=ro["rollout_id"]:
                    _is_action(r, "rollback", rid))


# ------------------------------- the #909 fault matrix through the REAL loop

def test_fault_matrix_select_empty_candidates(tmp_path):
    run, ws = _run(tmp_path, laps=3, seed=7,
                   faults={"select": "empty_candidates"})
    assert run["chain_stopped_lap"] == 2
    lap = run["per_lap"][1]
    assert lap["fault"]["response"] == "raised-fail-closed"
    rows = q_cells.trajectory_rows(ws)
    assert not _idx(rows, lambda r: _is_action(
        r, "select_task", "ro-core-lap2"))


def test_fault_matrix_execute_worker_exception(tmp_path):
    run, ws = _run(tmp_path, laps=3, seed=7,
                   faults={"execute": "worker_exception"})
    lap = run["per_lap"][1]
    ro = lap["rollouts"][0]
    assert ro["fault"]["response"] == "worker-raise-captured"
    faulted = [s for s in ro["steps"] if s["fault"]]
    assert faulted and faulted[0]["result_row"] is None
    assert ro["disposition"] == "rolled_back"
    # the loop CONTINUES: lap 3 ran its own full rollout
    assert run["per_lap"][2]["rollouts"][0]["steps"]
    assert run["chain_stopped_lap"] is None


def test_fault_matrix_execute_worker_garbage(tmp_path):
    run, ws = _run(tmp_path, laps=3, seed=7,
                   faults={"execute": "worker_garbage"})
    lap = run["per_lap"][1]
    ro = lap["rollouts"][0]
    faulted = [s for s in ro["steps"] if s["fault"]]
    assert faulted and faulted[0]["fault"]["response"] == "result-refused"
    assert ro["disposition"] == "rolled_back"
    assert run["per_lap"][2]["rollouts"][0]["steps"]


def test_fault_matrix_settle_crash_mid_rollout(tmp_path):
    run, ws = _run(tmp_path, laps=2, seed=7,
                   faults={"settle": "crash_mid_rollout"})
    lap = run["per_lap"][1]
    assert lap["fault"]["seam"] == "settle"
    recovery = lap["fault"]["recovery"]
    assert recovery["late_commit"]["appended"]
    rid = lap["rollouts"][0]["rollout_id"]
    marker = [r for r in cl.read(ws, "settlement")
              if r.get("schema") == draft_commit.COMMIT_SCHEMA
              and r.get("rollout_id") == rid]
    assert marker


def test_fault_matrix_credit_out_of_rail(tmp_path):
    run, _ws = _run(tmp_path, laps=2, seed=7,
                    faults={"credit": "out_of_rail_credit"})
    lap = run["per_lap"][1]
    receipts = [s["bank_receipt"] for ro in lap["rollouts"]
                for s in ro["steps"] if s["bank_receipt"]]
    assert receipts and receipts[0]["injected"] == 2.5
    assert receipts[0]["banked"] == 1.0 and receipts[0]["clamped"]


def test_fault_matrix_ledger_noise(tmp_path, monkeypatch,
                                   tmp_path_factory):
    """The ledger walls hold through the real loop: an unsealed row
    (ARMED seal) and a foreign-schema row are both EXCLUDED from every
    trusted read."""
    arm = tmp_path_factory.mktemp("seal") / "seal.key"
    arm.write_bytes(b"k" * 64)
    monkeypatch.setattr(seal, "KEY_PATH", arm)
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
    run, ws = _run(tmp_path, name="armed", laps=3, seed=7,
                   faults={"ledger": "unsealed_row"})
    assert run["per_lap"][1]["noise"]["observed"] == "excluded"
    run2, ws2 = _run(tmp_path, name="foreign", laps=3, seed=7,
                     faults={"ledger": "foreign_schema"})
    assert run2["per_lap"][1]["noise"]["observed"] == "excluded"
    for w in (ws, ws2):
        assert all("noise-909" not in str(r.get("target") or "")
                   for r in q_cells.trajectory_rows(w))


def test_fault_matrix_watchdog_malformed_deadline(tmp_path):
    run, _ws = _run(tmp_path, laps=2, seed=7,
                    faults={"watchdog": "malformed_deadline"})
    lap = run["per_lap"][1]
    assert lap["watchdog"]["fault"]["response"] == "cold-default-rearmed"
    assert lap["watchdog"]["deadline"]["cold"] is True
    assert lap["watchdog"]["fault"]["error"]


def test_fault_matrix_belief_malformed_spec(tmp_path):
    run, _ws = _run(tmp_path, laps=2, seed=7,
                    faults={"belief": "malformed_spec"})
    lap = run["per_lap"][1]
    assert lap["belief"]["fault"]["observed"] == "honest-empty"
    assert lap["belief"]["snapshot"]["open_questions"] == []
