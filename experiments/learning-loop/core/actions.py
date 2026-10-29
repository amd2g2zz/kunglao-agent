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
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

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
    document or raises ActionError naming the offending field."""
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
    return dict(doc)


def parse_action(doc: Mapping) -> Action:
    """Validate an ``action/1`` document and build the frozen Action."""
    validate_action(doc)
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
