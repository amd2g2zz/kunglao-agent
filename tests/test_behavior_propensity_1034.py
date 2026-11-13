"""Reject unsupported behavior propensities using synthetic workspaces."""
import json
from types import SimpleNamespace

from rlvr import consolidated_ledger as cl
from rlvr import policy_compare as pc
from e2e.checkpoints import _stamp_ope_propensity


def _record(ws, claim, family, *, propensity=0.5, reward=1.0, **env_extra):
    (ws / 'runs' / 'logs').mkdir(parents=True, exist_ok=True)
    env = {'family': family, 'propensity': propensity,
           'candidates': {'a': {'weight': 1.0}, 'b': {'weight': 1.0}}}
    env.update(env_extra)
    with (ws / 'runs' / 'logs' / 'e2e-audit.jsonl').open('a') as f:
        f.write(json.dumps({'event': 'method_family_recorded', 'claim': claim,
                            'detail': {'method_family': family, 'envelope': env}}) + '\n')
    transition = {'schema': 'transition/1', 'dispatch_id': claim, 'a': family,
                  'propensity': propensity}
    if reward != 'absent':
        transition['r_incr'] = reward
    assert cl.append(ws, 'experience', transition)


def test_historical_numeric_probability_is_not_behavior_probability(tmp_path):
    ws = tmp_path / 'ws'
    _record(ws, 'C1', 'a')
    report = pc.compare(ws, bootstrap=0)
    assert report['decisions'] == 0
    assert report['skipped_unknown_probability'] == 1
    assert report['verdict'] == 'underpowered'


def test_default_and_uniform_stamps_are_unknown(tmp_path):
    for scheduler in ('learned', 'uniform'):
        receipt = {'family': 'a', 'scheduler': scheduler,
                   'candidates': {'a': {'weight': 1}, 'b': {'weight': 1}}}
        _stamp_ope_propensity(SimpleNamespace(repo=tmp_path, ws=tmp_path), receipt, False, 'a', None)
        assert receipt['propensity'] is None
        assert receipt['probability_source'] == 'unknown'


def test_repeated_claim_family_never_joins_last_receipt(tmp_path):
    ws = tmp_path / 'ws'
    _record(ws, 'C1', 'a', probability_source='legacy_mc_estimate')
    _record(ws, 'C1', 'a', probability_source='legacy_mc_estimate')
    report = pc.compare(ws, bootstrap=0)
    assert report['decisions'] == 0
    assert report['skipped_ambiguous_dispatch'] == 2


def test_randomized_label_alone_does_not_authorize_probability(tmp_path):
    ws = tmp_path / 'ws'
    _record(ws, 'C1', 'a', probability_source='randomized_control')
    report = pc.compare(ws, bootstrap=0)
    assert report['decisions'] == 0
    assert report['skipped_unknown_probability'] == 1


def test_invalid_probability_and_support_are_counted_without_crashing(tmp_path):
    ws = tmp_path / 'ws'
    _record(ws, 'C1', 'a', propensity=float('nan'))
    _record(ws, 'C2', 'a', propensity='bad')
    _record(ws, 'C3', 'a', candidates={'b': {'weight': 1}})
    report = pc.compare(ws, bootstrap=0)
    assert report['decisions'] == 0
    assert report['skipped_invalid_probability'] == 2
    assert report['skipped_invalid_support'] == 1


def test_trusted_control_design_replays_through_real_compare(tmp_path):
    ws = tmp_path / 'ws'
    design = pc.ControlledOPE(seed=7, weights={'a': 1.0, 'b': 1.0},
                              decision_ids=[f'C{i}' for i in range(50)])
    for claim, receipt in design.receipts().items():
        _record(ws, claim, receipt['family'], propensity=receipt['propensity'],
                candidates={k: {'weight': v} for k, v in receipt['weights'].items()},
                probability_source=receipt['probability_source'],
                information_set=receipt['information_set'])
    report = pc.compare(ws, bootstrap=0, experiment=design)
    assert report['decisions'] == 50
    assert isinstance(report['verdict'], dict)


def test_trusted_control_rejects_tampered_receipt_and_missing_context(tmp_path):
    ws = tmp_path / 'ws'
    design = pc.ControlledOPE(seed=7, weights={'a': 1.0, 'b': 1.0}, decision_ids=['C1'])
    receipt = design.receipts()['C1']
    _record(ws, 'C1', receipt['family'], propensity=0.1,
            candidates={k: {'weight': v} for k, v in receipt['weights'].items()},
            probability_source='experiment_owned_rng', information_set='fixed_observed_weights')
    report = pc.compare(ws, bootstrap=0, experiment=design)
    assert report['decisions'] == 0
    assert report['skipped_experiment_mismatch'] == 1


