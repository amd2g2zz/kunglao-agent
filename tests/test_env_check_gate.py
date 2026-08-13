# -*- coding: utf-8 -*-
"""Tests for hooks/env_check_gate.py — PreToolUse hard-REJECT on AGENT_TEAMS flag (#233).

Acceptance (issue #233):
  - flag set (process scope) + Agent dispatch in a kunglao workspace
    -> exit 2, stderr REJECT, additionalContext guidance non-empty
    (problem / alternative / fix)
  - flag unset -> exit 0, silent (zero IO when clean)
  - non-kunglao workspace -> silent regardless of the flag
  - the hook reads os.environ directly — no state file, no activation check
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from env_check_gate import (  # pytest.ini pythonpath = . hooks scripts tools
    FLAG_NAME,
    evaluate,
)


def _kunglao_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-001\n  status: OPEN\n", encoding="utf-8")
    return ws


def _payload(ws: Path) -> dict:
    return {
        "hookEventName": "PreToolUse",
        "tool_name": "Agent",
        "cwd": str(ws),
        "tool_input": {"prompt": "[T1 tools=grep] claim C-001 strings"},
    }


def test_flag_set_rejects_with_guidance(tmp_path):
    """flag on -> exit 2 + REJECT on stderr + non-empty guidance (3 points)."""
    ws = _kunglao_ws(tmp_path)
    rc, stderr, ctx = evaluate(_payload(ws), environ={FLAG_NAME: "1"})
    assert rc == 2
    assert "REJECT env_check_gate" in stderr
    assert FLAG_NAME in stderr
    assert ctx, "additionalContext must be non-empty on REJECT"
    # guidance carries the three points: problem / alternative / fix
    assert "teammate" in ctx, "problem: teammate-channel routing must be named"
    assert "400" in ctx, "problem: 2026-08-12 400 [1210] evidence must be named"
    assert "通道" in ctx, "alternative: independent-worker path must be named"
    assert "unset" in ctx, "fix: unset + restart must be named"
    assert str(ws) in ctx, "guidance should name the workspace"


def test_flag_unset_silent_ok(tmp_path):
    """flag unset -> exit 0, no output, no guidance."""
    ws = _kunglao_ws(tmp_path)
    rc, stderr, ctx = evaluate(_payload(ws), environ={})
    assert rc == 0
    assert stderr == ""
    assert ctx is None


def test_non_kunglao_workspace_silent_even_with_flag(tmp_path):
    """no claim-register.yaml -> silent (exit 0) even with the flag set —
    the global-wired hook must not police unrelated projects."""
    other = tmp_path / "other"
    other.mkdir()
    rc, stderr, ctx = evaluate(
        {"cwd": str(other), "tool_input": {}}, environ={FLAG_NAME: "1"})
    assert rc == 0 and stderr == "" and ctx is None


def test_workspace_via_malware_analysis_workspace_subdir(tmp_path):
    """_resolve_workspace fallback: dispatch from a dir whose
    malware-analysis-workspace/ child carries claim-register.yaml (#88 shape)."""
    root = tmp_path / "root"
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    rc, stderr, ctx = evaluate(
        {"cwd": str(root), "tool_input": {}}, environ={FLAG_NAME: "1"})
    assert rc == 2 and ctx is not None


def test_main_stdin_reject_end_to_end(tmp_path):
    """The wired shape: JSON payload on stdin, flag set -> exit 2, stderr
    REJECT, stdout carries the hookSpecificOutput JSON."""
    ws = _kunglao_ws(tmp_path)
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "hooks" / "env_check_gate.py")],
        input=json.dumps(_payload(ws)), capture_output=True,
        encoding="utf-8", errors="replace",
        env={"PYTHONIOENCODING": "utf-8", FLAG_NAME: "1", **os.environ},
        cwd=str(ws), timeout=60,
    )
    assert r.returncode == 2
    assert "REJECT env_check_gate" in r.stderr
    out = json.loads(r.stdout)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert ctx and "teammate" in ctx


def test_main_stdin_pass_without_flag(tmp_path):
    """The wired shape, flag absent -> exit 0, no output."""
    ws = _kunglao_ws(tmp_path)
    clean = {k: v for k, v in os.environ.items() if k != FLAG_NAME}
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "hooks" / "env_check_gate.py")],
        input=json.dumps(_payload(ws)), capture_output=True,
        encoding="utf-8", errors="replace",
        env={"PYTHONIOENCODING": "utf-8", **clean},
        cwd=str(ws), timeout=60,
    )
    assert r.returncode == 0
    assert r.stdout == ""
    assert r.stderr == ""


# ---------- #276: default-disabled semantics — only TRUTHY rejects ----------

def test_flag_zero_passes(tmp_path):
    """#276: flag=0 -> exit 0, silent (the default-disabled state is clean)."""
    ws = _kunglao_ws(tmp_path)
    rc, stderr, ctx = evaluate(_payload(ws), environ={FLAG_NAME: "0"})
    assert rc == 0
    assert stderr == ""
    assert ctx is None


def test_flag_false_and_off_pass(tmp_path):
    """#276: 'false'/'off'/'' are clean — no REJECT."""
    ws = _kunglao_ws(tmp_path)
    for value in ("false", "off", ""):
        rc, stderr, ctx = evaluate(_payload(ws), environ={FLAG_NAME: value})
        assert rc == 0, f"{value!r}: rc={rc}"
        assert stderr == ""
        assert ctx is None


def test_flag_true_rejects(tmp_path):
    """#276: 'true' is truthy -> hard REJECT (exit 2) with guidance."""
    ws = _kunglao_ws(tmp_path)
    rc, stderr, ctx = evaluate(_payload(ws), environ={FLAG_NAME: "true"})
    assert rc == 2
    assert "REJECT env_check_gate" in stderr
    assert ctx is not None


def test_flag_yes_on_case_insensitive_reject(tmp_path):
    """#276: 'YES'/'on' (case-insensitive truthy) -> hard REJECT."""
    ws = _kunglao_ws(tmp_path)
    for value in ("YES", "on", "On", "TRUE"):
        rc, stderr, ctx = evaluate(_payload(ws), environ={FLAG_NAME: value})
        assert rc == 2, f"{value!r}: rc={rc}"
        assert ctx is not None


def test_main_stdin_zero_passes_end_to_end(tmp_path):
    """The wired shape, flag=0 -> exit 0, no output."""
    ws = _kunglao_ws(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != FLAG_NAME}
    env[FLAG_NAME] = "0"
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "hooks" / "env_check_gate.py")],
        input=json.dumps(_payload(ws)), capture_output=True,
        encoding="utf-8", errors="replace",
        env={"PYTHONIOENCODING": "utf-8", **env},
        cwd=str(ws), timeout=60,
    )
    assert r.returncode == 0
    assert r.stdout == ""
    assert r.stderr == ""
