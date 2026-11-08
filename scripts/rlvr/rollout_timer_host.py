# -*- coding: utf-8 -*-
"""rlvr/rollout_timer_host.py — the rollout-timer's production host faces.

The policy core (rlvr.rollout_timer) is pure: the helpers take ``now``,
never the wall clock. THIS module is the dumb data-moving boundary that
wires the policy into the workspace lifecycle:

  - ``arm_for_dispatch``     the dispatch-commit face: arm the rollout's
    one-shot deadline timer (rollout_id = the dispatch ledger id) with
    the claim's kind + difficulty family, and publish the wake contract
    to ``runs/rollout-timer-wake.json`` for the orchestrator's one-shot
    CronCreate face.
  - ``round_close_face``     the round-closure face: cancel the finished
    rollout's timer and learn its outcome from the run's actuals. A
    deadline-fired rollout is CENSORED — cancel only, never learn (the
    deadline stop is excluded from strategic learning).
  - ``deadline_wake_face``   the one-shot cron wake face: fire, record
    the settlement-facing deadline stop, cancel, learn the timeout, and
    publish the graceful-stop contract. It NEVER starts a rollout — the
    only steps are persist, settle, cancel, learn, arm-next.

The single-slot wake file is the PUBLISH face (the orchestrator reads it
to create/delete the cron); the durable timer/budget rows in the
telemetry ledger are the truth, and every state transition is readable
back through ``timer_state``.

Fail-open posture: every face converts its failures into ONE canonical
warn and a ``None`` receipt — timer telemetry must never break the
lifecycle face it rides.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from kunglao_log import warn

from rlvr import rollout_timer

#: the orchestrator's wake-contract publish face — a MAP keyed by
#: rollout_id (``{rollout_id: contract}``), so concurrently-armed
#: rollouts never clobber each other's contract and a rollout's clear
#: removes ONLY its own entry (the last entry out unlinks the file)
WAKE_STATE_REL = Path("runs") / "rollout-timer-wake.json"

#: the kind token for dispatches that declare no method family
DEFAULT_KIND = "claim"

#: the difficulty family when the feed is unreadable (the thresholds
#: module's own fail-closed default, mirrored here for the read face)
FALLBACK_DIFFICULTY = "hard"

_TS_FORMAT = rollout_timer._TS_FORMAT


def difficulty_family(ws) -> str:
    """The workspace's difficulty family (the calibration feed's tier).

    Reads the same feed the promotion gates read; a missing/corrupt
    feed fail-closes to ``hard`` — the same posture as the gates."""
    try:
        from difficulty_thresholds import thresholds_for_workspace
        tier = str(thresholds_for_workspace(ws).get("tier") or "").strip()
        if tier:
            return tier.lower()
    except Exception as exc:  # noqa: BLE001 — telemetry, never the caller
        warn("rollout_timer_host.difficulty",
             f"{type(exc).__name__}: {exc} — fail-closed to "
             f"{FALLBACK_DIFFICULTY}")
    return FALLBACK_DIFFICULTY


def _load_wake_map(ws: Path) -> dict:
    """The tolerant read of the wake map (absent/dirty -> rebuild empty;
    a stale entry whose contract names a different rollout_id is
    dropped — the key IS the identity)."""
    p = ws / WAKE_STATE_REL
    if not p.is_file():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        warn("rollout_timer_host.wake_publish",
             "unreadable wake map — rebuilding empty")
        return {}
    if not isinstance(doc, dict):
        return {}
    return {str(k): v for k, v in doc.items()
            if isinstance(v, dict)
            and str(v.get("rollout_id") or "") == str(k)}


def _save_wake_map(ws: Path, wake_map: dict) -> None:
    """Atomic map write; an empty map removes the file (no wake
    remains)."""
    p = ws / WAKE_STATE_REL
    try:
        if not wake_map:
            p.unlink(missing_ok=True)
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(wake_map, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        warn("rollout_timer_host.wake_publish",
             f"{type(exc).__name__}: {exc} — wake state not updated")


def _publish_wake(ws: Path, payload: dict | None, rollout_id: str) -> None:
    """Publish (or clear) THIS rollout's wake contract entry.

    The map is keyed by rollout_id, so a publish overwrites only its
    own key and a clear pops only its own key — no cross-rollout
    clobber is possible WITHIN ONE PROCESS (the journal serializes the
    arm and discard callers). The load-modify-save is not serialized
    across processes; if an external cron wake interleaves, the ledger
    stays the durable truth and the stale fire refuses."""
    wake_map = _load_wake_map(ws)
    if payload is None:
        if rollout_id not in wake_map:
            return
        wake_map.pop(rollout_id, None)
    else:
        wake_map[rollout_id] = payload
    _save_wake_map(ws, wake_map)


def arm_for_dispatch(ws, claim: str, dispatch_id: str, *,
                     method_family: str | None = None,
                     now: datetime | None = None) -> dict | None:
    """Arm the dispatch's one-shot deadline timer and publish the wake
    contract. The rollout identity is the dispatch ledger id minted at
    the approval point. Returns the timer's arm result or ``None`` (a
    failed arm is ONE warn — the dispatch verdict is never disturbed)."""
    try:
        rid = str(dispatch_id or "").strip()
        who = str(claim or "").strip()
        if not rid or not who:
            return None
        workspace = Path(ws)
        kind = str(method_family or "").strip() or DEFAULT_KIND
        result = rollout_timer.arm(
            workspace, rid, claim=who, kind=kind,
            difficulty=difficulty_family(workspace),
            now=now or datetime.now(timezone.utc))
        _publish_wake(workspace, {
            **result["wake"],
            "claim": who,
            "kind": kind,
            "difficulty": result["row"]["difficulty"],
        }, rid)
        return result
    except Exception as exc:  # noqa: BLE001 — telemetry, never the dispatch
        warn("rollout_timer_host.arm",
             f"{type(exc).__name__}: {exc}")
        return None


def _actual_minutes(receipt: dict) -> float | None:
    """The rollout's actual minutes from the settle receipt: duration_ms
    first, the wall clock's wall_s second; neither -> ``None`` (the
    caller cancels but never guesses a duration)."""
    duration_ms = receipt.get("duration_ms")
    if isinstance(duration_ms, (int, float)) and duration_ms >= 0:
        return round(float(duration_ms) / 60000.0, 6)
    wall_s = receipt.get("wall_s")
    if isinstance(wall_s, (int, float)) and wall_s >= 0:
        return round(float(wall_s) / 60.0, 6)
    return None


def _close_outcome(state: dict, receipt: dict,
                   actual_min: float | None) -> str | None:
    """The bounded table's outcome word for a finished rollout.

    ``completed`` + inside the early band -> ``early``; ``completed``
    within budget -> ``on_time``; everything else (a failed worker, a
    completion past its budget with no fired deadline) -> ``aborted``,
    the table's honest no-update word — the host never stretches the
    vocabulary to force an update."""
    if str(receipt.get("outcome") or "") != "completed":
        return "aborted"
    if actual_min is None:
        return None
    try:
        budget = float(state.get("budget_min") or 0.0)
    except (TypeError, ValueError):
        budget = 0.0
    if budget <= 0:
        return None
    if actual_min <= rollout_timer.EARLY_RATIO * budget:
        return "early"
    if actual_min <= budget:
        return "on_time"
    return "aborted"


def round_close_face(ws, receipt) -> dict | None:
    """The round-closure face: cancel the finished rollout's timer and
    learn its outcome. ``receipt`` is the settle face's receipt (the
    claim/outcome/duration keys); a receipt without a claim, or a claim
    whose latest committed dispatch never armed a timer, is a silent
    no-op. Returns the receipt dict or ``None``."""
    if not isinstance(receipt, dict) \
            or not str(receipt.get("claim") or "").strip():
        return None
    try:
        workspace = Path(ws)
        claim = str(receipt["claim"])
        rid = _resolve_rollout_id(workspace, claim)
        if not rid:
            return None
        state = rollout_timer.timer_state(workspace, rid)
        if state is None:
            return None
        when = datetime.now(timezone.utc)
        censored = bool(state.get("fired_ts"))
        canceled = rollout_timer.cancel(
            workspace, rid, now=when,
            reason="deadline wrap-up cleanup" if censored
            else "rollout finished")
        learned: dict | None = None
        if not censored:
            # close the decide-then-learn window: the cron wake may have
            # fired between the state read above and this point — a
            # timer that flipped to fired is CENSORED (cancel only,
            # never learn), and the policy table's own fired-deadline
            # predicates refuse the update as the backstop
            current = rollout_timer.timer_state(workspace, rid) or {}
            if current.get("fired_ts"):
                censored = True
        if not censored:
            actual_min = _actual_minutes(receipt)
            outcome = _close_outcome(state, receipt, actual_min)
            if outcome is not None and actual_min is not None:
                learned = rollout_timer.learn(
                    workspace, rid, actual_min=actual_min,
                    completed=str(receipt.get("outcome")) == "completed",
                    outcome=outcome)
        _publish_wake(workspace, None, rid)
        return {
            "rollout_id": rid,
            "canceled": bool(canceled.get("canceled")),
            "learned": bool(learned and learned.get("updated")),
            "censored": censored,
        }
    except Exception as exc:  # noqa: BLE001 — telemetry, never the closure
        warn("rollout_timer_host.round_close",
             f"{type(exc).__name__}: {exc}")
        return None


def _resolve_rollout_id(workspace: Path, claim: str) -> str:
    """The claim's latest committed dispatch id — the rollout identity
    the arm face used. Empty when the claim has no committed dispatch
    (a pre-ledger dispatch owns no timer)."""
    try:
        import claims_store
        row = claims_store.latest_committed_dispatch(workspace, claim)
        return str((row or {}).get("dispatch_id") or "").strip()
    except Exception as exc:  # noqa: BLE001 — telemetry, never the closure
        warn("rollout_timer_host.resolve",
             f"{type(exc).__name__}: {exc}")
        return ""


def discard_rollout_timer(ws, rollout_id: str, *,
                          reason: str) -> dict | None:
    """Cancel-only cleanup for a rollout whose dispatch never happened
    (the recovery face's committed-journal inversion). No learn, no
    censoring logic — the timer simply must not survive an inverted
    dispatch. A rollout with no timer is a silent no-op."""
    try:
        rid = str(rollout_id or "").strip()
        if not rid:
            return None
        workspace = Path(ws)
        state = rollout_timer.timer_state(workspace, rid)
        if state is None:
            return None
        canceled = rollout_timer.cancel(workspace, rid,
                                        now=datetime.now(timezone.utc),
                                        reason=reason)
        _publish_wake(workspace, None, rid)
        return {"rollout_id": rid,
                "canceled": bool(canceled.get("canceled"))}
    except Exception as exc:  # noqa: BLE001 — telemetry, never recovery
        warn("rollout_timer_host.discard",
             f"{type(exc).__name__}: {exc}")
        return None


def deadline_wake_face(ws, rollout_id: str, *,
                       now: datetime | None = None) -> dict | None:
    """The one-shot cron wake face: fire, record the settlement-facing
    deadline stop, cancel, learn the timeout, publish the graceful-stop
    contract. A refused fire (not yet due, already canceled, unknown
    rollout) is ONE warn + ``None`` — the cron wake never force-fires."""
    try:
        rid = str(rollout_id or "").strip()
        if not rid:
            return None
        workspace = Path(ws)
        when = now or datetime.now(timezone.utc)
        fired = rollout_timer.fire(workspace, rid, now=when)
        if not fired.get("fired"):
            warn("rollout_timer_host.wake",
                 f"{rid}: deadline wake refused "
                 f"({fired.get('reason') or 'not fired'})")
            return None
        row = fired["row"]
        stop = rollout_timer.deadline_stop_record(row, now=when)
        # the GRACEFUL_STEPS order: settle (the stop record), then
        # cancel_timer, then update_coefficient
        canceled = rollout_timer.cancel(workspace, rid, now=when,
                                        reason="deadline wrap-up")
        budget = float(row.get("budget_min") or 0.0)
        learned: dict | None = None
        if budget > 0:
            learned = rollout_timer.learn(
                workspace, rid, actual_min=budget, completed=False,
                outcome="timeout")
        contract = fired.get("contract") or {}
        _publish_wake(workspace, {**contract, "claim": stop.get("claim"),
                                  "stop": stop}, rid)
        return {
            "rollout_id": rid,
            "stop": stop,
            "canceled": bool(canceled.get("canceled")),
            "learned": bool(learned and learned.get("updated")),
            "contract": contract,
        }
    except Exception as exc:  # noqa: BLE001 — telemetry, never the wake
        warn("rollout_timer_host.wake",
             f"{type(exc).__name__}: {exc}")
        return None
