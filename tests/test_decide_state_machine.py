# -*- coding: utf-8 -*-
"""#443 behavior tests — decide() as an explicit (State, Event) machine.

RED phase: every test asserts on the new module surface (State / Event /
TRANSITIONS / STAGE_PROBES / _EVENT_PREDICATES / VERDICTS / _run_machine /
_decide_inputs) via getattr-None guards — pre-GREEN these FAIL as
assertions, not import errors.

Invariants (design.md §6): table completeness, probe coverage, catch-all
tails, verdict mapping, zero-elif meta-guard, ladder-flavor seam,
determinism, #495 artifact predicate.
"""
from __future__ import annotations

import inspect
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS = Path(__file__).parent
if str(TESTS) not in sys.path:  # sibling-module import under and outside pytest
    sys.path.insert(0, str(TESTS))

import convergence_check as cc

# Import anchor builders for matrix-driven machine tests.
import test_decide_regression_anchor as anchor

STAGES = ("SCHEMA", "DRAIN", "SCHEDULE")
VERDICT_STATES = ("INVALID", "CONVERGED", "DISPATCH", "DISPATCH_VERIFIER",
                  "SATURATED", "BLOCKED", "PARK")  # #634: PARK 5th verdict


def _surface(name: str):
    """Fetch a #443 surface symbol; None pre-GREEN so asserts fail, not imports."""
    return getattr(cc, name, None)


def _snapshots():
    """(label, workspace) pairs: all-empty and busy snapshots for catch-alls."""
    base = Path(tempfile.mkdtemp(prefix="sm-inv-"))
    empty = anchor._ws(base, "empty")
    anchor._reg(empty, [])
    anchor._ts(empty, anchor._pq("[]"))
    busy = anchor._ws(base, "busy")
    anchor._reg(busy, [anchor._claim("C-1", blocked=True, promotion_attempts=2)])
    anchor._ts(busy, "primary_questions:\n  - 5\n")
    anchor._fact_dir(busy, index=anchor._PARTIAL_INDEX)
    anchor._workers(busy, 3)
    return [("empty", empty), ("busy", busy)]


# ------------------------------------------------------------- declaration

def test_state_enum_declared() -> None:
    State = _surface("State")
    assert State is not None, "#443: State enum missing from convergence_check"
    for s in STAGES + VERDICT_STATES:
        assert s in State.__members__, f"State.{s} missing"


def test_event_enum_declared_with_landed_vocabulary() -> None:
    """Event names consume the LANDED vocabulary — no second taxonomy (#446 F):
    #495 failure three-artifact protocol, #497 ladder flavors, and the
    historical gate names (M2/#147/#77/S8-C0)."""
    Event = _surface("Event")
    assert Event is not None, "#443: Event enum missing from convergence_check"
    expected = {
        "SCHEMA_INVALID",            # #77 malformed primary_questions
        "WORK_PENDING", "DRAINED",
        "ORPHAN_TERMINAL_CLAIM",     # M2 completeness
        "PRIMARY_Q_UNVERIFIED",      # M2 BLIND-verified PROVEN
        "NOTE_LAYER_GAP",            # DESIGN S8 C0
        "OPEN_HYPOTHESIS_AT_CLOSE",  # #662 unadjudicated hypothesis gate
        "DISCOVERY_UNCONSUMED",      # #147 discovery consumption
        "GLOBAL_CONTRADICTION",      # #147 completion transaction
        "ANOMALY_DETECTED",          # #663 anomaly observation gate
        "DRAIN_CLEAN",
        "WORK_AND_FREE_SLOT", "PARTIALS_AND_FREE_SLOT", "WORK_NO_FREE_SLOT",
        "STUCK_WORKERS_PRESENT",     # #595 silent-detect consumes stuck_workers
        "ACTIVE_WORKERS_PRESENT",    # #98 DRAIN: live worker on a drained claim surface
        "FAILURE_ARTIFACTS_DUE",     # #495 validated_capability/identified_obstacle
        "LADDER_REQUIRED_BLOCKER",   # #497 climb-the-ladder flavor
        "LADDER_EXHAUSTED_BLOCKER",  # #497 ladder-exhaustion marker
        "UNEXPECTED_STATE",
        "JADX_INFEASIBLE",           # #670 intake-level (NOT in DRAIN)
    }
    assert expected == set(Event.__members__), \
        f"Event vocabulary drift: missing={expected - set(Event.__members__)} " \
        f"extra={set(Event.__members__) - expected}"


