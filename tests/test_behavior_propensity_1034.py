"""Reject unsupported behavior propensities using synthetic workspaces."""
import json
from types import SimpleNamespace

import pytest

from rlvr import consolidated_ledger as cl
from rlvr import policy_compare as pc
from e2e.checkpoints import _stamp_ope_propensity


def _record(ws, claim, family, *, propensity=0.5, reward=1.0, dispatch_id=None, **env_extra):
    (ws / 'runs' / 'logs').mkdir(parents=True, exist_ok=True)
    decision_id = dispatch_id or claim
    env = {'family': family, 'dispatch_id': decision_id, 'propensity': propensity,
           'candidates': {'a': {'weight': 1.0}, 'b': {'weight': 1.0}}}
    env.update(env_extra)
    with (ws / 'runs' / 'logs' / 'e2e-audit.jsonl').open('a') as f:
        f.write(json.dumps({'event': 'method_family_recorded', 'claim': claim,
                            'detail': {'method_family': family, 'envelope': env}}) + '\n')
    transition = {'schema': 'transition/1', 'dispatch_id': decision_id, 'a': family,
                  'probability_action': 'method_family',
                  'probability_source': env.get('probability_source'),
                  'information_set': env.get('information_set'), 'propensity': propensity}
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


def test_dispatch_source_labels_never_authorize_ope(tmp_path):
    ctx = SimpleNamespace(repo=tmp_path, ws=tmp_path)
    stamps = []
    for declared, scheduler in ((True, None), (False, 'uniform'), (False, 'learned')):
        receipt = {'family': 'a',
                   'candidates': {'a': {'weight': 1}, 'b': {'weight': 1}}}
        if scheduler:
            receipt['scheduler'] = scheduler
        _stamp_ope_propensity(ctx, receipt, declared, 'a', None)
        stamps.append(receipt)
    assert stamps[0]['propensity'] is None
    assert stamps[0]['probability_source'] == 'unknown'
    assert stamps[1]['propensity'] == 0.5
    assert stamps[1]['probability_source'] == 'uniform_exact'
    assert stamps[2]['propensity'] == 0.5
    assert stamps[2]['probability_source'] == 'selection_law_exact'
    ws = tmp_path / 'ws'
    sources = ('unknown', 'uniform_exact', 'legacy_mc_estimate', 'randomized_control')
    for i, source in enumerate(sources):
        _record(ws, f'C{i}', 'a', probability_source=source)
    report = pc.compare(ws, bootstrap=0)
    assert report['decisions'] == 0
    assert report['skipped_unknown_probability'] == len(sources)


def test_repeated_claim_family_never_joins_last_receipt(tmp_path):
    ws = tmp_path / 'ws'
    _record(ws, 'C1', 'a', probability_source='legacy_mc_estimate')
    _record(ws, 'C1', 'a', probability_source='legacy_mc_estimate')
    report = pc.compare(ws, bootstrap=0)
    assert report['decisions'] == 0
    assert report['skipped_ambiguous_dispatch'] == 2


def test_recipe_probability_is_not_method_evidence_even_if_numbers_match(tmp_path, monkeypatch):
    from rlvr import incremental_reward as ir, learning_seal, q_cells

    ws = tmp_path / 'ws'
    key = tmp_path / 'key'
    key.write_bytes(b'k' * 64)
    monkeypatch.setattr(learning_seal, 'KEY_PATH', key)
    design = pc.ControlledOPE(seed=7, weights={'a': 1.0}, decision_ids=['C1'])
    expected = design.receipts()['C1']
    _record(ws, 'C1', 'a', propensity=1.0, candidates={'a': {'weight': 1}},
            probability_source=expected['probability_source'],
            information_set=expected['information_set'])
    (ws / 'runs/experience.jsonl').unlink()
    q_cells.append_observation(ws, 'aaaaaaaaaaaa', 'a', None, source='dispatch',
                               claim='C1', recipe_id='inspect', recipe_propensity=1.0,
                               recipe_source='sampled', arm_key_col='a|inspect|none|0')
    ir.record_launch(ws, 'C1', 'a', phi=0, propensity=1.0)
    row = ir.append_transition(ws, 'C1', 'completed', r_settle=1.0)
    assert row['propensity'] == 1.0
    report = pc.compare(ws, bootstrap=0, experiment=design)
    assert report['decisions'] == 0
    assert report['skipped_unbound_method_probability'] == 1
    assert report['verdict'] == 'incomplete_experiment'


