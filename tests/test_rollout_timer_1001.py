# -*- coding: utf-8 -*-
"""Rollout timer: learned deadline arm/cancel/fire, coefficient learning.

The timer is a per-rollout one-shot wake: `arm` persists a
`rollout-timer/1` row plus the one-shot wake contract, `cancel` retires
an early finish, `fire` records the deadline and returns the graceful-stop
contract, and `learn` moves ONE global coefficient inside its bounds and
audits every decision as a `rollout-budget/1` row. Pure policy helpers
carry no clock and no I/O.
"""
from __future__ import annotations

import multiprocessing
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rlvr import consolidated_ledger as ledger
from rlvr import rollout_timer as timer

NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def ws(tmp_path) -> Path:
    workspace = tmp_path / "ws"
    (workspace / "runs").mkdir(parents=True)
    return workspace


def _arm(ws, rollout_id="r-1", *, now=NOW, base=30.0, kind="claim",
         difficulty="hard"):
    return timer.arm(ws, rollout_id, claim="C-1", kind=kind,
                     difficulty=difficulty, now=now,
                     base_estimate_min=base)


def _seed_budget_row(ws, *, coeff_after=1.0, actual=30.0, outcome="on_time",
                     kind="claim", difficulty="hard"):
    ledger.append(ws, "telemetry", {
        "schema": "rollout-budget/1",
        "rollout_id": "seed",
        "claim": "C-seed",
        "kind": kind,
        "difficulty": difficulty,
        "bucket_key": timer.bucket_key(kind, difficulty),
        "base_min": 30.0,
        "coeff_before": 1.0,
        "budget_min": 30.0,
        "actual_min": actual,
        "completed": outcome == "on_time",
        "outcome": outcome,
        "coeff_after": coeff_after,
        "updated": True,
        "reason": "seed",
        "policy_ref": timer.POLICY_REF,
        "ts": "2026-11-05T11:00:00Z",
    })


# ---------- arm ----------

def test_arm_persists_timer_row_and_one_shot_wake(ws):
    result = _arm(ws)
    row = result["row"]
    assert row["schema"] == "rollout-timer/1"
    assert row["state"] == "armed"
    assert row["rollout_id"] == "r-1"
    assert row["claim"] == "C-1"
    assert row["armed_ts"] == "2026-11-05T12:00:00Z"
    assert row["deadline_ts"] == "2026-11-05T12:30:00Z"
    assert row["base_min"] == 30.0
    assert row["coeff"] == 1.0
    assert row["budget_min"] == 30.0
    assert row["bucket_key"] == "claim/hard"
    assert row["policy_ref"] == timer.POLICY_REF

    wake = result["wake"]
    assert wake["kind"] == "one-shot-deadline"
    assert wake["once"] is True
    assert wake["cron"] == "31 12 5 11 *"  # :30 is the early-fire window
    assert wake["deadline_ts"] == row["deadline_ts"]
    assert wake["may_start_rollout"] is False
    assert wake["steps"] == [
        "persist_evidence", "settle", "cancel_timer",
        "update_coefficient", "arm_next_timer",
    ]
    assert ledger.read(ws, "telemetry",
                       schema_prefix="rollout-timer/") == [row]


def test_arm_cron_avoids_the_half_hour_window_and_rolls_forward(ws):
    on_the_hour = _arm(ws, "r-hour", base=60.0)
    assert on_the_hour["row"]["deadline_ts"] == "2026-11-05T13:00:00Z"
    assert on_the_hour["wake"]["cron"] == "1 13 5 11 *"

    quarter = _arm(ws, "r-quarter", base=45.0)
    assert quarter["row"]["deadline_ts"] == "2026-11-05T12:45:00Z"
    assert quarter["wake"]["cron"] == "45 12 5 11 *"


def test_budget_clamps_to_floor_and_ceiling(ws):
    assert timer.budget_minutes(0.0, 1.0) == 15.0
    assert timer.budget_minutes(1.0, 1.0) == 15.0
    assert timer.budget_minutes(1000.0, 4.0) == 480.0
    assert _arm(ws, "r-zero", base=0.0)["row"]["budget_min"] == 15.0
    assert _arm(ws, "r-low", base=1.0)["row"]["budget_min"] == 15.0
    assert _arm(ws, "r-high", base=1000.0)["row"]["budget_min"] == 480.0


