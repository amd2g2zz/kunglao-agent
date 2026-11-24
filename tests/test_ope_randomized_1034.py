"""Controlled OPE experiment: independent actions are owned by the evaluator."""
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from devkit.experiments import ope_randomized_1034 as exp
from e2e.checkpoints import _stamp_ope_propensity
from rlvr import learning_seal, q_cells
from rlvr import policy_compare as pc

ROOT = Path(__file__).resolve().parents[1]
A, B = 'static-decompile', 'dynamic-trace'
TRIALS = 5000
# design.md, the calibration record: each configuration's observed A count,
# the expected count and the tolerance the protocol fixed beforehand.
RECORDED = {
    'asymmetric': (4177, 4208.02, 92.2),
    'history': (3939, 3957.97, 103.9),
    'excluded': (5000, 5000.0, 1.0),
    'downweighted': (1789, 1794.77, 128.1),
}
# the same selection laws integrated over their posterior draws. This is the
# comparison target: a property of the law, so it stays put when a receipt's
# own weights move. (The recorded expectations are the realized draws'
# conditional probabilities; each carries roughly 12 counts of draw noise.)
LAW_TARGET = {
    'asymmetric': 4231.00,
    'history': 3967.28,
    'excluded': 5000.0,
    'downweighted': 1793.81,
}


def test_seeded_fixed_weight_control_replays_and_matches_distribution():
    weights = {'a': 0.9, 'b': 0.1}
    first = exp.evaluate(weights, 31, {'a': 1, 'b': 0}, 2000)
    second = exp.evaluate(weights, 31, {'a': 1, 'b': 0}, 2000)
    assert first == second
    count_a = sum(x['family'] == 'a' for x in first['decisions'])
    assert abs(count_a / 2000 - 0.9) < 0.03
    assert all(x['propensity'] == pytest.approx(0.9 if x['family'] == 'a' else 0.1)
               for x in first['decisions'])
    assert first['verdict'] == 'exploratory'


def test_insufficient_overlap_and_invalid_support_are_not_ranked():
    result = exp.evaluate({'a': 1, 'b': 1}, 3, {'a': 1, 'b': 0}, 10)
    assert result['verdict'] == 'insufficient_overlap'
    from rlvr import policy_compare as pc
    scarce = {'head': 0.999, 'whole': 0.001}
    design = pc.ControlledOPE(seed=31, weights=scarce, decision_ids=[f'id{i}' for i in range(48)])
    measured = exp.recorded_control(design, lambda family: float(family == 'whole'))
    assert measured['decisions'] == 48 and measured['verdict'] == 'insufficient_overlap'
    assert measured['missing_target_families'] == ['whole']
    assert exp.evaluate(scarce, 31, {'head': 0, 'whole': 1}, 48)['verdict'] == 'insufficient_overlap'
    with pytest.raises(ValueError, match='support'):
        pc.ControlledOPE(seed=31, weights={'head': 1e308, 'whole': 1e-308}, decision_ids=['id1'])
    with pytest.raises(ValueError):
        exp.draw({'a': 1, 'b': 0}, random.Random(0))
    with pytest.raises(ValueError):
        exp.evaluate({'a': 1, 'b': 1}, 3, {'a': 1}, 10)


def test_experiment_rejects_receipt_tampering_and_information_set_mismatch():
    result = exp.evaluate({'a': 0.9, 'b': 0.1}, 31, {'a': 1, 'b': 0}, 50)
    rows = result['decisions']
    assert exp.verify_receipts({'a': 0.9, 'b': 0.1}, 31, rows)
    tampered = [dict(row) for row in rows]
    tampered[0]['propensity'] = 0.123
    assert not exp.verify_receipts({'a': 0.9, 'b': 0.1}, 31, tampered)
    assert not exp.verify_receipts({'a': 0.8, 'b': 0.2}, 31, rows)
    tampered[0] = {**rows[0], 'information_set': 'state_only'}
    assert not exp.verify_receipts({'a': 0.9, 'b': 0.1}, 31, tampered)


def test_recorded_control_measures_an_existing_js_fixture():
    from pathlib import Path
    from rlvr import policy_compare as pc

    fixture = Path(__file__).parent / 'fixtures/web751/unpacked/src/sign.js'
    design = pc.ControlledOPE(seed=31, weights={'head': 1, 'whole': 1},
                              decision_ids=[f'run-{n}' for n in range(48)])

    def measure(action):
        source = fixture.read_text(encoding='utf-8')
        visible = source if action == 'whole' else source.splitlines()[0]
        return float('function buildSignature(' in visible)

    result = exp.recorded_control(design, measure)
    assert result['decisions'] == 48
    assert not any(result['experiment_integrity'].values())
    assert result['policies']['uniform']['snips'] == pytest.approx(
        sum(row['family'] == 'whole' for row in design.receipts().values()) / 48)


