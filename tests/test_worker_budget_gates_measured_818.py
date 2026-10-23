# -*- coding: utf-8 -*-
"""tests/test_worker_budget_gates_measured_818.py — the dispatch
admission battery (worker_budget_gates) in the MEASURED leg (issue #818
coverage climb; the hooks gate chain).

The existing pins (test_framework_rigidity_57, test_gate_residuals_427,
...) live in the fast tier, which the CI measured-set coverage leg does
not execute. This file re-pins the mechanical gates on REAL fixture
registers / workspaces / counter files: the capacity gate + its
fail-closed scan posture, the promotion and tier ladders, the #604
silent-failure circuit breaker, the #690 branch act budget, the
tool-channel prohibitions, and the deadline face.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml

import worker_budget_gates as wbg  # noqa: E402  (hooks/ on pytest path)
from worker_budget_core import HOST_FORBIDDEN_TOOLS, MAX_RETRIES


def _register(tmp_path: Path, claims: list[dict]) -> Path:
    p = tmp_path / "claim-register.yaml"
    p.write_text(yaml.safe_dump({"claims": claims}, sort_keys=False),
                 encoding="utf-8")
    return p


# ---------- capacity gate (#37) ----------

def _active_worker(ws: Path, name: str, status="in-progress") -> None:
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"worker-status-{name}.md").write_text(
        f"[2026-10-24T00:00:00Z] step: x | status: {status}\n",
        encoding="utf-8")


def test_capacity_gate_no_workspace_is_a_noop_pass() -> None:
    assert wbg.check_workers_lt_3({}) == (True, "")
    assert wbg.check_workers_lt_3({"workspace": ""}) == (True, "")


def test_capacity_gate_counts_active_workers_and_blocks_at_cap(
        tmp_path) -> None:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    ok, msg = wbg.check_workers_lt_3({"workspace": str(ws)})
    assert ok is True and "active_workers=0" in msg
    for i in range(3):
        _active_worker(ws, f"w{i}")
    ok, msg = wbg.check_workers_lt_3({"workspace": str(ws)})
    assert ok is False and ">= 3" in msg
    # a waiting worker is exempt from the count (the wait loop renews it)
    (ws / "runs" / "worker-status-w0.md").write_text(
        "[2026-10-24T00:00:00Z] step: x | status: waiting\n",
        encoding="utf-8")
    ok, msg = wbg.check_workers_lt_3({"workspace": str(ws)})
    assert ok is True and "active_workers=2" in msg


def test_capacity_gate_scan_error_is_fail_closed(tmp_path,
                                                 monkeypatch) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    from _path_hygiene import load_hooks_lib
    def boom(_ws):
        raise RuntimeError("scan exploded")
    monkeypatch.setattr(load_hooks_lib(), "scan_active_workers", boom)
    ok, msg = wbg.check_workers_lt_3({"workspace": str(ws)})
    assert ok is False
    assert "fail-closed" in msg and "scan exploded" in msg


# ---------- promotion ladder (#520) ----------

def test_promotion_attempts_gate(tmp_path) -> None:
    reg = _register(tmp_path, [
        {"id": "C-1", "status": "OPEN", "promotion_attempts": 3},
        {"id": "C-2", "status": "OPEN", "promotion_attempts": 1},
    ])
    ok, msg = wbg.check_promotion_attempts(reg, "C-1")
    assert ok is False and ">= 3" in msg
    ok, msg = wbg.check_promotion_attempts(reg, "C-2")
    assert ok is True and "promotion_attempts=1" in msg
    assert wbg.check_promotion_attempts(reg, None) == (True, "no target claim")
    ok, msg = wbg.check_promotion_attempts(reg, "C-404")
    assert ok is True and "not in register" in msg


# ---------- #690 branch act budget ----------

def test_branch_budget_unconstrained_shapes(tmp_path) -> None:
    paths = {"workspace": str(tmp_path)}
    for budget in ({}, {"retries": None}, {"retries": True},
                   {"retries": "many"}, {"retries": 0}):
        ok, msg = wbg.check_branch_budget(paths, "C-1", budget)
        assert (ok, msg) == (True, "")
    ok, _ = wbg.check_branch_budget(paths, None, {"retries": 2})
    assert ok is True
    ok, _ = wbg.check_branch_budget({}, "C-1", {"retries": 2})
    assert ok is True


def test_branch_budget_exhaustion_rejects(tmp_path) -> None:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-1\n    status: OPEN\n", encoding="utf-8")
    # two real recorded dispatches on the branch (the #690 grain)
    grain = wbg._step_grain()
    for _ in range(2):
        assert grain.bump_dispatch_count(ws, "C-1") == 1 + _
    paths = {"workspace": str(ws)}
    ok, msg = wbg.check_branch_budget(paths, "C-1", {"retries": 2})
    assert ok is False
    assert "branch act budget is spent" in msg
    ok, msg = wbg.check_branch_budget(paths, "C-1", {"retries": 5})
    assert ok is True and "dispatch_count=2/5" in msg


# ---------- #604 silent-failure circuit breaker ----------

def test_retry_counter_record_reset_and_breaker(tmp_path) -> None:
    ws = tmp_path
    assert wbg.read_retry_counter(ws) == {}
    for i in range(1, MAX_RETRIES):
        assert wbg.record_retry(ws, "worker-a", "C-1") == i
    ok, msg = wbg.check_max_retries(ws, "worker-a", "C-1")
    assert ok is True and f"retry={MAX_RETRIES - 1}" in msg
    # the third silent failure trips the breaker
    assert wbg.record_retry(ws, "worker-a", "C-1") == MAX_RETRIES
    ok, msg = wbg.check_max_retries(ws, "worker-a", "C-1")
    assert ok is False
    assert "BLOCKED" in msg and "failure-analysis-C-1.md" in msg
    # a different worker/claim pair is independent
    assert wbg.check_max_retries(ws, "worker-b", "C-1")[0] is True
    # PROVEN completion resets; resetting an absent key is False
    assert wbg.reset_retry_counter(ws, "worker-a", "C-1") is True
    assert wbg.reset_retry_counter(ws, "worker-a", "C-1") is False
    assert wbg.check_max_retries(ws, "worker-a", "C-1")[0] is True


def test_retry_counter_fail_open_shapes(tmp_path) -> None:
    assert wbg.record_retry("", "w", "C-1") == 0
    assert wbg.record_retry(tmp_path, "", "C-1") == 0
    ok, msg = wbg.check_max_retries("", "w", "C-1")
    assert (ok, msg) == (True, "no workspace/worker_id/claim_id - "
                               "max-retries skipped")
    assert wbg.reset_retry_counter("", "w", "C-1") is False
    # a corrupt counter file reads as empty (fail-open)
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / ".retry-counter.yaml").write_text(
        "]]] not: [yaml", encoding="utf-8")
    assert wbg.read_retry_counter(tmp_path) == {}
    assert wbg.check_max_retries(tmp_path, "w", "C-1")[0] is True


# ---------- tool-channel faces ----------

def test_host_forbidden_tools_and_wildcards() -> None:
    ok, msg = wbg.check_host_forbidden_tools(["mcp__frida__spawn"])
    assert ok is False and "forbidden" in msg
    ok, msg = wbg.check_host_forbidden_tools(["mcp__x64dbg__*"])
    assert ok is False and "covers" in msg
    ok, msg = wbg.check_host_forbidden_tools(
        ["mcp__x64dbg__connect_remote", "mcp__camoufox__*"])
    assert ok is True
    ok, _ = wbg.check_host_forbidden_tools(list(HOST_FORBIDDEN_TOOLS[:1]))
    assert ok is False


def test_tools_allowed_against_task_spec(tmp_path) -> None:
    spec = tmp_path / "task_spec.yaml"
    spec.write_text("constraints:\n  vm_detonation: forbidden\n",
                    encoding="utf-8")
    ok, msg = wbg.check_tools_allowed(["mcp__x64dbg__connect_remote"], spec)
    assert ok is False and "forbids it" in msg
    ok, msg = wbg.check_tools_allowed(["Read"], spec)
    assert (ok, msg) == (True, "tools allowed")
    # no task_spec at all -> allow
    ok, msg = wbg.check_tools_allowed(["mcp__x64dbg__connect_remote"],
                                      tmp_path / "void.yaml")
    assert (ok, msg) == (True, "no task_spec (allow)")


# ---------- deadline face ----------

def test_deadline_faces(tmp_path) -> None:
    missing = tmp_path / "void.txt"
    assert wbg.check_deadline(missing) == (True, "no state file")
    past = tmp_path / "state.txt"
    past.write_text("deadline_ts: 1000\n", encoding="utf-8")
    ok, msg = wbg.check_deadline(past)
    assert ok is False and "now >= deadline_ts 1000" in msg
    future = tmp_path / "future.txt"
    future.write_text(f"deadline_ts: {int(time.time()) + 3600}\n",
                      encoding="utf-8")
    ok, msg = wbg.check_deadline(future)
    assert ok is True and "deadline_ts=" in msg
    broken = tmp_path / "broken.txt"
    broken.write_text("deadline_ts: soon\n", encoding="utf-8")
    assert wbg.check_deadline(broken) == (True, "deadline_ts unparseable "
                                                   "(allow)")
    none = tmp_path / "none.txt"
    none.write_text("other: key\n", encoding="utf-8")
    assert wbg.check_deadline(none) == (True, "no deadline_ts set")


# ---------- tier ladder (#627/#680) ----------

def test_tier_gate_threshold_and_exemptions(tmp_path) -> None:
    assert wbg.check_tier_gate(tmp_path / "void.yaml", 1)[0] is True
    reg = _register(tmp_path, [
        {"id": "C-1", "status": "OPEN", "evidence_tier_attempted": 0},
        {"id": "C-2", "status": "PROVEN", "evidence_tier_attempted": 0},
        {"id": "C-3", "status": "PARK", "evidence_tier_attempted": 0},
        {"id": "C-4", "status": "OPEN", "evidence_tier_attempted": 2},
    ])
    ok, msg = wbg.check_tier_gate(reg, 2)
    assert ok is False and "C-1" in msg and "evidence_tier=0 < 1" in msg
    ok, msg = wbg.check_tier_gate(reg, 3)
    assert ok is False  # C-4 is at 2 >= 2, but C-1 still gates
    sub = tmp_path / "2"
    sub.mkdir()
    reg2 = _register(sub, [
        {"id": "C-9", "status": "OPEN", "evidence_tier_attempted": 2},
    ])
    ok, msg = wbg.check_tier_gate(reg2, 3)
    assert ok is True and ">= 2" in msg


def test_tier_consistency_derives_the_envelope_tier(tmp_path) -> None:
    reg = _register(tmp_path, [
        {"id": "C-1", "status": "OPEN", "evidence_tier_attempted": 0},
    ])
    assert wbg.check_tier_consistency(reg, None, 2)[0] is True
    ok, msg = wbg.check_tier_consistency(reg, "C-404", 2)
    assert ok is True and "not in register" in msg
    ok, msg = wbg.check_tier_consistency(reg, "C-1", 1)
    assert ok is True and "matches action_tier" in msg
    ok, msg = wbg.check_tier_consistency(reg, "C-1", 3)
    assert ok is False and "tier mismatch" in msg and "tier=1" in msg
    # a recorded deviation passes with the stderr note
    ok, msg = wbg.check_tier_consistency(reg, "C-1", 3,
                                         prompt="agent-reasoning: deeper")
    assert ok is True and "deviation recorded" in msg


# ---------- the step-settled sync barrier (#690) ----------

def test_step_settled_barrier_faces(tmp_path) -> None:
    assert wbg.check_step_settled({}) == (True, "")
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    ok, msg = wbg.check_step_settled({"workspace": str(ws)})
    assert ok is True            # no open step -> admit


# ---------- register IO ----------

def test_register_worker_remove_and_read_roundtrip(tmp_path) -> None:
    reg = _register(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    workers_path = tmp_path / "workers.yaml"
    entry = {"worker_id": "w-1", "claim_id": "C-1", "status": "in-progress"}
    wbg.register_worker(workers_path, entry)
    # the workers store is the pipe-line format (read via the same
    # single-source reader register_worker writes through)
    stored = wbg.read_active_workers(workers_path)
    assert stored and stored[0]["worker_id"] == "w-1"
    assert stored[0]["claim_id"] == "C-1"
    removed = wbg.remove_worker(workers_path, "w-1")
    assert removed["claim_id"] == "C-1"
    assert wbg.remove_worker(workers_path, "w-1") is None
    assert wbg.read_claim(reg, "C-1")["id"] == "C-1"
    assert wbg.read_claim(reg, "C-404") is None


# ---------- worker self-promotion compare (#57 gate family) ----------

def test_compare_register_change_faces(tmp_path) -> None:
    reg = _register(tmp_path, [{"id": "C-1", "status": "PROVEN"},
                               {"id": "C-2", "status": "OPEN"}])
    before = {"C-1": "OPEN", "C-2": "OPEN"}
    # no snapshot / orchestrator actors are exempt
    assert wbg.compare_register_change(reg, None, "worker-a") == \
        (True, "no-before")
    assert wbg.compare_register_change(reg, before, "orchestrator") == \
        (True, "orchestrator exempt")
    assert wbg.compare_register_change(reg, before, "") == \
        (True, "orchestrator exempt")
    # a worker flipping a claim to terminal is self-promotion: blocked
    ok, msg = wbg.compare_register_change(reg, before, "worker-a")
    assert ok is False and "SELF-PROMOTION BLOCKED" in msg
    assert "C-1:OPEN->PROVEN" in msg
    # a non-terminal flip is fine
    sub = tmp_path / "2"
    sub.mkdir()
    reg2 = _register(sub, [{"id": "C-1", "status": "IN_PROGRESS"}])
    ok, msg = wbg.compare_register_change(
        reg2, {"C-1": "OPEN"}, "worker-a")
    assert (ok, msg) == (True, "ok")
    # a register the yaml loader cannot parse reads as "unreadable" and
    # this gate allows (the proven gate is the fail-closed twin)
    broken = tmp_path / "broken.yaml"
    broken.write_text("]]]: ]]] not: [yaml", encoding="utf-8")
    assert wbg.compare_register_change(broken, before, "worker-a") == \
        (True, "register unreadable")


def test_compare_register_change_proven_gate_faces(tmp_path) -> None:
    facts = tmp_path / "facts"
    facts.mkdir(parents=True)
    reg = _register(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
    before = {"C-1": "OPEN"}
    # no snapshot: vacuous
    assert wbg.compare_register_change_proven_gate(
        reg, None, "orchestrator", facts)[0] is True
    # unreadable register AFTER a write: fail closed (a promotion may
    # have been written and cannot be verified) — a register that makes
    # the yaml loader RAISE is the unreadable shape
    broken = tmp_path / "broken.yaml"
    broken.write_text("]]]: ]]] not: [yaml", encoding="utf-8")
    ok, msg = wbg.compare_register_change_proven_gate(
        broken, before, "orchestrator", facts)
    assert ok is False and "fail closed" in msg


# ---------- the self-cap face ----------

def _spec(tmp_path, budget) -> Path:
    p = tmp_path / f"spec-{budget}.yaml"
    body = {} if budget == "absent" else {"time_budget_minutes": budget}
    p.write_text(yaml.safe_dump(body or {}), encoding="utf-8")
    return p


def test_no_self_cap_faces(tmp_path) -> None:
    clean = "analyze the packed section and map the imports"
    assert wbg.check_no_self_cap(clean, _spec(tmp_path, "absent")) == \
        (True, "no self-cap detected")
    # explicit negation suppresses the detector
    assert wbg.check_no_self_cap("work until done, then stop",
                                 _spec(tmp_path, 0))[0] is True
    capped = "cap it at 30 minutes on the unpack stage"
    # zero/absent budget: any self-cap is rejected
    ok, msg = wbg.check_no_self_cap(capped, _spec(tmp_path, 0))
    assert ok is False and "no budget authorised" in msg
    ok, msg = wbg.check_no_self_cap(capped, _spec(tmp_path, "absent"))
    assert ok is False
    # budget > 0: within budget passes, over budget rejects
    ok, msg = wbg.check_no_self_cap("a 30 min cap",
                                    _spec(tmp_path, 60))
    assert (ok, msg) == (True, "self-cap within budget 60.0 min")
    ok, msg = wbg.check_no_self_cap("a 90 min cap", _spec(tmp_path, 60))
    assert ok is False and "exceeds task_spec" in msg
    # constraints-nested budget is honored
    p = tmp_path / "nested.yaml"
    p.write_text(yaml.safe_dump(
        {"constraints": {"time_budget_minutes": 45}}), encoding="utf-8")
    ok, msg = wbg.check_no_self_cap("run for 40 min", p)
    assert ok is True and "45.0" in msg
    # a non-numeric budget degrades to no-authorization
    ok, msg = wbg.check_no_self_cap(capped, _spec(tmp_path, "soon"))
    assert ok is False
