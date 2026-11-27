# -*- coding: utf-8 -*-
"""rlvr/disposition_reward.py — the disposition classification and reward face.

The episode disposition algebra owns the closed vocabulary and the
evidence gates. This module is the REWARD consumer, and it never grows a
second classifier:

  classify_episode(record, ...)
      the evidence normalizer in front of the algebra's classifier. The
      wall gate is filled only from evidence carrying BOTH censoring
      legs — a caller wall with strict ``session_bound`` AND
      ``corroborated``, or the interruption classifier RE-RUN over the
      session record and workspace (its ``censored_env`` class is emitted
      only for a blocker bound to the dying session and corroborated per
      its own table; the caller cannot inject the class word). A
      one-legged wall never censors; an early stop without the route
      ledger and without both legs is SURRENDER. Authorization decides
      the refusal split: an authorized refusal is SURRENDER, an
      out-of-scope refusal is OUT_OF_SCOPE.

  reward_for(disposition)
      the consumer mapping. SOLVED earns the oracle lock (1.0);
      SURRENDER settles 0.0 inside the declared [0, 1] rails (the TRACE
      floor only with reproducible evidence) and carries a
      strategic-action failure outcome while staying in the capability
      denominator; ATTEMPTED_EXHAUSTED is a capability-gap record with no
      strategy credit; CENSORED_ENV is explicit censoring (excluded from
      strategy learning, reported as a censoring rate); OUT_OF_SCOPE /
      INFRA / FAILED are reported separately with no strategic-choice
      signal.

  settle_disposition(ws, row)
      the bounded choice signal: one ``disposition-signal/1`` row per
      episode through the unified TELEMETRY ledger plus the registered
      ``disposition_signal`` event. The row is bounded by construction —
      a fixed field set, credit and propensity inside [0, 1], and the
      strategy verdict re-derived from the mapping at validation time.
      One episode settles one signal (a replay is a no-op).

``settle_workspace`` sweeps an existing ``runs/disposition/`` set; it is
the mission-terminal settlement call site (rlvr.episode_settle). The
pure faces carry no clock; the writer stamps ``ts``. Fail-open reads,
fail-closed vocabulary: an unknown disposition word settles nothing.
"""
from __future__ import annotations

import json
from pathlib import Path

from kunglao_log import emit, warn

from . import authorization, consolidated_ledger, disposition, interruption
from . import scalar

#: the bounded choice signal's row stamp (the unified-ledger contract)
SIGNAL_SCHEMA = "disposition-signal/1"

#: the registered telemetry event word for the choice signal
EVENT = "disposition_signal"

#: the unified-ledger family the signal rides
TELEMETRY_FAMILY = "telemetry"

#: the signal's fixed field set — bounded by construction, no free text
SIGNAL_FIELDS = (
    "schema",
    "episode_id",
    "claim",
    "disposition",
    "credit",
    "strategic_action",
    "propensity",
    "strategy_learning",
    "strategic_action_outcome",
    "ts",
)

#: the closed strategy-learning outcomes the signal may carry
STRATEGY_OUTCOMES = ("positive", "failure")

#: the strategy word or None (no strategic-choice signal)
SIGNAL_OUTCOMES = (None,) + STRATEGY_OUTCOMES

#: dispositions that enter strategic-action learning at all
_STRATEGY_LEARNING = frozenset({"SOLVED", "SURRENDER"})

#: dispositions that stay in the capability denominator
_CAPABILITY_DENOMINATOR = frozenset({"SOLVED", "SURRENDER"})

#: dispositions reported separately, never as a strategic choice
_REPORTED_SEPARATELY = frozenset({"OUT_OF_SCOPE", "INFRA", "FAILED"})


# ------------------------------------------------------------- classification

def _both_wall_legs(wall) -> bool:
    """Censoring needs BOTH legs as strict booleans — a one-legged wall,
    a string ``"true"``, or any non-mapping is not evidence."""
    return (isinstance(wall, dict)
            and wall.get("session_bound") is True
            and wall.get("corroborated") is True)


def wall_evidence(*, wall=None) -> dict | None:
    """The two-leg wall dict, or None.

    A wall counts only when BOTH strict legs are present — the same
    anti-laundering rule the algebra applies. A one-legged wall, a string
    ``"true"``, or any non-mapping is not evidence."""
    if _both_wall_legs(wall):
        return {"session_bound": True, "corroborated": True}
    return None


