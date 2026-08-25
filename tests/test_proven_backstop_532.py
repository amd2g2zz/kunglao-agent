# -*- coding: utf-8 -*-
"""Issue #532 item 4 (F-B3) — the PROVEN backstop stops being dead code.

RED contract (dev baseline, 2026-08-20): worker_budget's
compare_register_change_proven_gate carried the comment "catches orchestrator
bypasses" and had ZERO production callers (tests only); post_check called
only the log-only check_claim_status_change. An agent editing
claim-register.yaml OPEN -> PROVEN by hand hit nothing.

Adaptation note (2026-08-21): the plan's `snapshot_register_statuses` helper
name does not exist at HEAD — the real snapshot helper is
`_claim_statuses(reg_path)`. Tests use the real API.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks"))
sys.path.insert(0, str(ROOT / "scripts"))

import worker_budget  # noqa: E402

RC_BLOCK = 2


def _ws(tmp_path: Path, status: str) -> Path:
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    (ws / "analysis_state.txt").write_text("[current_task]\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-001\n"
        f"    status: {status}\n"
        "    statement: imports resolved at runtime\n",
        encoding="utf-8")
    (ws / "facts" / "F001-x.md").write_text(
        "---\nid: F001-x\ntype: fact\ntitle: t\nstatus: INFERRED\n"
        "created: 2026-08-20\nlast_reviewed: 2026-08-20\nclaim_id: C-001\n"
        "claim: imports resolved at runtime\nboundary_type: observation\n"
        "promotion_gate: gate\nsource: static-decompile\nconfidence: medium\n"
        "verify_status: partial\nreproduce: python runs/verify.py\n"
        "expected: pending\nverified: pending\nprovenance:\n"
        "  - {role: decompiled_c, path: evidence/x.c}\n---\n\n"
        "## Status\nINFERRED\n",
        encoding="utf-8")
    return ws


def test_gate_has_a_production_caller():
    """grep-level proof the function stopped being an orphan.

    #568: worker_budget.py is now a shim over core/gates/sinks; the real
    call site lives in the module family (sinks), so the scan covers all
    four files instead of the pre-split monolith."""
    family = ["worker_budget.py", "worker_budget_core.py",
              "worker_budget_gates.py", "worker_budget_sinks.py"]
    calls = []
    for fname in family:
        src = (ROOT / "hooks" / fname).read_text(encoding="utf-8")
        calls += [f"{fname}:{ln}" for ln in src.splitlines()
                  if "compare_register_change_proven_gate(" in ln
                  and not ln.lstrip().startswith("def ")
                  and "def compare_register_change_proven_gate" not in ln]
    assert calls, (
        "F-B3: compare_register_change_proven_gate still has zero call sites "
        "inside the worker_budget module family — the backstop is dead code")


def test_gate_blocks_unverified_proven_promotion(tmp_path):
    """OPEN -> PROVEN by direct register edit, no verifier_sign_off -> reject."""
    ws = _ws(tmp_path, "OPEN")
    reg = ws / "claim-register.yaml"
    before = worker_budget._claim_statuses(reg)
    reg.write_text(reg.read_text(encoding="utf-8").replace(
        "status: OPEN", "status: PROVEN"), encoding="utf-8")
    ok, reason = worker_budget.compare_register_change_proven_gate(
        reg, before, "orchestrator", ws / "facts")
    assert ok is False, "an unsigned PROVEN promotion must be rejected"
    assert "PROMOTION GATE" in reason, reason


def test_gate_allows_a_non_promoting_edit(tmp_path):
    ws = _ws(tmp_path, "OPEN")
    reg = ws / "claim-register.yaml"
    before = worker_budget._claim_statuses(reg)
    reg.write_text(reg.read_text(encoding="utf-8").replace(
        "imports resolved at runtime", "imports resolved lazily"),
        encoding="utf-8")
    ok, _reason = worker_budget.compare_register_change_proven_gate(
        reg, before, "orchestrator", ws / "facts")
    assert ok is True, "a statement-only edit must not trip the promotion gate"


def test_post_check_wires_the_gate_and_blocks_on_promotion(tmp_path, capsys):
    """post_check with a register_before snapshot that differs by a PROVEN
    flip must BLOCK (rc 2) — the F-B3 wiring, not just the gate in isolation."""
    ws = _ws(tmp_path, "PROVEN")  # register AFTER: claim already flipped
    reg = ws / "claim-register.yaml"
    before = {"C-001": "OPEN"}    # register BEFORE the unverified flip
    payload = {
        "tool_input": {"name": "w-alpha",
                       "description": "[T1 tools=grep] claim C-001 strings"},
        "tool_result": "",
        "register_before": before,
    }
    paths = {
        "workspace": str(ws), "state": ws / "analysis_state.txt",
        "register": reg, "deps": ws / "claim_deps.yaml",
        "task_spec": ws / "task_spec.yaml",
    }
    rc = worker_budget.post_check(payload, paths)
    assert rc == RC_BLOCK, (
        f"post_check must block an unverified PROVEN promotion (rc={rc})")
    err = capsys.readouterr().err
    assert "PROMOTION GATE" in err, err


def test_post_check_emits_write_blocked_event(tmp_path):
    """#532 item 5: the post_check block is observable in kunglao_log."""
    import json
    ws = _ws(tmp_path, "PROVEN")
    reg = ws / "claim-register.yaml"
    payload = {
        "tool_input": {"name": "w-alpha",
                       "description": "[T1 tools=grep] claim C-001 strings"},
        "tool_result": "",
        "register_before": {"C-001": "OPEN"},
    }
    paths = {
        "workspace": str(ws), "state": ws / "analysis_state.txt",
        "register": reg, "deps": ws / "claim_deps.yaml",
        "task_spec": ws / "task_spec.yaml",
    }
    worker_budget.post_check(payload, paths)
    logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
    assert logs, "a post_check block must land in runs/logs/"
    events = [json.loads(ln) for p in logs
              for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    blocked = [e for e in events if e["action"] == "write_blocked"]
    assert blocked, f"no write_blocked event: {events}"
    assert blocked[0]["exit"] == RC_BLOCK


def test_post_check_clean_completion_stays_silent(tmp_path):
    """No promotion, no snapshot delta -> rc 0 and no write_blocked event."""
    import json
    ws = _ws(tmp_path, "OPEN")
    payload = {
        "tool_input": {"name": "w-alpha",
                       "description": "[T1 tools=grep] claim C-001 strings"},
        "tool_result": "",
    }
    paths = {
        "workspace": str(ws), "state": ws / "analysis_state.txt",
        "register": ws / "claim-register.yaml",
        "deps": ws / "claim_deps.yaml",
        "task_spec": ws / "task_spec.yaml",
    }
    assert worker_budget.post_check(payload, paths) == 0
    logs = list((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
    events = [json.loads(ln) for p in logs
              for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()] \
        if logs else []
    assert [e for e in events if e["action"] == "write_blocked"] == []


def test_module_still_importable_as_a_hook(tmp_path):
    """The block reason must reach stderr, and the hook binary must stay
    importable end-to-end (no import-order regression from the new wiring)."""
    r = subprocess.run(
        [sys.executable, "-c", "import sys, worker_budget; sys.exit(0)"],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(
                 [str(ROOT / "hooks"), str(ROOT / "scripts")])})
    assert r.returncode == 0, r.stderr
