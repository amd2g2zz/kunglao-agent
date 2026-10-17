# -*- coding: utf-8 -*-
"""scheduling_selection.py — the wake sampler's math, pure and IO-free.

The decision recorder (scripts/intelligent_scheduling.py) needs three
derived quantities, and all three are pure functions of numbers:

  width      k = min(free_slots, f(entropy)) — the entropy-derived
             demand, floored at one action, capped by the slot room. No
             branch tests the state against a threshold: f() names an
             AMOUNT, and the amount is the learnable prior's seat (the
             decision recorder supplies the day-one priors and logs what
             the width actually was).
  sampler    Gumbel top-k WITHOUT replacement: perturb every logit with
             Gumbel(0, 1) noise and take the ordered top k. By the
             Gumbel-max lemma the ordered draw is exactly a
             Plackett-Luce sample of k members without replacement.
  propensity the exact sampling probability of that draw: the product of
             the sequential softmax terms over the REMAINING candidates.
             This is what makes the wake decision off-policy evaluable —
             a deterministic top-k ranking cannot name a probability,
             which is why none of the tree's ranking helpers is reused
             here.

Kept separate from the recorder deliberately: pure math is replay-checked
without a workspace, and the recorder stays about state, records, and the
logging seat. Everything here is deterministic for an injected rng.
"""
from __future__ import annotations

import math

#: The width floor: never fewer than one action when the demand is read.
K_MIN = 1
#: Gumbel draws are clamped off the two singular points so both logs stay
#: finite; the clamp sits far below any distinguishable probability mass.
GUMBEL_EPS = 1e-12


def f_entropy(h_bits: float | None) -> int:
    """The entropy-derived exploration demand: max(K_MIN, ceil(h)) over
    the frontier entropy in bits. Unknown entropy (None, non-numbers,
    non-finite floats) -> K_MIN, the conservative floor — never a bigger
    commitment than the evidence supports."""
    if not isinstance(h_bits, (int, float)) or isinstance(h_bits, bool):
        return K_MIN
    value = float(h_bits)
    if not math.isfinite(value):
        return K_MIN
    return max(K_MIN, int(math.ceil(value)))


def adapt_k(entropy_bits: float | None, free_slots: int | None) -> int:
    """The selection width: k = min(free_slots, f(entropy)).

    free_slots None (no slot ledger) -> the demand stands alone; free_slots
    0 -> k = 0, the forced-null case (no room to act)."""
    demand = f_entropy(entropy_bits)
    if free_slots is None:
        return demand
    return max(0, min(int(free_slots), demand))


def gumbel_topk(logits: dict[str, float], k: int, rng) -> list[str]:
    """Gumbel top-k WITHOUT replacement: perturb every logit with
    Gumbel(0, 1) noise and take the top k in perturbed order (an ordered
    subset of distinct members — no replacement). Ties break on the
    sorted key, so replay is deterministic for a given rng stream."""
    keys = sorted(logits)
    width = max(0, min(int(k), len(keys)))
    scored: list[tuple[float, str]] = []
    for key in keys:
        u = min(max(rng.random(), GUMBEL_EPS), 1.0 - GUMBEL_EPS)
        gumbel = -math.log(-math.log(u))
        scored.append((float(logits[key]) + gumbel, key))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [key for _, key in scored[:width]]


def pl_terms(ordered: list[str], logits: dict[str, float]) -> list[float]:
    """The per-position Plackett-Luce terms: softmax over the REMAINING
    candidates at each step (max-subtracted, so extreme logits stay
    finite). The product is the ordered batch's sampling probability.
    [] when a name is not a candidate or the remaining mass degenerates."""
    remaining = sorted(logits)
    terms: list[float] = []
    for key in ordered:
        if key not in remaining:
            return []
        top = max(float(logits[r]) for r in remaining)
        weights = {r: math.exp(float(logits[r]) - top) for r in remaining}
        total = sum(weights.values())
        if not math.isfinite(total) or total <= 0:
            return []
        terms.append(weights[key] / total)
        remaining.remove(key)
    return terms


def pl_propensity(ordered: list[str], logits: dict[str, float]) -> float:
    """Exact sampling probability of the ordered selection: the product of
    the sequential Plackett-Luce terms. 0.0 when a name is not a candidate
    or the remaining mass is degenerate."""
    terms = pl_terms(ordered, logits)
    if len(terms) != len(ordered):
        return 0.0
    p = 1.0
    for t in terms:
        p *= t
    return round(p, 12)
