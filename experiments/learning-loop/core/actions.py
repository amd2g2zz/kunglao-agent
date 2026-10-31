# -*- coding: utf-8 -*-
"""core/actions.py — the ``action/1`` schema: the closed action space.

The unified decision protocol (state -> candidates -> score -> select
-> execute -> record) acts ONLY through one of the ten closed action
kinds (#878). The LLM is a candidate-generator tool — it proposes; the
state-driven scoring face disposes — so an Action records what the
loop DECIDED, never what a model suggested. The parse face is the
fail-closed system boundary (the episode_schema validator posture):
an illegal action document raises ActionError, and the ledger face
downstream trusts these validated values (validation lives at the
boundary, not at every consumer).

#924: the parse boundary ALSO enforces the per-kind parameter spec
(``rlvr.action_params`` — the single source; re-exported here so a
re-implemented table next door cannot drift). WHY the scripts-side
import: the spec must be enforced at BOTH walls and the deployed
scripts tree cannot import experiments/ — experiments→scripts is the
loop's existing dependency direction.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

SCHEMA = "action/1"


class ActionError(ValueError):
    """A document is not a legal ``action/1`` action. Fail-closed."""


class ActionKind(Enum):
    """The closed action vocabulary — every decision the loop can act."""

    SELECT_TASK = "select_task"
    DECOMPOSE = "decompose"
    ASSIGN_STEP = "assign_step"
    PROBE = "probe"
    SWITCH_METHOD = "switch_method"
    TERMINATE_STEP = "terminate_step"
    TERMINATE_ROLLOUT = "terminate_rollout"
    ROLLBACK = "rollback"
    SPAWN_CANDIDATE = "spawn_candidate"
    MATERIALIZE = "materialize"


_KINDS = frozenset(k.value for k in ActionKind)

# after ActionKind — the spec table's keys resolve through it (the
# keys are validated against ActionKind by the #924 test pin, both
# directions fail-closed)
from rlvr import action_params as _ap  # noqa: E402 — the path bootstrap lands first


@dataclass(frozen=True)
class Budget:
    """The resources one action may spend (wall seconds; optional cap)."""

    wall_s: float
    max_calls: int | None = None


@dataclass(frozen=True)
class Context:
    """Where the action sits in the trajectory (rollout/step/policy)."""

    rollout_id: str
    step_id: str | None
    policy_version: str


@dataclass(frozen=True)
class Action:
    """One decided action — the ``a`` of the (s, a, r) triple."""

    kind: ActionKind
    target: str
    params: Mapping[str, Any]
    budget: Budget
    context: Context


def _fail(field: str, why: str) -> ActionError:
    return ActionError(f"action.{field}: {why}")


def _req(doc: Mapping, field: str):
    if field not in doc:
        raise _fail(field, "missing (schema action/1 requires it)")
    return doc[field]


def _non_empty_str(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, "must be a non-empty string")
    return value


def _real(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value):
        raise _fail(field, "must be a finite number")
    return float(value)


def action_to_doc(action: Action) -> dict:
    """The canonical ``action/1`` document for an Action (the ledger
    and review faces' persistence shape)."""
    return {
        "schema": SCHEMA,
        "kind": action.kind.value,
        "target": action.target,
        "params": dict(action.params),
        "budget": {"wall_s": action.budget.wall_s,
                   "max_calls": action.budget.max_calls},
        "context": {"rollout_id": action.context.rollout_id,
                    "step_id": action.context.step_id,
                    "policy_version": action.context.policy_version},
    }


def validate_action(doc: Mapping) -> dict:
    """Fail-closed ``action/1`` validation — returns the normalized
    document (params spec-complete: optional-absent at their explicit
    defaults, #924) or raises naming the offending field."""
    if not isinstance(doc, Mapping):
        raise _fail("doc", "must be a mapping")
    if doc.get("schema") != SCHEMA:
        raise _fail("schema", f"must be {SCHEMA!r}")
    kind = _non_empty_str(_req(doc, "kind"), "kind")
    if kind not in _KINDS:
        raise _fail("kind", f"{kind!r} outside the closed action space")
    _non_empty_str(_req(doc, "target"), "target")
    params = _req(doc, "params")
    if not isinstance(params, Mapping):
        raise _fail("params", "must be a mapping")
    # the #924 param wall: the ONE spec decides required/optional/
    # unknown — the boundary returns the EFFECTIVE params
    params = _ap.normalize_params(kind, params)
    budget = _req(doc, "budget")
    if not isinstance(budget, Mapping):
        raise _fail("budget", "must be a mapping")
    wall_s = _real(_req(budget, "wall_s"), "budget.wall_s")
    if wall_s < 0.0:
        raise _fail("budget.wall_s", "must be >= 0")
    max_calls = budget.get("max_calls")
    if max_calls is not None and (isinstance(max_calls, bool)
                                  or not isinstance(max_calls, int)
                                  or max_calls < 1):
        raise _fail("budget.max_calls", "must be None or an integer >= 1")
    context = _req(doc, "context")
    if not isinstance(context, Mapping):
        raise _fail("context", "must be a mapping")
    _non_empty_str(_req(context, "rollout_id"), "context.rollout_id")
    step_id = context.get("step_id")
    if step_id is not None:
        _non_empty_str(step_id, "context.step_id")
    _non_empty_str(_req(context, "policy_version"),
                   "context.policy_version")
    return {**dict(doc), "params": dict(params)}


def parse_action(doc: Mapping) -> Action:
    """Validate an ``action/1`` document and build the frozen Action —
    the Action carries the EFFECTIVE params (the spec-complete set,
    #924)."""
    doc = validate_action(doc)
    budget = doc["budget"]
    context = doc["context"]
    return Action(
        kind=ActionKind(doc["kind"]),
        target=doc["target"],
        params=dict(doc["params"]),
        budget=Budget(wall_s=float(budget["wall_s"]),
                      max_calls=budget.get("max_calls")),
        context=Context(rollout_id=context["rollout_id"],
                        step_id=context.get("step_id"),
                        policy_version=context["policy_version"]),
    )


def __getattr__(name: str):
    """The single-source re-exports (#924): the boundary face proves
    it consumes THE table, never a local re-implementation. Lazy — a
    module-level bind would run mid-import inside the spec table's own
    build cycle."""
    if name == "ACTION_PARAM_SPECS":
        return _ap.ACTION_PARAM_SPECS
    if name == "ActionParamError":
        return _ap.ActionParamError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