@pytest.fixture(scope='module')
def calibration():
    """The four recorded configurations over seeds 0..4999, run once."""
    return {row['scenario']: row for row in exp.sampler_calibration()}


@pytest.mark.parametrize('scenario', sorted(RECORDED))
def test_observed_count_stays_inside_the_recorded_tolerance(calibration, scenario):
    # Arrange
    _, expected, tolerance = RECORDED[scenario]

    # Act
    observed = calibration[scenario]['observed_A']

    # Assert
    assert abs(observed - expected) <= tolerance


@pytest.mark.parametrize('scenario', sorted(LAW_TARGET))
def test_comparison_target_is_the_law_itself_not_the_receipts_own_weights(calibration, scenario):
    # Act
    target = calibration[scenario]['expected_A']

    # Assert
    assert target == pytest.approx(LAW_TARGET[scenario], abs=0.05)


def test_sampler_that_stops_applying_the_prior_is_refused(monkeypatch):
    # Arrange
    monkeypatch.setattr(q_cells, '_normalize_prior',
                        lambda prior: {family: 1.0 for family in prior})

    # Act
    def calibrate():
        return exp.sampler_calibration()

    # Assert
    with pytest.raises(AssertionError, match='asymmetric: observed'):
        calibrate()


@pytest.mark.parametrize('damage, refusal', [
    # a zero-weight candidate outside the requested support rides the receipt
    ("receipt['candidates']['unrequested'] = {'weight': 0.0}", 'the requested support is'),
    # a credited family's posterior ignores its history
    ("receipt['candidates'].get('dynamic-trace', {}).update(alpha=1.0)", 'did not move'),
], ids=['support', 'posterior'])
def test_receipt_checks_hold_under_optimized_python(damage, refusal):
    # Arrange
    code = (
        'from rlvr import q_cells\n'
        'draw = q_cells.sample_method_family\n'
        'def damaged(*args, **kwargs):\n'
        '    receipt = draw(*args, **kwargs)\n'
        f'    {damage}\n'
        '    return receipt\n'
        'q_cells.sample_method_family = damaged\n'
        'from devkit.experiments import ope_randomized_1034 as experiment\n'
        'experiment.sampler_calibration()\n'
    )

    # Act
    completed = subprocess.run(
        [sys.executable, '-O', '-c', code], cwd=ROOT, capture_output=True, text=True,
        env={**os.environ,
             'PYTHONPATH': os.pathsep.join((str(ROOT), str(ROOT / 'scripts')))},
        timeout=600)

    # Assert
    assert refusal in completed.stderr, completed.stderr


class _SamplerControl(pc.ControlledOPE):
    """A preregistered design that owns the production sampler's seed and
    candidate prior: its receipts are regenerated by replaying the sampler
    from them, never read from the workspace."""

    def __init__(self, *, seed, weights, decision_ids):
        super().__init__(seed=seed, weights=weights, decision_ids=decision_ids)

    def draw(self, index):
        return q_cells.sample_method_family(
            'aaaaaaaaaaaa', self.weights, q_cells.InMemoryStore(()),
            random.Random(self.seed + index), gamma=1.0)

    def receipts(self):
        receipts = {}
        for index, decision_id in enumerate(self.decision_ids):
            receipt = self.draw(index)
            weights = {family: row['weight'] for family, row in receipt['candidates'].items()}
            # what the production dispatcher's stamp puts on this draw: the
            # chosen family's weight share under the law that made it
            receipts[decision_id] = {
                'family': receipt['family'], 'weights': weights,
                'propensity': round(weights[receipt['family']] / sum(weights.values()), 4),
                'information_set': None, 'probability_source': 'selection_law_exact'}
        return receipts


