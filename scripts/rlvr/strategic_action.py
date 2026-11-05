# -*- coding: utf-8 -*-
"""rlvr/strategic_action.py — the strategic route choice, recorded.

``FIGHT`` / ``BYPASS`` / ``INVEST`` exist in the action registry
(``scripts/action_space.py``, the STRATEGIC level) as vocabulary only;
this module makes the choice an ATTRIBUTED episode fact:

  - one ``strategic-action/1`` row per episode, recorded BEFORE
    termination, carrying the action and its propensity in [0, 1];
  - the row lands in the unified experience ledger
    (``consolidated_ledger.append(ws, "experience", row)`` — the learning
    feed), mirrored by the registered ``strategic_action_recorded`` event;
  - an episode with NO recorded action is not an error: it is the
    classifier's SURRENDER fall-through (``effective_action(None)`` ->
    ``SURRENDER``). The disposition algebra owns the precedence; this
    module only supplies the action face.

The words are DERIVED from the ``action_space`` STRATEGIC registry — never
restated here. Re-recording the identical row for an episode is idempotent
(a retry cannot double-book the choice); a divergent rewrite is refused —
an episode's strategic action, like its disposition, is never rewritten.
"""
from __future__ import annotations

import json
import math
from datetime import datetime

import action_space  # the STRATEGIC vocabulary owner (no copy of the words)
from kunglao_log import emit

from . import consolidated_ledger
from .disposition import _EPISODE_ID_RE  # the shared file-token contract

#: the row's schema stamp (the unified-ledger attribution contract)
SCHEMA = "strategic-action/1"

#: the registered telemetry event word
EVENT = "strategic_action_recorded"

#: the classifier's fall-through word when no action was recorded
SURRENDER = "SURRENDER"

#: the strategic vocabulary, derived from the action_space STRATEGIC level
STRATEGIC_ACTIONS = tuple(
    spec.name.split(".", 1)[1].upper()
    for spec in action_space.actions_of(action_space.STRATEGIC))

#: the row's identity timestamp format (the house ISO-8601 UTC stamp)
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

#: every field the `strategic-action/1` row carries
ROW_FIELDS = ("schema", "episode_id", "claim", "action", "propensity", "ts")


class StrategicActionError(ValueError):
    """An action record violates the `strategic-action/1` contract."""


def _nonempty_str(value) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    return token or None


def _is_real_number(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def effective_action(action) -> str:
    """The recorded action, or SURRENDER when none was recorded.

    Absence is NOT an error (the classifier's fall-through); an unknown
    word is (fail closed — a typo must never ride the learning feed).
    """
    if action is None:
        return SURRENDER
    if action in STRATEGIC_ACTIONS:
        return action
    raise StrategicActionError(
        f"unknown strategic action {action!r}; expected one of "
        f"{STRATEGIC_ACTIONS} or None")


def build_row(*, episode_id: str, claim: str, action: str,
              propensity: float, ts: str) -> dict:
    """Validate and shape one `strategic-action/1` row (pure)."""
    if not isinstance(episode_id, str) or not _EPISODE_ID_RE.fullmatch(
            episode_id):
        raise StrategicActionError(
            "episode_id must be a safe file token (letters, digits, '.', "
            "'_', '-')")
    claim_token = _nonempty_str(claim)
    if claim_token is None:
        raise StrategicActionError("claim must be a non-empty string")
    if action not in STRATEGIC_ACTIONS:
        raise StrategicActionError(
            f"action must be one of {STRATEGIC_ACTIONS} (an absent action "
            "is expressed as no row, never as a placeholder word)")
    if not _is_real_number(propensity) or not 0.0 <= propensity <= 1.0:
        raise StrategicActionError(
            "propensity must be a finite number in [0, 1]")
    if not isinstance(ts, str):
        raise StrategicActionError(
            "ts must be an ISO-8601 UTC second stamp (YYYY-MM-DDTHH:MM:SSZ)")
    try:
        datetime.strptime(ts, _TS_FORMAT)
    except ValueError as exc:
        raise StrategicActionError(
            "ts must be an ISO-8601 UTC second stamp (YYYY-MM-DDTHH:MM:SSZ)"
        ) from exc
    return {
        "schema": SCHEMA,
        "episode_id": episode_id,
        "claim": claim_token,
        "action": action,
        "propensity": propensity,
        "ts": ts,
    }


def _event_detail(row: dict) -> str:
    return json.dumps({
        "episode_id": row["episode_id"],
        "claim": row["claim"],
        "action": row["action"],
        "propensity": row["propensity"],
    }, ensure_ascii=False, sort_keys=True)


def read(ws) -> list[dict]:
    """Every recorded strategic-action row, oldest first."""
    return consolidated_ledger.read(ws, "experience", schema_prefix=SCHEMA)


def record(ws, *, episode_id: str, claim: str, action: str,
           propensity: float, ts: str) -> dict:
    """Record one episode's strategic action through the unified ledger.

    Returns ``{"row", "appended", "emitted"}``. The ledger append is the
    evidence-bearing write (the learning feed); the event is the
    observability mirror. A failed append is reported (``appended``
    False), never hidden — a choice with no ledger row did not happen.
    Re-recording the identical row is idempotent; a different action or
    propensity for the same episode is refused.
    """
    row = build_row(episode_id=episode_id, claim=claim, action=action,
                    propensity=propensity, ts=ts)
    existing = [r for r in read(ws) if r.get("episode_id") == episode_id]
    if existing:
        if all(r == row for r in existing):
            return {"row": row, "appended": False, "emitted": False}
        raise StrategicActionError(
            f"episode {episode_id!r} already carries a different strategic "
            "action row")
    appended = bool(consolidated_ledger.append(ws, "experience", row))
    emitted = bool(emit(ws, "orchestrator", EVENT, claim=row["claim"],
                        detail=_event_detail(row)))
    return {"row": row, "appended": appended, "emitted": emitted}


def disposition_fields(row: dict) -> dict:
    """The two fields a disposition record copies from an action row.

    The disposition object is the ONE consumer face: the action row stays
    the evidence, and the episode record carries exactly these fields
    before ``disposition.build_row`` classifies it.
    """
    if not isinstance(row, dict) or row.get("schema") != SCHEMA:
        raise StrategicActionError(
            f"row must be a {SCHEMA!r} object")
    missing = [field for field in ROW_FIELDS if field not in row]
    if missing:
        raise StrategicActionError(f"row missing required field(s): {missing}")
    return {"strategic_action": row["action"],
            "propensity": row["propensity"]}
