# -*- coding: utf-8 -*-
"""A5 canary graduation (#823): shadow -> canary behavior tests.

Shadow = count + emit only. Canary = the signal CONSUMES (always-on
since #51 — the experiment flag is gone):
  1. check_zero_output_circuit REJECTS dispatch when a fingerprint is
     tripped.
  2. attach_signals carries infeasible_candidate when the doomed-
     trajectory condition holds.
"""
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import zero_output_fingerprint as zf

# #762 convention: load hook modules by path under an isolated name —
# a top-level hooks/ sys.path.insert reorders shared-name module
# resolution for later-collected suites (#770 hygiene gate).
import importlib.util as _ilu
_gates_path = Path(__file__).resolve().parents[1] / "hooks" / "worker_budget_gates.py"
_spec = _ilu.spec_from_file_location("canary_worker_budget_gates", _gates_path)
gates = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(gates)


def _mk_ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "facts" / "_INDEX.md").write_text("F001 | OPEN | C-001 | x\n", encoding="utf-8")
    return ws


def _tripped_ws(tmp_path: Path) -> Path:
    ws = _mk_ws(tmp_path)
    for _ in range(zf.ZERO_OUTPUT_N):
        zf.record_action(ws, "mcp__ghidra__decompile_function", "function")
    return ws


def test_canary_gate_rejects_when_tripped(tmp_path, monkeypatch):
    """The would-repeat dispatch (same claim context the state was
    recorded under) is REJECTed; the reason names the state file."""
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    ws = _tripped_ws(tmp_path)
    ok, reason = gates.check_zero_output_circuit(
        ws, "function", ["mcp__ghidra__decompile_function"])
    assert ok is False
    assert "zero-output circuit tripped" in reason
    assert "zero-output-fingerprint.json" in reason


def test_canary_gate_scopes_to_dispatched_claim(tmp_path, monkeypatch):
    """One thrashing claim must not lock the workspace: a dispatch of a
    DIFFERENT claim (or a different tool family) passes even while the
    C-fingerprint is tripped."""
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    ws = _tripped_ws(tmp_path)
    ok, reason = gates.check_zero_output_circuit(
        ws, "C-999", ["mcp__ghidra__decompile_function"])
    assert ok is True, reason
    ok, reason = gates.check_zero_output_circuit(
        ws, "function", ["grep"])
    assert ok is True, reason


def test_canary_gate_passes_stale_state_after_belief_move(tmp_path,
                                                          monkeypatch):
    """The gate derives belief freshness itself: after the belief moves,
    the stored ledger is stale (= reset) and the would-repeat dispatch
    PASSES — clearing the block never requires a successful dispatch
    (which the block itself would prevent) nor manual state deletion."""
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    ws = _tripped_ws(tmp_path)
    with (ws / "facts" / "_INDEX.md").open("a", encoding="utf-8") as f:
        f.write("F002 | OPEN | C-002 | belief moved\n")
    ok, reason = gates.check_zero_output_circuit(
        ws, "function", ["mcp__ghidra__decompile_function"])
    assert ok is True, reason
    assert "stale" in reason


def test_canary_gate_fails_open_on_missing_state(tmp_path, monkeypatch):
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    ws = tmp_path / "empty"
    ws.mkdir()
    ok, reason = gates.check_zero_output_circuit(ws)
    assert ok is True  # fail-open, never deadlock the loop


def test_attach_signals_carries_infeasible(tmp_path, monkeypatch):
    import rho_checkpoint as rc
    import infeasible_signal
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    ws = _mk_ws(tmp_path, "ws2")
    (ws / "runs" / "logs").mkdir(parents=True)
    with (ws / "runs" / "logs" / "kunglao-2026-08-31.jsonl").open("w", encoding="utf-8") as f:
        for _ in range(infeasible_signal.K_ROUNDS):
            f.write(json.dumps({
                "actor": "rho_checkpoint", "action": "rho_checkpoint",
                "claim": None, "tool": None, "artifact": None,
                "duration_ms": None, "exit": None,
                "detail": json.dumps({"v": 0.05}),
            }) + "\n")
    decision = rc.attach_signals(ws, {"decision": "DISPATCH"})
    sig = decision["value_signals"]
    assert sig["infeasible_candidate"] is True
    assert sig["v_flat_rounds"] >= infeasible_signal.K_ROUNDS