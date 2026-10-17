#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_rl_output_path_691.py — issue #691: the RL's output path
into decisions (declaration reconciliation + case-posterior rank check).

The sampler was advisory-only: the LLM declares ``method_family`` in the
envelope and ``runs/method-family-log.jsonl`` recorded neither the
propensity nor what the sampler would have chosen, so a deviation was
structurally invisible. The gate now reconciles EVERY declaration against
its own sampler draw — the same face ``method_lead`` renders, recomputed
at dispatch time (anti-spoof: nothing the envelope says can move it) —
and records the outcome:

1. the declaration row carries ``propensity`` (the sampler's draw
   probability of the DECLARED family), ``sampled_family`` and
   ``prior_source`` (history | llm_prior | store);
2. a deviation emits a unified-log ``sample_deviation`` event — recorded,
   never rejected (2026-10-14 acceptance amendment: NOT another rule
   gate — exception paths are decisions with recorded reasons);
3. the ``agent-reasoning:`` prefixed deviation is recorded the same way —
   the prefix may excuse the top-1 claim rank elsewhere, it never
   silences the family reconciliation (the reason rides the event);
4. ``settle_round_credit.record_case_settlements`` moves the linked
   ``CasePosterior`` and the rank order follows — the non-empty-posterior
   face: ``Thompson Beta over N linked`` instead of cold-start.

Fail-open throughout: a sampler failure degrades to the all-None gap row
and never turns an ALLOW into anything else.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

import worker_budget_sinks as sinks

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

_SEED_SIG = "abcdabcdabcd"          # any 12-hex state signature
_K = 40                             # settlement passes per side (test 4)


# ---------------------------------------------------------------------------
# fixtures (same shapes as tests/test_method_families_432.py — the sink-face
# pre_check harness: minimal paths, v1 envelope + facts-snapshot marker)
# ---------------------------------------------------------------------------

def _min_paths(ws: Path) -> dict:
    ws.mkdir(parents=True, exist_ok=True)
    return {
        'workspace': str(ws),
        'state': ws / 'analysis_state.txt',
        'register': ws / 'claim-register.yaml',
        'deps': ws / 'claim_deps.yaml',
        'task_spec': ws / 'task_spec.yaml',
    }


def _dispatch_payload(prompt: str) -> dict:
    return {'tool_input': {'name': 'w-test', 'description': '',
                           'prompt': prompt}}


def _full_prompt(family: str, extra: str = '') -> str:
    env = {'version': 1, 'claim': 'C-001', 'tier': 1,
           'tools': ['grep'], 'agent': 'w-test',
           'method_family': family}
    prompt = json.dumps({'kunglao_dispatch': env}) + '\nfacts-snapshot: 1 facts'
    return f'{prompt}\n{extra}' if extra else prompt


def _seed_history(ws: Path, family: str, n: int = 3) -> None:
    """Proposal history for the prior: n dispatch-source q-cell rows —
    ``_proposal_prior`` counts THESE (outcome rows never enter a prior)."""
    from rlvr import q_cells
    for i in range(n):
        q_cells.append_observation(ws, _SEED_SIG, family, None,
                                   source='dispatch', claim=f'seed-{i}')


def _usage_rows(ws: Path) -> list[dict]:
    p = ws / 'runs' / 'method-family-log.jsonl'
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding='utf-8').splitlines() if ln.strip()]


def _events(ws: Path, action: str) -> list[dict]:
    out: list[dict] = []
    logs = ws / 'runs' / 'logs'
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob('kunglao-*.jsonl')):
        for ln in p.read_text(encoding='utf-8').splitlines():
            if not ln.strip():
                continue
            row = json.loads(ln)
            if row.get('action') == action:
                out.append(row)
    return out


def _detail(row: dict) -> dict:
    det = row.get('detail')
    if isinstance(det, str):
        return json.loads(det)
    return det or {}


# ---------------------------------------------------------------------------
# 1. the declaration row records the sampler view
# ---------------------------------------------------------------------------

