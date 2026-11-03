# -*- coding: utf-8 -*-
"""core/state.py — the loop's ``State`` value object (#878).

The policy face's view of the world at one decision point: the goal
tree, the verified fact base, the memory face's distilled knowledge,
and the remaining resources. Frozen — a decision consumes a State and
PRODUCES a new one (the protocol's update step never mutates in
place, so the trajectory stays replayable).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .actions import Budget


@dataclass(frozen=True)
class State:
    """The ``s`` of the (s, a, r) triple at one decision point."""

    goal_tree: Mapping[str, Any]
    fact_base: tuple[str, ...]
    memory: Mapping[str, Any]
    resources: Budget