def test_two_executions_of_one_claim_match_their_own_method_receipts(tmp_path):
    design = pc.ControlledOPE(seed=7, weights={'a': 1.0, 'b': 1.0},
                              decision_ids=['000000000001', '000000000002'])
    for did, receipt in design.receipts().items():
        _record(tmp_path, 'C1', receipt['family'], dispatch_id=did,
                probability_source=receipt['probability_source'],
                information_set=receipt['information_set'])
    report = pc.compare(tmp_path, bootstrap=0, experiment=design)
    assert report['decisions'] == 2
    assert report['verdict'] == 'underpowered'


def test_qcell_conflicts_belong_to_a_single_execution(tmp_path):
    from rlvr import q_cells

    ids = ['000000000001', '000000000002']
    design = pc.ControlledOPE(seed=2, weights={'a': 1.0}, decision_ids=ids)
    for did, receipt in design.receipts().items():
        _record(tmp_path, 'C1', 'a', dispatch_id=did, candidates={'a': {'weight': 1.0}},
                propensity=1.0, probability_source=receipt['probability_source'],
                information_set=receipt['information_set'])
    assert cl.append(tmp_path, 'experience', {
        'schema': q_cells.OBS_SCHEMA, 'source': 'dispatch', 'claim': 'C1',
        'dispatch_id': ids[0], 'method_family': 'b', 'sampled_family': 'b',
        'arm_key': 'b|facts_snapshot|none|0'})
    report = pc.compare(tmp_path, bootstrap=0, experiment=design)
    assert report['skipped_family_mismatch'] == 1 and report['decisions'] == 1
    assert report['verdict'] == 'incomplete_experiment'


def _rewrite(ws, edit):
    """Parse both on-disk carriers, let ``edit`` change their rows, write them back."""
    audits = ws / 'runs/logs/e2e-audit.jsonl'
    transitions = ws / 'runs/experience.jsonl'
    audit_rows = [json.loads(line) for line in audits.read_text().splitlines()]
    transition_rows = [json.loads(line) for line in transitions.read_text().splitlines()]
    edit(audit_rows, transition_rows)
    audits.write_text(''.join(json.dumps(row) + '\n' for row in audit_rows))
    transitions.write_text(''.join(json.dumps(row) + '\n' for row in transition_rows))


@pytest.mark.parametrize('corruption, reason', [
    ('envelope_family', 'skipped_family_mismatch'),
    ('family_as_number', 'skipped_no_propensity'),
    ('probability_action', 'skipped_family_mismatch'),
    ('declared_source', 'skipped_declared_fiat'),
    ('audit_arm', 'skipped_family_mismatch'),
    ('transition_claim', 'skipped_family_mismatch'),
    ('transition_action_key', 'skipped_family_mismatch'),
])
def test_one_incoherent_carrier_refuses_only_its_own_execution(tmp_path, corruption, reason):
    ids = ['kept', 'corrupted']
    design = pc.ControlledOPE(seed=7, weights={'2': 1.0}, decision_ids=ids)
    for did, receipt in design.receipts().items():
        _record(tmp_path, 'C1', '2', dispatch_id=did, propensity=1.0,
                candidates={'2': {'weight': 1.0}}, probability_source=receipt['probability_source'],
                information_set=receipt['information_set'])

    def confuse(audit_rows, transition_rows):
        """The second recorded execution carries one incoherent carrier."""
        audit_row, transition = audit_rows[1], transition_rows[1]
        envelope = audit_row['detail']['envelope']
        if corruption == 'envelope_family':
            envelope['family'] = '3'
        elif corruption == 'family_as_number':
            envelope['family'] = audit_row['detail']['method_family'] = 2
        elif corruption == 'probability_action':
            envelope['probability_action'] = 'recipe'
        elif corruption == 'declared_source':
            envelope['method_source'] = 'declared'
        elif corruption == 'audit_arm':
            audit_row['arm'] = '3'
        elif corruption == 'transition_claim':
            transition['claim_ref'] = 'C-other'
        else:
            transition['action_key'] = '3'

    _rewrite(tmp_path, confuse)

    result = pc.compare(tmp_path, bootstrap=0, experiment=design)

    assert result[reason] == 1
    assert result['decisions'] == 1


