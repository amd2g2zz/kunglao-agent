# -*- coding: utf-8 -*-
"""Integration tests for #234 — the dispatch-failure 3-strike wiring.

The fast module (tests/test_obstacle_ladder.py) pins the pure unit
contracts; this module drives the REAL hook face:
hooks/worker_budget_sinks.post_check (the Agent PostToolUse completion
sink) must record a promotion attempt when the finished worker's terminal
status is a failure (failed/blocked/error) and stay silent on done —
fail-open on garbage input (the hook must never break dispatch).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402

import worker_budget  # noqa: E402  (#568 shim — post_check lives in sinks)


WORKER_LINE = ("worker_id=w-alpha | claim_id=C-001 | dispatched_at=1 | "
               "tier=1 | tools=grep")


def _ws(tmp_path: Path, worker_status: str) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "analysis_state.txt").write_text(
        "[current_task]\n"
        "[active_workers]\n"
        f"{WORKER_LINE}\n"
        "[/active_workers]\n",
        encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [
            {"id": "C-001", "status": "OPEN",
             "statement": "extract the C2 config",
             "promotion_attempts": 0},
        ]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    if worker_status:
        (ws / "runs" / "worker-status-w-alpha.md").write_text(
            f"# worker w-alpha\nstatus: {worker_status}\n",
            encoding="utf-8")
    return ws


def _post_check(ws: Path, tool_result: str = "") -> int:
    payload = {
        "tool_input": {"name": "w-alpha",
                       "description": "[T1 tools=grep] claim C-001 strings"},
        "tool_result": tool_result,
    }
    paths = {
        "workspace": str(ws), "state": ws / "analysis_state.txt",
        "register": ws / "claim-register.yaml",
        "deps": ws / "claim_deps.yaml",
        "task_spec": ws / "task_spec.yaml",
    }
    return worker_budget.post_check(payload, paths)


def _attempts(ws: Path) -> int:
    reg = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}
    claim = next(c for c in reg.get("claims", []) if c.get("id") == "C-001")
    return int(claim.get("promotion_attempts") or 0)


def test_failed_worker_increments_promotion_attempts(tmp_path):
    ws = _ws(tmp_path, "blocked")
    rc = _post_check(ws)
    assert rc == 0
    assert _attempts(ws) == 1


def test_error_worker_increments_too(tmp_path):
    ws = _ws(tmp_path, "error")
    _post_check(ws)
    assert _attempts(ws) == 1


def test_done_worker_stays_silent(tmp_path):
    ws = _ws(tmp_path, "done")
    _post_check(ws)
    assert _attempts(ws) == 0


def test_status_falls_back_to_closing_line_only(tmp_path):
    """F5: the fallback accepts ONLY the transcript's own closing status
    line — an embedded/quoted `status: failed` fragment (a delivered
    worker echoing a log excerpt) must NOT burn a strike."""
    ws = _ws(tmp_path, "")  # no status file
    rc = _post_check(ws, tool_result=(
        "step 1 ok\n"
        "quoted log: status: failed\n"
        "final wrap-up\n"
        "status: done\n"))
    assert rc == 0
    assert _attempts(ws) == 0


def test_status_fallback_closing_failed_counts(tmp_path):
    ws = _ws(tmp_path, "")  # no status file
    rc = _post_check(ws, tool_result=(
        "quoted log: status: done\n"
        "work wrapped\n"
        "status: failed\n"))
    assert rc == 0
    assert _attempts(ws) == 1


def test_missing_entry_warns_for_claim_dispatch(tmp_path, capsys):
    """F5: the starvation path (dispatched claim, no [active_workers]
    entry) warns to stderr — the 3-strike family must not go silent."""
    ws = _ws(tmp_path, "blocked")
    (ws / "analysis_state.txt").write_text("[current_task]\n",
                                           encoding="utf-8")
    rc = _post_check(ws)
    assert rc == 0
    assert _attempts(ws) == 0
    err = capsys.readouterr().err
    assert "strike not recorded" in err, err
    assert "C-001" in err, err


def test_missing_entry_silent_for_nonclaim_agent(tmp_path, capsys):
    """F5: non-claim Agent completions (verifiers, ad-hoc) stay silent."""
    ws = _ws(tmp_path, "blocked")
    (ws / "analysis_state.txt").write_text("[current_task]\n",
                                           encoding="utf-8")
    payload = {
        "tool_input": {"name": "w-alpha",
                       "description": "explore the binary layout"},
        "tool_result": "",
    }
    paths = {
        "workspace": str(ws), "state": ws / "analysis_state.txt",
        "register": ws / "claim-register.yaml",
        "deps": ws / "claim_deps.yaml",
        "task_spec": ws / "task_spec.yaml",
    }
    rc = worker_budget.post_check(payload, paths)
    assert rc == 0
    assert "strike not recorded" not in capsys.readouterr().err


def test_three_failed_dispatches_escalate_must_ask(tmp_path):
    """F6: strike 3 escalates to the charter must-ask lane through the real
    hook face — no synchronous DEAD flip; the claim stays in the ask lane."""
    ws = _ws(tmp_path, "blocked")
    for _ in range(3):
        rc = _post_check(ws)
        assert rc == 0
        # a re-dispatch re-registers the worker entry (remove_worker consumed
        # the previous one at completion — the real dispatch cycle)
        (ws / "analysis_state.txt").write_text(
            "[current_task]\n"
            "[active_workers]\n"
            f"{WORKER_LINE}\n"
            "[/active_workers]\n",
            encoding="utf-8")
    assert _attempts(ws) == 3
    reg = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}
    claim = next(c for c in reg.get("claims", []) if c.get("id") == "C-001")
    assert claim["status"] == "OPEN", "must-ask must not flip the status"
    artifact = ws / "blockers" / "must-ask-C-001.md"
    assert artifact.exists()
    assert "must-ask" in artifact.read_text(encoding="utf-8")
    assert not (ws / "blockers" / "dead-letter-C-001.md").exists()


# ---------- F1: the post_check face rejects the register-edit bypass ----------

def test_post_check_rejects_obstacle_proven_register_edit(tmp_path, capsys):
    """F1: an obstacle claim flipped OPEN -> PROVEN by direct register edit
    must be BLOCKED on the hook face with the named TARGET LADDER GATE
    reason — the dual-face policy (#15/#78), no claim_migrator bypass."""
    ws = _ws(tmp_path, "")  # worker state irrelevant here
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [
            {"id": "C-001", "status": "PROVEN",
             "origin": "failure-obstacle", "obstacle_class": "interception",
             "statement": "Obstacle (from C-002): CA pinning"},
        ]}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    payload = {
        "tool_input": {"name": "w-alpha",
                       "description": "[T1 tools=grep] claim C-001 strings"},
        "tool_result": "",
        "register_before": {"C-001": "OPEN"},
    }
    paths = {
        "workspace": str(ws), "state": ws / "analysis_state.txt",
        "register": ws / "claim-register.yaml",
        "deps": ws / "claim_deps.yaml",
        "task_spec": ws / "task_spec.yaml",
    }
    rc = worker_budget.post_check(payload, paths)
    assert rc == 2, "the direct-edit PROVEN promotion must block"
    err = capsys.readouterr().err
    assert "TARGET LADDER GATE" in err, err


def test_fail_open_on_garbage_state(tmp_path):
    """A broken state file must not break post_check (fail-open)."""
    ws = _ws(tmp_path, "blocked")
    (ws / "analysis_state.txt").write_text("[active_workers]\n", encoding="utf-8")
    rc = _post_check(ws)
    assert rc == 0, "post_check must keep its own rc even on hook-side garbage"
