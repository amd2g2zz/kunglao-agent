"""Controlled randomization for OPE experiments only.

The evaluator owns the independent random stream and never accepts a claimed
probability or chosen action from a workspace audit record as a receipt.
``recorded_control`` writes a temporary workspace through the real audit and
ledger writers before the comparison reads it. ``sampler_calibration`` holds
the production proportional sampler against the marginal law of each
configuration - a law stated by hand and integrated over its posterior draws,
never summed from the receipts' own weights. A failed check raises. Run:
``PYTHONPATH=scripts python -m devkit.experiments.ope_randomized_1034``.
"""
from __future__ import annotations

import math
import random
from collections.abc import Mapping

from rlvr import policy_compare

# the calibration protocol: independent per-trial seeds 0..TRIALS-1
TRIALS = 5000
A, B = 'static-decompile', 'dynamic-trace'
SIGNATURE = 'aaaaaaaaaaaa'


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


def marginal_choice(law: Mapping, chosen: str) -> tuple[float, float]:
    """P(chosen) and E[p(1-p)] of the proportional selection law - each
    family's weight is a coefficient times an independent Beta draw -
    integrated over the posterior draws. ``law`` states that law by hand,
    ``{family: ((alpha, beta), prior * modifier)}`` for one or two families
    with alpha, beta >= 1, so the expectation is a property of the law and
    cannot follow a receipt whose weights lost a prior or a modifier."""
    import numpy as np
    from numpy.polynomial.legendre import leggauss

    if chosen not in law or len(law) > 2:
        raise ValueError('the law names the chosen family and at most one rival')
    if len(law) == 1:
        return 1.0, 0.0
    nodes, weights = leggauss(128)
    theta = (nodes + 1.0) / 2.0
    mass, share = {}, {}
    for family, ((alpha, beta), coefficient) in law.items():
        norm = math.lgamma(alpha) + math.lgamma(beta) - math.lgamma(alpha + beta)
        mass[family] = np.exp((alpha - 1) * np.log(theta)
                              + (beta - 1) * np.log1p(-theta) - norm) * weights / 2
        share[family] = coefficient * theta
    rival = next(family for family in law if family != chosen)
    p = share[chosen][:, None] / (share[chosen][:, None] + share[rival][None, :])
    joint = mass[chosen][:, None] * mass[rival][None, :]
    return float((joint * p).sum()), float((joint * p * (1 - p)).sum())


def measure_selection(name: str, candidates: Mapping[str, float], rows: list[dict],
                      death: Mapping | None, law: Mapping, *,
                      gamma: float = 1.0) -> dict:
    """Run one configuration over seeds 0..TRIALS-1 and return A's observed
    count beside the count ``law`` predicts. Raises when a receipt leaves the
    requested support or drops the credited history from its posterior;
    whether the two counts agree is the caller's call. ``rows`` are sealed
    the way the production writer seals a q-cell row: armed, the fold
    refuses a row without a seal."""
    from rlvr import learning_seal, q_cells

    store = q_cells.InMemoryStore(learning_seal.sign_row(row) for row in rows)
    observed = 0
    for seed in range(TRIALS):
        receipt = q_cells.sample_method_family(
            SIGNATURE, candidates, store, random.Random(seed), gamma=gamma, death=death)
        actual = receipt['candidates']
        if set(actual) != set(candidates):
            raise RuntimeError(f'{name}: the receipt names candidates {sorted(actual)}; '
                               f'the requested support is {sorted(candidates)}')
        if B in actual and rows and not actual[B]['alpha'] > 1.0:
            raise RuntimeError(f'{name}: the credited history did not move the posterior of {B} '
                               f'(alpha {actual[B]["alpha"]})')
        observed += receipt['family'] == A
    probability, spread = marginal_choice(law, A)
    return {'scenario': name, 'trials': TRIALS, 'observed_A': observed,
            'expected_A': TRIALS * probability,
            'tolerance_count': 4 * math.sqrt(TRIALS * spread) + 1}


def sampler_calibration() -> list[dict]:
    """Audit the production proportional sampler against each configuration's
    marginal law (fixed gamma=1; A is the counted family)."""
    from rlvr import q_cells

    history = [{
        'schema': q_cells.OBS_SCHEMA, 'source': 'settlement', 'signature_hash': SIGNATURE,
        'method_family': B, 'arm_key': q_cells.arm_key(B, 'facts_snapshot', 'none', 1),
        'dispatch_id': f'history-{i}', 'credit': 1.0, 'credit_kind': 'step',
    } for i in range(4)]
    # The law of each configuration, stated by hand - never read off a
    # receipt. A family without settled credit draws from Beta(1,1); four
    # credited B settlements and no failure enter B's shrunk family anchor
    # with mean (1+4)/(2+4) at weight min(8, 4), so B draws from
    # Beta(1 + 4*5/6, 1 + 4/6) = Beta(13/3, 5/3). A coefficient is the
    # prior times the death multiplier.
    cold, credited = (1.0, 1.0), (13.0 / 3, 5.0 / 3)
    prior = {A: 0.9, B: 0.1}
    dead_a = {A: {'dead': True, 'weight_multiplier': 0.1}}
    cases = [
        ('asymmetric', prior, [], None, {A: (cold, 0.9), B: (cold, 0.1)}),
        ('history', prior, history, None, {A: (cold, 0.9), B: (credited, 0.1)}),
        ('excluded', {A: 0.9}, history, None, {A: (cold, 0.9)}),
        ('downweighted', prior, history, dead_a, {A: (cold, 0.09), B: (credited, 0.1)}),
    ]
    reports = []
    for name, candidates, rows, death, law in cases:
        report = measure_selection(name, candidates, rows, death, law)
        if abs(report['observed_A'] - report['expected_A']) > report['tolerance_count']:
            raise AssertionError(f"{name}: observed {report['observed_A']}, "
                                 f"expected {report['expected_A']} "
                                 f"± {report['tolerance_count']}")
        reports.append(report)
    return reports


if __name__ == '__main__':
    import json

    print(json.dumps(sampler_calibration(), indent=2))