def _interruption_wall(session_record, ws) -> dict | None:
    """Re-run the interruption classifier and translate its verdict.

    The ``censored_env`` class is derived HERE from the session record
    and the workspace's blockers — the caller supplies evidence, never
    the class word. The classifier emits ``censored_env`` only for a
    session-bound blocker corroborated per its own table, so deriving
    the two legs from it is faithful."""
    if session_record is None or ws is None:
        return None
    verdict = interruption.classify(session_record, ws)
    if verdict.get("class") == interruption.CENSORED_ENV:
        return {"session_bound": True, "corroborated": True}
    return None


def classify_episode(record, *, session_record=None, ws=None,
                     wall=None) -> dict:
    """Classify one episode -> the algebra's ``{"disposition", "gate"}``.

    The wall gate is normalized first: a caller wall must carry both
    strict legs, and the interruption classifier is re-run over
    ``session_record`` + ``ws`` when supplied (the caller cannot pass a
    class word — the classifier derives it). Every other gate reads the
    record unmodified. The disposition vocabulary, precedence, and gate
    coupling belong to ``rlvr.disposition`` — this face adds evidence
    normalization only. A non-mapping record is delegated unmodified so
    the algebra's refusal stays the single contract."""
    if not isinstance(record, dict):
        return disposition.classify_episode(record)
    rec = dict(record)
    supplied = rec.get("wall") if wall is None else wall
    rec["wall"] = (wall_evidence(wall=supplied)
                   or _interruption_wall(session_record, ws))
    return disposition.classify_episode(rec)


def authorized_for(task_spec, target) -> bool:
    """True iff the task_spec authorization context covers ``target``.

    The dispatch copies this block verbatim; an absent or malformed
    context authorizes nothing, so the refusal classifies OUT_OF_SCOPE
    (the authorization face is the single scope reader)."""
    block = authorization.authorization_from_task_spec(task_spec)
    return authorization.authorized_target(block, target)


# ------------------------------------------------------------- reward face

def _credit(disposition_name: str, has_reproducible_evidence: bool) -> float:
    """The bounded credit of one disposition. SOLVED is the oracle lock;
    SURRENDER is the anti-surrender floor (0.0 without reproducible
    evidence, TRACE canonical with it); every other disposition settles
    0.0. Everything passes through the declared [0, 1] clamp."""
    if disposition_name == "SOLVED":
        return scalar.clamp_credit(scalar.ORACLE_PASS_LOCK)
    if disposition_name == "SURRENDER":
        floor = (scalar.TRACE_CANONICAL if has_reproducible_evidence
                 else 0.0)
        return scalar.clamp_credit(floor)
    return scalar.clamp_credit(0.0)


def _strategy_outcome(disposition_name: str) -> str | None:
    """The strategy-learning outcome word: solved episodes are positive
    samples, surrendered episodes are failure samples; the rest carry no
    strategic-choice signal."""
    if disposition_name == "SOLVED":
        return "positive"
    if disposition_name == "SURRENDER":
        return "failure"
    return None


def reward_for(disposition_name, *,
               has_reproducible_evidence: bool = False) -> dict:
    """The consumer mapping for one disposition (pure; credit bounded).

    Returns the credit, its declared rail, and the strategy/measurement
    verdict words consumers read: ``strategy_learning``,
    ``strategic_action_outcome``, ``capability_gap``,
    ``capability_denominator``, ``censoring``, ``reported_separately``.
    An unknown disposition raises — a word outside the closed vocabulary
    must never settle as a silent zero."""
    name = str(disposition_name or "").strip()
    if name not in disposition.DISPOSITIONS:
        raise ValueError(f"unknown disposition: {disposition_name!r}")
    credit = _credit(name, has_reproducible_evidence)
    return {
        "disposition": name,
        "credit": credit,
        "rail": scalar.rail_of(credit),
        "strategy_learning": name in _STRATEGY_LEARNING,
        "strategic_action_outcome": _strategy_outcome(name),
        "capability_gap": name == "ATTEMPTED_EXHAUSTED",
        "capability_denominator": name in _CAPABILITY_DENOMINATOR,
        "censoring": name == "CENSORED_ENV",
        "reported_separately": name in _REPORTED_SEPARATELY,
    }


# ------------------------------------------------------------- signal row

def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _signal_fail(field: str, why: str) -> ValueError:
    return ValueError(f"disposition-signal.{field}: {why}")


