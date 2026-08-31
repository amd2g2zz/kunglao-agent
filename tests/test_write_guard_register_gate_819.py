# -*- coding: utf-8 -*-
"""Issue #819 — write_guard register leg: evidence-gated ->PROVEN (integration).

Subprocess-driven (mirrors test_write_guard_532.py): a register post-image
that adds a ->PROVEN transition with no evidence -> BLOCK rc=2, the on-disk
register is unchanged, reason on stderr + ledger write_blocked.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITE_GUARD = ROOT / "hooks" / "write_guard.py"

RC_ALLOW = 0
RC_BLOCK = 2

REG = (
    "claims:\n"
    "  - id: C-001\n"
    "    status: OPEN\n"
    "    statement: synthetic claim for gate tests\n"
    "  - id: C-002\n"
    "    status: OPEN\n"
    "    statement: second synthetic claim\n"
)

EDIT_PROVEN = {
    "old_string": "    status: OPEN\n    statement: synthetic claim for gate tests",
    "new_string": "    status: PROVEN\n    statement: synthetic claim for gate tests",
}


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "notes").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(REG, encoding="utf-8")
    (ws / "analysis_state.txt").write_text("kunglao workspace\n", encoding="utf-8")
    return ws


def _payload(ws, file_path, **tool_input):
    return json.dumps({
        "tool_name": "Edit",
        "cwd": str(ws),
        "tool_input": {"file_path": str(file_path), **tool_input},
    }, ensure_ascii=False)


def _run_guard(ws, payload):
    env = {k: v for k, v in os.environ.items()}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(ROOT / "hooks"), str(ROOT / "scripts")])
    return subprocess.run(
        [sys.executable, str(WRITE_GUARD)],
        input=payload, capture_output=True, text=True, timeout=60,
        env=env, errors="replace")


def _verify(ws, claim, verdict):
    d = ws / "runs"
    (d / f"2026-08-31-verify-{claim}.md").write_text(
        f"---\nclaim_id: {claim}\n---\n\n## Overall verdict\n{verdict}\n",
        encoding="utf-8")


def _redteam(ws, claim, verdict):
    d = ws / "runs"
    (d / f"verify-redteam-{claim}.md").write_text(
        f"---\ntarget: {claim}\n---\n\nRED-TEAM VERDICT: {verdict}\nclaim: {claim}\n",
        encoding="utf-8")


def _waiver(ws, claim, justify):
    d = ws / "runs"
    (d / f"proven-waiver-{claim}.md").write_text(
        f"---\nclaim_id: {claim}\n---\n\njustify: {justify}\n", encoding="utf-8")


def _reg_path(ws):
    return ws / "claim-register.yaml"


def test_blocked_no_evidence(tmp_path):
    ws = _mk_ws(tmp_path)
    fp = _reg_path(ws)
    r = _run_guard(ws, _payload(ws, fp, **EDIT_PROVEN))
    assert r.returncode == RC_BLOCK, r.stderr
    assert "proven-gate" in r.stderr
    assert "PROVEN" not in _reg_path(ws).read_text(encoding="utf-8")


def test_allowed_with_evidence(tmp_path):
    ws = _mk_ws(tmp_path)
    _verify(ws, "C-001", "passes")
    _redteam(ws, "C-001", "CONFIRMED")
    fp = _reg_path(ws)
    r = _run_guard(ws, _payload(ws, fp, **EDIT_PROVEN))
    assert r.returncode == RC_ALLOW, r.stderr


def test_refuted_blocks(tmp_path):
    ws = _mk_ws(tmp_path)
    _verify(ws, "C-001", "passes")
    _redteam(ws, "C-001", "REFUTED")
    fp = _reg_path(ws)
    r = _run_guard(ws, _payload(ws, fp, **EDIT_PROVEN))
    assert r.returncode == RC_BLOCK
    assert "REFUTED" in r.stderr


def test_waiver_allows_and_is_logged(tmp_path):
    ws = _mk_ws(tmp_path)
    _waiver(ws, "C-001", "operator override: family X already public")
    fp = _reg_path(ws)
    r = _run_guard(ws, _payload(ws, fp, **EDIT_PROVEN))
    assert r.returncode == RC_ALLOW, r.stderr
    logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")) \
        if (ws / "runs" / "logs").exists() else []
    rows = [json.loads(x) for p in logs for x in
            p.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert any(r.get("action") == "proven_waiver_used" for r in rows), rows


def test_unrelated_edit_allowed(tmp_path):
    ws = _mk_ws(tmp_path)
    fp = _reg_path(ws)
    r = _run_guard(ws, _payload(ws, fp,
                                old_string="    statement: second synthetic claim",
                                new_string="    statement: second claim amended"))
    assert r.returncode == RC_ALLOW, r.stderr
