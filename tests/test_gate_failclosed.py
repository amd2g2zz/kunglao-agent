#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_gate_failclosed.py — owner ruling 2026-09-28: a gate that
ERRORS must NOT pass the action.

For every converted gate site, a fixture forces the gate to throw and
asserts (a) the action is REJECTED, (b) the reason carries the gate
error, (c) there is no silent pass. Companions to the #417 record-only
batch: the warn stays, the verdict flips.

Converted sites covered here:
  worker_budget_gates.check_workers_lt_3          (audited #417 site)
  worker_budget_gates.check_rotation_experiment   (audited #417 site)
  worker_budget_gates.check_tool_search_citation
  worker_budget_gates.check_zero_output_circuit
  worker_budget_sinks.check_env_premise (vocab + reconcile, audited site)
  dispatch_gate._top1_enforcement (scorer + audit)
  dispatch_gate._mcp_prefix_gate (helper + unparseable payload)
  dispatch_gate._capability_guard (scorer + payload + evidence)
  completion_gate.process_event (judge crash -> block, #717 shape)
  write_guard._ws_has_live_workers (scan error -> ARMED, fail-closed)
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import worker_budget_gates as gates
import worker_budget_sinks as sinks


def _stderr(capsys) -> str:
    return capsys.readouterr().err


# ---------------------------------------------------------------------------
# worker_budget_gates
# ---------------------------------------------------------------------------

def test_workers_lt_3_scan_error_rejects(monkeypatch, capsys):
    class _BoomLib:
        @staticmethod
        def scan_active_workers(_ws):
            raise RuntimeError("scan exploded")

    monkeypatch.setattr(gates, "load_hooks_lib", lambda: _BoomLib)
    gates._WARN_LAST.clear()
    ok, msg = gates.check_workers_lt_3({"workspace": "/tmp/ws"})
    assert ok is False  # (a) rejected
    assert "RuntimeError" in msg and "scan exploded" in msg  # (b) cause
    assert "ACTIVE-WORKERS GATE" in msg
    assert "gate_error:active_workers_scan" in _stderr(capsys)


def test_rotation_experiment_error_rejects(monkeypatch, capsys):
    def _boom(_ws):
        raise KeyError("flag store corrupted")

    monkeypatch.setattr(gates, "load_rotation_flags", _boom)
    gates._WARN_LAST.clear()
    ok, msg = gates.check_rotation_experiment(
        {"workspace": "/tmp/ws"}, "C-7", "no marker prompt")
    assert ok is False
    assert "reject:" in msg
    assert "KeyError" in msg and "flag store corrupted" in msg
    assert "gate_error:rotation_check" in _stderr(capsys)


def test_rotation_experiment_corrupt_store_rejects_for_real(tmp_path,
                                                             capsys):
    """End-to-end through the real loader: a corrupt flag store reaches
    the gate as an error (load_rotation_flags no longer swallows), so a
    flagged dispatch cannot slip past a broken store."""
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / ".rotation-induction.json").write_text(
        "{corrupt json", encoding="utf-8")
    gates._WARN_LAST.clear()
    ok, msg = gates.check_rotation_experiment(
        {"workspace": str(tmp_path)}, "C-9", "no marker prompt")
    assert ok is False
    assert "reject: rotation gate error" in msg
    assert "gate_error:rotation_check" in _stderr(capsys)


def test_load_rotation_flags_missing_store_is_empty(tmp_path):
    """An ABSENT store is a designed no-op (not an error): no flags."""
    assert gates.load_rotation_flags(tmp_path) == {}


def test_tool_search_citation_import_error_rejects(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "instrument_menu", None)
    gates._WARN_LAST.clear()
    ok, msg = gates.check_tool_search_citation({"workspace": "/tmp/ws"},
                                               "C-1", "prompt")
    assert ok is False
    assert "TOOL-SEARCH GATE" in msg
    assert "ModuleNotFoundError" in msg
    assert "check_tool_search_citation" in _stderr(capsys)


def test_zero_output_circuit_belief_hash_error_rejects(tmp_path, monkeypatch,
                                                       capsys):
    fake = types.ModuleType("zero_output_fingerprint")
    fake.STATE_FILE = "runs/zero-output-fingerprint.json"

    def _boom(_ws):
        raise ValueError("belief hash collapsed")

    fake.belief_hash = _boom
    monkeypatch.setitem(sys.modules, "zero_output_fingerprint", fake)
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "zero-output-fingerprint.json").write_text(
        json.dumps({"belief_hash": "x"}), encoding="utf-8")
    gates._WARN_LAST.clear()
    ok, msg = gates.check_zero_output_circuit(tmp_path, "C-1", [])
    assert ok is False
    assert "ZERO-OUTPUT CIRCUIT" in msg
    assert "ValueError" in msg and "belief hash collapsed" in msg
    assert "gate_error:zero_output_circuit" in _stderr(capsys)


# ---------------------------------------------------------------------------
# worker_budget_sinks
# ---------------------------------------------------------------------------

def test_env_premise_vocab_error_rejects(monkeypatch, capsys):
    def _boom(_tier, _tools):
        raise TypeError("vocab broken")

    monkeypatch.setattr(sinks, "_env_caps_needed", _boom)
    sinks._B3_WARN_LAST.clear()
    ok, msg = sinks.check_env_premise({"workspace": "/tmp/ws"}, 0,
                                      tools=["adb"])
    assert ok is False  # no silent pass
    assert "ENV-PREMISE GATE" in msg
    assert "TypeError" in msg and "vocab broken" in msg
    assert "gate_error:env_caps_vocab" in _stderr(capsys)


def test_env_premise_reconcile_crash_rejects(tmp_path, monkeypatch, capsys):
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "env-state.json").write_text(
        json.dumps({"per_capability": {"vmr-shell": {"status": "PASS"}}}),
        encoding="utf-8")
    monkeypatch.setitem(sys.modules, "premise_gate", None)
    sinks._B3_WARN_LAST.clear()
    # tier=2 + vmr-shell: the same needed-cap shape the #340 tests use
    ok, msg = sinks.check_env_premise({"workspace": str(tmp_path)}, 2,
                                      tools=["vmr-shell"])
    assert ok is False
    assert "reconciliation crashed" in msg
    assert "ModuleNotFoundError" in msg
    assert "gate_error:env_premise_reconcile" in _stderr(capsys)


