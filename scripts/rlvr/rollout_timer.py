# -*- coding: utf-8 -*-
"""rlvr/rollout_timer.py — the per-rollout learned deadline timer.

A rollout gets ONE timer. ``arm`` computes its budget from a comparable-
rollout median and ONE global coefficient, persists a ``rollout-timer/1``
row, and returns the one-shot wake contract (cron expression + prompt).
``cancel`` retires an early finish; ``fire`` records that the deadline
fired and returns the graceful-stop contract. Both prompts wrap up,
settle, cancel, learn and arm the next timer — neither starts a rollout.

``learn`` moves the global coefficient through the bounded outcome table
and audits every decision as a ``rollout-budget/1`` row. The bucket key
(``<kind>/<difficulty>``) rides every row for a later bucket split, but
the coefficient stays global until a bucket reaches its sample floor.

Budget semantics::

    budget = clamp(base_estimate x coeff, 15 minutes, 480 minutes)
    coeff  = clamp(coeff_before x factor, 0.5, 4.0)

The policy helpers are pure (no clock, no I/O); callers pass ``now``.
"""
from __future__ import annotations

import math
import os
import statistics
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from platform_matrix import fd_lock, fd_unlock

from . import consolidated_ledger

#: the row stamps (registered in consolidated_ledger.NATIVE_SCHEMAS)
TIMER_SCHEMA = "rollout-timer/1"
BUDGET_SCHEMA = "rollout-budget/1"

#: the policy identity carried by every row
POLICY_REF = "rollout-timer-policy/1"

#: budget and coefficient bounds (minutes / multiplier)
MIN_BUDGET_MIN = 15.0
MAX_BUDGET_MIN = 480.0
MIN_COEFF = 0.5
MAX_COEFF = 4.0

#: the cold-start estimate for a family with no comparable history
DEFAULT_BASE_MIN = 30.0
DEFAULT_COEFF = 1.0

#: an early finish is at most this share of the budget
EARLY_RATIO = 0.6

#: a bucket may split its own coefficient only after this many samples
BUCKET_SAMPLE_THRESHOLD = 5

#: outcome vocabulary (the audit row's closed set)
OUTCOMES = ("early", "timeout", "on_time", "infra", "aborted")

#: outcomes that carry a real duration (and therefore feed the median)
SAMPLE_OUTCOMES = ("early", "timeout", "on_time")

#: outcomes whose duration is an OBSERVED completion time — the median's
#: feed. A timeout's recorded actual is the budget itself (the true
#: duration is unknown — the rollout never finished), so a timeout-heavy
#: history is right-censored data: feeding it would drag the median
#: toward the budget (budgets stop adapting, more deadlines fire, the
#: coefficient pegs). The coefficient table still learns timeout x1.25;
#: only the duration feed excludes it.
DURATION_OUTCOMES = ("early", "on_time")

#: update factors (the bounded coefficient table)
EARLY_FACTOR = 0.9
TIMEOUT_FACTOR = 1.25
ON_TIME_FACTOR = 0.98

#: the settlement-facing stop reason (no new disposition is introduced)
STOP_REASON_DEADLINE = "deadline"

#: the graceful wrap-up steps, in contract order
GRACEFUL_STEPS = (
    "persist_evidence",
    "settle",
    "cancel_timer",
    "update_coefficient",
    "arm_next_timer",
)

#: cron minutes the scheduler may fire up to ~90 seconds early
_EARLY_FIRE_MINUTES = (0, 30)

#: the scheduler's early-fire tolerance around the exact deadline
EARLY_FIRE_TOLERANCE_SECONDS = 90

_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class RolloutTimerError(ValueError):
    """A timer call violates the rollout-timer contract."""


