#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_sampled_binds_794.py — the sampler draw is recorded evidence.

Record-only sampling posture: the dispatch envelope's declaration is the
policy; the gate's own draw is evidence on the record, never a gate.

  - declared == sampled            -> pass (unchanged);
  - declared != sampled, SILENT    -> pass, and the deviation is recorded
    (family_override with the reason slot explicitly null + one
    ``sample_deviation`` event — the 17/17 production shape can never
    recur silently because the pair is on the row);
  - declared != sampled, reasoned  -> pass, and the ``agent-reasoning:``
    line rides the deviation record;
  - an undeclared dispatch adopts the gate's own draw as its
    declaration when the sampler has material; a cold sampler leaves
    the honest gap (no family fabricated);
  - the task contract stays a REJECT: a sampled dynamic-trace under a
    ``dynamic_re: forbidden`` task_spec still refuses (the constraint
    runs after the adoption);
  - the off-registry other(...) escape keeps the #432 quarantine face.

Synthetic fixtures throughout (public repo): the sampler view is
monkeypatched at the sink boundary — no private corpora.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import worker_budget_sinks as sinks

_SEED_SIG = "abcdabcdabcd"


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


def _undeclared_prompt(extra: str = '') -> str:
    """The envelope declares no method_family — the undeclared face."""
    env = {'version': 1, 'claim': 'C-001', 'tier': 1,
           'tools': ['grep'], 'agent': 'w-test'}
    prompt = json.dumps({'kunglao_dispatch': env}) + '\nfacts-snapshot: 1 facts'
    return f'{prompt}\n{extra}' if extra else prompt


def _seed_history(ws: Path, family: str, n: int = 3) -> None:
    from rlvr import q_cells
    for i in range(n):
        q_cells.append_observation(ws, _SEED_SIG, family, None,
                                   source='dispatch', claim=f'seed-{i}')


def _usage_rows(ws: Path, claim: str = "C-001") -> list[dict]:
    """The gated claim"s dispatch observation rows (#804 usage merge:
    the former usage-log read — the dispatch row IS the record)."""
    from rlvr import q_cells
    return [r for r in q_cells.JSONLQStore(ws).observations()
            if r.get("source") == "dispatch"
            and r.get("claim") == claim]


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


# ---------- 1. the 17/17 shape: silent deviation passes, recorded --------

def test_silent_deviation_is_allowed_and_recorded(tmp_path, capsys):
    """The production 17/17 replay, record-only posture: the prior holds
    only static-decompile (the sampler's only candidate), the envelope
    declares dynamic-trace with NO recorded override — the dispatch
    passes and the row records the pair (family_override with the
    reason slot explicitly null) plus one ``sample_deviation`` event, so
    a silent deviation can never recur invisibly."""
    ws = tmp_path / 'ws'
    _seed_history(ws, 'static-decompile')
    rc = sinks.pre_check(
        _dispatch_payload(_full_prompt('dynamic-trace')), _min_paths(ws))
    err = capsys.readouterr().err
    assert rc == 0, f"the recorded deviation must pass: rc={rc}, err={err[-300:]}"
    row = _usage_rows(ws)[-1]
    assert row['method_family'] == 'dynamic-trace'
    assert row['sampled_family'] == 'static-decompile'
    assert row['family_override'] is True
    assert row['override_source'] == 'declared'
    assert row['override_reason'] is None
    evs = _events(ws, 'sample_deviation')
    assert len(evs) == 1
    det = _detail(evs[0])
    assert det['declared'] == 'dynamic-trace'
    assert det['sampled'] == 'static-decompile'
    assert det['reason'] is None


