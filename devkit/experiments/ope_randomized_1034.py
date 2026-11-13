"""Controlled, in-memory randomization for OPE experiments only.

The evaluator owns the independent random stream and never accepts a claimed
probability or chosen action from a workspace audit record as a receipt.
"""
from __future__ import annotations

import math
import random
from collections.abc import Mapping

from rlvr import policy_compare


def draw(weights: Mapping[str, float], rng: random.Random) -> dict:
    """Draw once from fixed, observed nonnegative weights and record its law."""
    if not weights or any(not math.isfinite(float(v)) or float(v) <= 0
                          for v in weights.values()):
        raise ValueError('experiment support must contain positive finite weights')
    names = sorted(weights)
    scale = max(float(weights[name]) for name in names)
    scaled = [float(weights[name]) / scale for name in names]
    total = math.fsum(scaled)
    threshold = rng.random() * total
    cumulative = 0.0
    index = len(names) - 1
    for i, weight in enumerate(scaled):
        cumulative += weight
        if threshold < cumulative:
            index = i
            break
    return {'family': names[index], 'weights': dict(weights),
            'propensity': scaled[index] / total,
            'information_set': 'fixed_observed_weights',
            'probability_source': 'experiment_owned_rng'}


def verify_receipts(weights: Mapping[str, float], seed: int, receipts: list[dict]) -> bool:
    """Replay a separately supplied experimental design against each receipt.

    This checks consistency, not whether a caller actually randomized the seed.
    The design and seed must be provided separately from observed audit records.
    """
    rng = random.Random(seed)
    try:
        for receipt in receipts:
            expected = draw(weights, rng)
            if any(receipt.get(key) != value for key, value in expected.items()):
                return False
    except (TypeError, ValueError, OverflowError):
        return False
    return True


def evaluate(weights: Mapping[str, float], seed: int, rewards: Mapping[str, float],
             count: int) -> dict:
    """Generate and evaluate the control within this process, with replay seed.

    Only this caller-owned stream supplies draws; audit JSON cannot provide the
    actions or propensity. The future draw sequence is excluded from the stated
    information set. A seed is for replay, not evidence about a production RNG.
    """
    if count < 1 or set(rewards) != set(weights):
        raise ValueError('count and complete reward mapping required')
    if any(not math.isfinite(float(v)) for v in rewards.values()):
        raise ValueError('experiment rewards must be finite')
    rng = random.Random(seed)
    decisions = []
    for _ in range(count):
        receipt = draw(weights, rng)
        decisions.append({**receipt, 'reward': float(rewards[receipt['family']])})
    if not verify_receipts(weights, seed, decisions):
        raise ValueError('experimental receipt failed independent replay')
    estimates = {p: policy_compare.snips(decisions, p) for p in policy_compare.POLICIES}
    n = len(decisions)
    overlap = all(v['ess'] >= 20 and v['ess'] / n >= 0.2
                  and v['value'] is not None for v in estimates.values())
    return {'decisions': decisions, 'estimates': estimates,
            'verdict': 'exploratory' if overlap else 'insufficient_overlap'}