def _is_number(value) -> bool:
    """A real, finite number (bool is not a number here)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _token(value, field: str) -> str:
    token = value.strip() if isinstance(value, str) else ""
    if not token:
        raise RolloutTimerError(f"{field} must be a non-empty string")
    return token


def _utc(now: datetime) -> datetime:
    """A UTC instant; naive input is read as UTC."""
    if not isinstance(now, datetime):
        raise TypeError("now must be a datetime")
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _iso(now: datetime) -> str:
    return _utc(now).strftime(_TS_FORMAT)


def _parse_ts(stamp: str) -> datetime:
    return datetime.strptime(stamp, _TS_FORMAT).replace(tzinfo=timezone.utc)


def _now_utc() -> datetime:
    """The I/O boundary's clock (the pure helpers never call it)."""
    return datetime.now(timezone.utc)


# ---------- pure policy helpers ----------

def bucket_key(kind: str, difficulty: str) -> str:
    """The future coefficient bucket: ``<kind>/<difficulty>``."""
    return f"{_token(kind, 'kind')}/{_token(difficulty, 'difficulty')}"


def base_estimate(rows, *, kind: str, difficulty: str,
                  default: float = DEFAULT_BASE_MIN) -> float:
    """Median duration of comparable rollouts (same kind + difficulty).

    Only OBSERVED completion durations count (``DURATION_OUTCOMES`` —
    an uncompleted rollout's duration is right-censored at its budget,
    never fed); absent, unreadable or non-numeric durations are
    skipped. A family with no comparables returns the cold-start
    default (30 minutes).
    """
    durations = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        if not str(row.get("schema") or "").startswith(BUDGET_SCHEMA):
            continue
        if row.get("kind") != kind or row.get("difficulty") != difficulty:
            continue
        if row.get("outcome") not in DURATION_OUTCOMES:
            continue
        actual = row.get("actual_min")
        if not _is_number(actual) or actual < 0:
            continue
        durations.append(float(actual))
    if not durations:
        return float(default)
    return float(statistics.median(durations))


def budget_minutes(base_min, coeff) -> float:
    """Clamp ``base x coeff`` to the [15, 480] minute window.

    A zero median is a real (instant) history and clamps to the floor; a
    negative base is a caller error.
    """
    if not _is_number(base_min) or base_min < 0:
        raise RolloutTimerError("base_min must be a non-negative number")
    if not _is_number(coeff) or coeff <= 0:
        raise RolloutTimerError("coeff must be a positive number")
    return round(min(max(float(base_min) * float(coeff), MIN_BUDGET_MIN),
                     MAX_BUDGET_MIN), 6)


def normalize_outcome(outcome) -> str:
    """The closed outcome vocabulary, case- and separator-insensitive."""
    word = str(outcome or "").strip().lower().replace("-", "_").replace(
        " ", "_")
    if word not in OUTCOMES:
        raise RolloutTimerError(f"outcome must be one of {OUTCOMES}")
    return word


def next_coefficient(coeff_before, *, actual_min, budget_min, completed,
                     outcome, deadline_fired: bool = False) -> dict:
    """Apply the bounded coefficient table to one rollout outcome.

    Returns ``{"coeff_after", "updated", "reason"}``. An outcome whose
    defining predicate does not hold is refused (no update, audited
    reason) rather than guessed; infra/aborted never move the coefficient.
    """
    if not _is_number(coeff_before) or coeff_before <= 0:
        raise RolloutTimerError("coeff_before must be a positive number")
    if not _is_number(actual_min) or actual_min < 0:
        raise RolloutTimerError("actual_min must be a non-negative number")
    if not _is_number(budget_min) or budget_min <= 0:
        raise RolloutTimerError("budget_min must be a positive number")
    if not isinstance(completed, bool):
        raise RolloutTimerError("completed must be an explicit bool")
    word = normalize_outcome(outcome)
    return _outcome_verdict(
        round(float(coeff_before), 6), word, actual_min=actual_min,
        budget_min=budget_min, completed=completed,
        deadline_fired=deadline_fired)


def _outcome_verdict(before, word, *, actual_min, budget_min, completed,
                     deadline_fired) -> dict:
    if word in ("infra", "aborted"):
        return _verdict(before, False, f"{word} no update")
    if word == "early":
        return _early_verdict(before, actual_min, budget_min, completed,
                              deadline_fired)
    if word == "timeout":
        return _timeout_verdict(before, completed, deadline_fired)
    return _on_time_verdict(before, actual_min, budget_min, completed,
                            deadline_fired)


