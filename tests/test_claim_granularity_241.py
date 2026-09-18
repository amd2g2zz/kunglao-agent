# -*- coding: utf-8 -*-
"""Issue 241 — claim granularity discipline: plan-size / domain-span gate.

Regression of the wbtest C-005 field evidence (issue 241, verbatim): a
12+-step plan hanging on ONE claim ("Reverse white-box crypto core —
safeEncrypt whitebox VM") dispatched to a single worker. Under the issue-239 v2
contract the plan-first gate checks plan EXISTENCE only — a monolithic plan
is itself the "should split" signal and no machinery reads it.

Contract after the fix (rides the issue-234 fan-out at CREATION time):
  1. The granularity gate fires at the plan-check point in the execution
     loop (NOT at first dispatch — post-issue-239 planning is the worker's first
     act, so on the first dispatch no worker-authored plan exists and the
     gate is not armed). From the NEXT dispatch on, a plan exceeding
     K = GRANULARITY_MAX_STEPS (8) enumerated steps OR spanning multiple
     mechanism domains (>= 2 distinct families with >= 2 steps each)
     REJECTS with mechanical split guidance.
  2. Split guidance is mechanical: it names the mint entrypoint
     (scripts/claim_granularity.py --split), the parent claim, and the
     observed domain split (which steps belong to which family — issue-234
     mechanism-family vocabulary where it fits, else an inference note).
  3. mint_split_claims fans out sub-claims with real depends_on edges
     (claim_deps.yaml) + a domain tag, each covering <= K steps — they
     enter the TS pool (OPEN => priority_ratio.is_open) and rank.
  4. Padded/trivial steps ("wait"/"check") count toward K — no free passes.

Fast tier (tests/_tiers.py FAST_MODULES): pure unit — no process spawns,
no network, no nested pytest.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

import claim_granularity as cg  # noqa: E402
import priority_ratio  # noqa: E402


# ---------- helpers (mirrors test_plan_first_ownership_239 / test_obstacle_ladder) ----------

def _seed_prior_dispatch(ws: Path, ts: str = '2026-09-10T01:00:00Z') -> None:
    """One prior approved dispatch for C-001 (approval-point anchor log)."""
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    (ws / 'runs' / '.dispatch-anchor-C001.jsonl').write_text(
        json.dumps({'ts': ts, 'claim': 'C-001'}) + '\n', encoding='utf-8')


def _write_reg(ws: Path, claims: list[dict]) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / 'claim-register.yaml').write_text(
        yaml.safe_dump({'claims': claims}, allow_unicode=True,
                       sort_keys=False), encoding='utf-8')


def _load_reg(ws: Path) -> dict:
    return yaml.safe_load(
        (ws / 'claim-register.yaml').read_text(encoding='utf-8')) or {}


def _parent_claim(cid: str = 'C-001') -> dict:
    return {
        'id': cid,
        'status': 'OPEN',
        'boundary_type': 'task',
        'evidence_tier_attempted': 0,
        'promotion_attempts': 0,
        'statement': 'Reverse white-box crypto core - safeEncrypt whitebox VM',
        'answers_question': 'q1',
    }


def _plan(steps: list[str], prefix: str = 'goal: reverse the core\n') -> str:
    body = ''.join(f'{i}. {s}\n' for i, s in enumerate(steps, 1))
    return f'{prefix}steps:\n{body}fallback: rerun with logs\n'


def _static(i: int) -> str:
    return f'static pass {i}: disasm the .rela.dyn array with ghidra'


def _dynamic(i: int) -> str:
    return f'dynamic pass {i}: frida attach and trace the VM dispatch loop'


def _network(i: int) -> str:
    return f'network pass {i}: replay the captured http session from the pcap'


def _monolithic_12() -> str:
    """The wbtest C-005 shape: 12 steps, 3 mechanism domains."""
    return _plan([_static(i) for i in range(1, 5)]
                 + [_dynamic(i) for i in range(1, 5)]
                 + [_network(i) for i in range(1, 5)])


def _seed_plan(ws: Path, text: str, name: str = 'plan-C001.md') -> Path:
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    p = ws / 'runs' / name
    p.write_text(text, encoding='utf-8')
    return p


# ---------- 0. the named constant ----------

def test_k_is_the_named_constant_eight():
    """Scope pin: K = named constant GRANULARITY_MAX_STEPS = 8."""
    assert cg.GRANULARITY_MAX_STEPS == 8


# ---------- 1. RED: the field instance ----------

def test_monolithic_12_step_plan_rejected_with_split_guidance(tmp_path):
    """wbtest C-005 replay: a 12-step plan on ONE claim passes plan-first
    (existence only) but the granularity gate rejects it with a mechanical
    split directive naming the mint entrypoint + parent + domain split."""
    from worker_budget_gates import check_claim_granularity
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    _seed_plan(ws, _monolithic_12())
    ok, msg = check_claim_granularity({'workspace': str(ws)}, 'C-001')
    assert not ok, 'a 12-step 3-domain plan must REJECT: ' + msg
    # mechanical guidance: entrypoint + parent + the observed split
    assert 'claim_granularity.py' in msg and '--split' in msg, msg
    assert 'C-001' in msg, 'guidance must name the parent claim'
    for family in ('static-unpacking', 'dynamic-tracing', 'network-replay'):
        assert family in msg, f'guidance must name the observed family {family}: {msg}'


def test_span_guidance_notes_inferred_family_vocabulary(tmp_path):
    """Families outside the issue-234 vocabulary are labelled as inferred, not
    passed off as ladder vocabulary."""
    from worker_budget_gates import check_claim_granularity
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    _seed_plan(ws, _plan([_network(i) for i in range(1, 5)]
                         + [_static(i) for i in range(1, 5)]))
    ok, msg = check_claim_granularity({'workspace': str(ws)}, 'C-001')
    assert not ok, msg
    assert 'inferred' in msg.lower(), (
        'inference-only families must be labelled: ' + msg)


# ---------- 2. K boundary ----------

def test_eight_step_single_domain_plan_passes(tmp_path):
    from worker_budget_gates import check_claim_granularity
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    _seed_plan(ws, _plan([_static(i) for i in range(1, 9)]))
    ok, msg = check_claim_granularity({'workspace': str(ws)}, 'C-001')
    assert ok, f'K=8 must pass (boundary): {msg}'


def test_nine_step_plan_rejects_on_size(tmp_path):
    from worker_budget_gates import check_claim_granularity
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    _seed_plan(ws, _plan([_static(i) for i in range(1, 10)]))
    ok, msg = check_claim_granularity({'workspace': str(ws)}, 'C-001')
    assert not ok, 'K=9 must reject (boundary)'
    assert '9' in msg and str(cg.GRANULARITY_MAX_STEPS) in msg, msg


# ---------- 3. size-only vs span-only defects ----------

def test_single_domain_long_plan_size_defect_only(tmp_path):
    """10 same-family steps: a SIZE violation only — no domain guidance."""
    from worker_budget_gates import check_claim_granularity
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    _seed_plan(ws, _plan([_static(i) for i in range(1, 11)]))
    ok, msg = check_claim_granularity({'workspace': str(ws)}, 'C-001')
    assert not ok, msg
    assert 'plan-size' in msg, msg
    assert 'domain-span' not in msg, (
        'a single-family plan must not carry domain guidance: ' + msg)


def test_multi_domain_short_plan_span_defect(tmp_path):
    """8 steps in 2 families (4+4): under K, but a domain-span violation."""
    from worker_budget_gates import check_claim_granularity
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    _seed_plan(ws, _plan([_static(i) for i in range(1, 5)]
                         + [_dynamic(i) for i in range(1, 5)]))
    ok, msg = check_claim_granularity({'workspace': str(ws)}, 'C-001')
    assert not ok, '4+4 across 2 families must reject on span: ' + msg
    assert 'domain-span' in msg, msg
    assert 'plan-size' not in msg, (
        'an under-K plan must not carry size guidance: ' + msg)


# ---------- 4. adversarial: padded steps count ----------

def test_padded_trivial_steps_count_toward_k(tmp_path):
    """No free passes: 6 real steps + 3 'wait'/'check' filler marker steps
    = 9 enumerated steps -> REJECT; the message counts all 9."""
    from worker_budget_gates import check_claim_granularity
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    steps = [_static(i) for i in range(1, 7)] + ['wait', 'check', 'wait']
    _seed_plan(ws, _plan(steps))
    ok, msg = check_claim_granularity({'workspace': str(ws)}, 'C-001')
    assert not ok, 'padded steps must count toward K: ' + msg
    assert '9' in msg, f'the count must include the padded steps: {msg}'


# ---------- 5. post-issue-239 arming discipline ----------

def test_first_dispatch_not_gated_even_with_monolithic_plan_on_disk(tmp_path):
    """Post-issue-239: planning is the worker's first act — on the FIRST dispatch
    no worker-authored plan exists and the gate does not fire (the plan that
    happens to sit on disk is not the gate's business yet)."""
    from worker_budget_gates import check_claim_granularity
    ws = tmp_path / 'ws'
    _seed_plan(ws, _monolithic_12())
    ok, msg = check_claim_granularity({'workspace': str(ws)}, 'C-001')
    assert ok, f'first dispatch must not be granularity-gated: {msg}'
    assert 'first dispatch' in msg.lower(), msg


def test_redispatch_without_plan_fails_open_to_plan_gate(tmp_path):
    """A re-dispatch with NO plan anywhere is the plan-first gate's rejection
    (single rejection, no double-fire): granularity fail-opens."""
    from worker_budget_gates import check_claim_granularity
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    ok, msg = check_claim_granularity({'workspace': str(ws)}, 'C-001')
    assert ok, f'granularity must fail open without a plan to read: {msg}'


def test_no_claim_fail_open(tmp_path):
    from worker_budget_gates import check_claim_granularity
    ok, _msg = check_claim_granularity({'workspace': str(tmp_path)}, None)
    assert ok


# ---------- 6. split-then-redispatch ----------

def test_split_mints_domain_subclaims_with_dep_edges(tmp_path):
    """The issue-234 fan-out at creation time: one sub-claim per domain group,
    depends_on the parent, real claim_deps.yaml edge, domain tag, chunked
    to <= K steps each, answers_question inherited."""
    ws = tmp_path / 'ws'
    _write_reg(ws, [_parent_claim()])
    _seed_plan(ws, _monolithic_12())
    r = cg.mint_split_claims(ws, 'C-001')
    assert r['refused'] is None, r
    minted = r['minted']
    assert minted, 'a monolithic plan must split into sub-claims'
    claims = {c['id']: c for c in _load_reg(ws)['claims']}
    deps = yaml.safe_load((ws / 'claim_deps.yaml').read_text(encoding='utf-8'))
    for row in minted:
        sub = claims[row['id']]
        assert sub['status'] == 'OPEN'
        assert sub['origin'] == cg.GRANULARITY_SPLIT_ORIGIN
        assert sub['split_for'] == 'C-001'
        assert sub['depends_on'] == ['C-001']
        assert sub['domain_family'] in row['family']
        assert sub['answers_question'] == 'q1', 'inherited from parent'
        assert deps['depends_on'][row['id']] == ['C-001']
        assert row['steps'] <= cg.GRANULARITY_MAX_STEPS, (
            f'each split unit covers <= K steps: {row}')
    families = {row['family'] for row in minted}
    assert families == {'static-unpacking', 'dynamic-tracing',
                        'network-replay'}, families
    # provenance on the parent: split_into + the issue-59 replacement semantics
    # (SUPERSEDED, superseded_by = sub ids) — an OPEN parent would
    # dep-block every sub-claim out of the dispatchable pool.
    parent = _find(claims.values(), 'C-001')
    assert parent.get('split_into'), 'parent must carry split_into provenance'
    assert parent['status'] == 'SUPERSEDED', parent
    assert parent['superseded_by'] == [row['id'] for row in minted]


def _find(claims, cid):
    return next(c for c in claims if c.get('id') == cid)


def test_split_chunks_oversized_single_domain_group(tmp_path):
    """A 9-step SAME-FAMILY plan splits into chunks each <= K (domain split
    alone cannot fix a size violation)."""
    ws = tmp_path / 'ws'
    _write_reg(ws, [_parent_claim()])
    _seed_plan(ws, _plan([_static(i) for i in range(1, 10)]))
    r = cg.mint_split_claims(ws, 'C-001')
    assert r['refused'] is None, r
    assert len(r['minted']) >= 2, '9 same-family steps must chunk'
    assert all(row['steps'] <= cg.GRANULARITY_MAX_STEPS
               for row in r['minted'])


def test_split_is_idempotent(tmp_path):
    ws = tmp_path / 'ws'
    _write_reg(ws, [_parent_claim()])
    _seed_plan(ws, _monolithic_12())
    first = cg.mint_split_claims(ws, 'C-001')
    second = cg.mint_split_claims(ws, 'C-001')
    assert first['refused'] is None and second['refused'] is None
    assert second['minted'] == [], (
        'the (origin, split_for, family, chunk) marker must dedupe')


def test_split_refusals_are_explicit(tmp_path):
    ws = tmp_path / 'ws'
    r = cg.mint_split_claims(ws, 'C-001')
    assert r['minted'] == [] and 'claim-register' in r['refused']
    _write_reg(ws, [_parent_claim()])
    r = cg.mint_split_claims(ws, 'C-001')
    assert r['minted'] == [] and 'plan' in r['refused'].lower(), (
        'no plan on disk -> explicit refusal')
    _seed_plan(ws, _plan([_static(i) for i in range(1, 5)]))
    r = cg.mint_split_claims(ws, 'C-001')
    assert r['minted'] == [] and r['refused'], (
        'a plan within the threshold has nothing to split')


def test_subclaim_redispatch_passes_granularity_gate(tmp_path):
    """Split-then-redispatch: after the fan-out, a sub-claim whose
    worker-authored plan is under K and single-domain PASSES the gate."""
    from worker_budget_gates import check_claim_granularity
    ws = tmp_path / 'ws'
    _write_reg(ws, [_parent_claim()])
    _seed_plan(ws, _monolithic_12())
    r = cg.mint_split_claims(ws, 'C-001')
    sub_id = r['minted'][0]['id']
    key = sub_id.replace('-', '')
    (ws / 'runs' / f'.dispatch-anchor-{key}.jsonl').write_text(
        json.dumps({'ts': '2026-09-10T02:00:00Z', 'claim': sub_id}) + '\n',
        encoding='utf-8')
    _seed_plan(ws, _plan([_static(i) for i in range(1, 5)]),
               name=f'plan-{key}.md')
    ok, msg = check_claim_granularity({'workspace': str(ws)}, sub_id)
    assert ok, f'sub-claim plan under K and single-domain must pass: {msg}'


def test_subclaims_enter_the_ts_rank_pool(tmp_path):
    """Minted sub-claims are OPEN, hence TS-samplable and rankable."""
    ws = tmp_path / 'ws'
    _write_reg(ws, [_parent_claim()])
    _seed_plan(ws, _monolithic_12())
    r = cg.mint_split_claims(ws, 'C-001')
    claims = _load_reg(ws)['claims']
    subs = [c for c in claims
            if c.get('origin') == cg.GRANULARITY_SPLIT_ORIGIN]
    assert len(subs) == len(r['minted'])
    assert subs and all(priority_ratio.is_open(c) for c in subs), (
        'a minted split unit must be TS-samplable (OPEN, non-terminal)')
    deps = yaml.safe_load((ws / 'claim_deps.yaml').read_text(encoding='utf-8'))
    # from_workspace: the issue-594 fallback reads the register's terminal
    # rows — the SUPERSEDED parent is what admits the sub-claims past the
    # dep gate.
    actions = priority_ratio.priority_ratio(
        claims, deps, priority_ratio.EvidenceView.from_workspace(ws))
    ranked = {a.claim_id for a in actions}
    assert {c['id'] for c in subs} <= ranked, (
        'sub-claims must rank in the pool, not sit outside it')


def test_split_ranks_in_a_settled_workspace_with_facts(tmp_path):
    """Review round 1 CRITICAL repro: a workspace whose facts/_INDEX.md
    already carries a terminal row (citing an UNRELATED settled claim) never
    reaches the issue-594 register fallback — the ranking face must admit
    the sub-claims via the superseded_by consult, or the split deadlocks
    forever (settled subs cite subs, never the parent)."""
    ws = tmp_path / 'ws'
    _write_reg(ws, [_parent_claim()])
    _seed_plan(ws, _monolithic_12())
    (ws / 'facts').mkdir(parents=True, exist_ok=True)
    (ws / 'facts' / '_INDEX.md').write_text(
        'facts index\n'
        'F001 | PROVEN | C-999 | unrelated settled claim\n',
        encoding='utf-8')
    r = cg.mint_split_claims(ws, 'C-001')
    assert r['refused'] is None, r
    claims = _load_reg(ws)['claims']
    subs = [c for c in claims
            if c.get('origin') == cg.GRANULARITY_SPLIT_ORIGIN]
    deps = yaml.safe_load((ws / 'claim_deps.yaml').read_text(encoding='utf-8'))
    view = priority_ratio.EvidenceView.from_workspace(ws)
    assert 'C-999' in view.terminal_fact_claims, (
        'fixture honesty: the facts index terminal row must be live')
    assert 'C-001' not in view.terminal_fact_claims, (
        'fixture honesty: the parent has NO terminal fact')
    actions = priority_ratio.priority_ratio(claims, deps, view)
    ranked = {a.claim_id for a in actions}
    assert subs, 'mint produced sub-claims'
    assert {c['id'] for c in subs} <= ranked, (
        'SUBS RANK must hold in the settled-workspace shape '
        '(superseded_by consult): ' + str(sorted(ranked)))


# ---------- HIGH: heading-enumerated steps count ----------

def test_heading_enumerated_steps_count_without_label(tmp_path):
    """Review round 1 HIGH: `## Step N` heading blocks are a natural LLM
    plan format — they must count, with or without a `steps:` label."""
    from worker_budget_gates import check_claim_granularity
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    body = ''.join(
        f'## Step {i}: {s}\n' for i, s in enumerate(
            [_static(k) for k in range(1, 5)]
            + [_dynamic(k) for k in range(1, 5)]
            + [_network(k) for k in range(1, 5)], 1))
    _seed_plan(ws, 'goal: reverse the core\n' + body)
    ok, msg = check_claim_granularity({'workspace': str(ws)}, 'C-001')
    assert not ok, 'a 12-step heading plan must not bypass the gate'
    assert 'plan-size' in msg and '12' in msg, msg


def test_heading_steps_inside_steps_block_count(tmp_path):
    """A bare `steps:` label followed by `## Step N` headings counts the
    headings (the old parser broke at the first heading -> 0 steps)."""
    from worker_budget_gates import check_claim_granularity
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    body = ''.join(
        f'## Step {i}: {s}\n' for i, s in enumerate(
            [_static(k) for k in range(1, 10)], 1))
    _seed_plan(ws, 'goal: reverse the core\nsteps:\n' + body)
    ok, msg = check_claim_granularity({'workspace': str(ws)}, 'C-001')
    assert not ok, 'heading steps inside the block must count'
    assert 'plan-size' in msg, msg


# ---------- MEDIUM-a: keyword precision ----------

def test_memory_words_in_cohesive_static_plan_do_not_force_split(tmp_path):
    """Review round 1 MEDIUM-a: bare 'dump'/'memory' keyed memory-imaging
    and forced a split of a cohesive static plan. Compound-phrase keywords
    + the 'binary' static keyword keep it single-domain."""
    from worker_budget_gates import check_claim_granularity
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    steps = ['dump the binary with objdump',
             'memory-map the binary sections']
    steps += [f'static pass {i}: disasm the .rela.dyn array with ghidra'
              for i in range(1, 7)]
    _seed_plan(ws, _plan(steps))
    ok, msg = check_claim_granularity({'workspace': str(ws)}, 'C-001')
    assert ok, 'a cohesive static plan must not span-reject: ' + msg


# ---------- MEDIUM-b: superseded parent reject names successors ----------

def test_superseded_parent_reject_names_subclaims_not_split_loop(tmp_path):
    """Review round 1 MEDIUM-b: re-dispatching the SUPERSEDED parent with
    its old monolithic plan must NOT loop on 'run --split' (a no-op now) —
    the rejection names the sub-claims to dispatch instead."""
    from worker_budget_gates import check_claim_granularity
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    _seed_plan(ws, _monolithic_12())
    _write_reg(ws, [dict(_parent_claim(), status='SUPERSEDED',
                         superseded_by=['C-002', 'C-003'])])
    ok, msg = check_claim_granularity({'workspace': str(ws)}, 'C-001')
    assert not ok, msg
    assert 'SUPERSEDED' in msg, msg
    assert 'C-002' in msg and 'C-003' in msg, (
        'the rejection must name the successors: ' + msg)
    assert 'claim_granularity.py' not in msg and (
        'split before re-dispatch' not in msg), (
        'the generic split-loop directive must not fire: ' + msg)


# ---------- MEDIUM-c: cross-chunk sequential deps ----------

def test_cross_chunk_sequential_deps_within_a_domain(tmp_path):
    """Review round 1 MEDIUM-c: chunk N+1 depends_on chunk N within the
    same domain group (sequential within, parallel across domains)."""
    ws = tmp_path / 'ws'
    _write_reg(ws, [_parent_claim()])
    _seed_plan(ws, _plan([_static(i) for i in range(1, 10)]))
    r = cg.mint_split_claims(ws, 'C-001')
    assert r['refused'] is None and len(r['minted']) >= 2, r
    first, second = r['minted'][0], r['minted'][1]
    claims = {c['id']: c for c in _load_reg(ws)['claims']}
    assert claims[first['id']]['depends_on'] == ['C-001']
    assert claims[second['id']]['depends_on'] == ['C-001', first['id']], (
        'chunk 2 must chain onto chunk 1 within the domain')
    deps = yaml.safe_load((ws / 'claim_deps.yaml').read_text(encoding='utf-8'))
    assert deps['depends_on'][second['id']] == ['C-001', first['id']], (
        'the real DAG edge carries the cross-chunk ordering')


# ---------- 7. battery wiring ----------

def _min_paths(ws: Path) -> dict:
    ws.mkdir(parents=True, exist_ok=True)
    return {
        'workspace': str(ws),
        'state': ws / 'analysis_state.txt',
        'register': ws / 'claim-register.yaml',
        'deps': ws / 'claim_deps.yaml',
        'task_spec': ws / 'task_spec.yaml',
    }


def _payload(prompt: str) -> dict:
    return {'tool_input': {
        'name': 'w-test',
        'description': '',
        'prompt': prompt,
    }}


def _dispatch_prompt() -> str:
    return ('{"kunglao_dispatch": {"version": 1, "claim": "C-001", '
            '"tier": 1, "tools": ["grep"], "agent": "w-test"}}\n'
            'facts-snapshot: 1 facts')


def _seed_live_heartbeat(ws: Path) -> None:
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    now_dt = datetime.now(timezone.utc)
    prev_dt = now_dt - timedelta(minutes=5)
    fmt = lambda dt: dt.isoformat(timespec='seconds').replace('+00:00', 'Z')
    (ws / 'runs' / '.heartbeat.json').write_text(json.dumps({
        'last_tick_ts': fmt(now_dt), 'activity_ts': fmt(now_dt),
        'started_ts': fmt(prev_dt),
        'tick_history': [fmt(prev_dt), fmt(now_dt)],
    }), encoding='utf-8')


def test_pre_check_battery_rejects_granularity(tmp_path, capsys):
    """Wiring: the granularity check sits in the pre_check battery at the
    plan-check point; a monolithic re-dispatch exits 2 with REJECT
    granularity and the split guidance on the reject channel. The seeded
    plan carries its dispatch-anchor provenance (issue-57 gate 3) so the PLAN
    gate passes and the rejection lands on granularity — provenance is
    checked first by battery order."""
    import worker_budget_sinks as sinks
    ws = tmp_path / 'ws'
    paths = _min_paths(ws)
    assert sinks.pre_check(_payload(_dispatch_prompt()), paths) == 0, \
        capsys.readouterr().err
    _seed_live_heartbeat(ws)
    anchor_ts = json.loads(
        (ws / 'runs' / '.dispatch-anchor-C001.jsonl')
        .read_text(encoding='utf-8').splitlines()[-1])['ts']
    _seed_plan(ws, f'dispatch-anchor: {anchor_ts}\n' + _monolithic_12())
    rc = sinks.pre_check(_payload(_dispatch_prompt()), paths)
    captured = capsys.readouterr()
    assert rc == 2, captured.err
    assert 'REJECT granularity' in captured.err, captured.err
    assert '--split' in captured.err, 'guidance rides the reject channel'
    assert 'granularity' in sinks.REJECT_FIXES, 'REJECT_FIXES entry exists'


def test_first_dispatch_battery_passes_with_monolithic_plan(tmp_path, capsys):
    """Post-issue-239 contract preserved end to end: a first dispatch passes even
    with a monolithic plan file already on disk."""
    import worker_budget_sinks as sinks
    ws = tmp_path / 'ws'
    _seed_plan(ws, _monolithic_12())
    rc = sinks.pre_check(_payload(_dispatch_prompt()), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
