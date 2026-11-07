# -*- coding: utf-8 -*-
"""The disposition measurement face.

Each acceptance bullet of the measurement card is pinned here:

- per-disposition denominators (capability / censoring / separate / gap);
- an exhausted episode emits a capability-gap row carrying its
  route-attempt ledger, and an unbacked exhaustion is refused;
- a censored episode reports a censoring rate and never enters strategy
  learning;
- process metrics join the existing sources per run and per arm, with
  explicit None/coverage where a source is absent;
- a learning claim refuses a single-episode verdict and requires a
  pre/post or ablation delta with uncertainty.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "scripts", ROOT / "hooks"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from rlvr import (  # noqa: E402
    consolidated_ledger,
    disposition,
    ledger,
    route_ledger,
    step_ledger,
)
from rlvr import disposition_measure as dm  # noqa: E402

TS = "2026-11-05T00:00:00Z"
SCOPE = {"targets": ["target.example.com"], "excluded": []}


# ---------- fixtures ----------

def _ws(tmp_path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _record(**fields) -> dict:
    record = {
        "claim": "C-001",
        "authorized": True,
        "authorization": SCOPE,
        "target": "target.example.com",
        "oracle_pass": False,
        "wall": None,
        "ledger": None,
        "act_outcomes": [],
        "session": {"returncode": None, "timed_out": False, "liveness": None},
        "strategic_action": None,
        "completion_claimed": False,
    }
    record.update(fields)
    return record


def _write(ws, episode_id="ep-001", claim="C-001", **fields) -> dict:
    return disposition.write_row(
        ws, _record(claim=claim, **fields), episode_id=episode_id, ts=TS)


def _solved(ws, episode_id="ep-solved", claim="C-001", **fields) -> dict:
    return _write(ws, episode_id=episode_id, claim=claim,
                  oracle_pass=True,
                  evidence_refs=["evidence/verdict.json"], **fields)


def _surrender(ws, episode_id="ep-surrender", claim="C-001", **fields) -> dict:
    return _write(ws, episode_id=episode_id, claim=claim, **fields)


def _censored(ws, episode_id="ep-censored", claim="C-001", **fields) -> dict:
    return _write(
        ws, episode_id=episode_id, claim=claim,
        wall={"session_bound": True, "corroborated": True},
        wall_ref="runs/walls/w-001.json", **fields)


def _exhausted(ws, episode_id="ep-exhausted", claim="C-001",
               ref="runs/rt-tests/C-001/routes.json", **fields) -> dict:
    return _write(
        ws, episode_id=episode_id, claim=claim,
        ledger={"routes": ["r1", "r2"], "attempted": ["r1", "r2"],
                "budget": 2},
        route_ledger_ref=ref, **fields)


def _failed(ws, episode_id="ep-failed", claim="C-001", **fields) -> dict:
    return _write(ws, episode_id=episode_id, claim=claim,
                  session={"returncode": 1, "timed_out": False,
                           "liveness": None}, **fields)


def _infra(ws, episode_id="ep-infra", claim="C-001", **fields) -> dict:
    return _write(ws, episode_id=episode_id, claim=claim,
                  act_outcomes=["BLOCKED"], **fields)


def _out_of_scope(ws, episode_id="ep-scope", claim="C-001") -> dict:
    return _write(ws, episode_id=episode_id, claim=claim,
                  authorized=False, authorization=None, target=None)


def _raw_row(ws, episode_id: str, **fields) -> Path:
    """Write a raw row bypassing the write path (the dirty-source face)."""
    row = {
        "schema": "disposition/1",
        "episode_id": episode_id,
        "claim": "C-001",
        "disposition": "SURRENDER",
        "gate": "unfinished",
        "evidence_refs": [],
        "route_ledger_ref": None,
        "wall_ref": None,
        "authorization_ref": None,
        "strategic_action": None,
        "propensity": None,
        "budget": None,
        "ts": TS,
    }
    row.update(fields)
    base = Path(ws) / "runs" / "disposition"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{episode_id}.json"
    path.write_text(json.dumps(row), encoding="utf-8")
    return path


def _q_cell(ws, claim: str, family: str, credit, *, arm_key=None) -> None:
    row = {
        "schema": "q-cell-obs/1",
        "ts": TS,
        "source": "settlement" if credit is not None else "dispatch",
        "signature_hash": "abcdef012345",
        "method_family": family,
        "claim": claim,
        "agent": "worker",
        "credit": credit,
    }
    if arm_key:
        row["arm_key"] = arm_key
    assert consolidated_ledger.append(ws, "experience", row)


def _step_grain(ws, claim: str, step_id: str, calls: int) -> None:
    row = step_ledger.build_step_grain_row(
        session_id="s-1", claim_ref=claim, step_id=step_id,
        call_ids=[f"c{i}" for i in range(calls)], ts=TS)
    assert step_ledger.record_step_grain(ws, row)


def _rollout(ws, claim: str) -> None:
    result = ledger.record(ws, "task", claim, [
        {"type": "probe", "source": "test", "value": 1, "ts": TS}])
    assert result["appended"] is True


def _settle_rollout(ws, claim: str) -> None:
    result = ledger.settle(
        ws, f"task/{claim}",
        {"reward": 1.0, "band": "SETTLED_GREEN", "rule_id": "test",
         "evidence_refs": ["evidence/verdict.json"]})
    assert result["appended"] is True


def _cost_event(ws, amount: float) -> None:
    # #1004: the cost face rides the settlement family's consolidated file
    from rlvr import consolidated_ledger as _cl
    assert _cl.append(ws, "settlement",
                      {"schema": dm.COST_SCHEMA, "ts": TS,
                       "amount": amount, "source": "test"})


def _routes(ws, claim: str, declared: int, attempted: int) -> str:
    rel = f"runs/rt-tests/{claim}/routes.json"
    path = Path(ws) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    routes = [f"route-{i}" for i in range(declared)]
    path.write_text(json.dumps({
        "routes": routes,
        "attempted": routes[:attempted],
        "budget": declared,
        "budget_exhausted": attempted >= declared,
    }), encoding="utf-8")
    return rel


def test_route_pruning_reads_the_production_writer_shape(tmp_path):
    """Cross-module pin: the production route_ledger writer shape must be
    readable by the measurement face instead of reporting a route-less
    ledger."""
    # Arrange: a real ledger written through the only production writer.
    ws = _ws(tmp_path)
    artifact = ws / "evidence" / "a.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"artifact-bytes")
    route_ledger.record_attempt(
        ws, claim="C-1", claim_kind="static_constant",
        route="disasm_constant_check",
        command="python3 check.py --offset=0x10",
        artifact="evidence/a.bin")
    _write(ws, episode_id="ep-rt", claim="C-1",
           ledger={"routes": ["disasm_constant_check"],
                   "attempted": ["disasm_constant_check"], "budget": 3},
           route_ledger_ref="runs/rt-tests/C-1/routes.json")

    # Act
    run = dm.measure(ws)["process"]["per_run"][0]

    # Assert
    assert run["route_pruning_coverage"] == "route_ledger"
    assert run["route_pruning"] is not None
    assert run["route_pruning"]["declared"] == 1


# ---------- per-disposition denominators ----------

def test_denominator_rules_cover_every_disposition():
    # Assert: the closed vocabulary has one declared rule per disposition
    assert set(dm.DENOMINATORS) == set(disposition.DISPOSITIONS)
    for rule in dm.DENOMINATORS.values():
        assert isinstance(rule["capability"], bool)
        assert isinstance(rule["strategy_learning"], bool)
        assert isinstance(rule["censoring"], bool)
        assert isinstance(rule["capability_gap"], bool)
        assert isinstance(rule["reported_separately"], bool)


def test_denominator_rules_carry_the_spec_mapping():
    # Assert: the fixed disposition -> denominator mapping
    rules = dm.DENOMINATORS
    assert rules["SOLVED"]["capability"] is True
    assert rules["SOLVED"]["strategy_learning"] is True
    assert rules["SURRENDER"]["capability"] is True
    assert rules["SURRENDER"]["strategy_learning"] is True
    assert rules["CENSORED_ENV"]["capability"] is False
    assert rules["CENSORED_ENV"]["censoring"] is True
    assert rules["CENSORED_ENV"]["strategy_learning"] is False
    assert rules["ATTEMPTED_EXHAUSTED"]["capability"] is False
    assert rules["ATTEMPTED_EXHAUSTED"]["capability_gap"] is True
    assert rules["ATTEMPTED_EXHAUSTED"]["strategy_learning"] is False
    for word in ("OUT_OF_SCOPE", "INFRA", "FAILED"):
        assert rules[word]["reported_separately"] is True
        assert rules[word]["strategy_learning"] is False


def test_capability_denominator_counts_solved_plus_surrender(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    _solved(ws, episode_id="ep-1", claim="C-1")
    _solved(ws, episode_id="ep-2", claim="C-2")
    _surrender(ws, episode_id="ep-3", claim="C-3")
    _censored(ws, episode_id="ep-4", claim="C-4")
    _exhausted(ws, episode_id="ep-5", claim="C-5")
    _out_of_scope(ws, episode_id="ep-6", claim="C-6")
    _infra(ws, episode_id="ep-7", claim="C-7")
    _failed(ws, episode_id="ep-8", claim="C-8")

    # Act
    report = dm.measure(ws)

    # Assert
    assert report["n_rows"] == 8
    assert report["by_disposition"] == {
        "SOLVED": 2, "OUT_OF_SCOPE": 1, "CENSORED_ENV": 1,
        "ATTEMPTED_EXHAUSTED": 1, "INFRA": 1, "FAILED": 1, "SURRENDER": 1}
    assert report["capability"] == {
        "denominator": 3, "solved": 2, "surrender": 1,
        "success_rate": round(2 / 3, 4)}


def test_success_rate_is_none_when_capability_denominator_is_zero(tmp_path):
    # Arrange: no solved/surrender episode, only censoring
    ws = _ws(tmp_path)
    _censored(ws, episode_id="ep-1", claim="C-1")

    # Act
    report = dm.measure(ws)

    # Assert: insufficient evidence is None, never a fabricated 0.0
    assert report["capability"]["denominator"] == 0
    assert report["capability"]["success_rate"] is None


def test_censoring_rate_is_over_all_valid_rows(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    _solved(ws, episode_id="ep-1", claim="C-1")
    _surrender(ws, episode_id="ep-2", claim="C-2")
    _censored(ws, episode_id="ep-3", claim="C-3")

    # Act
    report = dm.measure(ws)

    # Assert
    assert report["censoring"] == {
        "censored": 1, "denominator": 3, "rate": round(1 / 3, 4)}


def test_censoring_rate_is_none_with_no_episodes(tmp_path):
    # Arrange
    ws = _ws(tmp_path)

    # Act
    report = dm.measure(ws)

    # Assert
    assert report["censoring"]["denominator"] == 0
    assert report["censoring"]["rate"] is None


def test_censored_episode_does_not_enter_strategy_learning(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    _solved(ws, episode_id="ep-solved", claim="C-1")
    _surrender(ws, episode_id="ep-surrender", claim="C-2")
    _censored(ws, episode_id="ep-censored", claim="C-3")
    _failed(ws, episode_id="ep-failed", claim="C-4")

    # Act
    report = dm.measure(ws)

    # Assert: strategy-learning inputs are SOLVED + SURRENDER only
    included = report["strategy_learning"]["episode_ids"]
    assert included == ["ep-solved", "ep-surrender"]
    assert report["strategy_learning"]["included"] == 2
    excluded = report["strategy_learning"]["excluded_from_strategy_learning"]
    assert excluded["CENSORED_ENV"] == 1
    assert excluded["FAILED"] == 1


def test_out_of_scope_infra_failed_reported_separately(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    _out_of_scope(ws, episode_id="ep-scope", claim="C-1")
    _infra(ws, episode_id="ep-infra", claim="C-2")
    _failed(ws, episode_id="ep-failed", claim="C-3")

    # Act
    report = dm.measure(ws)

    # Assert
    assert report["reported_separately"] == {
        "OUT_OF_SCOPE": 1, "INFRA": 1, "FAILED": 1}
    assert report["strategy_learning"]["included"] == 0


# ---------- capability gaps ----------

def test_exhausted_run_emits_capability_gap_with_route_ledger(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    ref = "runs/rt-tests/C-001/routes.json"
    _exhausted(ws, episode_id="ep-exhausted", claim="C-001", ref=ref)

    # Act
    report = dm.measure(ws)

    # Assert
    assert len(report["capability_gaps"]) == 1
    gap = report["capability_gaps"][0]
    assert gap["schema"] == "capability-gap/1"
    assert gap["episode_id"] == "ep-exhausted"
    assert gap["claim"] == "C-001"
    assert gap["disposition"] == "ATTEMPTED_EXHAUSTED"
    assert gap["route_ledger_ref"] == ref
    assert gap["budget"] == 2
    assert gap["strategy_credit"] is None
    assert gap["learning_verdict"] is None
    assert report["capability_gap_refusals"] == []


def test_exhausted_run_without_route_ledger_is_refused(tmp_path):
    # Arrange: a raw exhaustion row with no ledger reference
    ws = _ws(tmp_path)
    _raw_row(ws, "ep-unbacked", disposition="ATTEMPTED_EXHAUSTED",
             gate="route_ledger", route_ledger_ref=None)

    # Act
    report = dm.measure(ws)

    # Assert: no gap row is emitted; the fall to SURRENDER is recorded and
    # measured (the failure stays in the capability denominator)
    assert report["capability_gaps"] == []
    assert len(report["capability_gap_refusals"]) == 1
    refusal = report["capability_gap_refusals"][0]
    assert refusal["episode_id"] == "ep-unbacked"
    assert "route_ledger_ref" in refusal["reason"]
    assert refusal["measured_as"] == "SURRENDER"
    assert report["by_disposition"]["ATTEMPTED_EXHAUSTED"] == 0
    assert report["by_disposition"]["SURRENDER"] == 1
    assert report["capability"]["denominator"] == 1
    assert report["capability"]["success_rate"] == 0.0
    assert report["strategy_learning"]["episode_ids"] == ["ep-unbacked"]
    # The recorded row stays visible beside the measured row
    assert report["rows"][0]["disposition"] == "ATTEMPTED_EXHAUSTED"
    assert report["measured_rows"][0]["disposition"] == "SURRENDER"
    process = report["process"]["per_run"][0]
    assert process["disposition"] == "SURRENDER"
    assert process["recorded_disposition"] == "ATTEMPTED_EXHAUSTED"


def test_exhausted_run_with_unsafe_route_ref_is_refused(tmp_path):
    # Arrange: a traversal reference is not a workspace-relative ledger
    ws = _ws(tmp_path)
    _write(ws, episode_id="ep-traversal", claim="C-1",
           ledger={"routes": ["r1"], "attempted": ["r1"], "budget": 1},
           route_ledger_ref="../../etc/passwd")

    # Act
    report = dm.measure(ws)

    # Assert: refused, never carried as a usable gap reference
    assert report["capability_gaps"] == []
    refusal = report["capability_gap_refusals"][0]
    assert "workspace-relative" in refusal["reason"]
    assert report["by_disposition"]["SURRENDER"] == 1


def test_exhausted_run_is_not_in_the_capability_denominator(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    _exhausted(ws, episode_id="ep-exhausted", claim="C-1")

    # Act
    report = dm.measure(ws)

    # Assert
    assert report["capability"]["denominator"] == 0
    assert report["by_disposition"]["ATTEMPTED_EXHAUSTED"] == 1


# ---------- tolerant readers ----------

def test_absent_sources_read_as_empty(tmp_path):
    # Arrange
    ws = _ws(tmp_path)

    # Act
    report = dm.measure(ws)

    # Assert
    assert report["schema"] == "disposition-measure/1"
    assert report["n_rows"] == 0
    assert report["n_invalid"] == 0
    assert report["capability"]["success_rate"] is None
    assert report["process"]["per_run"] == []
    assert report["process"]["per_arm"] == {}


def test_dirty_sources_are_empty_contributions(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    _solved(ws, episode_id="ep-good", claim="C-1")
    base = Path(ws) / "runs" / "disposition"
    (base / "corrupt.json").write_text("{not json", encoding="utf-8")
    (base / "list.json").write_text("[1, 2]", encoding="utf-8")
    (base / "no-identity.json").write_text(
        json.dumps({"schema": "disposition/1"}), encoding="utf-8")

    # Act
    report = dm.measure(ws)

    # Assert: the good row still measures; dirty rows contribute nothing
    assert report["n_rows"] == 1
    assert report["n_invalid"] == 3
    assert report["by_disposition"]["SOLVED"] == 1


def test_mirror_rows_are_read_and_deduped_with_files(tmp_path):
    # Arrange: one file-backed episode plus one mirror-only episode
    ws = _ws(tmp_path)
    _solved(ws, episode_id="ep-file", claim="C-1")
    row = disposition.build_row(_record(claim="C-2"),
                                episode_id="ep-mirror", ts=TS)
    assert consolidated_ledger.append(ws, "telemetry", row)

    # Act
    report = dm.measure(ws)

    # Assert: both episodes count once each (mirror is not a double)
    assert report["n_rows"] == 2
    assert report["by_disposition"]["SOLVED"] == 1
    assert report["by_disposition"]["SURRENDER"] == 1
    assert report["sources"]["mirror_only"] == 1


def test_malformed_mirror_row_is_an_empty_contribution(tmp_path):
    # Arrange: a mirror row with a disposition stamp but no usable identity
    ws = _ws(tmp_path)
    assert consolidated_ledger.append(
        ws, "telemetry", {"schema": "disposition/1", "episode_id": "ep-x"})

    # Act
    report = dm.measure(ws)

    # Assert
    assert report["n_rows"] == 0
    assert report["n_invalid"] == 1


def test_capability_gap_rows_cover_alternate_route_ledger_shapes(tmp_path):
    # Arrange: a name-keyed routes map with per-route attempts
    ws = _ws(tmp_path)
    rel = "runs/rt-tests/C-001/routes.json"
    path = Path(ws) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "routes": {
            "alpha": {"attempted": True},
            "beta": {"attempts": [{"command": "probe"}]},
            "gamma": {},
        },
    }), encoding="utf-8")
    ref = _routes(ws, "C-002", declared=1, attempted=1)
    _write(ws, episode_id="ep-1", claim="C-001",
           ledger={"routes": ["alpha", "beta", "gamma"],
                   "attempted": ["alpha", "beta"], "budget": 3,
                   "budget_exhausted": True},
           route_ledger_ref=rel,
           evidence_refs=["evidence/route.log"])
    _exhausted(ws, episode_id="ep-2", claim="C-002", ref=ref)

    # Act
    report = dm.measure(ws)

    # Assert: both exhaustion rows emit gaps carrying their ledger refs
    refs = {gap["episode_id"]: gap for gap in report["capability_gaps"]}
    assert refs["ep-1"]["evidence_refs"] == ["evidence/route.log"]
    assert refs["ep-1"]["budget"] == 3
    assert refs["ep-2"]["route_ledger_ref"] == ref
    runs = {run["episode_id"]: run for run in report["process"]["per_run"]}
    assert runs["ep-1"]["route_pruning"] == {
        "declared": 3, "attempted": 2, "pruned": 1, "pruned_fraction": 0.3333}


def test_missing_route_ledger_file_is_an_explicit_none(tmp_path):
    # Arrange: the row points at a ledger that does not exist
    ws = _ws(tmp_path)
    _write(ws, episode_id="ep-1", claim="C-1",
           ledger={"routes": ["r1"], "attempted": ["r1"], "budget": 1},
           route_ledger_ref="runs/rt-tests/C-1/routes.json")

    # Act
    report = dm.measure(ws)

    # Assert
    run = report["process"]["per_run"][0]
    assert run["route_pruning"] is None
    assert run["route_pruning_coverage"] == "missing"


def test_cost_events_skip_dirty_lines(tmp_path):
    # Arrange — #1004: the cost face rides the settlement family's
    # consolidated file; a non-numeric amount row never enters the sum
    # (the family read skips unparseable lines silently)
    ws = _ws(tmp_path)
    _surrender(ws, episode_id="ep-1", claim="C-1")
    from rlvr import consolidated_ledger as _cl
    assert _cl.append(ws, "settlement",
                      {"schema": dm.COST_SCHEMA, "ts": TS,
                       "amount": "nope", "source": "test"})
    assert _cl.append(ws, "settlement",
                      {"schema": dm.COST_SCHEMA, "ts": TS,
                       "amount": 1.25, "source": "test"})

    # Act
    report = dm.measure(ws)

    # Assert
    cost = report["process"]["workspace"]["cost"]
    assert cost["amount"] == 1.25
    assert cost["events"] == 1
    assert cost["files"] == [dm.COST_FACE]


# ---------- process metrics ----------

def test_process_metrics_per_run_join_existing_sources(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    ref = _routes(ws, "C-001", declared=4, attempted=2)
    _solved(ws, episode_id="ep-1", claim="C-001", route_ledger_ref=ref)
    _q_cell(ws, "C-001", "family-a", 0.8)
    _q_cell(ws, "C-001", "family-a", 0.0)
    _q_cell(ws, "C-001", "family-a", None)  # pending dispatch: no credit
    _step_grain(ws, "C-001", "st-1", 2)
    _step_grain(ws, "C-001", "st-2", 3)
    _rollout(ws, "C-001")
    _settle_rollout(ws, "C-001")
    _cost_event(ws, 0.25)
    _cost_event(ws, 0.50)

    # Act
    report = dm.measure(ws)

    # Assert
    per_run = report["process"]["per_run"]
    assert len(per_run) == 1
    run = per_run[0]
    assert run["episode_id"] == "ep-1"
    assert run["claim"] == "C-001"
    assert run["steps"] == 5            # two grains: 2 + 3 calls
    assert run["steps_coverage"] == 2
    assert run["cost"] is None          # no per-run cost identity exists
    assert run["cost_coverage"] == "unattributable"
    assert run["dead_end_rate"] == 0.5  # one of two settled credits is zero
    assert run["dead_end_settled"] == 2
    assert run["route_pruning"] == {
        "declared": 4, "attempted": 2, "pruned": 2,
        "pruned_fraction": 0.5}
    assert run["route_pruning_quality"] == 0.5
    assert run["rollouts"] == 1          # identity + amendment = one rollout
    assert run["rollout_settlements"] == 1
    workspace = report["process"]["workspace"]
    assert workspace["cost"]["amount"] == pytest.approx(0.75)
    assert workspace["cost"]["events"] == 2
    assert workspace["cost"]["coverage"].startswith("workspace-total")


def test_process_metrics_per_arm(tmp_path):
    # Arrange: two arms split by the q-cell method family
    ws = _ws(tmp_path)
    _solved(ws, episode_id="ep-1", claim="C-1")
    _surrender(ws, episode_id="ep-2", claim="C-2")
    _q_cell(ws, "C-1", "family-a", 1.0)
    _q_cell(ws, "C-2", "family-b", 0.0)
    _step_grain(ws, "C-1", "st-1", 2)
    _step_grain(ws, "C-2", "st-2", 4)

    # Act
    report = dm.measure(ws)

    # Assert
    arms = report["process"]["per_arm"]
    assert set(arms) == {"family-a", "family-b"}
    assert arms["family-a"]["episodes"] == 1
    assert arms["family-a"]["steps"] == 2
    assert arms["family-a"]["dead_end_rate"] == 0.0
    assert arms["family-a"]["dead_end_settled"] == 1
    assert arms["family-b"]["episodes"] == 1
    assert arms["family-b"]["steps"] == 4
    assert arms["family-b"]["dead_end_rate"] == 1.0
    assert arms["family-b"]["dead_end_settled"] == 1
    assert arms["family-b"]["by_disposition"] == {"SURRENDER": 1}


def test_per_arm_does_not_double_count_a_shared_claim(tmp_path):
    # Arrange: two episodes on one claim (the join grain is the claim)
    ws = _ws(tmp_path)
    _solved(ws, episode_id="ep-1", claim="C-001")
    _surrender(ws, episode_id="ep-2", claim="C-001")
    _q_cell(ws, "C-001", "family-a", 1.0)
    _step_grain(ws, "C-001", "st-1", 3)

    # Act
    report = dm.measure(ws)

    # Assert: episodes count per episode, joined metrics once per claim
    arm = report["process"]["per_arm"]["family-a"]
    assert arm["episodes"] == 2
    assert arm["steps"] == 3
    assert arm["steps_coverage"] == 1
    assert arm["dead_end_settled"] == 1
    runs = {run["episode_id"]: run for run in report["process"]["per_run"]}
    assert runs["ep-1"]["claim_metrics_owner"] == "ep-1"
    assert runs["ep-1"]["steps"] == 3
    assert runs["ep-2"]["claim_metrics_owner"] == "ep-1"
    assert runs["ep-2"]["steps"] is None
    assert runs["ep-2"]["steps_coverage"] == 0


def test_shared_claim_with_different_actions_does_not_split_across_arms(
        tmp_path):
    # Arrange: no q-cell rows, so the arm falls back to the strategic
    # action; the two episodes record different actions
    ws = _ws(tmp_path)
    _write(ws, episode_id="ep-1", claim="C-001",
           strategic_action="FIGHT", propensity=0.5)
    _write(ws, episode_id="ep-2", claim="C-001",
           strategic_action="INVEST", propensity=0.5)
    _step_grain(ws, "C-001", "st-1", 7)

    # Act
    report = dm.measure(ws)

    # Assert: the claim's metrics land in exactly one arm
    per_arm = report["process"]["per_arm"]
    assert set(per_arm) == {"FIGHT"}
    assert per_arm["FIGHT"]["episodes"] == 2
    assert per_arm["FIGHT"]["steps"] == 7
    assert sum(arm["steps"] for arm in per_arm.values()) == 7


def test_rollout_identity_and_amendment_count_once(tmp_path):
    # Arrange: a record row plus a settle amendment share one rollout id
    ws = _ws(tmp_path)
    _surrender(ws, episode_id="ep-1", claim="C-001")
    _rollout(ws, "C-001")
    _settle_rollout(ws, "C-001")

    # Act
    report = dm.measure(ws)

    # Assert
    run = report["process"]["per_run"][0]
    assert run["rollouts"] == 1
    assert run["rollout_settlements"] == 1


def test_learning_claim_rejects_an_unrepresentable_cohort_size():
    # Act / Assert: a huge integer is a contract error, not OverflowError
    with pytest.raises(dm.LearningClaimError):
        dm.learning_claim(
            "success_rate",
            pre={"n": 10 ** 400, "value": 0.2, "stderr": 0.1},
            post={"n": 4, "value": 0.6, "stderr": 0.1})


def test_learning_claim_rejects_unrepresentable_cohort_numbers():
    # Act / Assert: value / stderr / sample overflow is a contract error
    huge = 10 ** 400
    post = {"n": 4, "value": 0.6, "stderr": 0.1}
    for pre in (
            {"n": 4, "value": huge, "stderr": 0.1},
            {"n": 4, "value": 0.2, "stderr": huge},
            {"values": [huge, 1, 0]}):
        with pytest.raises(dm.LearningClaimError):
            dm.learning_claim("success_rate", pre=pre, post=post)


def test_exhausted_run_with_drive_letter_ref_is_refused(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    _write(ws, episode_id="ep-drive", claim="C-1",
           ledger={"routes": ["r1"], "attempted": ["r1"], "budget": 1},
           route_ledger_ref="C:" + "/Windows/system32/config")

    # Act
    report = dm.measure(ws)

    # Assert
    assert report["capability_gaps"] == []
    assert "workspace-relative" in report["capability_gap_refusals"][0][
        "reason"]


def test_process_metrics_report_explicit_absence(tmp_path):
    # Arrange: a disposition row with no process sources at all
    ws = _ws(tmp_path)
    _surrender(ws, episode_id="ep-1", claim="C-1")

    # Act
    report = dm.measure(ws)

    # Assert: unavailable metrics are explicit None + zero coverage
    run = report["process"]["per_run"][0]
    assert run["steps"] is None
    assert run["steps_coverage"] == 0
    assert run["cost"] is None
    assert run["dead_end_rate"] is None
    assert run["dead_end_settled"] == 0
    assert run["route_pruning"] is None
    assert run["route_pruning_quality"] is None
    assert run["arm"] == "unknown"
    workspace = report["process"]["workspace"]
    assert workspace["cost"]["amount"] is None
    assert workspace["cost"]["events"] == 0


def test_route_ledger_outside_the_workspace_is_ignored(tmp_path):
    # Arrange: a row points at a traversal ref
    ws = _ws(tmp_path)
    _write(ws, episode_id="ep-1", claim="C-1",
           ledger={"routes": ["r1"], "attempted": ["r1"], "budget": 1},
           route_ledger_ref="../outside.json")

    # Act
    report = dm.measure(ws)

    # Assert
    run = report["process"]["per_run"][0]
    assert run["route_pruning"] is None
    assert run["route_pruning_coverage"] == "refused"


def test_huge_integer_cost_amount_is_a_dirty_line(tmp_path):
    # Arrange: one amount above float range plus one valid amount
    # (#1004: the rows ride the settlement family's consolidated file)
    ws = _ws(tmp_path)
    _surrender(ws, episode_id="ep-1", claim="C-1")
    from rlvr import consolidated_ledger as _cl
    assert _cl.append(ws, "settlement",
                      {"schema": dm.COST_SCHEMA, "ts": TS,
                       "amount": 10 ** 400, "source": "test"})
    assert _cl.append(ws, "settlement",
                      {"schema": dm.COST_SCHEMA, "ts": TS,
                       "amount": 1.25, "source": "test"})

    # Act
    report = dm.measure(ws)

    # Assert: the dirty line is absorbed, the report still measures
    cost = report["process"]["workspace"]["cost"]
    assert cost["amount"] == 1.25
    assert cost["events"] == 1


# ---------- learning claims ----------

def test_learning_claim_refuses_single_episode_verdict():
    # Act / Assert: one cohort is not a delta
    with pytest.raises(dm.LearningClaimError):
        dm.learning_claim(
            "success_rate", pre={"n": 5, "value": 0.4, "stderr": 0.1})


def test_learning_claim_refuses_a_single_rollout_cohort():
    # Act / Assert: n=1 on either side is a single-episode verdict
    with pytest.raises(dm.LearningClaimError):
        dm.learning_claim(
            "success_rate",
            pre={"n": 1, "value": 0.0, "stderr": 0.0},
            post={"n": 5, "value": 0.4, "stderr": 0.1})


def test_learning_claim_requires_uncertainty():
    # Act / Assert: a bare point estimate cannot carry a claim
    with pytest.raises(dm.LearningClaimError):
        dm.learning_claim(
            "success_rate",
            pre={"n": 4, "value": 0.25},
            post={"n": 4, "value": 0.75})


def test_learning_claim_pre_post_emits_a_delta_row():
    # Act
    claim = dm.learning_claim(
        "success_rate",
        pre={"n": 4, "value": 0.25, "stderr": 0.1},
        post={"n": 4, "value": 0.75, "stderr": 0.1})

    # Assert
    expected_se = math.sqrt(0.1 ** 2 + 0.1 ** 2)
    assert claim["schema"] == "learning-claim/1"
    assert claim["metric"] == "success_rate"
    assert claim["design"] == "pre_post"
    assert claim["delta"] == 0.5
    assert claim["uncertainty"] == round(expected_se, 6)
    assert claim["ci95"] == [
        round(0.5 - 1.96 * expected_se, 6),
        round(0.5 + 1.96 * expected_se, 6)]
    assert claim["cohorts"]["pre"]["n"] == 4
    assert claim["cohorts"]["post"]["n"] == 4


def test_learning_claim_ablation_delta():
    # Act
    claim = dm.learning_claim(
        "success_rate",
        ablation={
            "arm": {"n": 5, "value": 0.6, "stderr": 0.05},
            "control": {"n": 5, "value": 0.3, "stderr": 0.05},
        })

    # Assert
    assert claim["design"] == "ablation"
    assert claim["delta"] == pytest.approx(0.3)
    assert claim["cohorts"]["arm"]["n"] == 5
    assert claim["cohorts"]["control"]["n"] == 5


def test_learning_claim_accepts_sample_values():
    # Act
    claim = dm.learning_claim(
        "success_rate",
        pre={"values": [0, 0, 1, 0]},
        post={"values": [1, 1, 1, 1]})

    # Assert
    assert claim["cohorts"]["pre"]["n"] == 4
    assert claim["cohorts"]["pre"]["value"] == pytest.approx(0.25)
    assert claim["cohorts"]["post"]["value"] == pytest.approx(1.0)
    assert claim["delta"] == pytest.approx(0.75)


def test_learning_claim_rejects_two_delta_designs():
    # Act / Assert: pre/post and ablation are mutually exclusive
    with pytest.raises(dm.LearningClaimError):
        dm.learning_claim(
            "success_rate",
            pre={"n": 4, "value": 0.2, "stderr": 0.1},
            post={"n": 4, "value": 0.6, "stderr": 0.1},
            ablation={"arm": {"n": 4, "value": 0.6, "stderr": 0.1},
                      "control": {"n": 4, "value": 0.2, "stderr": 0.1}})


def test_learning_claim_rejects_a_pre_cohort_on_an_ablation_claim():
    # Act / Assert: a stray pre cohort is refused, never silently dropped
    with pytest.raises(dm.LearningClaimError):
        dm.learning_claim(
            "success_rate",
            pre={"n": 4, "value": 0.2, "stderr": 0.1},
            ablation={"arm": {"n": 4, "value": 0.6, "stderr": 0.1},
                      "control": {"n": 4, "value": 0.2, "stderr": 0.1}})


def test_learning_claim_rejects_non_finite_cohort_sizes():
    # Act / Assert: inf / nan are contract errors, not raw Python errors
    for bad_n in (float("inf"), float("nan")):
        with pytest.raises(dm.LearningClaimError):
            dm.learning_claim(
                "success_rate",
                pre={"n": bad_n, "value": 0.2, "stderr": 0.1},
                post={"n": 4, "value": 0.6, "stderr": 0.1})


def test_empty_cohort_cannot_form_a_claim():
    # Arrange
    cohort = dm.success_rate_cohort([])

    # Assert: an empty cohort is explicitly insufficient
    assert cohort == {"n": 0, "value": None, "successes": 0, "stderr": None}
    with pytest.raises(dm.LearningClaimError):
        dm.learning_claim(
            "success_rate",
            pre=cohort,
            post={"n": 4, "value": 0.5, "stderr": 0.1})


def test_success_rate_cohort_uses_the_capability_denominator(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    _solved(ws, episode_id="ep-1", claim="C-1")
    _surrender(ws, episode_id="ep-2", claim="C-2")
    _censored(ws, episode_id="ep-3", claim="C-3")
    _exhausted(ws, episode_id="ep-4", claim="C-4")
    report = dm.measure(ws)

    # Act
    cohort = dm.success_rate_cohort(report["measured_rows"])

    # Assert
    assert cohort["n"] == 2
    assert cohort["value"] == 0.5
    assert cohort["successes"] == 1
    assert cohort["stderr"] == pytest.approx(math.sqrt(0.5 * 0.5 / 2))
