# -*- coding: utf-8 -*-
"""learning-loop ``core`` — the canonical rl-v2 types (#878).

Pure value objects plus the fail-closed ``action/1`` validator: the
dependency FLOOR of the trajectory-semantics redesign. Zero logic,
zero repository imports — every downstream face (policy, credit,
settlement, the loop) consumes these types; nothing here consumes
anything. The unified decision protocol acts only through
``ActionKind``; the LLM stays a candidate-generator tool (the scoring
face is state-driven — no second authority).
"""
from __future__ import annotations

from .actions import (
    Action,
    ActionError,
    ActionKind,
    Budget,
    Context,
    action_to_doc,
    parse_action,
)
from .events import Transition, TransitionEvent
from .results import RolloutResult, StepResult
from .state import State

__all__ = [
    "Action",
    "ActionError",
    "ActionKind",
    "Budget",
    "Context",
    "RolloutResult",
    "State",
    "StepResult",
    "Transition",
    "TransitionEvent",
    "action_to_doc",
    "parse_action",
]
