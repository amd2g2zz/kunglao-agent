# -*- coding: utf-8 -*-
"""tests/test_settlement_fairness_689.py — settlement fairness contracts.

Issue 689 (settlement is unfair across worker sizes): the ladder receipt
ignores cost, dispatches are not counted independently of the DLQ
failure-strike counter, branch_budget has zero consumers, and infra
refusals book into the strategy pools as if the strategy failed.

Pinned contracts:

1. equal output at higher cost settles LOWER on the sorted observation
   face (r_sorted = r_ladder - lambda * cost) while the banked ladder
   receipt stays the ladder value — ordering/observation only.
2. dispatch_count is an independent register field; promotion_attempts
   stays the DLQ failure-strike counter; attempts_of = the max (a
   failed dispatch counts once — flip potential decay + rank feed),
   strikes_of = failures only (candidate filter unchanged).
3. a branch_budget overrun lands in attributed waste and subtracts from
   r (the hard budget constraint's settlement face).
4. an infra outcome is classified infra, rides the store row, and never
   contributes mass to a warm strategy pool.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
for p in (SCRIPTS, SCRIPTS.parent / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import dead_letter as dl  # noqa: E402
import priority_ratio as pr  # noqa: E402
from rlvr import ledger as rl  # noqa: E402
from rlvr import scalar as ss  # noqa: E402
from rlvr import strategy_store as store  # noqa: E402


def _artifact(fid: str, creator: str, *, cited: bool = True) -> dict:
    return {"id": fid, "creator": creator, "status": "PROVEN",
            "verify_status": "passes",
            "cited_by_deliverable": cited, "answers_question": False,
            "oracle_backed_refutation": False}


# ---------------------------------------------- 1. cost sorts, receipt holds

def test_higher_cost_same_output_settles_lower():
    """Same credited output, higher cost -> lower r_sorted; the ladder
    receipt r is identical (cost is ordering/observation only)."""
    artifacts = [_artifact("F001-a", "d-cheap"),
                 _artifact("F002-b", "d-dear")]
    dispatches = [{"dispatch_id": "d-cheap", "round": 1, "cost": 0.0},
                  {"dispatch_id": "d-dear", "round": 2, "cost": 5.0}]
    out = ss.round_credit(dispatches, artifacts, waste=[])
    rows = {r["dispatch_id"]: r for r in out["rows"]}
    assert rows["d-cheap"]["r"] == rows["d-dear"]["r"] == 1.0
    assert rows["d-dear"]["r_sorted"] < rows["d-cheap"]["r_sorted"]
    assert rows["d-dear"]["r_sorted"] == 1.0 - ss.SORT_COST_LAMBDA * 5.0


def test_ladder_receipt_unchanged_by_cost_term(tmp_path):
    """The banked settlement reward is the ladder value even when the
    dispatch carried cost; r_sorted rides the settlement additively and
    the Q bank still sees the ladder r."""
    ws = tmp_path / "ws-cost"
    ws.mkdir()
    artifacts = [_artifact("F010-a", "d-1")]
    dispatches = [{"dispatch_id": "d-1", "round": 1, "cost": 3.0}]
    res = ss.settle_round_credit(ws, dispatches, artifacts, [])
    assert res["banked"] == ["d-1"]
    fold = rl.fold(ws, "round_credit/d-1")
    settlement = fold["settlement"]
    assert settlement["reward"] == 1.0  # the ladder receipt, not r_sorted
    assert settlement["r_sorted"] == pytest.approx(1.0
                                                  - ss.SORT_COST_LAMBDA * 3.0)


# --------------------------------------- 2. dispatch_count vs failure strikes

def _register(tmp_path, claim_id="C-1", **extra) -> Path:
    ws = tmp_path / "ws-reg"
    ws.mkdir(exist_ok=True)
    claims = [{"id": claim_id, "status": "OPEN",
               "promotion_attempts": 0, **extra}]
    lines = ["claims:"]
    for c in claims:
        lines.append(f"- id: {c['id']}")
        for k, v in c.items():
            if k == "id":
                continue
            lines.append(f"  {k}: {v}")
    (ws / "claim-register.yaml").write_text("\n".join(lines) + "\n",
                                           encoding="utf-8")
    return ws


def test_dispatch_count_separate_from_promotion_attempts(tmp_path):
    """A dispatch increments dispatch_count only; a failure increments
    promotion_attempts only; attempts_of is the dispatch mass (a failed
    dispatch is ONE attempt — the strike is a quality signal inside it,
    never a second attempt); strikes_of is the failure face the
    candidate filter keeps."""
    ws = _register(tmp_path)
    for _ in range(2):
        out = dl.record_dispatch_count(ws, "C-1")
        assert out["counted"] is True
    strike = dl.record_dispatch_failure(ws, "C-1")
    assert strike["incremented"] is True
    claim = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8"))[
        "claims"][0]
    assert claim["dispatch_count"] == 2
    assert claim["promotion_attempts"] == 1
    assert pr.dispatch_count_of(claim) == 2
    assert pr.strikes_of(claim) == 1
    assert pr.attempts_of(claim) == 2  # not 3: no double-counting
    # legacy registers without the counter fall back to the strikes
    assert pr.attempts_of({"promotion_attempts": 2}) == 2
    # the flip-potential decay + the rank feed see the dispatch mass
    actions = pr.priority_ratio(
        [dict(claim, answers_question="q1")], {},
        pr.EvidenceView())
    feed = actions[0].feeds["case_flip_potential"]
    assert "dispatches=2" in feed
    assert "failure_strikes=1" in feed
    # dispatch churn alone never evicts the claim from the frontier
    churned = {"id": "C-9", "promotion_attempts": 0, "dispatch_count": 5}
    assert pr.strikes_of(churned) < 3
    assert any(a.claim_id == "C-9" for a in pr.priority_ratio(
        [churned], {}, pr.EvidenceView()))


# ------------------------------------------- 3. branch_budget -> attributed waste

def test_budget_overrun_subtracts_from_r():
    """A branch_budget overrun books attributed waste (wall overrun
    normalized at COST_SECONDS_DIV, one unit per extra retry) and
    subtracts from r; a within-budget sibling is untouched."""
    artifacts = [_artifact("F020-a", "d-over"),
                 _artifact("F021-b", "d-ok")]
    dispatches = [
        {"dispatch_id": "d-over", "round": 1,
         "branch_budget": {"wall_s": 100, "retries": 1},
         "usage": {"wall_s": 4600, "retries": 3}},
        {"dispatch_id": "d-ok", "round": 2,
         "branch_budget": {"wall_s": 100, "retries": 1},
         "usage": {"wall_s": 50, "retries": 1}},
    ]
    out = ss.round_credit(dispatches, artifacts, waste=[])
    rows = {r["dispatch_id"]: r for r in out["rows"]}
    # wall over = (4600-100)/3600 = 1.25, retries over = 2 -> 3.25 waste
    assert rows["d-over"]["waste"] == pytest.approx(3.25)
    assert rows["d-over"]["budget_overrun"] == pytest.approx(3.25)
    assert rows["d-over"]["r"] == pytest.approx(1.0 - 3.25)
    assert rows["d-ok"]["waste"] == 0.0
    assert rows["d-ok"]["r"] == 1.0
    assert "budget_overrun" not in rows["d-ok"]


# --------------------------------------------- 4. infra never books as strategy

def test_infra_outcome_not_booked_as_strategy(tmp_path, monkeypatch):
    """BLOCKED classifies infra; an infra store row carries the class and
    contributes zero mass to a warm strategy pool."""
    assert ss.classify_outcome("BLOCKED") == "infra"
    assert ss.classify_outcome("TIMEOUT") == "censored"
    assert ss.classify_outcome("DISPATCHED") == "strategy"
    assert ss.classify_outcome("FAIL") == "strategy"
    root = tmp_path / "posterior-store"
    root.mkdir()
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(root))
    ws_a = tmp_path / "ws-a"
    ws_a.mkdir()
    assert store.append_store_row(
        ws_a, method_family="frida", status="BLOCKED", credit=0.0,
        outcome_class="infra")["appended"]
    assert store.append_store_row(
        ws_a, method_family="frida", status="DISPATCHED", credit=1.0,
        outcome_class="strategy")["appended"]
    row = json.loads(
        (root / store.STORE_REL).read_text(encoding="utf-8"
                                           ).splitlines()[0])
    assert row["outcome_class"] == "infra"
    pools = store.warm_pools(tmp_path / "ws-b", ["frida"])
    # only the strategy row books mass; the infra refusal is invisible
    assert pools["frida"].rows == 1