def test_env_premise_missing_env_state_still_passes(tmp_path):
    """Designed no-op paths are NOT errors: a missing env-state.json keeps
    the documented fail-open pass (the ruling flips error verdicts only)."""
    (tmp_path / "runs").mkdir()
    ok, msg = sinks.check_env_premise({"workspace": str(tmp_path)}, 0,
                                      tools=["adb"])
    assert ok is True


# ---------------------------------------------------------------------------
# dispatch_gate — top1 / mcp_prefix / capability, via _gate_error_reject
# ---------------------------------------------------------------------------

def _ws_with_runs(tmp_path: Path) -> Path:
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_top1_scorer_unavailable_rejects(tmp_path, monkeypatch, capsys):
    import dispatch_gate as dg
    ws = _ws_with_runs(tmp_path)
    monkeypatch.setitem(sys.modules, "worker_budget", None)
    rc = dg._top1_enforcement(ws, "C-1", "prompt text")
    err = _stderr(capsys)  # single read: capsys consumes on readouterr
    assert rc == 2  # (a) rejected
    assert "REJECT top1" in err
    assert "ModuleNotFoundError" in err  # (b) cause surfaced
    ledger = ws / "runs" / "gate-rejections.jsonl"
    rows = [json.loads(line) for line in
            ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows and rows[-1]["gate"] == "top1"  # (c) durable, not silent
    assert "ModuleNotFoundError" in rows[-1]["msg"]


def test_top1_audit_crash_rejects(tmp_path, monkeypatch, capsys):
    import dispatch_gate as dg

    fake = types.ModuleType("worker_budget")

    def _boom(*a, **k):
        raise RuntimeError("audit exploded")

    fake.check_priority = _boom
    monkeypatch.setitem(sys.modules, "worker_budget", fake)
    ws = _ws_with_runs(tmp_path)
    rc = dg._top1_enforcement(ws, "C-1", "prompt text")
    assert rc == 2
    err = _stderr(capsys)
    assert "REJECT top1" in err
    assert "audit exploded" in err
    ledger = ws / "runs" / "gate-rejections.jsonl"
    rows = [json.loads(line) for line in
            ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows and "RuntimeError" in rows[-1]["msg"]


def test_mcp_prefix_helper_unavailable_rejects(monkeypatch, capsys):
    import dispatch_gate as dg

    def _boom():
        raise OSError("lib gone")

    monkeypatch.setattr(dg, "load_hooks_lib", _boom)
    rc = dg._mcp_prefix_gate("prompt with tools")
    assert rc == 2
    err = _stderr(capsys)
    assert "REJECT mcp_prefix" in err
    assert "OSError" in err


def test_mcp_prefix_unparseable_payload_rejects(monkeypatch, capsys):
    import dispatch_gate as dg

    class _Lib:
        @staticmethod
        def parse_dispatch(_text):
            raise ValueError("payload garbage")

        @staticmethod
        def check_mcp_prefix(_tool):
            return True, ""

    monkeypatch.setattr(dg, "load_hooks_lib", lambda: _Lib)
    rc = dg._mcp_prefix_gate("prompt with tools")
    assert rc == 2
    err = _stderr(capsys)
    assert "REJECT mcp_prefix" in err
    assert "payload garbage" in err


def test_capability_scorer_unavailable_rejects(tmp_path, monkeypatch, capsys):
    import dispatch_gate as dg
    ws = _ws_with_runs(tmp_path)
    monkeypatch.setitem(sys.modules, "priority_ratio", None)
    rc = dg._capability_guard(ws, "C-1", "prompt text")
    err = _stderr(capsys)  # single read: capsys consumes on readouterr
    assert rc == 2
    assert "REJECT capability" in err
    assert "ModuleNotFoundError" in err
    ledger = ws / "runs" / "gate-rejections.jsonl"
    rows = [json.loads(line) for line in
            ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows and rows[-1]["gate"] == "capability"


def test_capability_unparseable_payload_rejects(tmp_path, monkeypatch, capsys):
    import dispatch_gate as dg

    class _Lib:
        @staticmethod
        def parse_dispatch(_text):
            raise ValueError("no tools readable")

    monkeypatch.setattr(dg, "load_hooks_lib", lambda: _Lib)
    ws = _ws_with_runs(tmp_path)
    rc = dg._capability_guard(ws, "C-1", "prompt text")
    assert rc == 2
    assert "no tools readable" in _stderr(capsys)


def test_capability_evidence_scan_error_rejects(tmp_path, monkeypatch, capsys):
    import dispatch_gate as dg

    fake = types.ModuleType("priority_ratio")

    class _EvidenceView:
        @staticmethod
        def from_workspace(_ws):
            raise OSError("artifact scan detonated")

    fake.EvidenceView = _EvidenceView
    monkeypatch.setitem(sys.modules, "priority_ratio", fake)

    class _Lib:
        @staticmethod
        def parse_dispatch(_text):
            return (0, [], None, {})

    monkeypatch.setattr(dg, "load_hooks_lib", lambda: _Lib)
    ws = _ws_with_runs(tmp_path)
    rc = dg._capability_guard(ws, "C-1", "prompt text")
    assert rc == 2
    err = _stderr(capsys)
    assert "REJECT capability" in err
    assert "artifact scan detonated" in err


def test_tools_rack_unparseable_payload_rejects(monkeypatch, capsys):
    """Reviewer-found sibling: same parse-error class as _mcp_prefix_gate —
    the rack gate cannot see the declared tools, so it rejects."""
    import dispatch_gate as dg

    class _Lib:
        @staticmethod
        def parse_dispatch(_text):
            raise ValueError("rack garbage")

    monkeypatch.setattr(dg, "load_hooks_lib", lambda: _Lib)
    rc = dg._tools_rack_gate({"agent_name": "kunglao-worker"}, "prompt")
    assert rc == 2
    err = _stderr(capsys)
    assert "REJECT tools_rack" in err
    assert "rack garbage" in err


def test_plan_contingency_infra_error_rejects(tmp_path, monkeypatch, capsys):
    """Reviewer-found sibling: a plan_epistemics infra error used to read
    as 'no violations' — the plan gate now fail-closes with the cause.
    Fixture mirrors tests/test_plan_gate_branching_250.py (prior dispatch
    anchor + on-disk plan so the flow reaches the contingency leg)."""
    monkeypatch.setitem(sys.modules, "plan_epistemics", None)
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / ".dispatch-anchor-C001.jsonl").write_text(
        json.dumps({"ts": "2026-09-10T01:00:00Z", "claim": "C-001",
                    "agent": "w-test"}) + "\n", encoding="utf-8")
    (runs / "plan-C001.md").write_text(
        "dispatch-anchor: t\ngoal: g\npreflight: p\nsteps:\n"
        "  1. do the thing -> expect evidence\nfallback: report blocker\n",
        encoding="utf-8")
    gates._WARN_LAST.clear()
    ok, msg = gates.check_worker_plan(
        {"workspace": str(tmp_path), "state": tmp_path / "analysis_state.txt",
         "register": tmp_path / "claim-register.yaml",
         "deps": tmp_path / "claim_deps.yaml",
         "task_spec": tmp_path / "task_spec.yaml"}, "C-001")
    assert ok is False
    assert "PLAN GATE" in msg
    assert "ModuleNotFoundError" in msg
    assert "gate_error:plan_contingency" in _stderr(capsys)


# ---------------------------------------------------------------------------
# completion_gate — judge crash blocks (the #717 shape)
# ---------------------------------------------------------------------------

def test_completion_judge_crash_blocks(tmp_path, monkeypatch, capsys):
    """The hooks/ shim (NOT the scripts/ judge of the same basename) must
    turn a judge crash into a fail-closed BLOCK carrying the cause."""
    import importlib.util
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "completion_gate_hook_failclosed",
        repo / "hooks" / "completion_gate.py")
    cg = importlib.util.module_from_spec(spec)
    sys.modules["completion_gate_hook_failclosed"] = cg
    spec.loader.exec_module(cg)

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "task-oracle.yaml").write_text("adjudication: {}\n",
                                         encoding="utf-8")

    class _Loaded:
        @staticmethod
        def judge(_oracle):
            raise RuntimeError("judge detonated")

    monkeypatch.setattr(cg, "_resolve_workspace", lambda _payload: ws)
    monkeypatch.setattr(cg, "_kunglao_active", lambda _ws: True)
    monkeypatch.setattr(cg, "_load_judge", lambda: _Loaded)
    rc = cg.process_event({})
    assert rc == 3  # blocked, the #717 fail-closed shape
    out = capsys.readouterr().out
    assert '"decision": "block"' in out
    assert "judge detonated" in out  # (b) cause in the block reason