def _validate_signal_text(signal: dict) -> None:
    for field in ("episode_id", "claim"):
        value = signal.get(field)
        if not isinstance(value, str) or not value.strip():
            raise _signal_fail(field, "must be a non-empty string")
    ts = signal.get("ts")
    if not isinstance(ts, str) or not ts.strip():
        raise _signal_fail("ts", "must be a non-empty string")


def _validate_signal_choice(signal: dict) -> None:
    action = signal.get("strategic_action")
    propensity = signal.get("propensity")
    if action is not None and action not in disposition.STRATEGIC_ACTIONS:
        raise _signal_fail("strategic_action",
                           f"must be one of "
                           f"{disposition.STRATEGIC_ACTIONS} or None")
    if action is None:
        if propensity is not None:
            raise _signal_fail("propensity",
                               "requires a recorded strategic_action")
        return
    if not _is_number(propensity) or not 0.0 <= float(propensity) <= 1.0:
        raise _signal_fail("propensity",
                           "a recorded action requires a number in [0, 1]")


def validate_signal(signal) -> dict:
    """Fail-closed validation of one ``disposition-signal/1`` row.

    The row is bounded: fixed fields, credit and propensity inside
    [0, 1], and the credit/strategy words re-derived from
    ``reward_for`` (a hand-built row cannot claim a strategy signal the
    disposition mapping does not grant)."""
    if not isinstance(signal, dict):
        raise _signal_fail("row", "must be a dict")
    missing = [field for field in SIGNAL_FIELDS if field not in signal]
    if missing:
        raise _signal_fail("row", f"missing required field(s): {missing}")
    unknown = sorted(set(signal) - set(SIGNAL_FIELDS))
    if unknown:
        raise _signal_fail("row", f"unknown field(s): {unknown}")
    if signal.get("schema") != SIGNAL_SCHEMA:
        raise _signal_fail("schema", f"must be {SIGNAL_SCHEMA!r}")
    _validate_signal_text(signal)
    name = signal.get("disposition")
    if name not in disposition.DISPOSITIONS:
        raise _signal_fail("disposition",
                           f"must be one of {disposition.DISPOSITIONS}")
    credit = signal.get("credit")
    if not _is_number(credit) or not 0.0 <= float(credit) <= 1.0:
        raise _signal_fail("credit", "must be a number in [0, 1]")
    _validate_signal_choice(signal)
    if not isinstance(signal.get("strategy_learning"), bool):
        raise _signal_fail("strategy_learning", "must be a bool")
    if signal.get("strategic_action_outcome") not in SIGNAL_OUTCOMES:
        raise _signal_fail("strategic_action_outcome",
                           f"must be one of {SIGNAL_OUTCOMES}")
    expected = reward_for(
        name, has_reproducible_evidence=(name == "SURRENDER"
                                         and float(credit) > 0.0))
    if float(credit) != expected["credit"]:
        raise _signal_fail("credit",
                           "contradicts the disposition reward mapping")
    if signal["strategy_learning"] != expected["strategy_learning"]:
        raise _signal_fail("strategy_learning",
                           "contradicts the disposition reward mapping")
    if (signal["strategic_action_outcome"]
            != expected["strategic_action_outcome"]):
        raise _signal_fail("strategic_action_outcome",
                           "contradicts the disposition reward mapping")
    return signal


def build_signal(row, *, has_reproducible_evidence: bool = False,
                 ts: str) -> dict:
    """Shape one bounded signal from a validated ``disposition/1`` row.

    Pure: the caller supplies ``ts``. The source row is validated by the
    algebra's own row validator, so the signal can only carry a
    vocabulary word and evidence the disposition row already proved."""
    disposition.validate_row(row)
    face = reward_for(row["disposition"],
                      has_reproducible_evidence=has_reproducible_evidence)
    signal = {
        "schema": SIGNAL_SCHEMA,
        "episode_id": row["episode_id"],
        "claim": row["claim"],
        "disposition": row["disposition"],
        "credit": face["credit"],
        "strategic_action": row["strategic_action"],
        "propensity": row["propensity"],
        "strategy_learning": face["strategy_learning"],
        "strategic_action_outcome": face["strategic_action_outcome"],
        "ts": ts,
    }
    return validate_signal(signal)


def _event_detail(signal: dict) -> str:
    """The event's bounded detail (the signal minus its own stamp)."""
    return json.dumps(
        {field: signal[field] for field in SIGNAL_FIELDS
         if field != "schema"},
        ensure_ascii=False, sort_keys=True)


