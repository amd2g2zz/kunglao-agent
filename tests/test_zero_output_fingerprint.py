# -*- coding: utf-8 -*-
"""A4 ① (#823): zero-output fingerprint circuit — same-type action thrash.

A "same-type action" = (tool, target_type) hash. N=3 consecutive
checkpoints with ZERO belief change (facts/_INDEX.md + claim-register
content hash) on the same fingerprint → circuit breaks: the caller is
told to interrupt and inject failure_analysis (#634 design). Shadow
posture: this module only counts, persists state, and emits; blocking
wiring graduates at A5 canary.
"""
import json
from pathlib import Path

import zero_output_fingerprint as zf


def _mk_ws(tmp: Path) -> Path:
    ws = tmp / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    (ws / "facts" / "_INDEX.md").write_text("F001 | PROVEN | C-001 | x\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def test_third_same_type_action_breaks_circuit(tmp_path):
    ws = _mk_ws(tmp_path)
    r1 = zf.record_action(ws, "mcp__ghidra__decompile_function", "function")
    r2 = zf.record_action(ws, "mcp__ghidra__decompile_function", "function")
    r3 = zf.record_action(ws, "mcp__ghidra__decompile_function", "function")
    assert (r1["streak"], r2["streak"]) == (1, 2)
    assert r3["circuit_broken"] is True
    assert "failure_analysis" in r3["inject"]


def test_belief_change_resets_streak(tmp_path):
    ws = _mk_ws(tmp_path)
    zf.record_action(ws, "tool_a", "target")
    zf.record_action(ws, "tool_a", "target")
    # belief moves → the ledger hash changes → streaks reset
    with (ws / "facts" / "_INDEX.md").open("a", encoding="utf-8") as f:
        f.write("F002 | OPEN | C-002 | y\n")
    r = zf.record_action(ws, "tool_a", "target")
    assert r["streak"] == 1
    assert r["circuit_broken"] is False


def test_different_fingerprints_independent(tmp_path):
    ws = _mk_ws(tmp_path)
    zf.record_action(ws, "tool_a", "target")
    zf.record_action(ws, "tool_b", "target")
    zf.record_action(ws, "tool_a", "target")
    r = zf.record_action(ws, "tool_a", "target")
    assert r["streak"] == 3 and r["circuit_broken"] is True


def test_state_persists_across_calls(tmp_path):
    ws = _mk_ws(tmp_path)
    zf.record_action(ws, "tool_a", "target")
    state_file = ws / "runs" / "zero-output-fingerprint.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(state["streaks"]) == 1
