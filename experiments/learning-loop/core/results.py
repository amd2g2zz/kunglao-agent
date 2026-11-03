# -*- coding: utf-8 -*-
"""core/results.py — the execution-result value objects (#878).

StepResult is what ONE dispatched step produced (verification verdict,
evidence refs, cost); RolloutResult aggregates a rollout's steps. The
credit face (#883) consumes these to compute R_t / A_t; the
settlement face (#884) banks them per dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StepResult:
    """The outcome of one step's execution."""

    step_id: str
    verified: bool
    evidence_refs: tuple[str, ...]
    summary: str
    cost: float
    verdict: str
    redteam: str | None
    confidence: float


@dataclass(frozen=True)
class RolloutResult:
    """The outcome of one full rollout (a serial step chain)."""

    rollout_id: str
    completed: bool
    steps: tuple[StepResult, ...]
    total_cost: float
