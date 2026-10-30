# -*- coding: utf-8 -*-
"""credit/advantage.py — the advantage and its confidence modulation.

A_t = R_t − V(s_t): the return minus the decision-time value baseline
(the pool's value estimate for the state the step was decided from).
Cold start has no baseline — ``values=None`` is the PINNED V≡0 case
where the advantage IS the raw return (the expected early-training
behavior, never smoothed away). The EMxPG-style modulation weights
each advantage by its outcome confidence: a CONFIDENT correct step
banks full credit; an UNCERTAIN one is attenuated — the update size
tracks how much the verdict can be trusted.
"""
from __future__ import annotations

import numpy as np


def advantages(returns: np.ndarray,
               values: np.ndarray | None) -> np.ndarray:
    """A = R − V; ``values=None`` (or an all-zero array) is the cold
    start where A == R elementwise — exact, never approximated. A NaN
    return is rejected on EVERY path (a poisoned advantage would land
    in the ledger's A_t column and fabricate the policy update)."""
    r = np.asarray(returns, dtype=float)
    if r.ndim != 1 or not np.all(np.isfinite(r)):
        raise ValueError(
            "credit.advantage: returns must be finite and 1-d")
    if values is None:
        return r.copy()
    v = np.asarray(values, dtype=float)
    if v.shape != r.shape:
        raise ValueError(
            "credit.advantage: values must match the returns shape")
    if not np.all(np.isfinite(v)):
        raise ValueError("credit.advantage: values must be finite")
    return r - v


def modulate(adv: np.ndarray, confidence: np.ndarray) -> np.ndarray:
    """A_weighted = A · confidence — the confidence is the outcome
    evaluation's trust weight in [0, 1] (1.5 is a caller bug, not a
    boosted credit). The advantage is SIGNED: a confident FAILURE
    banks a more-negative update than an uncertain one — trust
    weighting is symmetric, the EMxPG posture (the update size tracks
    how much the verdict can be trusted, in both directions)."""
    a = np.asarray(adv, dtype=float)
    c = np.asarray(confidence, dtype=float)
    if a.size and not np.all(np.isfinite(a)):
        raise ValueError("credit.advantage: advantages must be finite")
    if a.shape != c.shape:
        raise ValueError(
            "credit.advantage: confidence must match the advantages")
    if c.size and (np.any(c < 0.0) or np.any(c > 1.0)
                   or not np.all(np.isfinite(c))):
        raise ValueError(
            "credit.advantage: confidence must lie in [0, 1]")
    return a * c
