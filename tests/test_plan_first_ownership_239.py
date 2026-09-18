# -*- coding: utf-8 -*-
"""Issue 239 — plan-first ownership: dispatch carries intent, not a plan.

Regression of umbrella issue 7, live field evidence: the plan-first gate was satisfiable by
an ORCHESTRATOR-GHOSTWRITTEN plan, because dispatch-time enforcement inverts
plan ownership — the cheapest way to unblock the orchestrator's own dispatch
was to write the plan itself. Owner ruling (settled):

    "Dispatch carries intent, not a plan; planning is the worker's first act
     of execution."

Contract after the fix:
  1. The FIRST dispatch of a claim passes WITHOUT any pre-existing plan —
     plan-first stops gating the dispatch and gates the worker's execution
     loop instead (the worker's first sanctioned write is its own plan).
  2. Plan provenance: `runs/plan-C*.md` carries dispatch linkage (the
     per-dispatch anchor, the plan-author gate) — a plan authored outside the
     dispatched worker's session does not satisfy plan-first for that
     worker (mirrors the issue 237 D3 maker != checker ruling).
  3. The in-prompt `--plan` reference path is reserved for re-dispatch
     continuity, not first dispatch; a re-dispatch beyond the planning
     round without a plan reference is still REJECTED.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ---------- helpers (self-contained; mirrors test_worker_budget._min_paths) ----------

def _min_paths(ws: Path) -> dict:
    """Minimal pre_check paths dict — every other gate fails open on it, so a
    rc here is attributable to the plan gate alone."""
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


def _anchor_log(ws: Path, key: str = 'C001') -> Path:
    return ws / 'runs' / f'.dispatch-anchor-{key}.jsonl'


def _seed_prior_dispatch(ws: Path, ts: str = '2026-09-10T01:00:00Z') -> None:
    """Seed ONE prior approved dispatch for C-001 (what stamp_dispatch_anchor
    writes at the approval point)."""
    ws.mkdir(parents=True, exist_ok=True)
    (ws / 'runs').mkdir(exist_ok=True)
    _anchor_log(ws).write_text(
        json.dumps({'ts': ts, 'claim': 'C-001', 'agent': 'w-test'}) + '\n',
        encoding='utf-8')


def _seed_live_heartbeat(ws: Path) -> None:
    """A live heartbeat (2 adjacent ticks, freshest now) — needed once the
    FIRST dispatch's lifecycle linkage has created analysis_state.txt (the
    heartbeat gate fail-opens only while that file is absent)."""
    from datetime import datetime, timedelta, timezone
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    now_dt = datetime.now(timezone.utc)
    prev_dt = now_dt - timedelta(minutes=5)
    fmt = lambda dt: dt.isoformat(timespec='seconds').replace('+00:00', 'Z')
    (ws / 'runs' / '.heartbeat.json').write_text(json.dumps({
        'last_tick_ts': fmt(now_dt), 'activity_ts': fmt(now_dt),
        'started_ts': fmt(prev_dt),
        'tick_history': [fmt(prev_dt), fmt(now_dt)],
    }), encoding='utf-8')


# ---------- 1. FIRST dispatch: no pre-existing plan required ----------

def test_first_dispatch_passes_without_any_plan(tmp_path):
    """Replay of the field evidence: a fresh claim, no plan file anywhere, no plan
    reference in the prompt — the FIRST dispatch must PASS. Planning is the
    worker's first act of execution, not a dispatch precondition."""
    from worker_budget_gates import check_worker_plan
    ws = tmp_path / 'ws'
    ok, msg = check_worker_plan({'workspace': str(ws)}, 'C-001')
    assert ok, f'first dispatch must not be plan-gated: {msg}'


