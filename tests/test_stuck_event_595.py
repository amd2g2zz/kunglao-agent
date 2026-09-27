# -*- coding: utf-8 -*-
"""RED tests for #595 — STUCK_WORKERS_PRESENT event consumed by the gate.

MDP (from .claude/PRPs/plans/v013-milestone.plan.md Round-1 / #595):
  - Add Event.STUCK_WORKERS_PRESENT to convergence_check.py
  - Insert predicate at index 2 of STAGE_PROBES[State.SCHEDULE]
  - Transition (SCHEDULE, STUCK_WORKERS_PRESENT) -> (BLOCKED, _act_stuck_workers)
  - _act_stuck_workers writes runs/.stuck-report.md (non-fatal)
  - Test backdates a worker-status file (in-progress + mtime > STUCK_MINUTES)

These tests FAIL until the GREEN step adds the Event + predicate + transition
+ action builder. They lock the surface area: enum member, probe position,
transition target state, and the report-file side effect.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import convergence_check as cc  # noqa: E402


# ---------- fixtures ---------------------------------------------------------

def _ws(base: Path) -> Path:
    ws = base / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _reg(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, sort_keys=False, allow_unicode=True),
        encoding="utf-8")


def _ts(ws: Path) -> None:
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n  - id: q1\n    q: what is it\n    need: model_selection\n",
        encoding="utf-8")


def _stuck_worker(ws: Path, name: str, age_min: int) -> Path:
    """Write a worker-status file whose mtime is backdated by age_min minutes.

    STUCK_MINUTES (hooks/lib_kunglao.py) = 20. So age_min > 20 → stuck.
    """
    p = ws / "runs" / f"worker-status-{name}.md"
    p.write_text(
        f"claim C-{name} | step x | status: in-progress\n", encoding="utf-8")
    old = time.time() - age_min * 60
    os.utime(p, (old, old))
    return p


# ---------- Event enum ------------------------------------------------------

def test_event_stuck_workers_present_declared() -> None:
    """#595: new Event enum member STUCK_WORKERS_PRESENT must exist."""
    assert hasattr(cc, "Event"), "Event enum missing"
    assert "STUCK_WORKERS_PRESENT" in cc.Event.__members__, (
        "Event.STUCK_WORKERS_PRESENT not declared (#595)")


# ---------- STAGE_PROBES position --------------------------------------------

def test_stuck_workers_present_at_schedule_index_2() -> None:
    """#595: the new Event must sit BEFORE the saturation tail of
    STAGE_PROBES[State.SCHEDULE] — a stuck worker can never be masked by
    dispatchable work. Originally pinned at index 2; #342 prepended
    VERIFY_STALE at index 0 (the stale-partial forcing point, evaluated
    FIRST per the issue), pushing the #595 probe set down one to 1/2/3.
    The pin's intent is unchanged: the pre-#342 probe order is preserved
    (pushed down, not replaced), STUCK still precedes the saturation tail.
    """
    probes = cc.STAGE_PROBES[cc.State.SCHEDULE]
    assert probes[0] is cc.Event.VERIFY_STALE, (
        f"VERIFY_STALE must sit at index 0 of STAGE_PROBES[SCHEDULE] (#342), "
        f"got {probes[0]!r}")
    assert probes[3] is cc.Event.STUCK_WORKERS_PRESENT, (
        f"STUCK_WORKERS_PRESENT must sit at index 3 of STAGE_PROBES[SCHEDULE] "
        f"(#595 semantics, displaced by #342's VERIFY_STALE at 0), "
        f"got {probes[3]!r} at position 3")
    # original entries preserved (not replaced): WORK_AND_FREE_SLOT,
    # PARTIALS_AND_FREE_SLOT stay in relative order (now 1/2); the
    # remaining tail stays in order.
    assert probes[1] is cc.Event.WORK_AND_FREE_SLOT
    assert probes[2] is cc.Event.PARTIALS_AND_FREE_SLOT
    tail = probes[4:]
    assert tail == [cc.Event.WORK_NO_FREE_SLOT,
                    cc.Event.FAILURE_ARTIFACTS_DUE,
                    cc.Event.LADDER_EXHAUSTED_BLOCKER,
                    cc.Event.LADDER_REQUIRED_BLOCKER,
                    cc.Event.UNEXPECTED_STATE]


