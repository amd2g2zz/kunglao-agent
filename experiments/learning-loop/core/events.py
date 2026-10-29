# -*- coding: utf-8 -*-
"""core/events.py — the transition vocabulary between states (#878).

A Transition names HOW the state moved (the protocol's update step);
a TransitionEvent carries the move's payload — the causing action, the
step reward r_t when the move is reward-bearing, and the
transition-specific body. The observer hooks and the trajectory views
consume the event stream; nothing polls.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .actions import Action


class Transition(Enum):
    """The closed set of state-moving events."""

    TASK_SELECTED = "task_selected"
    STEP_ASSIGNED = "step_assigned"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    METHOD_SWITCHED = "method_switched"
    STEP_TERMINATED = "step_terminated"
    ROLLOUT_TERMINATED = "rollout_terminated"
    ROLLED_BACK = "rolled_back"
    CANDIDATE_SPAWNED = "candidate_spawned"
    ARTIFACT_MATERIALIZED = "artifact_materialized"


@dataclass(frozen=True)
class TransitionEvent:
    """One state move: what happened, where, why, and what it earned."""

    transition: Transition
    rollout_id: str
    step_id: str | None
    action: Action | None
    reward: float | None
    payload: Mapping[str, Any]