def test_declared_family_records_propensity_and_sampled_family(
        tmp_path, capsys):
    """#691 T2: one prior family, declared as-is — the usage row carries
    the full reconciliation: sampled_family matches the declaration,
    propensity is the sampler's draw probability (1.0 for the sole
    candidate), prior_source names where the prior came from."""
    ws = tmp_path / 'ws'
    _seed_history(ws, 'static-decompile')
    rc = sinks.pre_check(
        _dispatch_payload(_full_prompt('static-decompile')), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    rows = _usage_rows(ws)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row['schema'] == 'method-family-usage/1'
    assert row['family'] == 'static-decompile'
    assert row['sampled_family'] == 'static-decompile'
    assert row['propensity'] == 1.0
    assert row['prior_source'] == 'history'
    # a matched declaration is not a deviation — no event
    assert _events(ws, 'sample_deviation') == []


# ---------------------------------------------------------------------------
# 2. a deviation from the sample is recorded, never silent (and never a gate)
# ---------------------------------------------------------------------------

def test_deviation_from_sample_is_recorded_not_silent(tmp_path, capsys):
    """#691: the prior holds only static-decompile, the envelope declares
    dynamic-trace — the sampler could never have picked it (propensity
    0.0), the row says so, and a sample_deviation event lands in the
    unified log. The dispatch still PASSES: deviation is a recorded
    decision, not a new rule gate (acceptance amendment (c))."""
    import event_taxonomy as et
    ws = tmp_path / 'ws'
    _seed_history(ws, 'static-decompile')
    rc = sinks.pre_check(
        _dispatch_payload(_full_prompt('dynamic-trace')), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    assert 'sample_deviation' in et.EMIT_ACTIONS
    rows = _usage_rows(ws)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row['family'] == 'dynamic-trace'
    assert row['sampled_family'] == 'static-decompile'
    assert row['propensity'] == 0.0      # outside the sampler's support
    assert row['prior_source'] == 'history'
    evs = _events(ws, 'sample_deviation')
    assert len(evs) == 1, evs
    det = _detail(evs[0])
    assert det['declared'] == 'dynamic-trace'
    assert det['sampled'] == 'static-decompile'
    assert det['propensity'] == 0.0
    assert det['prior_source'] == 'history'
    assert det['reason'] is None


# ---------------------------------------------------------------------------
# 3. the agent-reasoning prefix never silences the record
# ---------------------------------------------------------------------------

def test_agent_reasoning_bypass_emits_sample_deviation_event(
        tmp_path, capsys):
    """#691: the same deviation with an ``agent-reasoning:`` prefix —
    the dispatch passes AND the deviation is still recorded, with the
    declared reason riding the event detail (a decision with a recorded
    reason, never a silent bypass)."""
    ws = tmp_path / 'ws'
    _seed_history(ws, 'static-decompile')
    prompt = _full_prompt(
        'dynamic-trace',
        extra='agent-reasoning: dynamic claims fit this binary better')
    rc = sinks.pre_check(_dispatch_payload(prompt), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    evs = _events(ws, 'sample_deviation')
    assert len(evs) == 1, evs
    det = _detail(evs[0])
    assert det['declared'] == 'dynamic-trace'
    assert det['sampled'] == 'static-decompile'
    assert det['reason'] == 'dynamic claims fit this binary better'
    # the row keeps the reconciliation too
    row = _usage_rows(ws)[-1]
    assert row['sampled_family'] == 'static-decompile'
    assert row['propensity'] == 0.0


# ---------------------------------------------------------------------------
# 4. settlement moves the CasePosterior and the rank order follows
# ---------------------------------------------------------------------------

def _rank_claims():
    def _c(cid, pq):
        return {'id': cid, 'status': 'OPEN', 'answers_question': pq,
                'evidence_tier_attempted': 0, 'promotion_attempts': 0,
                'statement': cid}
    return [_c('C-1', 'q1'), _c('C-2', 'q2')]


def _armed_case_doc(case_id, pq):
    """All five arming fields present, `expected` in the runner's
    canonical entry-list shape (the ONE shape law)."""
    return {'id': case_id, 'target_pq': pq, 'channel': 'probe',
            'hypothesis_ref': 'H-001',
            'update_map': {'red_up': ['H-002']},
            'expected': [{'field': 'probe', 'value': 'observed',
                          'evidence_refs': ['E-001']}],
            'mutations': [{'kind': 'omit', 'target': 'E-001'}]}


def test_case_posterior_moves_claim_rank_after_settlement(tmp_path):
    """#691 T4: two open claims each linked to an oracle case; the rank
    runs on the cold Beta(1,1) priors (no runs/posteriors.yaml yet —
    ``Thompson Beta over N linked``, not cold-start), then settlements
    drag the leader's case down and boost the trailer's case up — the
    posterior moves and the order flips. The settlement writer itself
    generates the ledger (the #678 face this verification stands in for)."""
    import priority_ratio as pr
    from settle_round_credit import record_case_settlements

    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    (ws / 'oracle' / 'cases').mkdir(parents=True)
    claims = _rank_claims()
    # _K DISTINCT settled claims per side: a claim settles ONCE, so _K
    # observations on a question means _K claims answering it. Re-banking
    # one claim _K times would count a single Bernoulli event _K times —
    # the double-count the pair-level dedup exists to prevent.
    sides = {
        'q1': {'pass': [f'C-p1-{i}' for i in range(_K)],
               'fail': [f'C-f1-{i}' for i in range(_K)]},
        'q2': {'pass': [f'C-p2-{i}' for i in range(_K)],
               'fail': [f'C-f2-{i}' for i in range(_K)]},
    }
    register = {'claims': [
        *claims,
        *[{'id': cid, 'status': 'PROVEN', 'answers_question': q}
          for q, s in sides.items() for cid in s['pass']],
        *[{'id': cid, 'status': 'REFUTED', 'answers_question': q}
          for q, s in sides.items() for cid in s['fail']],
    ]}
    (ws / 'claim-register.yaml').write_text(
        yaml.safe_dump(register, allow_unicode=True), encoding='utf-8')
    for case_id, pq in (('case-1', 'q1'), ('case-2', 'q2')):
        (ws / 'oracle' / 'cases' / f'{case_id}.yaml').write_text(
            yaml.safe_dump(_armed_case_doc(case_id, pq)),
            encoding='utf-8')

    deps = {'depends_on': {}, 'competitor_groups': {}}
    evidence = pr.EvidenceView(terminal_fact_claims=frozenset(),
                               verified_fact_count=0, ws=ws)

    # cold rank: linked cases, no ledger yet (the honest Beta(1,1) face)
    assert not (ws / 'runs' / 'posteriors.yaml').exists()
    before_actions = pr.priority_ratio(claims, deps, evidence)
    before = [a.claim_id for a in before_actions]
    assert before == ['C-1', 'C-2'] or before == ['C-2', 'C-1'], before
    for a in before_actions:
        assert 'Thompson Beta over 1 linked' in a.feeds['thompson_sample'], \
            a.feeds['thompson_sample']

    # drag the leader's case down (+1 beta per REFUTED settlement),
    # boost the trailer's case up (+1 alpha per PROVEN settlement)
    leader_q, trailer_q = ('q1', 'q2') if before[0] == 'C-1' else ('q2', 'q1')
    for cid in sides[leader_q]['fail']:
        failed = record_case_settlements(ws, [cid])
        assert failed['cases_failed'] == 1, failed
    for cid in sides[trailer_q]['pass']:
        passed = record_case_settlements(ws, [cid])
        assert passed['cases_passed'] == 1, passed

    # the ledger the settlement generated carries the moved posteriors
    led = yaml.safe_load(
        (ws / 'runs' / 'posteriors.yaml').read_text(encoding='utf-8'))
    assert led['schema'] == 'posteriors-schema/1'
    leader_case = 'case-1' if leader_q == 'q1' else 'case-2'
    trailer_case = 'case-2' if trailer_q == 'q2' else 'case-1'
    assert led['cases'][leader_case]['beta'] == 1 + _K
    assert led['cases'][trailer_case]['alpha'] == 1 + _K

    # the posterior moved the rank — the order flipped
    after = [a.claim_id for a in pr.priority_ratio(claims, deps, evidence)]
    assert after == list(reversed(before)), (before, after)
