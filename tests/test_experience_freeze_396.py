# -*- coding: utf-8 -*-
"""tests/test_experience_freeze_396.py — the ZERO-behavior-change proof
(issue 396 hard invariant).

The v0.1.6 recording face must be pure recording: benchmarks measure the
CURRENT behavior, so the diff may not alter any dispatch/gate/settlement
decision. Four mechanical pins:

  1. IMPORT DIRECTION  no decision face (dispatch gate, worker budget,
     recall inject, settlement rules, convergence/priority decide chain)
     imports the recording modules — recording can only be pulled by the
     post-session loop-runner telemetry site;
  2. SETTLEMENT BYTE IDENTITY  the rollout ledger's byte prefix is
     identical with recording interleaved: extraction/snapshot/journal
     writes never amend settlement rows, and a settlement re-run after
     recording produces zero new rows (dedupe holds);
  3. HARVEST METRICS INVARIANT  eval_loop_runner.harvest returns the
     same metrics before and after the recording calls on the same
     workspace;
  4. NO DECISION INPUT reads the derived views: the recording output
     filenames appear nowhere in the settlement/decision module sources.
All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(SCRIPTS))

import eval_loop_runner as elr  # noqa: E402
import experience_triples as xt  # noqa: E402
import rollout_ledger as rl  # noqa: E402
import scalar_settlement as ss  # noqa: E402
import state_signature as ssig  # noqa: E402
import tc_journal  # noqa: E402

RECORDING_MODULES = ("state_signature", "tc_journal", "experience_triples")

# the decision faces that must never pull recording in
DECISION_SOURCES = [
    HOOKS / "dispatch_gate.py",
    HOOKS / "worker_budget.py",
    HOOKS / "worker_budget_core.py",
    HOOKS / "worker_budget_gates.py",
    HOOKS / "worker_budget_sinks.py",
    HOOKS / "recall_inject.py",
    HOOKS / "completion_gate.py",
    SCRIPTS / "reward_settlement.py",
    SCRIPTS / "scalar_settlement.py",
    SCRIPTS / "convergence_check.py",
    SCRIPTS / "priority_ratio.py",
    SCRIPTS / "rollout_ledger.py",
]

DERIVED_VIEW_NAMES = ("triples.csv", "situation-stream.jsonl",
                      "tc-journal.jsonl")

TS = "2026-09-27T00:00:00Z"


def _module_imports(path: Path) -> set[str]:
    """Top-level + nested import names of one module (AST)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


# ---------- 1. import direction ----------

class TestImportDirection:
    @pytest.mark.parametrize("src", DECISION_SOURCES,
                             ids=lambda p: p.name)
    def test_decision_face_never_imports_recording(self, src):
        assert src.is_file(), f"decision face missing: {src}"
        imports = _module_imports(src)
        touch = imports & set(RECORDING_MODULES)
        assert not touch, f"{src.name} imports recording: {touch}"

    def test_recording_never_imports_settlement_rules(self):
        """Recording reads the ledger read-face only — it must not import
        the frozen rules module (reward_settlement) at all."""
        for mod in RECORDING_MODULES:
            imports = _module_imports(SCRIPTS / f"{mod}.py")
            assert "reward_settlement" not in imports


# ---------- 2. settlement byte identity ----------

def _seed_settled_workspace(ws: Path) -> None:
    signals = [
        {"type": "oracle_verdict", "source": "checker", "value": "pass",
         "ts": TS},
        {"type": "unit_family", "source": "manifest", "value": "kdf",
         "ts": TS},
        {"type": "strategy_arm", "source": "eval", "value": "arm-a",
         "ts": TS},
        {"type": "method_choices", "source": "eval", "value": ["x"],
         "ts": TS},
    ]
    rl.record(ws, kind="task", anchor="T-1", signals=signals)
    rl.settle(ws, "task/T-1", {
        "reward": 1.0, "band": "SETTLED_GREEN", "rule_id": "r/1",
        "evidence_refs": []})
    rl.record(ws, kind=ss.KIND_ROUND_CREDIT, anchor="C-1", signals=[
        {"type": "round_credit_signal", "source": "scalar_settlement",
         "value": {"credited": 1, "waste": 0}, "ts": TS}])
    rl.settle(ws, "round_credit/C-1", {
        "reward": 1.0, "band": ss.BAND_ROUND_CREDIT,
        "rule_id": ss.RULE_ROUND_CREDIT, "evidence_refs": [],
        "credited": ["F001"], "waste": 0.0, "round": 1, "untraced": [],
        "settled_ts": TS})
    # a settlement-eligible task rollout (tier scalar pending)
    rl.record(ws, kind="task", anchor="T-2", signals=[
        {"type": "oracle_verdict", "source": "checker", "value": "pass",
         "ts": TS},
        {"type": "unit_difficulty", "source": "manifest", "value": "hard",
         "ts": TS},
    ])


