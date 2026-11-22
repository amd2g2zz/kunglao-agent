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
    if min(scaled) / total == 0:
        raise ValueError("controlled experiment support underflows")
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
    overlap = (not policy_compare.unobserved_families(decisions)
               and all(v['ess'] >= 20 and v['ess'] / n >= 0.2
                       and v['value'] is not None for v in estimates.values()))
    return {'decisions': decisions, 'estimates': estimates,
            'verdict': 'exploratory' if overlap else 'insufficient_overlap'}


def recorded_control(design: policy_compare.ControlledOPE, measure) -> dict:
    """Observe each independently drawn action and compare its recorded outcome."""
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from e2e import audit
    from rlvr import consolidated_ledger, learning_seal

    rng = random.Random(design.seed)
    with TemporaryDirectory(prefix='method-ope-') as directory:
        ws = Path(directory)
        for dispatch_id in design.decision_ids:
            receipt = draw(design.weights, rng)
            family = receipt['family']
            probability = {key: receipt[key] for key in
                           ('propensity', 'information_set', 'probability_source')}
            envelope = {**probability, 'dispatch_id': dispatch_id, 'family': family,
                        'candidates': {key: {'weight': w} for key, w in design.weights.items()}}
            if not audit.emit_method_family(ws, 'control', family, envelope=envelope):
                raise OSError('could not record controlled method receipt')
            transition = {**probability, 'schema': 'transition/1', 'dispatch_id': dispatch_id,
                          'a': family, 'probability_action': 'method_family',
                          'r_settle': measure(family)}
            if not consolidated_ledger.append(ws, 'experience', learning_seal.sign_row(transition)):
                raise OSError('could not record controlled method outcome')
        return policy_compare.compare(ws, bootstrap=0, experiment=design)


def sampler_calibration() -> list[dict]:
    """Audit the production proportional sampler against each draw's full support."""
    from rlvr import q_cells

    sig = 'aaaaaaaaaaaa'
    a, b = 'static-decompile', 'dynamic-trace'
    prior = {a: 0.9, b: 0.1}
    history = [{
        'schema': q_cells.OBS_SCHEMA, 'source': 'settlement', 'signature_hash': sig,
        'method_family': b, 'arm_key': q_cells.arm_key(b, 'facts_snapshot', 'none', 1),
        'dispatch_id': f'history-{i}', 'credit': 1.0, 'credit_kind': 'step',
    } for i in range(4)]
    cases = [('asymmetric', prior, [], None), ('history', prior, history, None),
             ('excluded', {a: 0.9}, history, None),
             ('downweighted', prior, history, {a: {'dead': True, 'weight_multiplier': 0.1}})]
    reports = []
    for name, candidates, rows, death in cases:
        store = q_cells.InMemoryStore(rows)
        observed = 0
        expected = variance = 0.0
        for seed in range(5000):
            receipt = q_cells.sample_method_family(
                sig, candidates, store, random.Random(seed), gamma=1.0, death=death)
            actual = receipt['candidates']
            assert set(actual) == set(candidates)
            if b in actual and rows:
                assert actual[b]['alpha'] > 1.0
            p = actual[a]['weight'] / math.fsum(row['weight'] for row in actual.values())
            observed += receipt['family'] == a
            expected += p
            variance += p * (1 - p)
        tolerance = 4 * math.sqrt(variance) + 1
        if abs(observed - expected) > tolerance:
            raise AssertionError(f'{name}: observed {observed}, expected {expected} ± {tolerance}')
        reports.append({'scenario': name, 'trials': 5000, 'observed_A': observed,
                        'expected_A': expected, 'tolerance_count': tolerance})
    return reports


if __name__ == '__main__':
    import json

    print(json.dumps(sampler_calibration(), indent=2))