def test_transition_and_probe_tables_declared() -> None:
    for name in ("TRANSITIONS", "STAGE_PROBES", "_EVENT_PREDICATES", "VERDICTS"):
        assert _surface(name) is not None, f"#443: {name} missing"


# ------------------------------------------------------------- invariants

def test_table_complete_for_every_probe() -> None:
    """Every (stage, probe event) pair must have a transition row — a probe
    that can fire but has no row is an unhandled state (KeyError today,
    silent fallback tomorrow)."""
    STAGE_PROBES, TRANSITIONS = _surface("STAGE_PROBES"), _surface("TRANSITIONS")
    assert STAGE_PROBES and TRANSITIONS
    missing = [(stage.value, ev.value) for stage, events in STAGE_PROBES.items()
               for ev in events if (stage, ev) not in TRANSITIONS]
    assert not missing, f"probe events without transitions: {missing}"


def test_predicate_coverage_exact() -> None:
    """Every probed event has a predicate, and no orphan predicates exist
    (a predicate nothing probes is dead vocabulary)."""
    STAGE_PROBES, PRED = _surface("STAGE_PROBES"), _surface("_EVENT_PREDICATES")
    probed = {ev for events in STAGE_PROBES.values() for ev in events}
    assert probed == set(PRED), \
        f"probed-without-predicate={probed - set(PRED)} " \
        f"predicate-without-probe={set(PRED) - probed}"


def test_probe_order_declared_for_all_stages() -> None:
    STAGE_PROBES, State = _surface("STAGE_PROBES"), _surface("State")
    for stage_name in STAGES:
        stage = State[stage_name]
        assert stage in STAGE_PROBES, f"stage {stage_name} has no probe list"
        assert len(STAGE_PROBES[stage]) >= 2, \
            f"stage {stage_name} needs >=2 probes (gate + catch-all)"


def test_stage_probes_cover_every_snapshot() -> None:
    """Coverage: for any snapshot, at least one probe of the stage fires
    (SCHEMA's WORK_PENDING/DRAINED are complementary, not each always-true)."""
    STAGE_PROBES, PRED = _surface("STAGE_PROBES"), _surface("_EVENT_PREDICATES")
    _decide_inputs = _surface("_decide_inputs")
    for stage_name in STAGES:
        stage = cc.State[stage_name]
        for label, ws in _snapshots():
            snap = _decide_inputs(ws)
            assert any(PRED[ev](snap) for ev in STAGE_PROBES[stage]), \
                f"stage {stage_name}: no probe fires on {label} snapshot"


def test_drain_schedule_tails_are_unconditional() -> None:
    """DRAIN and SCHEDULE end in literal catch-alls (DRAIN_CLEAN /
    UNEXPECTED_STATE): true on an all-empty AND a maximal snapshot."""
    STAGE_PROBES, PRED = _surface("STAGE_PROBES"), _surface("_EVENT_PREDICATES")
    _decide_inputs = _surface("_decide_inputs")
    for stage_name in ("DRAIN", "SCHEDULE"):
        tail = STAGE_PROBES[cc.State[stage_name]][-1]
        for label, ws in _snapshots():
            snap = _decide_inputs(ws)
            assert PRED[tail](snap) is True, \
                f"stage {stage_name} tail {tail.value} not always-true on {label}"


def test_verdict_mapping_matches_exit_constants() -> None:
    """Terminal state → (decision, exit_code) must agree with the frozen
    EXIT_* constants and the six decisions of the old matrix."""
    VERDICTS, State = _surface("VERDICTS"), _surface("State")
    expected = {
        State.INVALID: ("INVALID", cc.EXIT_BLOCKED),
        State.CONVERGED: ("CONVERGED", cc.EXIT_CONVERGED),
        State.DISPATCH: ("DISPATCH", cc.EXIT_DISPATCH),
        State.DISPATCH_VERIFIER: ("DISPATCH_VERIFIER", cc.EXIT_VERIFY),
        State.SATURATED: ("SATURATED", cc.EXIT_SATURATED),
        State.BLOCKED: ("BLOCKED", cc.EXIT_BLOCKED),
        State.PARK: ("PARK", cc.EXIT_PARK),  # #634: 5th verdict, legal idle
    }
    assert VERDICTS == expected, "verdict/exit-code mapping drifted"
    assert set(VERDICTS) == {State[s] for s in VERDICT_STATES}, \
        "non-terminal states must not carry verdicts"


