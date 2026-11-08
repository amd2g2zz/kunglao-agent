# -*- coding: utf-8 -*-
"""Rollout-timer host wiring: dispatch arm, round-close cancel+learn,
deadline wake, and the wake-state contract surface.

The policy core (rlvr.rollout_timer) is pure; these pins cover the
production host faces around it:

  - the dispatch-commit face arms the rollout's one-shot timer with the
    claim's kind + difficulty family and publishes the wake contract;
  - the round-closure face cancels the finished rollout's timer and
    learns its outcome from the run's actuals (a deadline-fired rollout
    is censored: cancel only, never learn);
  - the one-shot deadline wake fires, records the settlement-facing
    deadline stop, cancels, learns the timeout, and never starts a
    rollout.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for _p in (SCRIPTS, SCRIPTS.parent / "tests", ROOT / "hooks"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import claims_store as claims_store  # noqa: E402
import rlvr.consolidated_ledger as ledger  # noqa: E402
import rlvr.rollout_timer as rollout_timer  # noqa: E402
import rlvr.rollout_timer_host as timer_host  # noqa: E402

from _factories import seed_difficulty, write_claims_register  # noqa: E402

NOW = datetime(2026, 11, 8, 9, 0, 0, tzinfo=timezone.utc)
WAKE_FILE = Path("runs") / "rollout-timer-wake.json"


@pytest.fixture
def ws(tmp_path) -> Path:
    workspace = tmp_path / "ws"
    (workspace / "runs").mkdir(parents=True)
    write_claims_register(workspace, [
        {"id": "C-1", "status": "OPEN"},
        {"id": "C-2", "status": "OPEN"},
    ])
    return workspace


def _dispatch(ws, claim: str, *, method_family: str | None = None):
    result = claims_store.begin_dispatch(
        ws, claim, actor="test", method_family=method_family)
    assert result.ok, result.reason
    committed = claims_store.commit_dispatch(ws, claim)
    assert committed.ok, committed.reason
    # the gate chain's rc=0 face: clears the journal slot for the next
    # dispatch (a committed journal answers intent-in-flight otherwise)
    assert claims_store.confirm_dispatch(ws, claim) is True
    return committed


def _timer_rows(ws) -> list[dict]:
    return ledger.read(ws, "telemetry",
                       schema_prefix=rollout_timer.TIMER_SCHEMA)


def _budget_rows(ws) -> list[dict]:
    return ledger.read(ws, "telemetry",
                       schema_prefix=rollout_timer.BUDGET_SCHEMA)


def _folded(ws, rollout_id: str):
    return rollout_timer.timer_state(ws, rollout_id)


def _wake_map(ws) -> dict:
    """The wake publish face: a map keyed by rollout_id (absent file ->
    empty)."""
    p = ws / WAKE_FILE
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


# ---------- the dispatch-commit arm face ----------

def test_dispatch_commit_arms_the_rollout_timer(ws):
    committed = _dispatch(ws, "C-1")
    rows = _timer_rows(ws)
    assert len(rows) == 1
    row = rows[0]
    assert row["state"] == "armed"
    assert row["rollout_id"] == committed.journal_id
    assert row["claim"] == "C-1"
    assert row["kind"] == "claim"
    assert row["difficulty"] == "hard"  # no feed: the fail-closed tier
    assert row["bucket_key"] == "claim/hard"

    wake = _wake_map(ws)[committed.journal_id]
    assert wake["rollout_id"] == committed.journal_id
    assert wake["once"] is True
    fields = wake["cron"].split()
    assert len(fields) == 5
    minute, hour, day, month = (int(f) for f in fields[:4])
    assert minute not in (0, 30)  # off the early-fire window
    assert 1 <= day <= 31 and 1 <= month <= 12  # one-shot, not */5
    assert wake["may_start_rollout"] is False


def test_dispatch_carries_method_family_and_difficulty_feed(ws):
    seed_difficulty(ws, "easy")
    committed = _dispatch(ws, "C-1", method_family="static")
    row = _timer_rows(ws)[0]
    assert row["rollout_id"] == committed.journal_id
    assert row["kind"] == "static"
    assert row["difficulty"] == "easy"
    assert row["bucket_key"] == "static/easy"


def test_an_aborted_intent_arms_nothing(ws):
    begun = claims_store.begin_dispatch(ws, "C-1", actor="test")
    assert begun.ok
    claims_store.abort_dispatch(ws, "C-1", actor="test")
    assert _timer_rows(ws) == []
    assert not (ws / WAKE_FILE).exists()


def test_a_failed_commit_arms_nothing(ws):
    # no intent journal: the commit face fails before any step lands
    failed = claims_store.commit_dispatch(ws, "C-1")
    assert failed.ok is False
    assert _timer_rows(ws) == []
    assert not (ws / WAKE_FILE).exists()


def test_an_in_flight_claim_gains_no_second_timer(ws):
    first = _dispatch(ws, "C-1")
    again = claims_store.begin_dispatch(ws, "C-1", actor="test")
    assert again.ok is True  # the confirmed journal slot is free again
    flipped = claims_store.commit_dispatch(ws, "C-1")
    assert flipped.ok is False  # the register refuses an in-flight claim
    assert len({r["rollout_id"] for r in _timer_rows(ws)}) == 1
    assert _timer_rows(ws)[0]["rollout_id"] == first.journal_id


def test_the_timer_face_never_breaks_an_approved_dispatch(ws, monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("timer host unavailable")

    monkeypatch.setattr(timer_host, "arm_for_dispatch", _boom)
    committed = _dispatch(ws, "C-1")
    assert committed.ok is True
    assert committed.to_status == "IN_PROGRESS"
    assert _timer_rows(ws) == []  # the arm failed open, the dispatch stood


# ---------- the round-closure cancel + learn face ----------

def test_round_close_cancels_and_learns_an_early_finish(ws):
    committed = _dispatch(ws, "C-1")
    assert (ws / WAKE_FILE).exists()
    receipt = timer_host.round_close_face(ws, {
        "claim": "C-1", "outcome": "completed",
        "duration_ms": 12 * 60000, "wall_s": 720,
    })
    assert receipt["canceled"] is True
    assert receipt["learned"] is True
    assert receipt["censored"] is False
    state = _folded(ws, committed.journal_id)
    assert state["state"] == "canceled"
    budget_rows = _budget_rows(ws)
    assert len(budget_rows) == 1
    row = budget_rows[0]
    assert row["outcome"] == "early"
    assert row["actual_min"] == 12.0
    assert row["coeff_before"] == 1.0
    assert row["coeff_after"] == 0.9
    assert "early" in row["reason"]
    assert row["budget_min"] == 30.0
    assert row["rollout_id"] == committed.journal_id
    assert not (ws / WAKE_FILE).exists()  # no wake remains


def test_round_close_classifies_an_on_time_finish(ws):
    committed = _dispatch(ws, "C-1")
    timer_host.round_close_face(ws, {
        "claim": "C-1", "outcome": "completed",
        "duration_ms": 25 * 60000, "wall_s": 1500,
    })
    row = _budget_rows(ws)[0]
    assert row["outcome"] == "on_time"
    assert row["coeff_after"] == 0.98


def test_round_close_classifies_a_completed_over_budget_run_as_no_update(ws):
    committed = _dispatch(ws, "C-1")
    receipt = timer_host.round_close_face(ws, {
        "claim": "C-1", "outcome": "completed",
        "duration_ms": 40 * 60000, "wall_s": 2400,
    })
    assert receipt["learned"] is False
    row = _budget_rows(ws)[0]
    assert row["updated"] is False
    assert row["coeff_after"] == 1.0


def test_round_close_maps_a_failed_worker_to_no_update(ws):
    _dispatch(ws, "C-1")
    receipt = timer_host.round_close_face(ws, {
        "claim": "C-1", "outcome": "failed",
        "duration_ms": 10 * 60000, "wall_s": 600,
    })
    assert receipt["canceled"] is True
    row = _budget_rows(ws)[0]
    assert row["outcome"] == "aborted"
    assert row["updated"] is False
    assert row["coeff_after"] == 1.0
    assert "aborted" in row["reason"]


def test_round_close_without_a_duration_cancels_but_never_guesses(ws):
    _dispatch(ws, "C-1")
    receipt = timer_host.round_close_face(ws, {
        "claim": "C-1", "outcome": "completed",
        "duration_ms": None, "wall_s": None,
    })
    assert receipt["canceled"] is True
    assert receipt["learned"] is False
    assert _budget_rows(ws) == []


def test_round_close_for_a_claim_without_a_timer_is_silent(ws):
    assert timer_host.round_close_face(ws, {
        "claim": "C-2", "outcome": "completed",
        "duration_ms": 60000, "wall_s": 60,
    }) is None
    assert _timer_rows(ws) == []
    assert _budget_rows(ws) == []


def test_a_deadline_fired_rollout_is_censored_from_learning(ws):
    committed = _dispatch(ws, "C-1")
    deadline = datetime.strptime(
        _folded(ws, committed.journal_id)["deadline_ts"],
        rollout_timer._TS_FORMAT).replace(tzinfo=timezone.utc)
    timer_host.deadline_wake_face(ws, committed.journal_id, now=deadline)
    receipt = timer_host.round_close_face(ws, {
        "claim": "C-1", "outcome": "completed",  # a late finish
        "duration_ms": 40 * 60000, "wall_s": 2400,
    })
    assert receipt["censored"] is True
    assert receipt["learned"] is False
    budget_rows = _budget_rows(ws)
    assert len(budget_rows) == 1  # only the wake's timeout audit row
    assert budget_rows[0]["outcome"] == "timeout"
    state = _folded(ws, committed.journal_id)
    assert state["state"] == "canceled"
    assert state["stop_reason"] == "deadline"
    assert not (ws / WAKE_FILE).exists()


# ---------- the one-shot deadline wake face ----------

def test_the_deadline_wake_fires_records_cancels_and_learns(ws):
    committed = _dispatch(ws, "C-1")
    rid = committed.journal_id
    deadline = datetime.strptime(
        _folded(ws, rid)["deadline_ts"],
        rollout_timer._TS_FORMAT).replace(tzinfo=timezone.utc)
    receipt = timer_host.deadline_wake_face(ws, rid, now=deadline)
    assert receipt["stop"]["stop_reason"] == "deadline"
    assert receipt["stop"]["excluded_from_strategy_learning"] is True
    assert receipt["stop"]["claim"] == "C-1"
    assert receipt["stop"]["budget_min"] == 30.0
    assert receipt["learned"] is True
    assert receipt["canceled"] is True

    state = _folded(ws, rid)
    assert state["state"] == "canceled"  # fired, then wrap-up cleanup
    assert state["fired_ts"] == deadline.strftime(
        rollout_timer._TS_FORMAT)
    assert state["stop_reason"] == "deadline"

    budget_rows = _budget_rows(ws)
    assert len(budget_rows) == 1
    row = budget_rows[0]
    assert row["outcome"] == "timeout"
    assert row["coeff_before"] == 1.0
    assert row["coeff_after"] == 1.25
    assert row["completed"] is False

    wake = _wake_map(ws)[rid]
    assert wake["kind"] == "graceful-stop"
    assert wake["stop"]["stop_reason"] == "deadline"
    assert wake["may_start_rollout"] is False


def test_the_wake_refuses_a_pre_deadline_fire(ws):
    committed = _dispatch(ws, "C-1")
    deadline = datetime.strptime(
        _folded(ws, committed.journal_id)["deadline_ts"],
        rollout_timer._TS_FORMAT).replace(tzinfo=timezone.utc)
    receipt = timer_host.deadline_wake_face(
        ws, committed.journal_id, now=deadline - timedelta(minutes=5))
    assert receipt is None
    assert _folded(ws, committed.journal_id)["state"] == "armed"
    assert _budget_rows(ws) == []


def test_the_wake_refuses_an_already_canceled_timer(ws):
    committed = _dispatch(ws, "C-1")
    timer_host.round_close_face(ws, {
        "claim": "C-1", "outcome": "completed",
        "duration_ms": 60000, "wall_s": 60,
    })
    assert timer_host.deadline_wake_face(
        ws, committed.journal_id,
        now=NOW + timedelta(minutes=60)) is None
    fired = [r for r in _timer_rows(ws) if r.get("state") == "fired"]
    assert fired == []


def test_the_wake_cli_executes_the_contract(ws):
    committed = _dispatch(ws, "C-1")
    rid = committed.journal_id
    deadline = datetime.strptime(
        _folded(ws, rid)["deadline_ts"],
        rollout_timer._TS_FORMAT).replace(tzinfo=timezone.utc)
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "rollout_timer_wake.py"),
         str(ws), "--wake", rid, "--now", deadline.strftime(
             rollout_timer._TS_FORMAT)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout)
    assert receipt["stop"]["stop_reason"] == "deadline"
    assert receipt["learned"] is True
    assert _folded(ws, rid)["state"] == "canceled"
    assert _budget_rows(ws)[0]["outcome"] == "timeout"

    # a canceled-NEVER-fired timer refuses the wake outright
    second = _dispatch(ws, "C-2")
    timer_host.round_close_face(ws, {
        "claim": "C-2", "outcome": "completed",
        "duration_ms": 60000, "wall_s": 60,
    })
    canceled_id = second.journal_id

    refused = subprocess.run(
        [sys.executable, str(SCRIPTS / "rollout_timer_wake.py"),
         str(ws), "--wake", canceled_id],
        capture_output=True, text=True, timeout=120)
    assert refused.returncode == 3  # canceled, never fired: nothing to fire


# ---------- the wrap-up prompt contract ----------

_STEPS_ORDER = (r"persist evidence[\s\S]*settle[\s\S]*cancel[\s\S]*"
                r"update coefficient[\s\S]*arm")
_FORBIDDEN_STARTS = (
    r"start a new rollout", r"begin a new rollout",
    r"dispatch a new claim", r"you may start",
    r"launch a (new )?rollout", r"resume a new rollout",
)


def _assert_wrap_up_contract(prompt: str) -> None:
    assert re.search(_STEPS_ORDER, prompt), prompt
    lowered = prompt.lower()
    for pattern in _FORBIDDEN_STARTS:
        assert not re.search(pattern, lowered), pattern


def test_the_armed_wake_contract_only_wraps_up(ws):
    committed = _dispatch(ws, "C-1")
    wake = _wake_map(ws)[committed.journal_id]
    assert wake["steps"] == list(rollout_timer.GRACEFUL_STEPS)
    assert wake["may_start_rollout"] is False
    _assert_wrap_up_contract(wake["prompt"])


def test_the_stop_contract_only_wraps_up(ws):
    committed = _dispatch(ws, "C-1")
    deadline = datetime.strptime(
        _folded(ws, committed.journal_id)["deadline_ts"],
        rollout_timer._TS_FORMAT).replace(tzinfo=timezone.utc)
    timer_host.deadline_wake_face(ws, committed.journal_id, now=deadline)
    wake = _wake_map(ws)[committed.journal_id]
    assert wake["steps"] == list(rollout_timer.GRACEFUL_STEPS)
    _assert_wrap_up_contract(wake["prompt"])


# ---------- cold start, the continuous run, the bucket floor ----------

def test_cold_start_uses_the_thirty_minute_default(ws):
    committed = _dispatch(ws, "C-1")
    row = _timer_rows(ws)[0]
    assert row["base_min"] == rollout_timer.DEFAULT_BASE_MIN
    assert row["coeff"] == rollout_timer.DEFAULT_COEFF
    assert row["budget_min"] == 30.0
    assert row["rollout_id"] == committed.journal_id


def test_one_continuous_run_arms_learns_and_arms_the_next(ws):
    first = _dispatch(ws, "C-1")
    timer_host.round_close_face(ws, {
        "claim": "C-1", "outcome": "completed",
        "duration_ms": 12 * 60000, "wall_s": 720,
    })
    second = _dispatch(ws, "C-2")
    ids = {r["rollout_id"] for r in _timer_rows(ws)}
    assert len(ids) == 2  # two rollouts, each with its append-only rows
    assert first.journal_id in ids and second.journal_id in ids
    first_fold = _folded(ws, first.journal_id)
    second_fold = _folded(ws, second.journal_id)
    assert first_fold["state"] == "canceled"
    assert second_fold["state"] == "armed"
    assert second_fold["coeff"] == 0.9  # the learned chain carries over
    assert second_fold["base_min"] == 12.0  # the family median learned
    assert second_fold["budget_min"] == 15.0  # 12 x 0.9 clamps to the floor
    # every deadline this run produced was one-shot, off :00/:30 (never */5)
    for row in _timer_rows(ws):
        moment = datetime.strptime(row["deadline_ts"],
                                   rollout_timer._TS_FORMAT).replace(
            tzinfo=timezone.utc)
        cron = rollout_timer.deadline_cron(moment).split()
        assert int(cron[0]) not in (0, 30)  # the early-fire window
        assert cron[4] == "*" and all(f != "*" for f in cron[:4])


def test_no_bucket_split_below_the_sample_floor(ws):
    for _index in range(rollout_timer.BUCKET_SAMPLE_THRESHOLD):
        _dispatch(ws, "C-1")
        timer_host.round_close_face(ws, {
            "claim": "C-1", "outcome": "completed",
            "duration_ms": 12 * 60000, "wall_s": 720,
        })
        write_claims_register(ws, [{"id": "C-1", "status": "OPEN"}])
    committed = _dispatch(ws, "C-1")
    row = _timer_rows(ws)[-1]
    assert row["rollout_id"] == committed.journal_id
    assert row["bucket_key"] == "claim/hard"
    # split-ready by now, yet still the ONE global coefficient chain —
    # the bucket split is a later card, the host never pre-empts it
    budget_rows = _budget_rows(ws)
    assert len(budget_rows) >= rollout_timer.BUCKET_SAMPLE_THRESHOLD
    assert row["coeff"] == budget_rows[-1]["coeff_after"]
    prev_after = None
    for budget_row in budget_rows:
        if prev_after is not None:
            assert budget_row["coeff_before"] == prev_after  # one chain
        prev_after = budget_row["coeff_after"]
    assert {r["bucket_key"] for r in budget_rows} == {"claim/hard"}


def test_timer_state_read_face(ws):
    committed = _dispatch(ws, "C-1")
    assert _folded(ws, committed.journal_id)["state"] == "armed"
    assert _folded(ws, "missing-rollout") is None


# ---------- the review pins (clobber, recovery, race, censor bias) ----------

def test_two_armed_rollouts_do_not_clobber_each_others_wake(ws):
    first = _dispatch(ws, "C-1")
    second = _dispatch(ws, "C-2")
    wake_map = _wake_map(ws)
    assert set(wake_map) == {first.journal_id, second.journal_id}
    # the first rollout fires and wraps up: the second's unconsumed
    # contract survives — a clear removes only its own key
    deadline = datetime.strptime(
        _folded(ws, first.journal_id)["deadline_ts"],
        rollout_timer._TS_FORMAT).replace(tzinfo=timezone.utc)
    timer_host.deadline_wake_face(ws, first.journal_id, now=deadline)
    timer_host.round_close_face(ws, {
        "claim": "C-1", "outcome": "failed",
        "duration_ms": None, "wall_s": None,
    })
    wake_map = _wake_map(ws)
    assert set(wake_map) == {second.journal_id}
    assert wake_map[second.journal_id]["once"] is True
    assert _folded(ws, second.journal_id)["state"] == "armed"


def test_recover_after_commit_cancels_the_armed_timer(ws, monkeypatch):
    claims_store.begin_dispatch(ws, "C-1", actor="test")
    committed = claims_store.commit_dispatch(ws, "C-1")
    assert committed.ok is True
    rid = committed.journal_id
    assert _folded(ws, rid)["state"] == "armed"
    # the owner died before confirm_dispatch: the next store open
    # inverts the committed journal — the dispatch never happened, so
    # the timer must not survive it (cancel only, never a phantom learn)
    monkeypatch.setattr(claims_store, "_pid_alive", lambda pid: False)
    recovered = claims_store.recover(ws)
    assert recovered and recovered[0].ok is True
    state = _folded(ws, rid)
    assert state["state"] == "canceled"
    assert "recovered" in state["cancel_reason"]
    assert _budget_rows(ws) == []
    assert "OPEN" in (ws / "claim-register.yaml").read_text(
        encoding="utf-8")  # the register flip is undone


def test_round_close_bails_to_the_censor_path_when_the_wake_flips(
        ws, monkeypatch):
    committed = _dispatch(ws, "C-1")
    real_timer_state = rollout_timer.timer_state
    calls = {"n": 0}

    def _fire_after_first(workspace, rollout_id):
        calls["n"] += 1
        state = real_timer_state(workspace, rollout_id)
        if calls["n"] == 1:
            return state  # the decide read: not yet fired
        return {**(state or {}), "fired_ts": "x"}  # the wake flipped it

    monkeypatch.setattr(rollout_timer, "timer_state", _fire_after_first)
    receipt = timer_host.round_close_face(ws, {
        "claim": "C-1", "outcome": "completed",
        "duration_ms": 12 * 60000, "wall_s": 720,
    })
    assert calls["n"] == 2  # decide, then the immediate re-check
    assert receipt["censored"] is True
    assert receipt["learned"] is False
    assert _budget_rows(ws) == []  # the spurious timeout never lands


def test_a_timeout_heavy_history_does_not_inflate_the_median():
    def _row(rollout_id, outcome, actual):
        return {"schema": "rollout-budget/1", "rollout_id": rollout_id,
                "kind": "claim", "difficulty": "hard", "outcome": outcome,
                "actual_min": actual}

    # timeouts are right-censored (their recorded actual is the budget):
    # they must never feed the family median...
    censored_only = [_row("t-one", "timeout", 200.0),
                     _row("t-two", "timeout", 240.0)]
    assert rollout_timer.base_estimate(
        censored_only, kind="claim",
        difficulty="hard") == rollout_timer.DEFAULT_BASE_MIN
    # ...while the observed completions still do
    mixed = censored_only + [_row("d-one", "on_time", 20.0),
                             _row("d-two", "on_time", 40.0)]
    assert rollout_timer.base_estimate(
        mixed, kind="claim", difficulty="hard") == 30.0


# ---------- the hook delegation ----------

def test_the_round_closure_hook_delegates_to_the_timer_face(ws, monkeypatch):
    import round_closure

    seen: list = []
    monkeypatch.setattr(
        timer_host, "round_close_face",
        lambda _ws, receipt: (seen.append(receipt), None)[1])
    payload = {"cwd": str(ws), "session_id": "sess-1",
               "agent_id": "agent-1", "transcript_path": ""}
    assert round_closure.process_event(payload) == 0
    assert len(seen) == 1  # the closure face ran with the settle receipt