@pytest.mark.parametrize('carrier', ['transition', 'envelope'])
def test_non_string_dispatch_id_is_counted_and_never_joins_the_planned_execution(tmp_path, carrier):
    design = pc.ControlledOPE(seed=7, weights={'a': 1.0}, decision_ids=['7'])
    expected = design.receipts()['7']
    _record(tmp_path, 'C1', 'a', dispatch_id='7', propensity=1.0,
            candidates={'a': {'weight': 1.0}}, probability_source=expected['probability_source'],
            information_set=expected['information_set'])

    def untype(audit_rows, transition_rows):
        """One carrier's id keeps its text but loses the string type."""
        row = (transition_rows[0] if carrier == 'transition'
               else audit_rows[0]['detail']['envelope'])
        row['dispatch_id'] = 7

    _rewrite(tmp_path, untype)

    result = pc.compare(tmp_path, bootstrap=0, experiment=design)

    assert result['decisions'] == 0
    assert result['experiment_integrity'][
        'unexpected_transition' if carrier == 'transition' else 'unexpected_audit'] == 1


def test_invalid_probability_and_support_are_counted_without_crashing(tmp_path):
    ws = tmp_path / 'ws'
    _record(ws, 'C1', 'a', propensity=float('nan'))
    _record(ws, 'C2', 'a', propensity='bad')
    _record(ws, 'C3', 'a', candidates={'b': {'weight': 1}})
    _record(ws, 'C4', 'a', candidates={'a': {'weight': True}, 'b': {'weight': True}})
    report = pc.compare(ws, bootstrap=0)
    assert report['decisions'] == 0
    assert report['skipped_invalid_probability'] == 2
    assert report['skipped_invalid_support'] == 2


def test_trusted_control_design_replays_through_real_compare(tmp_path):
    """Every execution of a complete preregistered population is admitted
    and ranked. The population is not a tie: with 0.9:0.1 weights and
    rewards that follow the family the three estimates are strictly ordered
    (eps-greedy 0.96044, thompson 0.92, uniform 0.560976). The flat 1:1
    population this test used before ties thompson and uniform exactly,
    which the evaluator reports as "tie" with no ranking."""
    ws = tmp_path / 'ws'
    design = pc.ControlledOPE(seed=7, weights={'a': 0.9, 'b': 0.1},
                              decision_ids=[f'C{i}' for i in range(200)])
    population = design.receipts()
    for claim, receipt in population.items():
        _record(ws, claim, receipt['family'], propensity=receipt['propensity'],
                reward=float(receipt['family'] == 'a'),
                candidates={k: {'weight': v} for k, v in receipt['weights'].items()},
                probability_source=receipt['probability_source'],
                information_set=receipt['information_set'])
    report = pc.compare(ws, bootstrap=0, experiment=design)
    estimates = [entry['snips'] for entry in report['policies'].values()]
    assert report['decisions'] == len(population)
    assert len(set(estimates)) == len(estimates)
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


def test_learned_stamp_is_the_receipts_exact_conditional_weight(tmp_path):
    ctx = SimpleNamespace(repo=tmp_path, ws=tmp_path)
    receipt = {'family': 'b',
               'candidates': {'a': {'weight': 2.0}, 'b': {'weight': 6.0},
                              'c': {'weight': 2.0}}}
    _stamp_ope_propensity(ctx, receipt, False, 'b', None)
    weights = {f: float(c['weight'])
               for f, c in receipt['candidates'].items()}
    assert receipt['propensity'] == round(
        weights['b'] / sum(weights.values()), 4)
    assert receipt['propensity'] == 0.6
    assert receipt['probability_source'] == 'selection_law_exact'