def test_reasoned_deviation_records_the_reason(tmp_path, capsys):
    """A deviation whose declared family was never a sampler candidate
    (the p=0 shape) passes under the record-only posture, and the
    ``agent-reasoning:`` line rides both the row and the event — the
    decision is recorded, never refused, never silent."""
    ws = tmp_path / 'ws'
    _seed_history(ws, 'static-decompile')
    prompt = _full_prompt(
        'dynamic-trace',
        extra='agent-reasoning: dynamic claims fit this binary better')
    rc = sinks.pre_check(_dispatch_payload(prompt), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    row = _usage_rows(ws)[-1]
    assert row['family_override'] is True
    assert row['override_source'] == 'agent-reasoning'
    assert row['override_reason'] == ('dynamic claims fit this binary '
                                      'better')
    evs = _events(ws, 'sample_deviation')
    assert len(evs) == 1
    det = _detail(evs[0])
    assert det['reason'] == 'dynamic claims fit this binary better'


# ---------- 2. the coherent recorded deviation passes --------------------

def test_coherent_reasoned_deviation_passes_and_records(
        tmp_path, capsys, monkeypatch):
    """deviates + recorded reason + propensity > 0 -> the dispatch passes,
    the dispatch row keeps the reconciliation marked as an explicit
    override (the draw-family propensity never pairs with the declared
    arm), and the sample_deviation event carries the reason AND the
    positive propensity (the 留痕 face)."""
    ws = tmp_path / 'ws'
    _seed_history(ws, 'static-decompile')
    monkeypatch.setattr(
        sinks, '_sample_reconciliation',
        lambda ws_, declared: {'sampled_family': 'static-decompile',
                               'propensity': 0.4,
                               'prior_source': 'history',
                               'deviates': True})
    prompt = _full_prompt(
        'dynamic-trace',
        extra='agent-reasoning: the pcap shows an obfuscated loader, '
              'dynamic first')
    rc = sinks.pre_check(_dispatch_payload(prompt), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    row = _usage_rows(ws)[-1]
    assert row['method_family'] == 'dynamic-trace'
    assert row['sampled_family'] == 'static-decompile'
    assert row['propensity'] is None
    assert row['family_override'] is True
    assert row['override_source'] == 'agent-reasoning'
    assert row['override_propensity'] == 0.4
    evs = _events(ws, 'sample_deviation')
    assert len(evs) == 1
    det = _detail(evs[0])
    assert det['propensity'] == 0.4
    assert det['reason'] and 'obfuscated loader' in det['reason']


# ---------- 3. the undeclared face: adopt the draw, or the honest gap ----

def test_undeclared_with_cold_sampler_passes_without_a_fabricated_family(
        tmp_path, capsys):
    """No declaration + no sampler material -> the honest gap: the
    dispatch passes, no family is fabricated anywhere (no observation
    row, no method_family on the lifecycle record, no deviation)."""
    ws = tmp_path / 'ws'
    rc = sinks.pre_check(
        _dispatch_payload(_undeclared_prompt()), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    assert _usage_rows(ws) == []
    dispatches = _events(ws, 'dispatch')
    assert len(dispatches) == 1
    assert 'method_family=' not in (dispatches[0].get('detail') or '')
    assert _events(ws, 'sample_deviation') == []
    assert not (ws / 'runs' / 'method-family-quarantine.jsonl').exists()


def test_undeclared_adopts_the_sampled_family_as_declaration(
        tmp_path, capsys):
    """No declaration + sampler material -> the gate's own draw becomes
    the dispatch's declaration: the dispatch passes and the adopted
    family is on the lifecycle record (countable, replay-indexable);
    the adopted draw is recorded with its source."""
    ws = tmp_path / 'ws'
    _seed_history(ws, 'static-decompile')
    rc = sinks.pre_check(
        _dispatch_payload(_undeclared_prompt()), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    dispatches = _events(ws, 'dispatch')
    assert len(dispatches) == 1
    assert 'method_family=static-decompile' in dispatches[0].get('detail', '')
    assert _events(ws, 'sample_deviation') == []


# ---------- 4. the kept boundary: the task contract still refuses --------

def test_forbidden_dynamic_sample_still_rejects(tmp_path, capsys,
                                                monkeypatch):
    """The record-only posture never overrides the task contract: an
    undeclared dispatch whose adopted draw is dynamic-trace under a
    ``dynamic_re: forbidden`` task_spec still REJECTS — the constraint
    check runs after the adoption, and dispatching forbidden dynamic RE
    would violate the contract itself."""
    ws = tmp_path / 'ws'
    paths = _min_paths(ws)
    paths['task_spec'].write_text(
        'constraints:\n  dynamic_re: forbidden\n', encoding='utf-8')
    from rlvr.strategy_store import PosteriorStrategyStore

    monkeypatch.setattr(
        PosteriorStrategyStore, 'method_sample',
        lambda self, fingerprint: {'family': 'dynamic-trace',
                                   'candidates': {'dynamic-trace': {'weight': 1}},
                                   'prior_source': 'history'})
    rc = sinks.pre_check(
        _dispatch_payload(_undeclared_prompt()), paths)
    err = capsys.readouterr().err
    assert rc == 2, f"the forbidden draw must still reject: rc={rc}"
    assert 'forbids dynamic_re' in err
    assert _usage_rows(ws) == [], "a rejected dispatch records no row"


# ---------- 5. the unchanged faces ---------------------------------------

def test_matched_declaration_still_passes(tmp_path, capsys):
    ws = tmp_path / 'ws'
    _seed_history(ws, 'static-decompile')
    rc = sinks.pre_check(
        _dispatch_payload(_full_prompt('static-decompile')), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    assert _events(ws, 'sample_deviation') == []


def test_cold_sampler_still_fails_open(tmp_path, capsys):
    """No prior material -> the honest all-None gap -> no deviation, no
    reject: cold-start dispatches are not the record contract's business."""
    ws = tmp_path / 'ws'
    rc = sinks.pre_check(
        _dispatch_payload(_full_prompt('dynamic-trace')), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err


def test_other_escape_keeps_the_quarantine_face(tmp_path, capsys):
    """The #432 off-registry escape is a triage face, not a bind-contract
    declaration — it keeps passing (and quarantining) even when sampler
    material exists."""
    ws = tmp_path / 'ws'
    _seed_history(ws, 'static-decompile')
    rc = sinks.pre_check(
        _dispatch_payload(_full_prompt('other(neat uncode trick)')),
        _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    q = ws / 'runs' / 'method-family-quarantine.jsonl'
    assert q.is_file() and 'neat uncode trick' in q.read_text(
        encoding='utf-8')


def test_adoption_records_the_same_draw_and_settles_by_dispatch_id(tmp_path, monkeypatch):
    from rlvr import q_cells, strategy_store

    ws = tmp_path / "workspace"
    paths = _min_paths(ws)
    draws = []

    def sample(self, fingerprint, **kwargs):
        draws.append(fingerprint)
        family = "static-decompile" if len(draws) == 1 else "dynamic-trace"
        return {"family": family, "prior_source": "history",
                "candidates": {family: {"weight": 1.0}},
                "candidate_sources": {family: ["history"]}}

    monkeypatch.setattr(strategy_store.PosteriorStrategyStore, "method_sample", sample)
    prompt = _undeclared_prompt()
    assert sinks.pre_check(_dispatch_payload(prompt), paths) == 0
    rows = _usage_rows(ws)
    assert len(rows) == 1
    row = rows[0]
    assert len(draws) == 1
    assert row["method_family"] == row["sampled_family"] == "static-decompile"
    assert row["method_source"] == "sampled-adoption"
    assert "method_family" not in json.loads(prompt.splitlines()[0])["kunglao_dispatch"]
    dispatch_id = row["dispatch_id"]
    assert q_cells.observe_settlement(ws, dispatch_id, 1.0)["appended"]
    assert q_cells.banked_mass(ws, dispatch_id) == (1.0, 0.0, 1)


def test_adopted_method_is_sent_to_worker_without_permission_override(
        tmp_path, capsys):
    ws = tmp_path / "ws"
    _seed_history(ws, "static-decompile")
    prompt = _undeclared_prompt()
    payload = _dispatch_payload(prompt)
    payload["tool_name"] = "Agent"
    payload["tool_use_id"] = "toolu_synthetic"
    assert sinks.pre_check(payload, _min_paths(ws)) == 0
    response = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert response["hookEventName"] == "PreToolUse"
    assert "permissionDecision" not in response
    updated = response["updatedInput"]
    assert updated["name"] == payload["tool_input"]["name"]
    assert updated["description"] == payload["tool_input"]["description"]
    head, suffix = updated["prompt"].split("\n", 1)
    assert suffix == prompt.split("\n", 1)[1]
    assert json.loads(head)["kunglao_dispatch"]["method_family"] == "static-decompile"


def test_hook_credit_observation_requires_the_correlated_execution(
        tmp_path, capsys):
    ws = tmp_path / "ws"
    paths = _min_paths(ws)
    _seed_history(ws, "static-decompile")
    payload = _dispatch_payload(_undeclared_prompt())
    payload.update(tool_name="Agent", tool_use_id="toolu_first")
    assert sinks.pre_check(payload, paths) == 0
    effective = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["updatedInput"]
    assert _usage_rows(ws) == []  # other hooks or permission checks can still refuse

    after = {**payload, "hook_event_name": "PostToolUse", "tool_response": {}}
    assert sinks.post_check(after, paths) == 0  # original input never confirms adoption
    assert sinks.post_check({**after, "tool_input": effective,
                             "tool_use_id": "toolu_other"}, paths) == 0
    assert _usage_rows(ws) == []
    after["tool_input"] = effective
    assert sinks.post_check(after, paths) == 0
    assert sinks.post_check(after, paths) == 0
    row, = _usage_rows(ws)
    assert row["method_family"] == row["sampled_family"] == "static-decompile"
    assert row["method_source"] == "sampled-adoption"


def test_concurrent_callback_replay_publishes_one_observation(tmp_path, capsys, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from threading import Event, local

    from rlvr import consolidated_ledger as cl, q_cells

    ws = tmp_path / "ws"
    paths = _min_paths(ws)
    _seed_history(ws, "static-decompile")
    payload = _dispatch_payload(_undeclared_prompt())
    payload.update(tool_name="Agent", tool_use_id="toolu_replay")
    assert sinks.pre_check(payload, paths) == 0
    effective = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["updatedInput"]
    after = dict(payload, tool_input=effective, hook_event_name="PostToolUse")
    first_read = Event()
    second_arrived = Event()
    role = local()
    read_rows = q_cells.dispatch_rows
    lock = cl.family_lock

    def snapshot(root):
        rows = read_rows(root)
        if role.number == 1:
            first_read.set()
            assert second_arrived.wait(10)
        else:
            second_arrived.set()
        return rows

    @contextmanager
    def observe_lock(*args, **kwargs):
        if role.number == 2:
            second_arrived.set()
        with lock(*args, **kwargs):
            yield

    def callback(number):
        role.number = number
        sinks._record_executed_method(after, paths)

    monkeypatch.setattr(q_cells, "dispatch_rows", snapshot)
    monkeypatch.setattr(cl, "family_lock", observe_lock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(callback, 1)
        assert first_read.wait(10)
        two = pool.submit(callback, 2)
        one.result(timeout=10)
        two.result(timeout=10)
    assert len(_usage_rows(ws)) == 1