def _early_verdict(before, actual_min, budget_min, completed,
                   deadline_fired) -> dict:
    if deadline_fired:
        return _verdict(
            before, False,
            "early requires an unfired deadline (the deadline already fired)")
    if not (completed and actual_min <= EARLY_RATIO * budget_min):
        return _verdict(
            before, False,
            "early requires completion at or below 0.6 x budget")
    return _apply(before, EARLY_FACTOR, "early")


def _timeout_verdict(before, completed, deadline_fired) -> dict:
    if not (deadline_fired and not completed):
        return _verdict(
            before, False,
            "timeout requires a fired deadline and an incomplete rollout")
    return _apply(before, TIMEOUT_FACTOR, "timeout")


def _on_time_verdict(before, actual_min, budget_min, completed,
                     deadline_fired) -> dict:
    if deadline_fired:
        return _verdict(
            before, False,
            "on time requires an unfired deadline (the deadline already "
            "fired)")
    if not completed or actual_min > budget_min:
        return _verdict(before, False,
                        "on time requires completion within budget")
    if actual_min <= EARLY_RATIO * budget_min:
        return _verdict(
            before, False,
            "on time requires a duration above the early band; classify "
            "the finish as early")
    return _apply(before, ON_TIME_FACTOR, "on time")


def _apply(before: float, factor: float, label: str) -> dict:
    raw = round(before * factor, 6)
    after = round(min(max(raw, MIN_COEFF), MAX_COEFF), 6)
    reason = f"{label} x{factor:g}"
    if after != raw:
        reason += " (clamped)"
    return _verdict(after, True, reason)


def _verdict(after: float, updated: bool, reason: str) -> dict:
    return {"coeff_after": round(float(after), 6), "updated": updated,
            "reason": reason}


def bucket_ready(rows, bucket_key_value: str, *,
                 threshold: int = BUCKET_SAMPLE_THRESHOLD) -> bool:
    """Whether one bucket has reached its split sample floor."""
    count = sum(
        1 for row in rows or ()
        if isinstance(row, dict)
        and row.get("bucket_key") == bucket_key_value
        and row.get("outcome") in SAMPLE_OUTCOMES)
    return count >= threshold


def deadline_cron(deadline: datetime) -> str:
    """A one-shot cron expression for the deadline's minute and day.

    Fields are rendered in UTC (the timer's clock). Whole-minute rounding
    is upward, and minutes :00/:30 are shifted one minute ahead so an
    early repository tick cannot fire before the deadline.
    """
    moment = _utc(deadline)
    if moment.second or moment.microsecond:
        moment = moment.replace(second=0, microsecond=0) + timedelta(
            minutes=1)
    if moment.minute in _EARLY_FIRE_MINUTES:
        moment += timedelta(minutes=1)
    return f"{moment.minute} {moment.hour} {moment.day} {moment.month} *"


# ---------- the wake and stop contracts ----------

def _wrap_up_prompt(row: dict) -> str:
    return (
        f"[kunglao rollout deadline] Rollout {row['rollout_id']} "
        f"(claim {row['claim']}) reached its learned deadline "
        f"({row['budget_min']:g} min budget, deadline "
        f"{row['deadline_ts']}).\n"
        "Graceful wrap-up ONLY. This wake performs no new rollout; it may "
        "not start, dispatch, resume, or expand any claim.\n"
        "1. persist evidence: write every partial finding and artifact to "
        "disk before anything else.\n"
        "2. settle: run the settlement path on what the rollout actually "
        "produced.\n"
        "3. cancel timer: delete this firing job and record cancel(...) so "
        "the wake never repeats.\n"
        "4. update coefficient: record learn(...) with the actual minutes "
        "and the outcome.\n"
        "5. arm next timer: only if another rollout is already queued, arm "
        "its one-shot timer under a NEW rollout_id.\n"
        "Nothing else: persist, settle, cancel, learn, arm."
    )