def test_first_dispatch_e2e_replay_fresh_claim(tmp_path, capsys):
    """RED e2e replay of the field evidence: dispatching a fresh claim with
    no plan on disk passes pre_check (rc=0)."""
    import worker_budget_sinks as sinks
    ws = tmp_path / 'ws'
    rc = sinks.pre_check(_payload(_dispatch_prompt()), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err


def test_first_dispatch_ignores_prewritten_plan_entirely(tmp_path):
    """The orchestrator's ghostwritten plan is IRRELEVANT to a first dispatch:
    it neither satisfies nor blocks anything — there is nothing left to
    satisfy at dispatch time (that is the point of the ruling)."""
    from worker_budget_gates import check_worker_plan
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    (ws / 'runs' / 'plan-C001-strings.md').write_text(
        'goal:\npreflight:\nsteps:\nfallback:\n', encoding='utf-8')
    ok, msg = check_worker_plan({'workspace': str(ws)}, 'C-001')
    assert ok, f'first dispatch must not inspect the pre-written plan: {msg}'


# ---------- 2. Re-dispatch beyond the planning round ----------

def test_redispatch_without_plan_reference_rejected(tmp_path):
    """A re-dispatch (prior approved dispatch exists) without any plan on
    disk and without a plan reference in the prompt is still REJECTED."""
    from worker_budget_gates import check_worker_plan
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    ok, msg = check_worker_plan({'workspace': str(ws)}, 'C-001')
    assert not ok, 're-dispatch beyond the planning round requires the plan'
    assert 'plan' in msg.lower()


def test_redispatch_e2e_replay_full_lifecycle(tmp_path, capsys):
    """E2E: first dispatch passes and stamps its anchor; a second dispatch
    with no worker-authored plan in between REJECTS on the plan gate."""
    import worker_budget_sinks as sinks
    ws = tmp_path / 'ws'
    payload = _payload(_dispatch_prompt())
    paths = _min_paths(ws)
    assert sinks.pre_check(payload, paths) == 0, capsys.readouterr().err
    assert _anchor_log(ws).exists(), 'first dispatch must stamp its anchor'
    _seed_live_heartbeat(ws)  # lifecycle linkage created the state file
    rc = sinks.pre_check(_payload(_dispatch_prompt()), paths)
    captured = capsys.readouterr()
    assert rc == 2, captured.err
    assert 'REJECT plan' in captured.err


def test_prompt_plan_reference_is_redispatch_continuity(tmp_path):
    """The in-prompt --plan reference is the RE-DISPATCH continuity leg:
    with a prior approved dispatch and no on-disk file yet, referencing the
    claim's plan path passes (timing relaxation lives on this leg only)."""
    from worker_budget_gates import check_worker_plan
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    ok, msg = check_worker_plan(
        {'workspace': str(ws)}, 'C-001',
        'facts-snapshot: 1 facts; write runs/plan-C001-strings.md first, '
        'then execute')
    assert ok, msg


def test_prompt_plan_reference_wrong_claim_on_redispatch_rejected(tmp_path):
    """A plan path for a DIFFERENT claim does not continue THIS claim."""
    from worker_budget_gates import check_worker_plan
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    ok, msg = check_worker_plan(
        {'workspace': str(ws)}, 'C-001',
        'facts-snapshot: 1 facts; plan: runs/plan-C002-strings.md')
    assert not ok, msg


# ---------- 3. Provenance: maker != checker for plans (issue 237 D3 mirror) ----------

def test_ghostwritten_plan_does_not_satisfy_redispatch(tmp_path, capsys):
    """A plan the orchestrator ghostwrites BETWEEN dispatches (no dispatch
    anchor citation, mtime predating the first dispatch) does not satisfy
    plan-first for the worker: the re-dispatch REJECTS on provenance."""
    import worker_budget_sinks as sinks
    from datetime import datetime, timezone
    ws = tmp_path / 'ws'
    paths = _min_paths(ws)
    assert sinks.pre_check(_payload(_dispatch_prompt()), paths) == 0, \
        capsys.readouterr().err
    _seed_live_heartbeat(ws)  # lifecycle linkage created the state file
    plan = ws / 'runs' / 'plan-C001-strings.md'
    plan.write_text('goal: decode strings\nsteps: dump\nfallback: xxd\n',
                    encoding='utf-8')
    anchor_ts = json.loads(
        _anchor_log(ws).read_text(encoding='utf-8').splitlines()[-1])['ts']
    before = (datetime.fromisoformat(
        anchor_ts.replace('Z', '+00:00')).timestamp() - 3600)
    os.utime(plan, (before, before))
    rc = sinks.pre_check(_payload(_dispatch_prompt()), paths)
    captured = capsys.readouterr()
    assert rc == 2, 'ghostwritten plan must not satisfy the re-dispatch'
    assert 'REJECT plan' in captured.err
    assert 'worker' in captured.err.lower()


def test_worker_authored_plan_satisfies_redispatch(tmp_path, capsys):
    """The happy path the ruling enables: first dispatch (planning round) ->
    the worker writes its own plan citing its dispatch anchor -> the
    re-dispatch (execution round) passes."""
    import worker_budget_sinks as sinks
    ws = tmp_path / 'ws'
    paths = _min_paths(ws)
    assert sinks.pre_check(_payload(_dispatch_prompt()), paths) == 0, \
        capsys.readouterr().err
    _seed_live_heartbeat(ws)  # lifecycle linkage created the state file
    anchor_ts = json.loads(
        _anchor_log(ws).read_text(encoding='utf-8').splitlines()[-1])['ts']
    plan = ws / 'runs' / 'plan-C001-strings.md'
    plan.write_text(
        f'dispatch-anchor: {anchor_ts}\n'
        'goal: decode strings\nsteps: dump strings\nfallback: xxd walk\n',
        encoding='utf-8')
    rc = sinks.pre_check(_payload(_dispatch_prompt()), paths)
    assert rc == 0, capsys.readouterr().err


@pytest.mark.parametrize('claim,prompt_ref', [
    ('C-001', 'runs/plan-c001-strings.md'),
    ('C-001', 'runs/plan-C001.md'),
])
def test_prompt_reference_case_insensitive_on_redispatch(tmp_path, claim,
                                                         prompt_ref):
    """Real-world lowercase plan naming (plan-c005.md style) continues to
    satisfy the re-dispatch continuity leg."""
    from worker_budget_gates import check_worker_plan
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    ok, msg = check_worker_plan(
        {'workspace': str(ws)}, claim,
        f'facts-snapshot: 1 facts; plan: {prompt_ref}')
    assert ok, msg
