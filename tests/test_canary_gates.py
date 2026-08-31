# -*- coding: utf-8 -*-
"""A5 canary graduation (#823): shadow -> canary behavior tests.

Shadow = count + emit only. Canary = the signal CONSUMES:
  1. check_zero_output_circuit REJECTS dispatch when a fingerprint is
     tripped (flag ON); flag OFF bypasses (byte-identical).
  2. attach_signals carries infeasible_candidate when the doomed-
     trajectory condition holds (flag ON); flag OFF adds no key.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))

import value_config
import zero_output_fingerprint as zf
import worker_budget_gates as gates


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
    ws = _tripped_ws(tmp_path)
    monkeypatch.setenv(value_config.ENV_NAME, "1")
    ok, reason = gates.check_zero_output_circuit(ws)
    assert ok is False
    assert "zero-output circuit tripped" in reason


def test_canary_gate_bypasses_flag_off(tmp_path, monkeypatch):
    ws = _tripped_ws(tmp_path)
    monkeypatch.delenv(value_config.ENV_NAME, raising=False)
    ok, reason = gates.check_zero_output_circuit(ws)
    assert ok is True
    assert "flag off" in reason


def test_canary_gate_fails_open_on_missing_state(tmp_path, monkeypatch):
    ws = tmp_path / "empty"
    ws.mkdir()
    monkeypatch.setenv(value_config.ENV_NAME, "1")
    ok, reason = gates.check_zero_output_circuit(ws)
    assert ok is True  # fail-open, never deadlock the loop


def test_attach_signals_carries_infeasible(tmp_path, monkeypatch):
    import rho_checkpoint as rc
    import infeasible_signal
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
    monkeypatch.setenv(value_config.ENV_NAME, "1")
    decision = rc.attach_signals(ws, {"decision": "DISPATCH"})
    sig = decision["value_signals"]
    assert sig["infeasible_candidate"] is True
    assert sig["v_flat_rounds"] >= infeasible_signal.K_ROUNDS


def test_flag_off_no_value_signals(tmp_path, monkeypatch):
    import rho_checkpoint as rc
    ws = _mk_ws(tmp_path, "ws3")
    (ws / "runs" / "logs").mkdir(parents=True)
    monkeypatch.delenv(value_config.ENV_NAME, raising=False)
    decision = rc.attach_signals(ws, {"decision": "DISPATCH"})
    assert "value_signals" not in decision