@pytest.fixture(scope='module')
def stamped_population(tmp_path_factory):
    """TRIALS executions of the asymmetric configuration, each stamped the
    way the production dispatcher stamps a draw, then compared through the
    workspace alone. The rows are written in bulk and are not the on-disk
    shape of the real writers: the audit row is a 4-field `event` row with
    `detail` as an object, where `audit.emit_method_family` writes a
    17-field row that names the kind in `action` and carries `detail` as
    JSON text; the transition row is the controlled experiment's
    (`recorded_control`) without `information_set`. `compare` reads both
    audit shapes the same way (`event` or `action`, `detail` an object or
    JSON text), and this population written through
    `audit.emit_method_family` and `consolidated_ledger.append` gives the
    same report apart from its `ts` and `workspace`. Bulk is kept for
    cost: the real writers took a few seconds more for this population
    when measured (under 1 ms a row for the two writes). In this file,
    `compare` admits rows written through those two writers in the two
    tests of `recorded_control`
    (`test_recorded_control_measures_an_existing_js_fixture` and
    `test_insufficient_overlap_and_invalid_support_are_not_ranked`, 48
    each); the claim-keyed tests in tests/test_behavior_propensity_1034.py
    run the production writers and assert only that everything is
    unbound."""
    design = _SamplerControl(seed=0, weights={A: 0.9, B: 0.1},
                             decision_ids=[f'{index:012x}' for index in range(TRIALS)])
    audits, transitions = [], []
    for index, decision_id in enumerate(design.decision_ids):
        receipt = design.draw(index)
        family = receipt['family']
        _stamp_ope_propensity(None, receipt, False, family, None)
        receipt['dispatch_id'] = decision_id
        audits.append(json.dumps({
            'event': 'method_family_recorded', 'claim': 'C-sampler', 'arm': family,
            'detail': {'method_family': family, 'envelope': receipt}}) + '\n')
        transitions.append(json.dumps(learning_seal.sign_row({
            'schema': 'transition/1', 'dispatch_id': decision_id, 'a': family,
            'probability_action': 'method_family',
            'propensity': receipt['propensity'],
            'probability_source': receipt['probability_source'],
            'r_settle': float(family == A)})) + '\n')
    ws = tmp_path_factory.mktemp('stamped-sampler')
    (ws / 'runs/logs').mkdir(parents=True)
    (ws / 'runs/logs/e2e-audit.jsonl').write_text(''.join(audits))
    (ws / 'runs/experience.jsonl').write_text(''.join(transitions))
    return design, pc.compare(ws, bootstrap=0, experiment=design)


def test_compare_admits_every_execution_the_production_stamp_bound(stamped_population):
    # Act
    report = stamped_population[1]

    # Assert
    assert report['decisions'] == TRIALS


def test_compare_recovers_the_recorded_frequency_of_the_stamped_sampler(stamped_population):
    # Arrange
    count, expected, tolerance = RECORDED['asymmetric']

    # Act
    estimate = stamped_population[1]['policies']['thompson']['snips']

    # Assert
    assert abs(estimate - expected / TRIALS) <= tolerance / TRIALS
    assert estimate == pytest.approx(count / TRIALS, abs=1e-3)


def test_history_discount_is_a_modifier_that_enters_the_weights():
    # Arrange
    history = [{'schema': q_cells.OBS_SCHEMA, 'source': 'settlement',
                'signature_hash': 'aaaaaaaaaaaa', 'method_family': B,
                'arm_key': q_cells.arm_key(B, 'facts_snapshot', 'none', 1),
                'dispatch_id': f'history-{i}', 'credit': 1.0, 'credit_kind': 'step'}
               for i in range(4)]
    # stated by hand: gamma=0.25 leaves 1 + .25 + .25^2 + .25^3 of credited
    # success, so B's shrunk anchor has that weight and the mean (1 + m)/(2 + m)
    mass = 1 + 0.25 + 0.25 ** 2 + 0.25 ** 3
    discounted = (1 + mass * (1 + mass) / (2 + mass), 1 + mass / (2 + mass))
    law = {A: ((1.0, 1.0), 0.9), B: (discounted, 0.1)}

    # Act
    row = exp.measure_selection('discounted', {A: 0.9, B: 0.1}, history, None, law, gamma=0.25)

    # Assert
    assert abs(row['observed_A'] - row['expected_A']) <= row['tolerance_count']


def test_credited_history_moves_the_posterior_on_a_host_with_an_armed_learning_seal(
        tmp_path, monkeypatch):
    # Arrange
    # the key lives in this test's directory: the host's real key is never read.
    # Armed, the production fold refuses every row that carries no seal.
    key = tmp_path / 'key'
    key.write_bytes(b'k' * 64)
    monkeypatch.setattr(learning_seal, 'KEY_PATH', key)
    # the seal anchors its build once per process: anchor it here, not on a
    # version another test left behind (tests/test_seal_799.py does the same)
    monkeypatch.setattr(learning_seal, '_ANCHOR', {'build': None})
    history = [{'schema': q_cells.OBS_SCHEMA, 'source': 'settlement',
                'signature_hash': 'aaaaaaaaaaaa', 'method_family': B,
                'arm_key': q_cells.arm_key(B, 'facts_snapshot', 'none', 1),
                'dispatch_id': f'history-{i}', 'credit': 1.0, 'credit_kind': 'step'}
               for i in range(4)]
    law = {A: ((1.0, 1.0), 0.9), B: ((13.0 / 3, 5.0 / 3), 0.1)}

    # Act
    row = exp.measure_selection('history', {A: 0.9, B: 0.1}, history, None, law)

    # Assert
    # the act cannot arm or disarm the channel, so the precondition is checked
    # here with the outcome: unarmed, the count below would pass as well
    assert learning_seal.armed(), 'the isolated key did not arm the learning channel'
    assert abs(row['observed_A'] - row['expected_A']) <= row['tolerance_count']