def _wake_contract(row: dict) -> dict:
    return {
        "kind": "one-shot-deadline",
        "once": True,
        "rollout_id": row["rollout_id"],
        "cron": deadline_cron(_parse_ts(row["deadline_ts"])),
        "deadline_ts": row["deadline_ts"],
        "steps": list(GRACEFUL_STEPS),
        "may_start_rollout": False,
        "prompt": _wrap_up_prompt(row),
    }


def _stop_contract(row: dict) -> dict:
    return {
        "kind": "graceful-stop",
        "rollout_id": row["rollout_id"],
        "deadline_ts": row["deadline_ts"],
        "steps": list(GRACEFUL_STEPS),
        "may_start_rollout": False,
        "prompt": _wrap_up_prompt(row),
    }


# ---------- ledger read faces ----------

def _fold_timer(ws, rollout_id: str):
    """The merged timer view for one rollout (append-only transitions)."""
    folded = None
    for row in consolidated_ledger.read(ws, "telemetry",
                                        schema_prefix=TIMER_SCHEMA):
        if row.get("rollout_id") != rollout_id:
            continue
        folded = {**folded, **row} if folded else dict(row)
    return folded


def timer_state(ws, rollout_id: str):
    """The public read face for one rollout's folded timer view.

    The host faces (rlvr.rollout_timer_host) resolve the timer's state
    through this seam; the fold itself is the append-only transition
    merge above. ``None`` = no timer row for that rollout id."""
    return _fold_timer(ws, rollout_id)


def _require_timer(ws, rollout_id: str) -> dict:
    state = _fold_timer(ws, rollout_id)
    if state is None:
        raise RolloutTimerError(f"unknown rollout_id {rollout_id!r}")
    missing = [field for field in ("claim", "budget_min", "deadline_ts")
               if field not in state]
    if missing:
        raise RolloutTimerError(
            f"timer row for {rollout_id!r} is malformed: missing {missing}")
    return state


def _current_coefficient(ws) -> float:
    """The latest audited coefficient, defaulting to the cold start."""
    rows = consolidated_ledger.read(ws, "telemetry",
                                    schema_prefix=BUDGET_SCHEMA)
    for row in reversed(rows):
        value = row.get("coeff_after")
        if _is_number(value) and value > 0:
            return round(min(max(float(value), MIN_COEFF), MAX_COEFF), 6)
    return DEFAULT_COEFF


def _budget_row(ws, rollout_id: str):
    for row in consolidated_ledger.read(ws, "telemetry",
                                        schema_prefix=BUDGET_SCHEMA):
        if row.get("rollout_id") == rollout_id:
            return row
    return None


def _append(ws, row: dict) -> None:
    if not consolidated_ledger.append(ws, "telemetry", row):
        raise RolloutTimerError(
            f"telemetry append refused for {row.get('schema')!r} "
            f"(rollout {row.get('rollout_id')!r})")


@contextmanager
def _timer_lock(ws):
    """Serialize one workspace's read-check-append sequences.

    The ledger's flock covers a single append; the timer transitions also
    depend on the state read before it. A workspace-local advisory lock
    keeps two callers (cron wake and stop hook) from arming or learning
    the same rollout twice. The host matrix supplies the portable lock,
    including its declared unlocked fallback.
    """
    runs = Path(ws) / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    lock_path = runs / ".rollout-timer.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fd_lock(fd)
        try:
            yield
        finally:
            fd_unlock(fd)
    finally:
        os.close(fd)


# ---------- the lifecycle ----------

