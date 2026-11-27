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

The module also owns the DISPATCH-DECLARATION face of the same stamp
(issue-1005, S5): the dispatch seam records its strategic route at the
ALLOW tail — a declared route with its behavior propensity, or the
honest gap (``declared: false`` / ``route: null``) when nothing was
declared, so silence can never be the norm. Declaration rows APPEND
(history — the LAST row is the live face, mirroring the strategy-log
reader) and carry ``{claim, route, propensity, declared, trace_id,
ts}``. At settle time the absence maps toward SURRENDER per the
disposition algebra (``absence_disposition``); the disposition producer
joins the LAST row per claim through ``disposition_fields``, which
speaks both faces of the stamp.
"""
from __future__ import annotations

import json
import math
from datetime import datetime

import action_space  # the STRATEGIC vocabulary owner (no copy of the words)
from kunglao_log import emit, warn

from . import consolidated_ledger
from . import disposition as _disposition
from .disposition import _EPISODE_ID_RE  # the shared file-token contract

#: the row's schema stamp (the unified-ledger attribution contract)
SCHEMA = "strategic-action/1"

#: the registered telemetry event word
EVENT = "strategic_action_recorded"

#: the documented residual word — the FALLBACK the derivation below
#: degrades to (with one warn) when the algebra's gate table ever drops
#: the unfinished face; a module import must never crash on a vocabulary
#: refactor (the disposition producer imports this module at module
#: level), it must degrade instead
_SURRENDER_SENTINEL = "SURRENDER"


def _derive_residual_word() -> str:
    """The residual disposition word, derived from the algebra's own
    vocabulary + gate table (imported, never restated or extended).
    Degrades to the documented sentinel when the unfinished gate is
    gone — never raises at import."""
    try:
        return next(
            word for word in _disposition.DISPOSITIONS
            if "unfinished" in _disposition.GATE_FOR_DISPOSITION.get(word, ()))
    except StopIteration:
        warn("rlvr.strategic_action",
             "disposition algebra carries no unfinished gate — residual "
             "word degraded to the documented sentinel")
        return _SURRENDER_SENTINEL


#: the classifier's fall-through word when no action was recorded
SURRENDER = _derive_residual_word()

#: the strategic vocabulary, derived from the action_space STRATEGIC level
STRATEGIC_ACTIONS = tuple(
    spec.name.split(".", 1)[1].upper()
    for spec in action_space.actions_of(action_space.STRATEGIC))

#: the row's identity timestamp format (the house ISO-8601 UTC stamp)
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

#: every field the `strategic-action/1` row carries
ROW_FIELDS = ("schema", "episode_id", "claim", "action", "propensity", "ts")

#: every field the dispatch-declaration row carries (the declaration face
#: of the same stamp — route/declared/trace_id instead of episode_id/action)
DECLARATION_FIELDS = ("schema", "claim", "route", "propensity",
                      "declared", "trace_id", "ts")

#: how many RECENT declaration rows the readers consider (the strategy-log
#: writer's cap pattern: the consolidated experience file is append-only
#: and grows one row per dispatch, so the per-dispatch reader faces bound
#: their window instead of scanning history without end). The prior share
#: is the RECENT behavior policy; the settle-side full join keeps its own
#: ``read()`` face.
DECLARATION_HISTORY_MAX = 200

#: the Laplace smoothing of the prior share: a route the workspace never
#: declared still keeps a positive propensity under any history (a
#: probability-0 draw for a taken action is invalid for IPS — the
#: propensity-coherence family's pathology), and the cold start falls out
#: as the exact uniform prior ((0 + alpha) / (0 + alpha * K) = 1 / K).
SMOOTHING_ALPHA = 1.0


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
    _validate_ts(ts)
    return {
        "schema": SCHEMA,
        "episode_id": episode_id,
        "claim": claim_token,
        "action": action,
        "propensity": propensity,
        "ts": ts,
    }


def _validate_ts(ts) -> None:
    """The shared identity-timestamp check (calendar-validated)."""
    if not isinstance(ts, str):
        raise StrategicActionError(
            "ts must be an ISO-8601 UTC second stamp (YYYY-MM-DDTHH:MM:SSZ)")
    try:
        datetime.strptime(ts, _TS_FORMAT)
    except ValueError as exc:
        raise StrategicActionError(
            "ts must be an ISO-8601 UTC second stamp (YYYY-MM-DDTHH:MM:SSZ)"
        ) from exc


# ------------------- the dispatch-declaration face -------------------

def build_declaration_row(*, claim: str, route, propensity, declared: bool,
                          trace_id, ts: str) -> dict:
    """Validate and shape one dispatch-declaration row (pure).

    A declared route carries the behavior propensity (the route's prior
    share under the workspace's own declaration history); an undeclared
    dispatch records the honest gap — ``declared: false`` with
    ``route: null`` and ``propensity: null`` (a propensity without a
    route would be a fabricated probability; a route word on a gap row
    would be a fabricated declaration). ``trace_id`` is optional (the
    mission chain id when the dispatch resolved one).
    """
    claim_token = _nonempty_str(claim)
    if claim_token is None:
        raise StrategicActionError("claim must be a non-empty string")
    if not isinstance(declared, bool):
        raise StrategicActionError("declared must be a bool")
    if trace_id is not None and _nonempty_str(trace_id) is None:
        raise StrategicActionError(
            "trace_id must be a non-empty string or None")
    _validate_ts(ts)
    if declared:
        if route not in STRATEGIC_ACTIONS:
            raise StrategicActionError(
                f"a declared row's route must be one of "
                f"{STRATEGIC_ACTIONS}; got {route!r}")
        if not _is_real_number(propensity) or not 0.0 <= propensity <= 1.0:
            raise StrategicActionError(
                "propensity must be a finite number in [0, 1]")
    else:
        if route is not None:
            raise StrategicActionError(
                "an undeclared dispatch carries no route (the honest gap "
                "is declared=false with route=null, never a route word)")
        if propensity is not None:
            raise StrategicActionError(
                "an undeclared dispatch carries no propensity (a "
                "propensity requires a declared route)")
    return {
        "schema": SCHEMA,
        "claim": claim_token,
        "route": route,
        "propensity": propensity,
        "declared": declared,
        "trace_id": _nonempty_str(trace_id),
        "ts": ts,
    }


def append_declaration(ws, row: dict) -> dict:
    """Append one dispatch-declaration row through the unified ledger.

    APPEND-only by contract: repeated dispatches preserve their history
    (the LAST row is the live face — the strategy-log reader's
    semantics), so there is no dedupe and no idempotence, and no event
    emission (the dispatch tail is high-frequency; the unified-log
    dispatch row is the observability face). The row is revalidated
    through the builder, so the file only ever carries builder-shaped
    rows. A failed append is reported (``appended`` False), never
    hidden.
    """
    if not isinstance(row, dict) or row.get("schema") != SCHEMA:
        raise StrategicActionError(f"row must be a {SCHEMA!r} object")
    missing = [field for field in DECLARATION_FIELDS if field not in row]
    if missing:
        raise StrategicActionError(
            f"row missing required field(s): {missing}")
    canonical = build_declaration_row(
        claim=row.get("claim"), route=row.get("route"),
        propensity=row.get("propensity"), declared=row.get("declared"),
        trace_id=row.get("trace_id"), ts=row.get("ts"))
    appended = bool(consolidated_ledger.append(ws, "experience", canonical))
    return {"row": canonical, "appended": appended}


def declaration_rows(ws, history_max: int = DECLARATION_HISTORY_MAX,
                     ) -> list[dict]:
    """The RECENT declaration-face rows, oldest first (episode-face rows
    — the ``action``/``episode_id`` shape — are excluded; at most the
    last ``history_max`` rows are considered, so the per-dispatch
    readers stay bounded over the append-only ledger)."""
    rows = [row for row in consolidated_ledger.read(
        ws, "experience", schema_prefix=SCHEMA)
        if isinstance(row, dict) and "declared" in row]
    if history_max is not None and history_max >= 0:
        rows = rows[-history_max:]
    return rows


def latest_declaration(ws, claim: str | None = None,
                       history_max: int = DECLARATION_HISTORY_MAX,
                       ) -> dict | None:
    """The live declaration face: the LAST declaration row (within the
    recent window), claim-scoped when a claim is given (the
    reversed-join the disposition producer uses; last-row-wins like the
    strategy-log reader). None on a cold workspace — the honest
    silence, never a fabricated row. The settle-side full join keeps
    its own ``read()`` face and is not windowed by this."""
    for row in reversed(declaration_rows(ws, history_max)):
        if claim is None or str(row.get("claim") or "") == claim:
            return row
    return None


def route_propensity(ws, route, history_max: int = DECLARATION_HISTORY_MAX,
                     ) -> float | None:
    """The behavior-policy propensity of a declared route: its
    Laplace-smoothed share of the workspace's PRIOR declared dispatch
    rows over the RECENT window (``(hits + alpha) / (total + alpha*K)``
    with the named module constants; the uniform prior over the closed
    set falls out on a cold workspace — the choice there is
    prior-only). The smoothing keeps a never-declared route strictly
    inside (0, 1): a probability-0 draw for a taken action is invalid
    for IPS, and a probability-1 draw would be the same pathology from
    the other end. None when no route was declared — the honest gap
    carries no propensity. Callers compute this BEFORE appending the
    dispatch's own row, so a choice never raises its own propensity.
    """
    if route not in STRATEGIC_ACTIONS:
        return None
    declared = [row for row in declaration_rows(ws, history_max)
                if row.get("declared") is True]
    alpha = SMOOTHING_ALPHA
    k = len(STRATEGIC_ACTIONS)
    hits = sum(1 for row in declared if row.get("route") == route)
    return round((hits + alpha) / (len(declared) + alpha * k), 6)


def absence_disposition(row) -> str | None:
    """The settle-side absence mapping (issue-1005 acceptance).

    A dispatch that declared no strategic route — a ``declared: false``
    row, or no row at all (``None``) — maps toward the disposition
    algebra's residual word (the unfinished gate's disposition). The
    word is the vocabulary's own (imported from ``rlvr.disposition``);
    the seven-word set is consumed here, never extended, and the
    episode classifier still owns the final verdict (an oracle pass
    outranks the residual — the precedence is the algebra's). A declared
    row maps nothing (``None``): the route is evidence for the episode
    record, not a disposition word.
    """
    if row is None:
        return SURRENDER
    if isinstance(row, dict) and row.get("schema") == SCHEMA \
            and row.get("declared") is False:
        return SURRENDER
    return None


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
    if not appended:
        # Admission-ticket rule (mirrors disposition_reward): an event is
        # never emitted for a row that did not land. The caller sees the
        # failed append; no observability row outlives its evidence.
        return {"row": row, "appended": False, "emitted": False}
    emitted = bool(emit(ws, "orchestrator", EVENT, claim=row["claim"],
                        detail=_event_detail(row)))
    return {"row": row, "appended": appended, "emitted": emitted}


def disposition_fields(row: dict) -> dict:
    """The two fields a disposition record copies from an action row.

    The disposition object is the ONE consumer face, and both shapes of
    the stamp flow through it: the episode row (the ``action`` field)
    and the dispatch-declaration row (the ``route``/``declared`` pair —
    a declared route becomes the strategic action, an explicit gap
    becomes the None face whose classifier residual is SURRENDER).
    """
    if not isinstance(row, dict) or row.get("schema") != SCHEMA:
        raise StrategicActionError(
            f"row must be a {SCHEMA!r} object")
    if "declared" in row:
        declared = row.get("declared")
        if declared is True:
            route = row.get("route")
            if route not in STRATEGIC_ACTIONS:
                raise StrategicActionError(
                    f"a declared row's route must be one of "
                    f"{STRATEGIC_ACTIONS}; got {route!r}")
            propensity = row.get("propensity")
            if not _is_real_number(propensity) \
                    or not 0.0 <= propensity <= 1.0:
                raise StrategicActionError(
                    "a declared row's propensity must be a finite number "
                    "in [0, 1]")
            return {"strategic_action": route, "propensity": propensity}
        if declared is False:
            if row.get("route") is not None \
                    or row.get("propensity") is not None:
                raise StrategicActionError(
                    "a gap row must carry route=null and propensity=null")
            # single-source the settle-side classification: the None face
            # IS the classifier's residual input, and the mapping helper
            # is its one derivation site (the gap maps toward SURRENDER —
            # anything else here means the row is not a gap row)
            if absence_disposition(row) != SURRENDER:
                raise StrategicActionError(
                    "a gap row must map toward the residual disposition")
            return {"strategic_action": None, "propensity": None}
        raise StrategicActionError("a declaration row's declared must be "
                                   "a bool")
    missing = [field for field in ROW_FIELDS if field not in row]
    if missing:
        raise StrategicActionError(f"row missing required field(s): {missing}")
    return {"strategic_action": row["action"],
            "propensity": row["propensity"]}