def test_a_zero_median_history_clamps_instead_of_crashing(ws):
    _arm(ws, "r-first", base=30.0)
    timer.learn(ws, "r-first", actual_min=0.0, completed=True,
                outcome="early")
    result = _arm(ws, "r-second", base=None)
    assert result["row"]["base_min"] == 0.0
    assert result["row"]["budget_min"] == 15.0


def test_base_estimate_median_cold_start_and_family_filter():
    rows = [
        {"schema": "rollout-budget/1", "kind": "claim",
         "difficulty": "hard", "actual_min": 20, "outcome": "on_time"},
        {"schema": "rollout-budget/1", "kind": "claim",
         "difficulty": "hard", "actual_min": 40, "outcome": "on_time"},
        {"schema": "rollout-budget/1", "kind": "claim",
         "difficulty": "hard", "actual_min": 60, "outcome": "on_time"},
    ]
    assert timer.base_estimate(rows, kind="claim",
                               difficulty="hard") == 40.0
    assert timer.base_estimate([], kind="claim",
                               difficulty="hard") == timer.DEFAULT_BASE_MIN
    assert timer.base_estimate(rows, kind="claim",
                               difficulty="easy") == timer.DEFAULT_BASE_MIN
    noisy = rows + [{"schema": "rollout-budget/1", "kind": "claim",
                     "difficulty": "hard", "actual_min": 999,
                     "outcome": "infra"}]
    assert timer.base_estimate(noisy, kind="claim",
                               difficulty="hard") == 40.0


def test_arm_uses_history_median_and_the_current_global_coefficient(ws):
    for actual in (20, 40, 60):
        _seed_budget_row(ws, coeff_after=1.25, actual=actual)
    result = _arm(ws, "r-history", base=None)
    assert result["row"]["base_min"] == 40.0
    assert result["row"]["coeff"] == 1.25
    assert result["row"]["budget_min"] == 50.0


def test_arm_is_idempotent_while_the_timer_is_armed(ws):
    first = _arm(ws)
    second = timer.arm(ws, "r-1", claim="C-1", kind="claim",
                       difficulty="hard",
                       now=NOW + timedelta(minutes=3),
                       base_estimate_min=30.0)
    assert second["idempotent"] is True
    assert second["row"] == first["row"]
    assert len(ledger.read(ws, "telemetry",
                           schema_prefix="rollout-timer/")) == 1
    with pytest.raises(ValueError):
        timer.arm(ws, "r-1", claim="C-1", kind="claim", difficulty="easy",
                  now=NOW, base_estimate_min=30.0)


# ---------- cancel ----------

def test_cancel_is_idempotent_and_a_canceled_timer_never_fires(ws):
    _arm(ws)
    canceled = timer.cancel(ws, "r-1", now=NOW + timedelta(minutes=5),
                            reason="early finish")
    assert canceled["canceled"] is True
    assert canceled["idempotent"] is False
    assert canceled["row"]["state"] == "canceled"
    assert canceled["row"]["canceled_ts"] == "2026-11-05T12:05:00Z"
    assert canceled["row"]["cancel_reason"] == "early finish"

    again = timer.cancel(ws, "r-1", now=NOW + timedelta(minutes=6),
                         reason="early finish")
    assert again["idempotent"] is True
    assert again["row"]["canceled_ts"] == "2026-11-05T12:05:00Z"

    fired = timer.fire(ws, "r-1", now=NOW + timedelta(minutes=31))
    assert fired["fired"] is False
    assert fired["reason"] == "canceled"
    assert len(ledger.read(ws, "telemetry",
                           schema_prefix="rollout-timer/")) == 2


def test_cancel_requires_a_reason(ws):
    _arm(ws)
    with pytest.raises(ValueError):
        timer.cancel(ws, "r-1", now=NOW, reason="   ")


# ---------- fire ----------

