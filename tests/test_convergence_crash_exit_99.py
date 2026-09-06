# -*- coding: utf-8 -*-
"""Issue #99: a decide() crash exited rc=1 — byte-identical to EXIT_DISPATCH.

main() called decide() unguarded: a malformed claim-register.yaml raised
inside yaml.safe_load and Python exited 1 — the SAME byte as EXIT_DISPATCH.
Any rc-based consumer (hooks that branch on 0-4) read the crash as
"dispatch now". convergence_health got EXIT_CRASHED for its own face in #3;
the decide face never did.

Fix: EXIT_CRASHED = 65 (64 is taken by MISSING_WORKSPACE), a catch-all in
main() around decide(): machine-readable {"decision": "CRASHED"} on stdout,
traceback preserved on stderr. The exit-code registry is a consumer
contract — every value must stay distinct.

Covers:
  RED1: the issue probe (register with ``title: [unclosed``) -> rc=65, not
        1; stdout parses as JSON with decision CRASHED; stderr keeps the
        YAML error class
  RED2: synthetic decide() crash -> main() returns 65, stdout contract
        holds, stderr carries the exception
  PINS: registry distinctness (0-5 + 64 + 65); a healthy workspace keeps
        its DISPATCH rc=1; MISSING_WORKSPACE keeps 64
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import convergence_check as cc  # noqa: E402

SCRIPT = ROOT / "scripts" / "convergence_check.py"


def _mk_ws(tmp_path: Path, name: str, register_text: str) -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(register_text, encoding="utf-8")
    (ws / "task_spec.yaml").write_text("primary_questions: []\n", encoding="utf-8")
    return ws


def _run(ws: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(ws), "--json"],
        capture_output=True, text=True, timeout=60,
        env={k: v for k, v in __import__("os").environ.items()
             if k != "KUNGLAO_VALUE_ALGO"})


# =====================================================================
# RED1: the issue probe — malformed register -> 65, not 1
# =====================================================================

def test_malformed_register_exits_65_not_1(tmp_path):
    """The probe from the issue: ``title: [unclosed`` crashes yaml parsing.
    Pre-fix: rc=1 (== EXIT_DISPATCH byte), 0-byte stdout, traceback only on
    stderr — a crash masquerading as "dispatch now"."""
    ws = _mk_ws(tmp_path, "bad_yaml", "title: [unclosed\nclaims: []\n")
    r = _run(ws)
    assert r.returncode == cc.EXIT_CRASHED, (
        f"#99: crashed decide must exit {cc.EXIT_CRASHED} (CRASHED), "
        f"not {r.returncode} (byte-identical to EXIT_DISPATCH); "
        f"stderr: {r.stderr[:300]}")
    assert r.returncode != cc.EXIT_DISPATCH, \
        "#99: crash rc must never collide with EXIT_DISPATCH"
    # machine-readable face: stdout parses and names the crash
    out = json.loads(r.stdout)
    assert out["decision"] == "CRASHED", \
        f"#99: stdout must carry decision=CRASHED, got: {r.stdout[:200]}"
    # traceback preserved on stderr, naming the YAML error class
    assert "Traceback" in r.stderr, "#99: traceback must stay on stderr"
    assert "yaml" in r.stderr.lower(), \
        f"#99: stderr must name the yaml error layer, got: {r.stderr[-300:]}"


# =====================================================================
# RED2: synthetic decide() crash -> main() returns EXIT_CRASHED
# =====================================================================

def test_decide_crash_returns_exit_crashed(tmp_path, monkeypatch, capsys):
    ws = _mk_ws(tmp_path, "synthetic", yaml.safe_dump({"claims": []}))

    def boom(_ws, **_kw):
        raise RuntimeError("synthetic decide failure (#99)")

    monkeypatch.setattr(cc, "decide", boom)
    rc = cc.main([str(ws), "--json"])
    assert rc == cc.EXIT_CRASHED, f"#99: main() must return 65, got {rc}"
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "CRASHED", \
        f"#99: stdout contract violated: {out}"


def test_decide_crash_stderr_keeps_exception(tmp_path, monkeypatch, capsys):
    """stderr keeps the traceback (operators debug from it); stdout stays
    clean JSON (machines parse it). The two channels must not merge."""
    ws = _mk_ws(tmp_path, "stderr", yaml.safe_dump({"claims": []}))

    def boom(_ws, **_kw):
        raise ValueError("the specific failure (#99)")

    monkeypatch.setattr(cc, "decide", boom)
    cc.main([str(ws)])
    captured = capsys.readouterr()
    assert "ValueError" in captured.err, \
        f"#99: exception class must reach stderr, got: {captured.err[-300:]}"
    assert "the specific failure (#99)" in captured.err
    assert json.loads(captured.out)["decision"] == "CRASHED"


# =====================================================================
# protocol pins: registry distinctness + healthy paths unchanged
# =====================================================================

def test_exit_code_registry_distinct():
    """#99: the registry is a consumer contract — every face own byte."""
    registry = {
        "CONVERGED": cc.EXIT_CONVERGED,
        "DISPATCH": cc.EXIT_DISPATCH,
        "DISPATCH_VERIFIER": cc.EXIT_VERIFY,
        "SATURATED": cc.EXIT_SATURATED,
        "BLOCKED": cc.EXIT_BLOCKED,
        "PARK": cc.EXIT_PARK,
        "MISSING_WORKSPACE": 64,
        "CRASHED": cc.EXIT_CRASHED,
    }
    assert len(set(registry.values())) == len(registry), \
        f"#99: exit-code collision in the consumer contract: {registry}"
    assert cc.EXIT_CRASHED == 65
    assert cc.EXIT_CRASHED not in (0, 1, 2, 3, 4, 5, 64)


def test_missing_workspace_still_64(tmp_path):
    """Pre-existing face unchanged: no claim-register.yaml -> 64."""
    r = _run(tmp_path / "absent")
    assert r.returncode == 64, f"MISSING_WORKSPACE moved: rc={r.returncode}"


def test_healthy_dispatch_still_1(tmp_path):
    """The contract this fix protects: rc=1 means DISPATCH, never a crash."""
    ws = _mk_ws(tmp_path, "healthy", yaml.safe_dump(
        {"claims": [{"id": "C-1", "status": "OPEN"}]}))
    r = _run(ws)
    assert r.returncode == cc.EXIT_DISPATCH
    assert json.loads(r.stdout)["decision"] == "DISPATCH"
