"""Controlled OPE experiment: independent actions are owned by the evaluator."""
import random

import pytest

from devkit.experiments import ope_randomized_1034 as exp


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