# ---------- TRANSITIONS wiring ----------------------------------------------

def test_transition_stuck_workers_to_blocked() -> None:
    """#595: (SCHEDULE, STUCK_WORKERS_PRESENT) -> (BLOCKED, _act_stuck_workers)."""
    transition = cc.TRANSITIONS.get(
        (cc.State.SCHEDULE, cc.Event.STUCK_WORKERS_PRESENT))
    assert transition is not None, (
        "TRANSITIONS[(SCHEDULE, STUCK_WORKERS_PRESENT)] missing (#595)")
    target_state, action_builder = transition
    assert target_state is cc.State.BLOCKED
    assert callable(action_builder), "action builder must be callable"
    # VERDICTS[BLOCKED] => decision='BLOCKED', exit_code=EXIT_BLOCKED
    assert cc.VERDICTS[cc.State.BLOCKED][0] == "BLOCKED"


# ---------- _act_stuck_workers exists + writes the report file --------------

def test_act_stuck_workers_writes_report(tmp_path: Path) -> None:
    """#595: _act_stuck_workers writes runs/.stuck-report.md (non-fatal)."""
    assert hasattr(cc, "_act_stuck_workers"), \
        "_act_stuck_workers action builder missing (#595)"
    # Build a _DecideInputs with one stuck worker.
    snap = cc._DecideInputs(
        workspace=tmp_path, opens=[], partials=[], active=1,
        stuck=[{"worker": "worker-status-w1", "age_min": 25}],
        done_violations=[], free_slots=2, blockers=[], failure_blocked_ids=[],
        orphans=[], unverified_pqs=[], pq_note_gaps=[], pq_error=None,
        blocked_claims=[], unblocked_open=[], failure_blocked_open=[])
    # MUST NOT raise — non-fatal report.
    msg = cc._act_stuck_workers(snap)
    report = tmp_path / "runs" / ".stuck-report.md"
    assert report.exists(), f"expected {report} to be created"
    body = report.read_text(encoding="utf-8")
    assert "worker-status-w1" in body, "report must mention the stuck worker stem"
    assert "25" in body, "report must mention the age"


# ---------- end-to-end decide() ----------------------------------------------

def test_decide_escalates_to_blocked_when_stuck_present(tmp_path: Path) -> None:
    """#595: backdated in-progress worker + non-empty opens => BLOCKED + report.

    Setup:
      - 1 OPEN claim with blocked=True  (so unblocked_open = [])
      - 1 worker-status file backdated 25 min (in-progress, > STUCK_MINUTES=20)
      - no failure_analysis file (so FAILURE_ARTIFACTS_DUE does not fire)
      - SCHEDULE probe order: WORK_AND_FREE_SLOT (False), PARTIALS_AND_FREE_SLOT
        (False), STUCK_WORKERS_PRESENT (True) -> BLOCKED + _act_stuck_workers.
    """
    ws = _ws(tmp_path)
    _reg(ws, [{"id": "C-1", "status": "OPEN", "blocked": True}])
    _ts(ws)
    _stuck_worker(ws, "w1", age_min=25)

    decision = cc.decide(ws)

    assert decision["decision"] == "BLOCKED", \
        f"expected BLOCKED (stuck worker), got {decision}"
    report = ws / "runs" / ".stuck-report.md"
    assert report.exists(), f"runs/.stuck-report.md must exist at {report}"


def test_decide_does_not_flag_when_workers_fresh(tmp_path: Path) -> None:
    """Control: no stuck workers + dispatchable open claim => DISPATCH.

    Proves STUCK_WORKERS_PRESENT predicate only fires when stuck != [].
    """
    ws = _ws(tmp_path)
    _reg(ws, [{"id": "C-1", "status": "OPEN", "blocked": False}])
    _ts(ws)
    # fresh in-progress worker (< STUCK_MINUTES)
    p = ws / "runs" / "worker-status-w1.md"
    p.write_text("claim C-1 | step x | status: in-progress\n", encoding="utf-8")

    decision = cc.decide(ws)

    assert decision["decision"] != "BLOCKED", \
        f"fresh worker should not trigger BLOCKED, got {decision}"
    assert not (ws / "runs" / ".stuck-report.md").exists(), \
        "no stuck-report.md should be written when no worker is stuck"