def test_fire_marks_the_deadline_and_returns_the_graceful_stop_contract(ws):
    _arm(ws)
    fired = timer.fire(ws, "r-1", now=NOW + timedelta(minutes=30))
    assert fired["fired"] is True
    assert fired["row"]["state"] == "fired"
    assert fired["row"]["fired_ts"] == "2026-11-05T12:30:00Z"
    assert fired["row"]["stop_reason"] == "deadline"
    assert fired["row"]["excluded_from_strategy_learning"] is True
    contract = fired["contract"]
    assert contract["kind"] == "graceful-stop"
    assert contract["steps"] == [
        "persist_evidence", "settle", "cancel_timer",
        "update_coefficient", "arm_next_timer",
    ]
    assert contract["may_start_rollout"] is False

    again = timer.fire(ws, "r-1", now=NOW + timedelta(minutes=40))
    assert again["idempotent"] is True
    assert len(ledger.read(ws, "telemetry",
                           schema_prefix="rollout-timer/")) == 2


def test_fire_refuses_a_wake_well_before_the_deadline(ws):
    _arm(ws)  # deadline 12:30
    with pytest.raises(ValueError):
        timer.fire(ws, "r-1", now=NOW)
    # the scheduler may fire up to 90 seconds early; 60 seconds is legal
    fired = timer.fire(ws, "r-1", now=NOW + timedelta(minutes=29))
    assert fired["fired"] is True


def test_fire_prompt_only_wraps_up_and_never_authorizes_a_new_rollout(ws):
    _arm(ws)
    fired = timer.fire(ws, "r-1", now=NOW + timedelta(minutes=30))
    prompt = fired["contract"]["prompt"].lower()
    for step in ("persist evidence", "settle", "cancel", "learn",
                 "arm"):
        assert step in prompt
    assert "no new rollout" in prompt
    for phrase in ("start a new rollout", "begin a new rollout",
                   "dispatch a new claim", "you may start",
                   "launch a rollout", "resume a new rollout"):
        assert phrase not in prompt
    assert fired["contract"]["may_start_rollout"] is False


# ---------- learn: coefficient matrix ----------

def test_learn_early_multiplies_by_0_9_and_audits(ws):
    _arm(ws, base=100.0)
    result = timer.learn(ws, "r-1", actual_min=50.0, completed=True,
                         outcome="early")
    assert result["updated"] is True
    assert result["coeff_after"] == 0.9
    row = result["row"]
    assert row["schema"] == "rollout-budget/1"
    assert row["base_min"] == 100.0
    assert row["coeff_before"] == 1.0
    assert row["budget_min"] == 100.0
    assert row["actual_min"] == 50.0
    assert row["outcome"] == "early"
    assert row["coeff_after"] == 0.9
    assert "early" in row["reason"]
    assert row["ts"].endswith("Z")


def test_learn_timeout_multiplies_by_1_25_after_the_deadline_fires(ws):
    _arm(ws, base=100.0)
    timer.fire(ws, "r-1", now=NOW + timedelta(minutes=100))
    result = timer.learn(ws, "r-1", actual_min=100.0, completed=False,
                         outcome="timeout")
    assert result["updated"] is True
    assert result["coeff_after"] == 1.25
    assert "timeout" in result["row"]["reason"]


def test_learn_on_time_multiplies_by_0_98(ws):
    _arm(ws, base=100.0)
    result = timer.learn(ws, "r-1", actual_min=90.0, completed=True,
                         outcome="on_time")
    assert result["updated"] is True
    assert result["coeff_after"] == 0.98


def test_learn_on_time_refuses_an_early_band_duration(ws):
    _arm(ws, base=100.0)
    result = timer.learn(ws, "r-1", actual_min=10.0, completed=True,
                         outcome="on_time")
    assert result["updated"] is False
    assert result["coeff_after"] == 1.0
    assert "early band" in result["row"]["reason"]


def test_a_fired_deadline_cannot_be_laundered_into_a_shrink(ws):
    _arm(ws, "r-on", base=100.0)
    timer.fire(ws, "r-on", now=NOW + timedelta(minutes=100))
    on_time = timer.learn(ws, "r-on", actual_min=90.0, completed=True,
                          outcome="on_time")
    assert on_time["updated"] is False
    assert "unfired deadline" in on_time["row"]["reason"]

    _arm(ws, "r-early", base=100.0)
    timer.fire(ws, "r-early", now=NOW + timedelta(minutes=100))
    early = timer.learn(ws, "r-early", actual_min=10.0, completed=True,
                        outcome="early")
    assert early["updated"] is False
    assert "unfired deadline" in early["row"]["reason"]