def _existing_signal(ws, signal: dict) -> bool:
    """One signal per episode: the episode id + claim identify a replay
    (the disposition row itself is never rewritten)."""
    for row in consolidated_ledger.read(
            ws, TELEMETRY_FAMILY, schema_prefix=SIGNAL_SCHEMA):
        if (row.get("episode_id") == signal["episode_id"]
                and row.get("claim") == signal["claim"]):
            return True
    return False


def _event_matches(line: str, signal: dict) -> bool:
    try:
        event = json.loads(line)
        if event.get("action") != EVENT:
            return False
        detail = json.loads(event.get("detail") or "{}")
    except (TypeError, ValueError):
        return False
    return (detail.get("episode_id") == signal["episode_id"]
            and detail.get("claim") == signal["claim"]
            and detail.get("disposition") == signal["disposition"])


def _event_exists(ws, signal: dict) -> bool:
    """An already-emitted signal event for THIS signal (retry dedupe:
    the event stream is append-only, so a healed retry must not add a
    second row for the same episode)."""
    logs = Path(ws) / "runs" / "logs"
    if not logs.is_dir():
        return False
    for path in sorted(logs.glob("kunglao-*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8",
                                   errors="replace").splitlines()
        except OSError as exc:
            warn("rlvr.disposition_reward.event_scan",
                 f"{path}: {type(exc).__name__}: {exc}")
            continue
        if any(_event_matches(line, signal) for line in lines):
            return True
    return False


def _emit_signal(ws, signal: dict) -> bool:
    return bool(emit(ws, "orchestrator", EVENT, claim=signal["claim"],
                     detail=_event_detail(signal)))


def _persist_signal(ws, signal: dict) -> dict:
    """Append the signal to the unified ledger and emit the registered
    event, keeping the two faces consistent on every retry.

    - the append is the admission ticket: an event is NEVER emitted for
      a row that did not land (a retry then appends once and emits once);
    - an existing row heals a missing event (the event stream is
      append-only, so the retry checks before emitting).
    The returned flags report the POST-CALL state."""
    validate_signal(signal)
    if _existing_signal(ws, signal):
        emitted = _event_exists(ws, signal) or _emit_signal(ws, signal)
        return {"signal": signal, "appended": False, "emitted": emitted}
    appended = bool(consolidated_ledger.append(
        ws, TELEMETRY_FAMILY, signal))
    if not appended:
        return {"signal": signal, "appended": False, "emitted": False}
    return {"signal": signal, "appended": True,
            "emitted": _emit_signal(ws, signal)}


def settle_disposition(ws, row, *,
                       has_reproducible_evidence: bool = False,
                       ts: str | None = None) -> dict:
    """Settle ONE disposition row's reward face.

    Builds the bounded signal and lands it. ``has_reproducible_evidence``
    is the settlement caller's reproducibility verdict (the same flag
    the trajectory settlement uses); the default settles the
    anti-surrender 0.0 floor. Returns
    ``{"signal", "appended", "emitted"}``."""
    if ts is None:
        from harness_common import utc_now_z  # noqa: PLC0415 — writer clock
        ts = utc_now_z()
    signal = build_signal(row, has_reproducible_evidence=has_reproducible_evidence,
                          ts=ts)
    return _persist_signal(ws, signal)


def settle_workspace(ws, *,
                     has_reproducible_evidence: bool = False,
                     ts: str | None = None) -> dict:
    """Settle every persisted disposition row's reward face.

    The mission-terminal sweep: reads ``runs/disposition/*.json`` and
    writes one signal per episode (replays skip). A corrupt or
    non-conforming row is reported (WARN + the ``failed`` list) and
    never blocks the other rows — the disposition row itself is the
    primary object. Returns ``{"settled", "skipped", "failed"}``."""
    ws = Path(ws)
    result: dict = {"settled": 0, "skipped": 0, "failed": []}
    base = ws / disposition.DISPOSITION_DIR
    if not base.is_dir():
        return result
    for path in sorted(base.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            out = settle_disposition(
                ws, row,
                has_reproducible_evidence=has_reproducible_evidence, ts=ts)
        except (OSError, ValueError) as exc:
            warn("rlvr.disposition_reward",
                 f"{path}: {type(exc).__name__}: {exc}")
            result["failed"].append(path.name)
            continue
        if out["appended"]:
            result["settled"] += 1
        else:
            result["skipped"] += 1
    return result


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
