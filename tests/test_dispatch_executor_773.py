# -*- coding: utf-8 -*-
"""tests/test_dispatch_executor_773.py — the RL executor wiring.

W2: the dispatch gate's sampler is the EXIT — an undeclared dispatch
draws one reject-with-guidance carrying the sampled family; cold
sampler keeps the honest default row. W3: plan() consumes live — the
admission receipt lands at the dispatch ALLOW tail
(runs/plan-receipts.jsonl, schema plan-receipt/1).

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
for p in (str(ROOT), str(SCRIPTS), str(HOOKS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import rlvr.strategy_store as _ss_preinit  # noqa: E402,F401

# Pin the WORKTREE rlvr.strategy_store into sys.modules BEFORE
# dispatch_gate's import graph runs — its load_hooks_lib face can insert
# the deployed skill root into sys.path, and a stale rlvr from that root
# would answer gate_sample with the cold gap (the exact wrong verdict
# this suite exists to catch).


def _load(name: str, base: Path):
    spec = importlib.util.spec_from_file_location(name, base / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def dg():
    return _load("dispatch_gate", HOOKS)


@pytest.fixture
def sinks():
    return _load("worker_budget_sinks", HOOKS)


@pytest.fixture
def ss():
    return _load("strategy_store",
                 SCRIPTS / "rlvr")


def _bare_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: IN_PROGRESS\n",
        encoding="utf-8")
    return ws


# #804 de-compat: the envelope field is the ONE declaration face (the
# v0 prose marker is retired)
DECLARED = ('{"kunglao_dispatch": {"version": 1, "claim": "C-001", '
            '"tier": 1, "tools": ["grep"], '
            '"method_family": "static-decompile"}}\n'
            "facts-snapshot: 1 facts\n")
UNDECLARED = "dispatch C-001 per the ranked plan"


def test_gate_sample_cold_returns_gap(tmp_path, ss):
    ws = _bare_ws(tmp_path)
    gap = ss.gate_sample(ws)
    assert gap == {"family": None, "propensity": None,
                   "prior_source": None}


def test_undeclared_reject_carries_the_sampled_family(
        sinks, tmp_path, capsys, monkeypatch):
    """The wiring pin (#773 W2): an undeclared dispatch's methodfamily
    reject carries the gate's own sampled family in the guidance — the
    retry declares it and the #691 reconciliation view rides the
    dispatch observation row (the #804 usage merge). (The draw's
    warm-fill belongs to the strategy_store suite; here the sampler is
    pinned, the guidance is proven.)"""
    ws = _bare_ws(tmp_path)
    import rlvr.strategy_store
    monkeypatch.setattr(rlvr.strategy_store, "gate_sample",
                        lambda ws: {"family": "static-decompile",
                                    "propensity": 0.62,
                                    "prior_source": "store"})
    paths = {"workspace": str(ws)}
    rc, value, _view = sinks._method_family_gate(
        paths, UNDECLARED, "C-001", "kunglao-worker", 1, [])
    assert rc == 2 and value is None
    out = capsys.readouterr().out
    assert "static-decompile" in out and "propensity" in out
    assert "sampler draw" in out


def test_declared_dispatch_records_the_sample_view(
        sinks, tmp_path, monkeypatch):
    ws = _bare_ws(tmp_path)
    import rlvr.strategy_store
    monkeypatch.setattr(rlvr.strategy_store, "reconcile_declaration",
                        lambda ws, declared: {
                            "sampled_family": "static-decompile",
                            "propensity": 0.62, "prior_source": "store",
                            "deviates": False})
    paths = {"workspace": str(ws)}
    rc, value, view = sinks._method_family_gate(
        paths, DECLARED, "C-001", "kunglao-worker", 1, [])
    assert rc is None and value == "static-decompile"
    # #804 usage merge: the gate RETURNS the reconciliation view; the
    # ALLOW tail's lifecycle record lands it on the dispatch observation
    # row (the side usage ledger is closed — no file is written here)
    assert view["sampled_family"] == "static-decompile"
    assert view["propensity"] == 0.62
    assert not (ws / "runs" / "method-family-log.jsonl").exists()


def test_cold_sampler_rejects_without_a_fabricated_family(
        sinks, tmp_path, capsys):
    ws = _bare_ws(tmp_path)
    paths = {"workspace": str(ws)}
    rc, value, _view = sinks._method_family_gate(
        paths, UNDECLARED, "C-001", "kunglao-worker", 1, [])
    assert rc == 2
    out = capsys.readouterr().out
    assert "sampler draw" not in out, ("a cold sampler must never "
                                       "fabricate a family")


def test_strategy_row_unchanged_without_sampled(dg, tmp_path):
    """The #496 marker row keeps its legacy shape: the DECLARED prompt
    carries no [strategy X] marker, so the row stays the honest
    default/declared:false (the method-family axis lives in the
    usage row, not here)."""
    ws = _bare_ws(tmp_path)
    dg._log_strategy_dispatch(ws, "C-001", "dispatch C-001, no marker")
    rows = [json.loads(l) for l in
            (ws / "runs" / "strategy-log.jsonl")
            .read_text(encoding="utf-8").splitlines() if l.strip()]
    assert rows[-1]["strategy"] == "default" and rows[-1]["declared"] is False


def test_plan_receipt_written_with_admitted_set(dg, tmp_path):
    ws = _bare_ws(tmp_path)
    dg._write_plan_receipt(ws, "C-001")
    rows = [json.loads(l) for l in
            (ws / "runs" / "plan-receipts.jsonl")
            .read_text(encoding="utf-8").splitlines() if l.strip()]
    assert rows and rows[0]["schema"] == "plan-receipt/1"
    assert rows[0]["claim"] == "C-001"
    assert rows[0]["admitted"], ("dispatch is always a candidate — the "
                                 "admitted set is non-empty")
    assert rows[0]["chosen"]


def test_plan_receipt_skips_unclaimable(dg, tmp_path):
    ws = _bare_ws(tmp_path)
    dg._write_plan_receipt(ws, None)
    assert not (ws / "runs" / "plan-receipts.jsonl").exists()



def test_w1_compiler_arms_one_case_per_question(tmp_path):
    from arm_oracle_cases import compile_cases
    (tmp_path / "task_spec.yaml").write_text(
        "primary_questions:\n"
        "  - 'PQ1 what is the entry url?'\n"
        "  - 'PQ2 how is the param signed?'\n"
        "success_criterion: Flag recovered and accepted\n"
        "verification_method: reproduction\n", encoding="utf-8")
    (tmp_path / "goal-operationalization.yaml").write_text(
        "acceptance:\n  - replay matches byte-for-byte\n",
        encoding="utf-8")
    cases = compile_cases(tmp_path)
    assert [c["id"] for c in cases] == ["case-pq-01", "case-pq-02"]
    for c in cases:
        for field in ("channel", "hypothesis_ref", "update_map",
                      "expected", "mutations"):
            assert c.get(field), (c["id"], field)
        assert c["channel"] == "replay"
        assert c["expected"][0]["field"] == "verdict"


def test_w1_compiler_refuses_blank_anchors(tmp_path):
    from arm_oracle_cases import compile_cases
    (tmp_path / "task_spec.yaml").write_text(
        "primary_questions: []\n", encoding="utf-8")
    assert compile_cases(tmp_path) == []


def test_w1_arm_idempotent_and_writes_armed_docs(tmp_path):
    from arm_oracle_cases import arm
    import settle_round_credit as src
    (tmp_path / "task_spec.yaml").write_text(
        "primary_questions:\n  - 'PQ1 x?'\n"
        "success_criterion: ok\nverification_method: static\n",
        encoding="utf-8")
    rc, msg = arm(tmp_path)
    assert rc == 0
    case_file = next((tmp_path / "oracle" / "cases").glob("*.yaml"))
    doc = yaml.safe_load(case_file.read_text(encoding="utf-8"))
    for field in src.CASE_ARMING_FIELDS:
        assert doc.get(field), (case_file.name, field)
    rc2, msg2 = arm(tmp_path)
    assert rc2 == 0 and "0 oracle case(s)" in msg2


def test_w1_init_tail_arms_cases_on_scaffold(tmp_path):
    """The init tail calls the compiler: a scaffolded ws with anchors
    ends up with armed cases (the reward source exists from tick 0)."""
    from arm_oracle_cases import arm
    (tmp_path / "task_spec.yaml").write_text(
        "primary_questions:\n  - 'PQ1 x?'\n"
        "success_criterion: ok\nverification_method: replay\n",
        encoding="utf-8")
    rc, _ = arm(tmp_path)
    assert rc == 0
    assert list((tmp_path / "oracle" / "cases").glob("*.yaml"))