def test_decide_source_contains_no_elif() -> None:
    """Meta-guard: decide() must stay elif-free (issue AC #1). New gates are
    table rows, never new elif rungs."""
    src = inspect.getsource(cc.decide)
    assert "elif" not in src, "#443 regression: an elif crept back into decide()"


def test_ladder_flavors_share_verdict_and_action() -> None:
    """#497 seam: both ladder flavors point at the SAME verdict+action today
    (decide() does not own must-ask vs climb). Splitting them later is a
    one-row table edit, not a new elif."""
    TRANSITIONS, State, Event = _surface("TRANSITIONS"), _surface("State"), _surface("Event")
    req = TRANSITIONS[(State.SCHEDULE, Event.LADDER_REQUIRED_BLOCKER)]
    exh = TRANSITIONS[(State.SCHEDULE, Event.LADDER_EXHAUSTED_BLOCKER)]
    assert req[0] is exh[0] is State.BLOCKED
    assert req[1] is exh[1], "ladder flavors must share one action builder"


def test_failure_event_consumes_495_artifact_gate() -> None:
    """FAILURE_ARTIFACTS_DUE derives from the #495 three-artifact protocol:
    an analysis missing identified_obstacle keeps the claim failure-blocked;
    both artifacts recorded releases it."""
    PRED, _decide_inputs = _surface("_EVENT_PREDICATES"), _surface("_decide_inputs")
    Event = _surface("Event")
    base = Path(tempfile.mkdtemp(prefix="sm-495-"))
    partial = anchor._ws(base, "partial")
    anchor._reg(partial, [anchor._claim("C-1", promotion_attempts=1)])
    anchor._ts(partial, anchor._pq("[]"))
    anchor._analysis(partial, "C-1", covers_attempt=1,
                     validated_capability="frida works", identified_obstacle="")
    full = anchor._ws(base, "full")
    anchor._reg(full, [anchor._claim("C-1", promotion_attempts=1)])
    anchor._ts(full, anchor._pq("[]"))
    anchor._analysis(full, "C-1", covers_attempt=1,
                     validated_capability="frida works",
                     identified_obstacle="vm network blocked")
    assert PRED[Event.FAILURE_ARTIFACTS_DUE](_decide_inputs(partial)) is True
    assert PRED[Event.FAILURE_ARTIFACTS_DUE](_decide_inputs(full)) is False


def test_ladder_event_uses_497_marker() -> None:
    """LADDER_EXHAUSTED_BLOCKER keys off the #497 marker: attempts>=3 with an
    empty method-ladder candidates list; fewer attempts → required (climb)."""
    PRED, _decide_inputs = _surface("_EVENT_PREDICATES"), _surface("_decide_inputs")
    Event = _surface("Event")
    base = Path(tempfile.mkdtemp(prefix="sm-497-"))
    ws = anchor._ws(base, "exhausted")
    anchor._reg(ws, [anchor._claim("C-1", blocked=True, promotion_attempts=3)])
    anchor._ts(ws, anchor._pq("[]"))
    anchor._analysis(ws, "C-1", covers_attempt=3,
                     validated_capability="x", identified_obstacle="y", candidates=[])
    assert PRED[Event.LADDER_EXHAUSTED_BLOCKER](_decide_inputs(ws)) is True
    assert PRED[Event.LADDER_REQUIRED_BLOCKER](_decide_inputs(ws)) is False
    ws2 = anchor._ws(base, "climbing")
    anchor._reg(ws2, [anchor._claim("C-1", blocked=True, promotion_attempts=1)])
    anchor._ts(ws2, anchor._pq("[]"))
    assert PRED[Event.LADDER_REQUIRED_BLOCKER](_decide_inputs(ws2)) is True
    assert PRED[Event.LADDER_EXHAUSTED_BLOCKER](_decide_inputs(ws2)) is False


