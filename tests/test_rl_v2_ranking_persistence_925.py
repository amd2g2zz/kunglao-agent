# -*- coding: utf-8 -*-
"""tests/test_rl_v2_ranking_persistence_925.py — decision-time ranking
distributions persisted to the ledger (card 925; reconciled onto the
#924/#926 wave — the suite helper passes the required worker and
spawn_slots explicitly per the #924 policy).

The old loop's ranking face recorded every ranking COMPLETE (scores,
full order, input fingerprint). The rl-v2 loop's decision-time
distributions lived only in the in-memory run report: the selector's
per-task {alpha, beta, theta} map and the assigner's per-candidate
{rank, p_llm, alpha, beta, theta, weight} doc were report-only, while
the ledger action rows carried just the winner. The logging bar
(screen logs do not count; only FILE rows count) applies to rankings.

The substrate is the ACTION ROW itself (not a paired telemetry row):
the decision's distribution is the decision's own payload, so it rides
the ``select_task`` / ``assign_step`` action-row ``params`` under the
key ``distribution``. The pins:

  PERSIST  a decision lands -> its FULL candidate distribution is
           readable back from the persistent face (selector AND
           assigner), with the complete per-candidate field set;
  EQUALITY the persisted values equal the run-report values exactly
           (one representation, no drift between face and ledger);
  WINNER   the row's target is consistent with the persisted
           distribution (selector: the sorted argmax over theta;
           assigner: the proportional replay over the persisted
           weights reproduces the recorded family);
  DETERMIN the distributions are posterior-derived, clock-free
           content — identical runs land identical rows (driver-clock
           stamps included), re-reads are stable;
  WIDENED  the stagnation-widened assign (the full registry
           vocabulary) persists its wide distribution too.

Mock worker only; deterministic seeds; no wall clock in any assertion.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import loop as loop913  # noqa: E402
from loop_worker import mock_worker  # noqa: E402
import method_families  # noqa: E402 — the closed vocabulary owner
from rlvr import learning_seal as seal  # noqa: E402
from rlvr import q_cells  # noqa: E402

SEL_FIELDS = frozenset({"alpha", "beta", "theta"})
ASSIGN_FIELDS = frozenset(
    {"rank", "p_llm", "alpha", "beta", "theta", "weight"})


@pytest.fixture(autouse=True)
def _unarmed_seal(monkeypatch, tmp_path):
    """The suite's default seal posture (the sibling rl-v2 suites'
    posture): rows pass through unsigned."""
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
    # and the worker are required, never-defaulted decisions per the
    # #924 policy)
    kw.setdefault("spawn_slots", 1)
    kw.setdefault("worker", mock_worker)
    run, ws2 = loop913.run_loop(ws, **kw)
    return run["report"], ws2


def _kind_rows(ws, kind: str) -> list[dict]:
    return [row for row in q_cells.trajectory_rows(ws)
            if row.get("schema") == q_cells.SCHEMA_ACTION_V2
            and row.get("kind") == kind]


def _all_steps(report: dict) -> list[dict]:
    return [step for lap in report["per_lap"]
            for ro in lap["rollouts"] for step in ro["steps"]]


def _all_picks(report: dict) -> list[dict]:
    return [pick for lap in report["per_lap"] for pick in lap["picks"]]


# ------------------------------------------------------- the selector face

def test_select_row_persists_the_full_distribution(tmp_path):
    """Every select_task action row carries the FULL per-task
    {alpha, beta, theta} distribution, equal to the report receipt."""
    report, ws = _run(tmp_path, laps=2, seed=7)
    rows = {str(r["rollout_id"]): r for r in _kind_rows(ws, "select_task")}
    picks = _all_picks(report)
    assert picks, "the run made selections"
    assert set(rows) == {str(p["row"]["rollout_id"]) for p in picks}
    for pick in picks:
        rid = str(pick["row"]["rollout_id"])
        row = rows[rid]
        dist = row["params"]["distribution"]
        receipt_doc = pick["receipt"]["candidates"]
        assert dist == receipt_doc, \
            f"{rid}: the persisted distribution drifts from the receipt"
        assert set(dist) == set(receipt_doc)
        for tid, doc in dist.items():
            assert frozenset(doc) == SEL_FIELDS, (rid, tid)
            assert doc["alpha"] >= 1.0 and doc["beta"] >= 1.0
            assert 0.0 <= doc["theta"] <= 1.0
            assert doc["theta"] == round(doc["theta"], 6)


def test_select_winner_is_the_persisted_argmax(tmp_path):
    """The row's target is the largest persisted theta (sorted fork
    order breaks ties) — the Thompson draw the face ran."""
    report, ws = _run(tmp_path, laps=3, seed=7)
    for row in _kind_rows(ws, "select_task"):
        dist = row["params"]["distribution"]
        chosen = max(sorted(dist), key=lambda t: dist[t]["theta"])
        assert row["target"] == chosen, \
            f"{row['rollout_id']}: winner vs persisted argmax"


# -------------------------------------------------------- the assigner face

def test_assign_row_persists_the_full_distribution(tmp_path):
    """Every assign_step action row carries the FULL per-candidate
    {rank, p_llm, alpha, beta, theta, weight} distribution, equal to
    the report receipt, with the harmonic conversion intact."""
    report, ws = _run(tmp_path, laps=2, seed=7)
    rows = {str(r["step_id"]): r for r in _kind_rows(ws, "assign_step")}
    steps = _all_steps(report)
    assert steps, "the run dispatched steps"
    assert set(rows) == {str(s["step_id"]) for s in steps}
    for step in steps:
        row = rows[str(step["step_id"])]
        dist = row["params"]["distribution"]
        receipt_doc = step["assign"]["candidates"]
        assert dist == receipt_doc, \
            f"{step['step_id']}: the persisted distribution drifts"
        assert row["params"]["method_family"] == row["target"]
        for fam, doc in dist.items():
            assert frozenset(doc) == ASSIGN_FIELDS, (step["step_id"], fam)
            assert doc["rank"] >= 1.0
            assert doc["p_llm"] == pytest.approx(1.0 / doc["rank"])
            assert doc["weight"] == round(doc["p_llm"] * doc["theta"], 6)
            assert 0.0 <= doc["theta"] <= 1.0


def _replay_assign_winner(row: dict, seed: int) -> str:
    """The proportional replay over the PERSISTED weights: the same
    anchor draw the face threaded (the loop's per-dispatch seed), the
    same sorted cumulative walk — the recorded family must fall out."""
    rid = str(row["rollout_id"])
    sid = str(row["step_id"])
    step_no = int(sid.rsplit("-s", 1)[1])
    base = random.Random(
        f"loop913/{seed}/{rid}/{step_no}/assign").getrandbits(64)
    dist = row["params"]["distribution"]
    order = sorted(dist)
    total = math.fsum(dist[f]["weight"] for f in order)
    u = random.Random(f"method-assign-select/{base}").random() * total
    chosen = order[-1]
    cumulative = 0.0
    for family in order:
        cumulative += dist[family]["weight"]
        if u <= cumulative:
            chosen = family
            break
    return chosen


def test_assign_winner_is_the_persisted_replay(tmp_path):
    """The row's target reproduces from the persisted distribution
    alone (the anchor seed is ledger-state-derived and documented)."""
    report, ws = _run(tmp_path, laps=3, seed=7)
    for row in _kind_rows(ws, "assign_step"):
        assert row["target"] == _replay_assign_winner(row, 7), \
            f"{row['rollout_id']}: winner vs persisted replay"


def test_widened_assign_persists_the_wide_distribution(tmp_path):
    """The stagnation-widened assign (full registry vocabulary) lands
    its WIDE distribution too — the widen posture never thins the
    persistent record."""
    registry = sorted(method_families.registered_tokens(None))
    report, ws = _run(tmp_path, laps=3, seed=7, situation="dead-1")
    rows = {str(r["step_id"]): r for r in _kind_rows(ws, "assign_step")}
    widened = [s for s in _all_steps(report)
               if sorted(s["assign"]["candidates"]) == registry]
    assert widened, "the flat-window advice must widen the candidates"
    for step in widened:
        dist = rows[str(step["step_id"])]["params"]["distribution"]
        assert dist == step["assign"]["candidates"]
        assert set(dist) == set(registry)


# ------------------------------------------------- coverage + determinism

def test_every_decision_lands_its_distribution(tmp_path):
    """The coverage pin over a whole run: one distribution-bearing row
    per selection AND per dispatch — a decision without its persistent
    distribution is the hole this card closes."""
    report, ws = _run(tmp_path, laps=4, seed=7)
    sel_rows = _kind_rows(ws, "select_task")
    asg_rows = _kind_rows(ws, "assign_step")
    assert len(sel_rows) == len(_all_picks(report))
    assert len(asg_rows) == len(_all_steps(report))
    assert all("distribution" in r["params"] for r in sel_rows + asg_rows)


def test_distributions_are_clock_free_and_deterministic(tmp_path):
    """The distributions are posterior-derived: no clock field inside
    any candidate doc, and two identical runs land byte-identical rows
    (driver-clock stamps included)."""
    report_a, ws_a = _run(tmp_path, name="a", laps=3, seed=7)
    _report_b, ws_b = _run(tmp_path, name="b", laps=3, seed=7)
    rows_a = _kind_rows(ws_a, "select_task") \
        + _kind_rows(ws_a, "assign_step")
    rows_b = _kind_rows(ws_b, "select_task") \
        + _kind_rows(ws_b, "assign_step")
    assert len(rows_a) == len(rows_b)
    for ra, rb in zip(rows_a, rows_b):
        assert ra == rb, "identical runs must land identical rows"
        for doc in ra["params"]["distribution"].values():
            assert not (frozenset(doc) & {"ts", "wall", "now", "time"}), \
                "a distribution doc carries no clock"
    # re-read stability: same ledger -> same persisted rows
    assert q_cells.trajectory_rows(ws_a) == q_cells.trajectory_rows(ws_a)
