# -*- coding: utf-8 -*-
"""tests/test_reject_emit_624.py — #624: REJECTs get a persistent trail.

RED (adjudicated): env_check_gate's REJECT paths returned one stderr line with
ZERO kunglao_log calls — an operator hit "workspace not fully initialized"
with nothing durable to diagnose. (dispatch_gate/write_guard already emit;
worker_budget is follow-up.) Adjudicated fix (方案 B scoped to the named
culprit): every REJECT return in env_check_gate also emits action=reject into
the existing kunglao_log stream (gate name + reason + exit=2). No third log
format, no new files.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "env_check_gate_uut", ROOT / "hooks" / "env_check_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _events(ws: Path) -> list[dict]:
    rows = []
    log = ws / "runs" / "logs"
    if log.exists():
        for f in sorted(log.glob("kunglao-*.jsonl")):
            rows += [json.loads(ln) for ln in
                     f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return rows


def test_init_incomplete_reject_emits_event(tmp_path):
    mod = _load_gate()
    ws = tmp_path / "ws"; ws.mkdir()
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    # no init marker → REJECT path
    rc, stderr, ctx = mod.evaluate({"cwd": str(ws), "tool_name": "Bash"})
    assert rc == 2
    ev = [e for e in _events(ws) if e["action"] == "reject"]
    assert ev, "REJECT must leave a persistent event"
    assert "env_check_gate" in ev[-1]["detail"] and "initialized" in ev[-1]["detail"]
    assert ev[-1].get("exit") == 2


def test_flag_reject_emits_event(tmp_path):
    mod = _load_gate()
    ws = tmp_path / "ws"; ws.mkdir()
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    env = {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
           "PATH": "/usr/bin:/bin"}
    rc, stderr, ctx = mod.evaluate({"cwd": str(ws), "tool_name": "Bash"}, env)
    assert rc == 2
    ev = [e for e in _events(ws) if e["action"] == "reject"]
    assert ev, "flag REJECT must also leave an event"


def test_pass_emits_nothing(tmp_path):
    mod = _load_gate()
    ws = tmp_path / "ws"; ws.mkdir()
    import init_state
    init_state.write_init_marker(ws, state_hash="h", project_type="android", seed_count=3)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "analysis_state.txt").write_text("project_type=android\n", encoding="utf-8")
    rc, _, _ = mod.evaluate({"cwd": str(ws), "tool_name": "Bash"})
    assert rc == 0
    assert [e for e in _events(ws) if e["action"] == "reject"] == []