def test_machine_terminates_on_whole_matrix() -> None:
    """Exhaustion: every matrix snapshot lands in a verdict state within the
    step bound (SCHEMA → one stage → verdict = ≤3 transitions)."""
    VERDICTS, _run_machine, _decide_inputs = (
        _surface("VERDICTS"), _surface("_run_machine"), _surface("_decide_inputs"))
    base = Path(tempfile.mkdtemp(prefix="sm-matrix-"))
    for name in sorted(anchor.CASES):
        ws = anchor.build_case(name, base)
        state, action = _run_machine(_decide_inputs(ws))
        assert state in VERDICTS, f"case {name}: machine stuck in {state}"
        assert isinstance(action, str) and action, f"case {name}: empty action"


def test_decide_is_deterministic() -> None:
    base = Path(tempfile.mkdtemp(prefix="sm-det-"))
    for name in ("drain_converged_full", "sched_ladder_exhausted_infra",
                 "sched_unexpected_partials_no_slots"):
        ws = anchor.build_case(name, base)
        first, second = cc.decide(ws), cc.decide(ws)
        assert first == second, f"case {name}: decide() not deterministic"


def test_decision_comes_from_verdict_mapping() -> None:
    """decide()'s (decision, exit_code) must be the VERDICTS lookup of the
    machine's terminal state — no side-channel verdicts."""
    VERDICTS, _run_machine, _decide_inputs = (
        _surface("VERDICTS"), _surface("_run_machine"), _surface("_decide_inputs"))
    base = Path(tempfile.mkdtemp(prefix="sm-verdict-"))
    for name in sorted(anchor.CASES):
        ws = anchor.build_case(name, base)
        d = cc.decide(ws)
        state, _ = _run_machine(_decide_inputs(ws))
        assert (d["decision"], d["exit_code"]) == VERDICTS[state], \
            f"case {name}: decide() verdict disagrees with machine terminal state"


# ------------------------------------------------------- #98 DRAIN worker gates

def _backdate(path: Path, minutes: int) -> None:
    import os
    import time
    old = time.time() - minutes * 60
    os.utime(path, (old, old))


def _mk_inprogress_ws(base: Path, name: str, worker_age_min: int) -> Path:
    """Issue #98 probe shape: all-IN_PROGRESS claim surface (opens==0,
    partials==0 -> SCHEMA routes DRAINED -> DRAIN) + one worker-status file
    with a backdated mtime. `_open_claims` excludes IN_PROGRESS, so this
    workspace has an EMPTY claim face while a worker is live — the exact
    false-CONVERGED window the issue's probe reproduced on dev b1c54b7."""
    ws = anchor._ws(base, name)
    anchor._reg(ws, [anchor._claim("C-1", status="IN_PROGRESS")])
    anchor._ts(ws, anchor._pq("[]"))
    status_file = ws / "runs" / "worker-status-C-1.md"
    status_file.write_text(
        "claim C-1 | step x | status: in-progress\n", encoding="utf-8")
    _backdate(status_file, worker_age_min)
    return ws


def test_drain_stuck_worker_not_converged_98(tmp_path: Path) -> None:
    """#98 probe (the spec): single IN_PROGRESS claim + 35-min-old
    worker-status (STUCK_MINUTES=20). Pre-fix this declared
    CONVERGED / exit 0 / "STOP dispatch; deliver" over live work — the
    DRAIN probe table never consulted worker data. Post-fix: BLOCKED with
    the #595 stuck-worker action (which also frees the claim per #607)."""
    ws = _mk_inprogress_ws(tmp_path, "drain_stuck_98", worker_age_min=35)
    d = cc.decide(ws)
    assert d["decision"] != "CONVERGED", (
        f"#98: decide() declared {d['decision']} over a stuck worker "
        f"(age {d['stuck_workers']})")
    assert d["decision"] == "BLOCKED", \
        f"#98: stuck worker must escalate BLOCKED, got {d['decision']}"
    assert d["exit_code"] == cc.EXIT_BLOCKED
    assert d["stuck_workers"], "#98: stuck data must feed the verdict"
    assert "Stuck worker" in d["action"], \
        f"#98: action must name the stuck workers, got: {d['action'][:200]}"