def arm(ws, rollout_id, *, claim, kind, difficulty, now,
        base_estimate_min=None) -> dict:
    """Arm the rollout's one-shot deadline timer.

    Persists a ``rollout-timer/1`` row and returns the row plus the wake
    contract. Arming an already-armed rollout is idempotent; a terminal
    rollout refuses re-arming (the next work needs a new rollout id).
    """
    rollout_id = _token(rollout_id, "rollout_id")
    claim = _token(claim, "claim")
    kind = _token(kind, "kind")
    difficulty = _token(difficulty, "difficulty")
    when = _utc(now)
    if base_estimate_min is not None:
        if not _is_number(base_estimate_min) or base_estimate_min < 0:
            raise RolloutTimerError(
                "base_estimate_min must be a non-negative number")
    with _timer_lock(ws):
        existing = _fold_timer(ws, rollout_id)
        if existing is not None:
            if existing.get("state") != "armed":
                raise RolloutTimerError(
                    f"rollout {rollout_id!r} is terminal "
                    f"({existing.get('state')!r}); arm the next rollout")
            if (existing.get("claim"), existing.get("kind"),
                    existing.get("difficulty")) != (
                        claim, kind, difficulty):
                raise RolloutTimerError(
                    f"rollout {rollout_id!r} is armed with a different "
                    "claim/kind/difficulty")
            return {"row": existing, "wake": _wake_contract(existing),
                    "idempotent": True}

        if base_estimate_min is None:
            base = base_estimate(
                consolidated_ledger.read(ws, "telemetry",
                                         schema_prefix=BUDGET_SCHEMA),
                kind=kind, difficulty=difficulty)
        else:
            base = float(base_estimate_min)
        coeff = _current_coefficient(ws)
        budget = budget_minutes(base, coeff)
        row = {
            "schema": TIMER_SCHEMA,
            "state": "armed",
            "rollout_id": rollout_id,
            "claim": claim,
            "kind": kind,
            "difficulty": difficulty,
            "bucket_key": bucket_key(kind, difficulty),
            "armed_ts": _iso(when),
            "deadline_ts": _iso(when + timedelta(minutes=budget)),
            "base_min": round(base, 6),
            "coeff": round(coeff, 6),
            "budget_min": budget,
            "policy_ref": POLICY_REF,
        }
        _append(ws, row)
    return {"row": row, "wake": _wake_contract(row), "idempotent": False}


def cancel(ws, rollout_id, *, now, reason) -> dict:
    """Retire the timer (early finish or post-settlement cleanup).

    Idempotent: a canceled timer stays canceled and never fires. A fired
    timer may be canceled afterwards (the stop contract's cleanup step);
    its ``fired_ts`` survives in the folded view.
    """
    rollout_id = _token(rollout_id, "rollout_id")
    reason = _token(reason, "reason")
    when = _iso(now)
    with _timer_lock(ws):
        state = _require_timer(ws, rollout_id)
        if state.get("state") == "canceled":
            return {"row": state, "canceled": True, "idempotent": True}
        row = {**state, "state": "canceled", "canceled_ts": when,
               "cancel_reason": reason}
        _append(ws, row)
        return {"row": _fold_timer(ws, rollout_id), "canceled": True,
                "idempotent": False}


def fire(ws, rollout_id, *, now) -> dict:
    """Record that the deadline fired and return the graceful-stop contract.

    A canceled timer never fires; a fired timer stays fired (idempotent);
    a wake more than the scheduler's early-fire tolerance before the
    deadline is refused. Neither branch starts a rollout.
    """
    rollout_id = _token(rollout_id, "rollout_id")
    when = _utc(now)
    with _timer_lock(ws):
        state = _require_timer(ws, rollout_id)
        if state.get("fired_ts"):
            return {"fired": True, "row": state,
                    "contract": _stop_contract(state), "idempotent": True}
        if state.get("state") == "canceled":
            return {"fired": False, "row": state, "contract": None,
                    "reason": "canceled", "idempotent": False}
        deadline = _parse_ts(state["deadline_ts"])
        if when < deadline - timedelta(seconds=EARLY_FIRE_TOLERANCE_SECONDS):
            raise RolloutTimerError(
                f"deadline for {rollout_id!r} has not arrived "
                f"({state['deadline_ts']}); refusing a pre-deadline fire")
        row = {**state, "state": "fired", "fired_ts": _iso(when),
               "stop_reason": STOP_REASON_DEADLINE,
               "excluded_from_strategy_learning": True}
        _append(ws, row)
        folded = _fold_timer(ws, rollout_id)
        return {"fired": True, "row": folded,
                "contract": _stop_contract(folded), "idempotent": False}


