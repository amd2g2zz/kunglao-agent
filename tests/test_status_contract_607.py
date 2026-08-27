# -*- coding: utf-8 -*-
"""tests/test_status_contract_607.py — #607: unknown worker statuses must be
VISIBLE, stuck workers must FREE their claims, parsing must be single-source.

RED (adjudicated facts): scan_active_workers skipped any status != in-progress
→ planning workers invisible (not active, not stuck, not W-15) → their claims
stuck IN_PROGRESS forever (claim_expiry has zero mechanical callers).
Adjudicated fix:
 1. scan_active_workers: terminal tokens {done,failed,blocked,error} → not
    active; ANYTHING ELSE (planning/preflight/None) → active (visible; feeds
    the stuck list after STUCK_MINUTES → #595 STUCK_WORKERS_PRESENT).
 2. backtrack_gate.parse_status delegates to lib_kunglao.parse_worker_status
    (#444 single parse point — kills the `## Status`-only mirror).
 3. 闭环: _act_stuck_workers reopens stuck workers' IN_PROGRESS claims →
    OPEN (audit comment trail; never touches PROVEN/terminal).
 4. Kicker pin: external_kicker.has_fresh_workers behavior UNCHANGED for
    planning workers (semantic change provably isolated to scan_active_workers).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
# hooks/lib_kunglao.py is loaded BY PATH under a unique name (repo-established
# pattern) — a bare sys.path insert of hooks/ makes the name ambiguous with
# scripts/lib_kunglao.py and breaks other suites' import order.
_PROTOCOL_NAME = "lib_kunglao_hooks_607"


def _load_protocol():
    lib = sys.modules.get(_PROTOCOL_NAME)
    if lib is None:
        spec = importlib.util.spec_from_file_location(
            _PROTOCOL_NAME, ROOT / "hooks" / "lib_kunglao.py")
        lib = importlib.util.module_from_spec(spec)
        sys.modules[_PROTOCOL_NAME] = lib
        spec.loader.exec_module(lib)
    return lib


lib_kunglao = _load_protocol()


def _backdate(p: Path, minutes: int) -> None:
    old = time.time() - minutes * 60
    os.utime(p, (old, old))


def _mk_worker(ws: Path, stem: str, status_line: str, age_min: int = 1) -> Path:
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    p = runs / f"worker-status-{stem}.md"
    p.write_text(f"[10:00] step: started | {status_line}\n", encoding="utf-8")
    _backdate(p, age_min)
    return p


# ---------- 1. scan_active_workers semantic tightening ----------

def test_planning_worker_counts_active(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    _mk_worker(ws, "C100", "status: planning")
    active, stuck = lib_kunglao.scan_active_workers(ws)
    assert active == 1, "planning must be visible-active (was skipped)"


def test_unknown_status_preflight_active(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    _mk_worker(ws, "C101", "status: preflight")
    active, _ = lib_kunglao.scan_active_workers(ws)
    assert active == 1


def test_terminal_statuses_not_active(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    for i, st in enumerate(["done", "failed", "blocked", "error"]):
        _mk_worker(ws, f"T{i}", f"status: {st}")
    active, stuck = lib_kunglao.scan_active_workers(ws)
    assert active == 0 and stuck == []


def test_aged_planning_worker_enters_stuck(tmp_path):
    STUCK_MINUTES = lib_kunglao.STUCK_MINUTES
    ws = tmp_path / "ws"; ws.mkdir()
    _mk_worker(ws, "C102", "status: planning", age_min=STUCK_MINUTES + 5)
    active, stuck = lib_kunglao.scan_active_workers(ws)
    assert active == 1
    assert any(w["worker"] == "worker-status-C102" for w in stuck), \
        "aged planning worker must reach the stuck list (→ #595 event)"


def test_in_progress_behavior_unchanged(tmp_path):
    STUCK_MINUTES = lib_kunglao.STUCK_MINUTES
    ws = tmp_path / "ws"; ws.mkdir()
    _mk_worker(ws, "C103", "status: in-progress", age_min=1)
    _mk_worker(ws, "C104", "status: in-progress", age_min=STUCK_MINUTES + 5)
    active, stuck = lib_kunglao.scan_active_workers(ws)
    assert active == 2
    assert [w["worker"] for w in stuck] == ["worker-status-C104"]


# ---------- 2. backtrack_gate delegates to canonical parser ----------

def test_backtrack_parse_delegates_inline_status():
    import backtrack_gate
    text = "[10:00] step: x | status: in-progress\n"  # no ## Status section
    assert backtrack_gate.parse_status(text) == "in_progress", \
        "mirror parser must read inline tokens via lib_kunglao (was None)"


def test_backtrack_parse_backcompat_section():
    import backtrack_gate
    text = "## Status\ndone\n"
    assert backtrack_gate.parse_status(text) == "done"


# ---------- 4. kicker behavior pin (unchanged) ----------

def test_kicker_pin_planning_worker_does_not_block_kick(tmp_path):
    import external_kicker
    ws = tmp_path / "ws"; ws.mkdir()
    _mk_worker(ws, "C105", "status: planning", age_min=1)
    # real signature: has_fresh_workers(runs_dir, fresh_minutes=...) — it has
    # its OWN in-progress-only loop (L349), untouched by this PR (pin).
    fresh = external_kicker.has_fresh_workers(ws / "runs", fresh_minutes=30)
    assert fresh is False, \
        "pin: planning workers do NOT block kicks (scan_active_workers " \
        "semantic change is isolated; converging the kicker loop is future work)"


# ---------- 3. stuck → claim reopen 闭环 ----------

def test_act_stuck_reopens_inprogress_claim(tmp_path):
    import yaml
    import convergence_check as cc
    STUCK_MINUTES = lib_kunglao.STUCK_MINUTES
    ws = tmp_path / "ws"; ws.mkdir()
    _mk_worker(ws, "C400", "status: planning", age_min=STUCK_MINUTES + 10)
    reg = ws / "claim-register.yaml"
    reg.write_text(yaml.safe_dump({"claims": [
        {"id": "C-400", "status": "IN_PROGRESS", "statement": "x"}]}), encoding="utf-8")
    (ws / "analysis_state.txt").write_text("project_type=android\n", encoding="utf-8")
    (ws / "claim_deps.yaml").write_text("depends_on: {}\n", encoding="utf-8")
    facts = ws / "facts"; facts.mkdir()
    (facts / "_INDEX.md").write_text("# _INDEX\n", encoding="utf-8")
    # Unit-level: exercise the stuck action directly (the SCHEDULE probe
    # path is covered by test_stuck_event_595; DRAIN-state wiring is future
    # work — this test pins the reopen 闭环 itself).
    import inspect
    import dataclasses
    fields = {f.name: None for f in dataclasses.fields(cc._DecideInputs)}
    fields.update(workspace=ws,
                  stuck=[{"worker": "worker-status-C400", "age_min": STUCK_MINUTES + 10}])
    inputs = cc._DecideInputs(**fields)
    summary = cc._act_stuck_workers(inputs)
    assert "C-400" in summary, f"reopen must surface in summary: {summary}"
    data = yaml.safe_load(reg.read_text(encoding="utf-8"))
    c400 = next(c for c in data["claims"] if c["id"] == "C-400")
    assert c400["status"] == "OPEN", \
        f"闭环: stuck worker's claim must reopen for dispatch (got {c400['status']})"
    assert any("#607 reopened" in h for h in c400.get("history", [])), "audit trail"