def test_drain_active_worker_not_converged_98(tmp_path: Path) -> None:
    """#98 (alive leg): a FRESH worker on an otherwise-drained claim surface
    must not read CONVERGED either — work is in flight, so the verdict is
    SATURATED (busy: poll workers, delivery forbidden) rather than BLOCKED
    (which means escalate — nothing is wrong with a healthy worker)."""
    ws = _mk_inprogress_ws(tmp_path, "drain_active_98", worker_age_min=1)
    d = cc.decide(ws)
    assert d["decision"] != "CONVERGED", (
        f"#98: decide() declared {d['decision']} with {d['active_workers']} "
        f"live worker(s) in flight")
    assert d["decision"] == "SATURATED", \
        f"#98: live worker on drained surface must poll (SATURATED), got {d['decision']}"
    assert d["exit_code"] == cc.EXIT_SATURATED
    assert "worker" in d["action"].lower(), \
        f"#98: action must direct polling, got: {d['action'][:200]}"


def test_drain_probe_table_consults_workers_98() -> None:
    """#98: the DRAIN probe table must consult worker data BEFORE the
    DRAIN_CLEAN catch-all (which is always-true, so anything after it can
    never fire). STUCK precedes ACTIVE: a stuck worker is also counted
    active, and its BLOCKED escalation (+ #607 claim reopen) must win over
    the poll verdict."""
    STAGE_PROBES, State, Event = (
        _surface("STAGE_PROBES"), _surface("State"), _surface("Event"))
    assert STAGE_PROBES and State and Event
    drain = STAGE_PROBES[State.DRAIN]
    assert Event.STUCK_WORKERS_PRESENT in drain, \
        "#98: DRAIN has no stuck-worker predicate (root cause)"
    assert Event.ACTIVE_WORKERS_PRESENT in drain, \
        "#98: DRAIN has no active-worker predicate"
    stuck_idx = drain.index(Event.STUCK_WORKERS_PRESENT)
    active_idx = drain.index(Event.ACTIVE_WORKERS_PRESENT)
    clean_idx = drain.index(Event.DRAIN_CLEAN)
    assert stuck_idx < active_idx < clean_idx, (
        f"#98: DRAIN worker gates must sit stuck<active<DRAIN_CLEAN, "
        f"got stuck={stuck_idx} active={active_idx} clean={clean_idx}")


def test_drain_worker_transition_rows_98() -> None:
    """#98: the two new DRAIN rows bind stuck -> BLOCKED (sharing the #595
    action builder with the SCHEDULE row — one stuck semantics, two stages)
    and active -> SATURATED with a poll action."""
    TRANSITIONS, State, Event = (
        _surface("TRANSITIONS"), _surface("State"), _surface("Event"))
    assert TRANSITIONS and State and Event
    stuck_row = TRANSITIONS[(State.DRAIN, Event.STUCK_WORKERS_PRESENT)]
    sched_stuck = TRANSITIONS[(State.SCHEDULE, Event.STUCK_WORKERS_PRESENT)]
    assert stuck_row[0] is State.BLOCKED, \
        f"#98: DRAIN stuck must land BLOCKED, got {stuck_row[0]}"
    assert stuck_row[1] is sched_stuck[1], \
        "#98: DRAIN and SCHEDULE stuck rows must share one #595 action builder"
    active_row = TRANSITIONS[(State.DRAIN, Event.ACTIVE_WORKERS_PRESENT)]
    assert active_row[0] is State.SATURATED, \
        f"#98: DRAIN active-worker must land SATURATED, got {active_row[0]}"


def test_active_workers_present_predicate_98(tmp_path: Path) -> None:
    """#98: the new predicate reads the snapshot's worker count — true iff a
    worker is alive (this is the data the DRAIN table used to ignore)."""
    PRED, Event, _decide_inputs = (
        _surface("_EVENT_PREDICATES"), _surface("Event"), _surface("_decide_inputs"))
    assert PRED and Event and _decide_inputs
    pred = PRED[Event.ACTIVE_WORKERS_PRESENT]
    live = _mk_inprogress_ws(tmp_path, "pred_live", worker_age_min=1)
    assert pred(_decide_inputs(live)) is True
    quiet = anchor._ws(tmp_path, "pred_quiet")
    anchor._reg(quiet, [])
    anchor._ts(quiet, anchor._pq("[]"))
    assert pred(_decide_inputs(quiet)) is False