def test_experiment_missing_context_and_override_never_enter_compare(tmp_path):
    ws = tmp_path / 'ws'
    design = pc.ControlledOPE(seed=11, weights={'a': 1.0, 'b': 1.0},
                              decision_ids=['C1', 'C2'])
    receipts = design.receipts()
    for claim, receipt in receipts.items():
        extra = {'probability_source': receipt['probability_source']}
        if claim == 'C2':
            extra.update(information_set=receipt['information_set'], family_override=True)
        _record(ws, claim, receipt['family'], propensity=receipt['propensity'],
                candidates={k: {'weight': v} for k, v in receipt['weights'].items()}, **extra)
    result = pc.compare(ws, bootstrap=0, experiment=design)
    assert result['decisions'] == 0
    assert result['skipped_experiment_mismatch'] == 2


def test_experiment_low_ess_never_produces_ranking(tmp_path):
    ws = tmp_path / 'ws'
    design = pc.ControlledOPE(seed=3, weights={'a': 0.99, 'b': 0.01},
                              decision_ids=[f'C{i}' for i in range(500)])
    for claim, receipt in design.receipts().items():
        _record(ws, claim, receipt['family'], propensity=receipt['propensity'],
                candidates={k: {'weight': v} for k, v in receipt['weights'].items()},
                probability_source=receipt['probability_source'],
                information_set=receipt['information_set'])
    result = pc.compare(ws, bootstrap=0, experiment=design)
    assert result['decisions'] == 500
    assert result['verdict'] == 'insufficient_overlap'
    assert result['policies']['uniform']['ess'] / 500 < 0.2


def test_malformed_hidden_candidate_cannot_be_dropped_from_support(tmp_path):
    ws = tmp_path / 'ws'
    design = pc.ControlledOPE(seed=7, weights={'a': 1.0, 'b': 1.0},
                              decision_ids=[f'C{i}' for i in range(50)])
    for claim, receipt in design.receipts().items():
        _record(ws, claim, receipt['family'], propensity=receipt['propensity'],
                candidates={'a': {'weight': 1.0}, 'b': {'weight': 1.0}, 'hidden': 'bad'},
                probability_source=receipt['probability_source'],
                information_set=receipt['information_set'])
    result = pc.compare(ws, bootstrap=0, experiment=design)
    assert result['decisions'] == 0
    assert result['skipped_invalid_support'] == 50
    assert result['verdict'] == 'incomplete_experiment'


def test_missing_or_nonfinite_reward_never_counts_as_decision(tmp_path):
    ws = tmp_path / 'ws'
    design = pc.ControlledOPE(seed=7, weights={'a': 1.0, 'b': 1.0},
                              decision_ids=[f'C{i}' for i in range(50)])
    for i, (claim, receipt) in enumerate(design.receipts().items()):
        reward = 'absent' if i < 10 else float('nan') if i < 30 else 1.0
        _record(ws, claim, receipt['family'], propensity=receipt['propensity'], reward=reward,
                candidates={k: {'weight': v} for k, v in receipt['weights'].items()},
                probability_source=receipt['probability_source'],
                information_set=receipt['information_set'])
    result = pc.compare(ws, bootstrap=0, experiment=design)
    assert result['decisions'] == 20
    assert result['skipped_invalid_reward'] == 30
    assert result['verdict'] == 'incomplete_experiment'


import pytest


@pytest.mark.parametrize('corruption', ['drop_both', 'drop_audit', 'drop_transition',
                                        'duplicate', 'extra', 'wrong_action', 'bad_reward'])
def test_controlled_experiment_requires_complete_preregistered_population(tmp_path, corruption):
    ws = tmp_path / 'ws'
    design = pc.ControlledOPE(seed=7, weights={'a': 1.0, 'b': 1.0},
                              decision_ids=[f'C{i}' for i in range(60)])
    for i, (claim, receipt) in enumerate(design.receipts().items()):
        if corruption == 'drop_both' and receipt['family'] == 'b':
            continue
        _record(ws, claim, receipt['family'], propensity=receipt['propensity'],
                candidates={k: {'weight': v} for k, v in receipt['weights'].items()},
                probability_source=receipt['probability_source'],
                information_set=receipt['information_set'],
                reward=float('nan') if corruption == 'bad_reward' and i == 0 else 1.0)
        if corruption == 'duplicate' and i == 0:
            _record(ws, claim, receipt['family'], propensity=receipt['propensity'],
                    candidates={k: {'weight': v} for k, v in receipt['weights'].items()},
                    probability_source=receipt['probability_source'],
                    information_set=receipt['information_set'])
    if corruption == 'extra':
        _record(ws, 'foreign', 'a')
    if corruption in ('drop_audit', 'drop_transition', 'wrong_action'):
        path = (ws / 'runs' / 'logs' / 'e2e-audit.jsonl' if corruption == 'drop_audit'
                else ws / 'runs' / 'experience.jsonl')
        lines = path.read_text().splitlines()
        if corruption == 'wrong_action':
            row = json.loads(lines[0])
            row['a'] = 'b' if row['a'] == 'a' else 'a'
            lines[0] = json.dumps(row)
        else:
            lines.pop(0)
        path.write_text('\n'.join(lines) + '\n')
    result = pc.compare(ws, bootstrap=0, experiment=design)
    assert result['verdict'] == 'incomplete_experiment'
    assert result['policies'] == {}
    assert sum(result['experiment_integrity'].values()) > 0