def _ledger_bytes(ws: Path) -> bytes:
    p = ws / "runs" / "rollout-ledger.jsonl"
    if not p.is_file():
        return b""
    return p.read_bytes()


class TestSettlementByteIdentity:
    def test_recording_interleave_leaves_ledger_byte_identical(
            self, tmp_path):
        _seed_settled_workspace(tmp_path)
        rules = ROOT / "references" / "contracts" / "reward-rules.yaml"
        before = _ledger_bytes(tmp_path)

        # the recording suite, exactly as the runner wiring invokes it
        tc_journal.harvest_from_log(tmp_path)
        ssig.append_snapshot(tmp_path, trigger="worker_return")
        xt.extract(tmp_path)

        assert _ledger_bytes(tmp_path) == before

        # settlement re-runs after recording: dedupe holds, zero churn
        r1 = ss.settle_workspace_scalars(tmp_path, rules_path=rules)
        assert _ledger_bytes(tmp_path) != before  # T-2 tier amendment lands
        after_tier = _ledger_bytes(tmp_path)
        r2 = ss.settle_workspace_scalars(tmp_path, rules_path=rules)
        tc_journal.harvest_from_log(tmp_path)
        ssig.append_snapshot(tmp_path, trigger="terminal")
        xt.extract(tmp_path)
        assert r2["settled"] == 0
        assert _ledger_bytes(tmp_path) == after_tier
        assert r1["settled"] == 1

    def test_extract_repeats_are_byte_identical(self, tmp_path):
        _seed_settled_workspace(tmp_path)
        xt.extract(tmp_path)
        csv1 = (tmp_path / "runs" / "triples.csv").read_bytes()
        ssig.append_snapshot(tmp_path, trigger="terminal")
        tc_journal.harvest_from_log(tmp_path)
        xt.extract(tmp_path)
        csv2 = (tmp_path / "runs" / "triples.csv").read_bytes()
        assert csv1 == csv2  # derived view: same inputs, same bytes


# ---------- 3. harvest metrics invariant ----------

class TestHarvestMetricsInvariant:
    def test_harvest_unchanged_by_recording(self, tmp_path):
        runs = tmp_path / "runs"
        runs.mkdir()
        (tmp_path / ".convergence_ledger.jsonl").write_text(
            json.dumps({"open_count": 1}) + "\n", encoding="utf-8")
        (runs / "oracle-status.json").write_text(json.dumps(
            {"cases": {"c1": {"status": "pass"}}}), encoding="utf-8")
        (runs / "mission_ledger.yaml").write_text(yaml.safe_dump(
            {"mission": {"history": [
                {"events": {"dispatch": 2}, "cost_tokens": 11.0}]}}),
            encoding="utf-8")
        (tmp_path / "cost_events.jsonl").write_text(
            json.dumps({"amount": 1.0}) + "\n", encoding="utf-8")
        m1 = elr.harvest(tmp_path)
        tc_journal.harvest_from_log(tmp_path)
        ssig.append_snapshot(tmp_path, trigger="terminal")
        xt.extract(tmp_path)
        m2 = elr.harvest(tmp_path)
        assert m1 == m2


# ---------- 4. derived views are not decision inputs ----------

class TestDerivedViewsNotRead:
    @pytest.mark.parametrize("src", DECISION_SOURCES,
                             ids=lambda p: p.name)
    def test_no_decision_face_reads_derived_views(self, src):
        text = src.read_text(encoding="utf-8")
        for name in DERIVED_VIEW_NAMES:
            assert name not in text, (
                f"{src.name} references derived view {name}")

    def test_runner_wiring_site_is_fail_open(self):
        """The runner's recording helper must swallow every exception
        (telemetry never breaks the measurement path)."""
        import inspect
        helper = getattr(elr, "_record_experience", None)
        assert helper is not None, "runner recording helper missing"
        source = inspect.getsource(helper)
        assert "except Exception" in source
        assert "_warn_fail_open" in source