def test_learn_infra_and_aborted_do_not_update_the_coefficient(ws):
    for index, outcome in enumerate(("infra", "aborted")):
        rollout_id = f"r-{outcome}"
        _arm(ws, rollout_id, base=100.0)
        result = timer.learn(ws, rollout_id, actual_min=5.0,
                             completed=False, outcome=outcome)
        assert result["updated"] is False
        assert result["coeff_after"] == 1.0
        assert outcome in result["row"]["reason"]
    assert len(ledger.read(ws, "telemetry",
                           schema_prefix="rollout-budget/")) == 2


def test_learn_timeout_requires_a_fired_deadline(ws):
    _arm(ws, base=100.0)
    result = timer.learn(ws, "r-1", actual_min=100.0, completed=False,
                         outcome="timeout")
    assert result["updated"] is False
    assert result["coeff_after"] == 1.0
    assert "fired" in result["row"]["reason"]


def test_learn_is_idempotent_per_rollout(ws):
    _arm(ws, base=100.0)
    first = timer.learn(ws, "r-1", actual_min=50.0, completed=True,
                        outcome="early")
    second = timer.learn(ws, "r-1", actual_min=50.0, completed=True,
                         outcome="early")
    assert second["idempotent"] is True
    assert second["row"] == first["row"]
    assert len(ledger.read(ws, "telemetry",
                           schema_prefix="rollout-budget/")) == 1


def test_learn_refuses_a_divergent_repeat(ws):
    _arm(ws, base=100.0)
    timer.learn(ws, "r-1", actual_min=50.0, completed=True,
                outcome="early")
    with pytest.raises(ValueError):
        timer.learn(ws, "r-1", actual_min=90.0, completed=True,
                    outcome="on_time")
    assert len(ledger.read(ws, "telemetry",
                           schema_prefix="rollout-budget/")) == 1


def test_learn_chains_the_one_global_coefficient_across_rollouts(ws):
    _arm(ws, "r-1", base=100.0)
    timer.learn(ws, "r-1", actual_min=50.0, completed=True, outcome="early")
    _arm(ws, "r-2", base=100.0)
    second = timer.learn(ws, "r-2", actual_min=50.0, completed=True,
                         outcome="early")
    assert second["row"]["coeff_before"] == 0.9
    assert second["coeff_after"] == 0.81


def test_coefficient_clamps_at_both_bounds(ws):
    _seed_budget_row(ws, coeff_after=4.0)
    _arm(ws, "r-max", base=100.0)
    timer.fire(ws, "r-max", now=NOW + timedelta(minutes=400))
    high = timer.learn(ws, "r-max", actual_min=100.0, completed=False,
                       outcome="timeout")
    assert high["coeff_after"] == 4.0
    assert "clamped" in high["row"]["reason"]

    _seed_budget_row(ws, coeff_after=0.5)
    _arm(ws, "r-min", base=100.0)
    low = timer.learn(ws, "r-min", actual_min=10.0, completed=True,
                      outcome="early")
    assert low["coeff_after"] == 0.5
    assert "clamped" in low["row"]["reason"]


def test_next_coefficient_is_pure_and_validates_its_inputs():
    early = timer.next_coefficient(1.0, actual_min=59.0, budget_min=100.0,
                                   completed=True, outcome="early")
    assert early == {"coeff_after": 0.9, "updated": True,
                     "reason": "early x0.9"}
    refused = timer.next_coefficient(1.0, actual_min=61.0, budget_min=100.0,
                                     completed=True, outcome="early")
    assert refused["updated"] is False
    assert refused["coeff_after"] == 1.0
    assert "early requires" in refused["reason"]
    fired_early = timer.next_coefficient(
        1.0, actual_min=10.0, budget_min=100.0, completed=True,
        outcome="early", deadline_fired=True)
    assert fired_early["updated"] is False
    assert "unfired deadline" in fired_early["reason"]
    early_band = timer.next_coefficient(
        1.0, actual_min=10.0, budget_min=100.0, completed=True,
        outcome="on_time")
    assert early_band["updated"] is False
    assert "early band" in early_band["reason"]
    with pytest.raises(ValueError):
        timer.next_coefficient(1.0, actual_min=10.0, budget_min=100.0,
                               completed=True, outcome="unknown")
    with pytest.raises(ValueError):
        timer.budget_minutes(-1.0, 1.0)
    with pytest.raises(ValueError):
        timer.budget_minutes(30.0, 0.0)