def learn(ws, rollout_id, *, actual_min, completed, outcome) -> dict:
    """Move the ONE global coefficient and audit the decision.

    The timer's budget and base ride the ``rollout-budget/1`` row, so the
    audit is self-contained. One update per rollout: an identical repeat
    is idempotent, a divergent repeat is refused. The bucket key is
    recorded for a future split, but the coefficient stays global.
    """
    rollout_id = _token(rollout_id, "rollout_id")
    if not isinstance(completed, bool):
        raise RolloutTimerError("completed must be an explicit bool")
    if not _is_number(actual_min) or actual_min < 0:
        raise RolloutTimerError("actual_min must be a non-negative number")
    word = normalize_outcome(outcome)
    with _timer_lock(ws):
        state = _require_timer(ws, rollout_id)
        existing = _budget_row(ws, rollout_id)
        if existing is not None:
            same = (
                existing.get("outcome") == word
                and existing.get("completed") == completed
                and _is_number(existing.get("actual_min"))
                and round(float(existing["actual_min"]), 6)
                == round(float(actual_min), 6))
            if not same:
                raise RolloutTimerError(
                    f"rollout {rollout_id!r} was already learned with "
                    "different actual_min/completed/outcome")
            rows = consolidated_ledger.read(ws, "telemetry",
                                            schema_prefix=BUDGET_SCHEMA)
            return {"row": existing, "updated": False, "idempotent": True,
                    "coeff_after": existing.get("coeff_after"),
                    "bucket_key": existing.get("bucket_key"),
                    "bucket_ready": bucket_ready(
                        rows, str(existing.get("bucket_key") or ""))}

        coeff_before = _current_coefficient(ws)
        verdict = next_coefficient(
            coeff_before, actual_min=float(actual_min),
            budget_min=float(state["budget_min"]), completed=completed,
            outcome=word, deadline_fired=bool(state.get("fired_ts")))
        row = {
            "schema": BUDGET_SCHEMA,
            "rollout_id": rollout_id,
            "claim": state["claim"],
            "kind": state["kind"],
            "difficulty": state["difficulty"],
            "bucket_key": state["bucket_key"],
            "base_min": state["base_min"],
            "coeff_before": round(coeff_before, 6),
            "budget_min": state["budget_min"],
            "actual_min": round(float(actual_min), 6),
            "completed": completed,
            "outcome": word,
            "coeff_after": verdict["coeff_after"],
            "updated": verdict["updated"],
            "reason": verdict["reason"],
            "policy_ref": POLICY_REF,
            "ts": _iso(_now_utc()),
        }
        _append(ws, row)
        rows = consolidated_ledger.read(ws, "telemetry",
                                        schema_prefix=BUDGET_SCHEMA)
        return {"row": row, "updated": verdict["updated"],
                "idempotent": False, "coeff_after": verdict["coeff_after"],
                "bucket_key": row["bucket_key"],
                "bucket_ready": bucket_ready(rows, row["bucket_key"])}


def deadline_stop_record(row, *, now) -> dict:
    """The settlement-facing deadline stop (no new disposition).

    The record carries the timer-level ``stop_reason`` and the strategic-
    learning exclusion; the seven-disposition vocabulary is untouched.
    """
    if not isinstance(row, dict):
        raise RolloutTimerError("row must be a dict")
    if not row.get("fired_ts"):
        raise RolloutTimerError(
            "a deadline stop requires a fired timer (fired_ts missing)")
    return {
        "rollout_id": _token(row.get("rollout_id"), "rollout_id"),
        "claim": _token(row.get("claim"), "claim"),
        "kind": row.get("kind"),
        "difficulty": row.get("difficulty"),
        "bucket_key": row.get("bucket_key"),
        "stop_reason": STOP_REASON_DEADLINE,
        "excluded_from_strategy_learning": True,
        "budget_min": row.get("budget_min"),
        "deadline_ts": row.get("deadline_ts"),
        "stopped_ts": _iso(now),
    }
