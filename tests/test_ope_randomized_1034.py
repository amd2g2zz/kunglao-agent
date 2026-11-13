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