def test_unreconstructable_receipts_fall_to_the_unknown_face(tmp_path):
    ctx = SimpleNamespace(repo=tmp_path, ws=tmp_path)
    cases = [
        # the chosen family is absent from the receipt's candidates
        {'family': 'a', 'candidates': {'b': {'weight': 1.0}}},
        # every candidate weight is zero: the total is not a support
        {'family': 'a', 'candidates': {'a': {'weight': 0.0},
                                       'b': {'weight': 0.0}}},
        # a non-finite weight cannot be a probability numerator
        {'family': 'a', 'candidates': {'a': {'weight': float('nan')},
                                       'b': {'weight': 1.0}}},
        # a candidate without a weight entry
        {'family': 'a', 'candidates': {'a': {'p_llm': 1.0},
                                       'b': {'weight': 1.0}}},
        # a candidate that is not a mapping
        {'family': 'a', 'candidates': {'a': 'bad', 'b': {'weight': 1.0}}},
        # a stringy weight is not a number
        {'family': 'a', 'candidates': {'a': {'weight': '1.0'},
                                       'b': {'weight': 1.0}}},
        # a boolean weight is not a probability weight
        {'family': 'a', 'candidates': {'a': {'weight': True},
                                       'b': {'weight': 1.0}}},
        # a non-positive weight cannot enter a proportional support
        {'family': 'a', 'candidates': {'a': {'weight': -1.0},
                                       'b': {'weight': 3.0}}},
        {'family': 'a', 'candidates': {'a': {'weight': 0.0},
                                       'b': {'weight': 3.0}}},
        # no candidates at all
        {'family': 'a', 'candidates': None},
    ]
    for receipt in cases:
        _stamp_ope_propensity(ctx, receipt, False, 'a', None)
        assert receipt['propensity'] is None, receipt
        assert receipt['probability_source'] == 'unknown', receipt


def test_compare_excludes_the_legacy_law_and_admits_the_exact_law(tmp_path):
    ws = tmp_path / 'ws'
    design = pc.ControlledOPE(seed=5, weights={'a': 1.0, 'b': 1.0},
                              decision_ids=['C-legacy', 'C-exact'])
    _record(ws, 'C-legacy', 'a', propensity=0.5,
            candidates={'a': {'weight': 1.0}, 'b': {'weight': 1.0}},
            probability_source='legacy_mc_estimate')
    _record(ws, 'C-exact', 'a', propensity=0.4,
            candidates={'a': {'weight': 2.0}, 'b': {'weight': 3.0}},
            probability_source='selection_law_exact')
    report = pc.compare(ws, bootstrap=0, experiment=design)
    # the legacy tag dies at the source gate; the exact tag passes it
    # and leaves at the experiment-mismatch gate instead
    assert report['skipped_unknown_probability'] == 1, report
    assert report['skipped_experiment_mismatch'] == 1, report
    assert report['decisions'] == 0


def test_end_to_end_stamp_audit_compare_uses_the_exact_law(tmp_path):
    import random

    from rlvr import q_cells as qc

    rng = random.Random(11)
    receipt = qc.sample_method_family(
        'aaaaaaaaaaaa', {'a': 1.0, 'b': 3.0}, qc.InMemoryStore(()), rng=rng)
    chosen = receipt['family']
    _stamp_ope_propensity(None, receipt, False, chosen, None)
    weights = {f: float(c['weight'])
               for f, c in receipt['candidates'].items()}
    exact = round(weights[chosen] / sum(weights.values()), 4)
    assert receipt['propensity'] == exact
    assert receipt['probability_source'] == 'selection_law_exact'
    ws = tmp_path / 'ws'
    (ws / 'runs' / 'logs').mkdir(parents=True)

    def _audit_row(claim):
        line = json.dumps({'event': 'method_family_recorded',
                           'claim': claim,
                           'detail': {'method_family': chosen,
                                      'envelope': receipt}}) + '\n'
        with (ws / 'runs' / 'logs' / 'e2e-audit.jsonl').open('a') as f:
            f.write(line)

    _audit_row('C-exact')
    assert cl.append(ws, 'experience', {
        'schema': 'transition/1', 'dispatch_id': 'C-exact', 'a': chosen,
        'propensity': exact, 'r_incr': 1.0})
    # a twin whose transition carrier disagrees with the stamped law
    _audit_row('C-twin')
    assert cl.append(ws, 'experience', {
        'schema': 'transition/1', 'dispatch_id': 'C-twin', 'a': chosen,
        'propensity': round(exact / 2, 4), 'r_incr': 1.0})
    report = pc.compare(ws, bootstrap=0)
    # the exact-law row traverses the source gate and the carrier
    # agreement, then stops at the missing-experiment gate; the twin
    # dies at the carrier gate on the stamped exact value
    assert report['skipped_unknown_probability'] == 1, report
    assert report['skipped_propensity_mismatch'] == 1, report
    assert report['decisions'] == 0