# ---------------------------------------------------------------------------
# write_guard — liveness scan error arms the guard (fail-closed)
# ---------------------------------------------------------------------------

def test_write_guard_liveness_scan_error_arms(tmp_path, monkeypatch, capsys):
    import write_guard as wg

    def _boom():
        raise OSError("scan unreachable")

    monkeypatch.setattr(wg, "load_hooks_lib", _boom)
    assert wg._ws_has_live_workers(tmp_path) is True  # armed, not waved through
    err = _stderr(capsys)
    assert "gate_error:worker_liveness_scan" in err
    assert "OSError" in err


# ---------------------------------------------------------------------------
# warn-patch-out freeze: the verdict comes from the reject path, and the
# warn is pure telemetry (patching it out changes nothing)
# ---------------------------------------------------------------------------

def test_failclosed_verdicts_survive_warn_patchout(monkeypatch):
    class _BoomLib:
        @staticmethod
        def scan_active_workers(_ws):
            raise RuntimeError("x")

    def _boom(_tier, _tools):
        raise ValueError("y")

    monkeypatch.setattr(gates, "load_hooks_lib", lambda: _BoomLib)
    monkeypatch.setattr(sinks, "_env_caps_needed", _boom)

    with monkeypatch.context() as m:
        m.setattr(gates, "warn", lambda op, reason: None)
        m.setattr(sinks, "warn", lambda op, reason: None)
        v1 = gates.check_workers_lt_3({"workspace": "/tmp/ws"})
        v2 = sinks.check_env_premise({"workspace": "/tmp/ws"}, 0, tools=[])
    assert v1[0] is False and "RuntimeError" in v1[1]
    assert v2[0] is False and "ValueError" in v2[1]
