#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_sampled_binds_794.py — #794 R2: sampled-binds-to-dispatch.

Production counterexample (logs panel 2026-10-23): 17/17 sample_deviation
rows joined to a dispatch that ran the DECLARED family, never the SAMPLED
one — the sampler never bound. This card pins the invariant: the sampler's
draw is the dispatch contract.

  - declared == sampled            -> pass (unchanged);
  - declared != sampled, SILENT    -> REJECT (the 17/17 shape: an override
    with no recorded decision is exactly "sampling never binds");
  - declared != sampled, reasoned  -> pass ONLY with a coherent deviation:
    propensity > 0 (a probability-0 draw is invalid for IPS — #792 family;
    the declared family was never in the policy's support);
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


# ---------- 1. the 17/17 shape: silent deviation REJECTS ----------------

def test_silent_deviation_rejected_sampled_family_is_the_exit(
        tmp_path, capsys):
    """The production 17/17 replay: the prior holds only static-decompile
    (the sampler's only candidate), the envelope declares dynamic-trace
    with NO recorded override — the dispatch must REJECT naming the
    sampled family, and no usage row / deviation row may paper over it."""
    ws = tmp_path / 'ws'
    _seed_history(ws, 'static-decompile')
    rc = sinks.pre_check(
        _dispatch_payload(_full_prompt('dynamic-trace')), _min_paths(ws))
    err = capsys.readouterr().err
    assert rc == 2, (
        f"RED (#794 R2): the silent deviation passed (rc={rc}) — the "
        f"sampler did not bind; err={err[-300:]}")
    assert 'static-decompile' in err, "guidance must name the sampled exit"
    assert _usage_rows(ws) == [], "a rejected dispatch records no row"
    assert _events(ws, 'sample_deviation') == []


def test_reasoned_deviation_with_zero_propensity_rejected(tmp_path, capsys):
    """An agent-reasoning line alone does not buy a deviation whose
    propensity is 0.0 — the declared family was never a candidate, so the
    "decision" is incoherent for IPS (#792 propensity-coherence family)."""
    ws = tmp_path / 'ws'
    _seed_history(ws, 'static-decompile')
    prompt = _full_prompt(
        'dynamic-trace',
        extra='agent-reasoning: dynamic claims fit this binary better')
    rc = sinks.pre_check(_dispatch_payload(prompt), _min_paths(ws))
    err = capsys.readouterr().err
    assert rc == 2, f"RED (#794 R2): the p=0 deviation passed (rc={rc})"
    assert 'propensity' in err


# ---------- 2. the coherent recorded deviation passes --------------------

def test_coherent_reasoned_deviation_passes_and_records(
        tmp_path, capsys, monkeypatch):
    """deviates + recorded reason + propensity > 0 -> the dispatch passes,
    the dispatch row keeps the reconciliation, and the sample_deviation event
    carries the reason AND the positive propensity (the 留痕 face)."""
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
    assert row['propensity'] == 0.4
    evs = _events(ws, 'sample_deviation')
    assert len(evs) == 1
    det = _detail(evs[0])
    assert det['propensity'] == 0.4
    assert det['reason'] and 'obfuscated loader' in det['reason']


# ---------- 3. the unchanged faces ---------------------------------------

def test_matched_declaration_still_passes(tmp_path, capsys):
    ws = tmp_path / 'ws'
    _seed_history(ws, 'static-decompile')
    rc = sinks.pre_check(
        _dispatch_payload(_full_prompt('static-decompile')), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    assert _events(ws, 'sample_deviation') == []


def test_cold_sampler_still_fails_open(tmp_path, capsys):
    """No prior material -> the honest all-None gap -> no deviation, no
    reject: cold-start dispatches are not the bind contract's business."""
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