@pytest.mark.parametrize('executions', [1, 2])
def test_claim_keyed_transition_is_counted_unbound_not_propensity_less(tmp_path, executions):
    from claims_store import mint_dispatch_id
    from e2e import audit
    from rlvr import incremental_reward as ir

    ws = tmp_path / 'ws'
    for _ in range(executions):
        receipt = {'family': 'a', 'candidates': {'a': {'weight': 1.0}, 'b': {'weight': 1.0}}}
        _stamp_ope_propensity(None, receipt, False, 'a', None)
        receipt['dispatch_id'] = mint_dispatch_id()
        audit.emit_method_family(ws, 'C-claim', 'a', envelope=receipt)
        # the production launch and settle writers: the stash rides the
        # minted execution id, the transition row rides the claim
        ir.record_launch(ws, 'C-claim', 'a', phi=0, propensity=receipt['propensity'],
                         dispatch_id=receipt['dispatch_id'])
        ir.append_transition(ws, 'C-claim', 'completed', r_settle=1.0)

    report = pc.compare(ws, bootstrap=0)

    assert report['decisions'] == 0
    assert report['skipped_unbound_method_probability'] == executions
    assert report['skipped_no_propensity'] == 0


def test_missing_dispatch_id_is_not_inferred_from_the_reused_claim(tmp_path):
    ids = ['000000000001', '000000000002']
    design = pc.ControlledOPE(seed=1, weights={'a': 1.0, 'b': 1.0}, decision_ids=ids)
    for did, receipt in design.receipts().items():
        _record(tmp_path, 'C1', receipt['family'], dispatch_id=did,
                probability_source=receipt['probability_source'],
                information_set=receipt['information_set'])

    def orphan(audit_rows, transition_rows):
        """The second execution's transition keeps its claim but names no execution."""
        transition_rows[1].pop('dispatch_id')
        transition_rows[1]['claim_ref'] = 'C1'

    _rewrite(tmp_path, orphan)

    report = pc.compare(tmp_path, bootstrap=0, experiment=design)

    assert report['decisions'] == 1
    assert report['experiment_integrity']['missing_transition'] == 1


def test_transition_naming_another_information_set_is_skipped(tmp_path):
    design = pc.ControlledOPE(seed=7, weights={'a': 1.0, 'b': 1.0}, decision_ids=['C1'])
    expected = design.receipts()['C1']
    _record(tmp_path, 'C1', expected['family'], probability_source=expected['probability_source'],
            information_set=expected['information_set'])

    _rewrite(tmp_path, lambda audit_rows, rows: rows[0].update(information_set='state_only'))

    report = pc.compare(tmp_path, bootstrap=0, experiment=design)

    assert report['skipped_unbound_method_probability'] == 1
    assert report['decisions'] == 0


def _uniform_population(tmp_path, reward_of):
    """A complete flat-weight controlled experiment (60 executions) whose
    rewards follow ``reward_of``; returns the comparison report."""
    ws = tmp_path / 'ws'
    design = pc.ControlledOPE(seed=7, weights={'a': 1.0, 'b': 1.0},
                              decision_ids=[f'C{i}' for i in range(60)])
    for claim, receipt in design.receipts().items():
        _record(ws, claim, receipt['family'], propensity=receipt['propensity'],
                reward=reward_of(receipt['family']),
                candidates={k: {'weight': v} for k, v in receipt['weights'].items()},
                probability_source=receipt['probability_source'],
                information_set=receipt['information_set'])
    return pc.compare(ws, bootstrap=0, experiment=design)


@pytest.mark.parametrize('rewarded', [None, 'b'], ids=['three_way_tie', 'tied_leaders'])
def test_estimates_sharing_the_top_value_report_a_tie_without_a_ranking(tmp_path, rewarded):
    # under a flat behavior design the thompson and uniform targets are one
    # policy, so they tie exactly; the greedy arm 'a' lifts eps-greedy when
    # 'a' pays and drops it below them when 'b' pays
    report = _uniform_population(tmp_path, lambda family: float(rewarded is None
                                                                or family == rewarded))

    estimates = {policy: entry['snips'] for policy, entry in report['policies'].items()}

    assert max(estimates.values()) == estimates['thompson'] == estimates['uniform']
    assert report['verdict'] == 'tie'


def test_a_strict_leader_keeps_its_ranking_when_only_the_tail_ties(tmp_path):
    report = _uniform_population(tmp_path, lambda family: float(family == 'a'))

    estimates = {policy: entry['snips'] for policy, entry in report['policies'].items()}

    assert estimates['eps-greedy'] > estimates['thompson'] == estimates['uniform']
    assert report['verdict']['best'] == 'eps-greedy'