# ---------- bucket threshold ----------

def test_bucket_ready_waits_for_five_informative_samples():
    rows = [{"bucket_key": "claim/hard", "outcome": "on_time"}
            for _ in range(4)]
    assert timer.bucket_ready(rows, "claim/hard") is False
    rows.append({"bucket_key": "claim/hard", "outcome": "timeout"})
    assert timer.bucket_ready(rows, "claim/hard") is True
    assert timer.bucket_ready(rows, "claim/easy") is False
    with_infra = rows + [{"bucket_key": "claim/hard", "outcome": "infra"}]
    assert timer.bucket_ready(with_infra, "claim/hard", threshold=6) is False


def test_learn_records_the_bucket_but_keeps_one_global_coefficient(ws):
    for index in range(5):
        _arm(ws, f"r-{index}", base=30.0)
        result = timer.learn(ws, f"r-{index}", actual_min=20.0,
                             completed=True, outcome="on_time")
        assert result["row"]["bucket_key"] == "claim/hard"
        assert result["row"]["coeff_before"] == round(0.98 ** index, 6)
    assert result["bucket_ready"] is True
    assert result["coeff_after"] == round(0.98 ** 5, 6)
    assert result["row"]["outcome"] == "on_time"


# ---------- deadline stop record ----------

def test_deadline_stop_record_is_settlement_facing_and_excluded(ws):
    armed_record = _arm(ws)["row"]
    with pytest.raises(ValueError):
        timer.deadline_stop_record(armed_record, now=NOW)
    fired = timer.fire(ws, "r-1", now=NOW + timedelta(minutes=30))
    record = timer.deadline_stop_record(
        fired["row"], now=NOW + timedelta(minutes=31))
    assert record["rollout_id"] == "r-1"
    assert record["claim"] == "C-1"
    assert record["stop_reason"] == "deadline"
    assert record["excluded_from_strategy_learning"] is True
    assert record["budget_min"] == 30.0
    assert record["stopped_ts"] == "2026-11-05T12:31:00Z"
    assert "disposition" not in record


# ---------- lifecycle errors and registration ----------

def test_unknown_rollouts_are_refused(ws):
    with pytest.raises(ValueError):
        timer.cancel(ws, "missing", now=NOW, reason="early")
    with pytest.raises(ValueError):
        timer.fire(ws, "missing", now=NOW)
    with pytest.raises(ValueError):
        timer.learn(ws, "missing", actual_min=1.0, completed=False,
                    outcome="aborted")


def test_a_malformed_timer_row_is_refused(ws):
    ledger.append(ws, "telemetry", {
        "schema": "rollout-timer/1",
        "rollout_id": "r-bad",
        "state": "armed",
        "claim": "C-1",
    })
    with pytest.raises(ValueError):
        timer.fire(ws, "r-bad", now=NOW)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="fork start method is POSIX-only")
def test_concurrent_arms_are_serialized(ws):
    ctx = multiprocessing.get_context("fork")
    barrier = ctx.Barrier(2)

    def _arm_in_child(path, ready):
        ready.wait(timeout=10)
        timer.arm(path, "r-race", claim="C-1", kind="claim",
                  difficulty="hard", now=NOW, base_estimate_min=30.0)

    children = [ctx.Process(target=_arm_in_child,
                            args=(str(ws), barrier))
                for _ in range(2)]
    for child in children:
        child.start()
    for child in children:
        child.join(20)
        assert child.exitcode == 0
    assert len(ledger.read(ws, "telemetry",
                           schema_prefix="rollout-timer/")) == 1


def test_timer_schemas_are_registered_and_counted_by_liveness(ws):
    counts = ledger.liveness(ws)
    assert counts["telemetry:rollout-timer/1"] == 0
    assert counts["telemetry:rollout-budget/1"] == 0
    _arm(ws)
    timer.fire(ws, "r-1", now=NOW + timedelta(minutes=30))
    timer.learn(ws, "r-1", actual_min=30.0, completed=False,
                outcome="timeout")
    counts = ledger.liveness(ws)
    assert counts["telemetry:rollout-timer/1"] == 2
    assert counts["telemetry:rollout-budget/1"] == 1
