#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_method_families_432.py — issue #432: method-family
vocabulary registry (make dispatch actions countable for
Q(state signature, method family)).

Covers the six spec faces:

1. scripts/method_families.yaml registry (EMIT_ACTIONS precedent: closed
   token set, gate-validated, fail-closed on unregistered/missing);
2. envelope required field method_family:<token> validated at ONE
   chokepoint — the worker_budget_sinks pre_check battery (the
   facts-snapshot/devreason field-validation zone). dispatch_gate.py
   stays method_family-free (pinned by source scan);
3. other(<one-line>) quarantine + triage face (frequency report +
   promotion candidates, NO auto-promote);
4. method family (approach) = the Q key; tool chain = rider — pinned in
   the registry header;
5. vocabulary MINED not invented (derivation doc exists, per-family
   counts; the token set is pinned exactly);
6. health signals (never-fills / dominates-all / other>20% persistent)
   computed from (family, cell) usage and rendered at the existing Q
   report face (experience_triples.q_report).

Replay re-index test uses an EMBEDDED compact fixture (no /kunglao-wt
dependency at test time): >= 3 cells with n >= 3.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import method_families as mf
import worker_budget_sinks as sinks

import experience_triples as xt

_HERE = Path(__file__).parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))


def _stderr(capsys) -> str:
    return capsys.readouterr().err


# ---------------------------------------------------------------------------
# fixtures (same shapes as tests/test_gate_residuals_427.py — the sink-face
# pre_check harness: minimal paths, v1 envelope + facts-snapshot marker)
# ---------------------------------------------------------------------------

def _min_paths(ws: Path) -> dict:
    """Minimal pre_check paths dict — other gates fail-open on it."""
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


def _envelope(family: str | None = None, claim: str = 'C-001') -> str:
    """v1 protocol envelope; method_family included unless None."""
    env = {'version': 1, 'claim': claim, 'tier': 1,
           'tools': ['grep'], 'agent': 'w-test'}
    if family is not None:
        env['method_family'] = family
    return json.dumps({'kunglao_dispatch': env})


def _full_prompt(family: str | None = None) -> str:
    """The full-pass dispatch prompt (envelope + facts-snapshot)."""
    return _envelope(family) + '\nfacts-snapshot: 1 facts'


# ---------------------------------------------------------------------------
# A. registry contract (closed vocabulary, mined, pinned exactly)
# ---------------------------------------------------------------------------

MINED_TOKENS = frozenset({
    'structural-anchoring',
    'static-decompile',
    'dynamic-trace',
    'obfuscation-peeling',
    'crypto-core-identification',
    'kdf-chain-reconstruction',
    'protocol-flow-reconstruction',
    'anti-analysis-discrimination',
    'replay-harness-verification',
    'pair-match-verification',
    'red-team-verification',
    'hypothesis-falsification',
})


def test_registry_pins_the_mined_token_set():
    """#432: the registry is a CLOSED set — one word per approach face,
    mined from the v016 campaign + quickref taxonomy (derivation doc
    carries the counts). Drift must be a conscious diff, never silent."""
    assert mf.registered_tokens() == MINED_TOKENS
    assert mf.SCHEMA == 'method-families/1'


def test_registry_tokens_are_unique_and_grammar_valid():
    toks = mf.load_registry()['families']
    tokens = [f['token'] for f in toks]
    assert len(tokens) == len(set(tokens)), 'duplicate token'
    for f in toks:
        assert mf.TOKEN_RE.fullmatch(f['token']), f['token']
        assert f.get('description'), f'{f["token"]} lacks description'
        assert f.get('mined'), f'{f["token"]} lacks mining citations'


def test_registry_header_documents_the_q_key_policy():
    """Method family (approach) = the Q key; the tool chain is a rider,
    never part of the key — pinned in the registry header itself."""
    text = mf.REGISTRY_PATH.read_text(encoding='utf-8')
    assert 'Q key' in text and 'rider' in text


def test_derivation_doc_exists_with_counts():
    """The vocabulary is MINED not invented: the derivation doc carries
    per-family counts/sources/examples from the mining sweep."""
    doc = _ROOT / 'scripts' / 'method_families.derivation.md'
    assert doc.is_file()
    body = doc.read_text(encoding='utf-8')
    for token in ('static-decompile', 'replay-roundtrip', 'kunglao-redteam'):
        assert token in body, f'derivation doc missing {token}'


# ---------------------------------------------------------------------------
# B. validate_method_family semantics (fail-closed vocabulary)
# ---------------------------------------------------------------------------

def test_validate_accepts_registered_token():
    ok, msg = mf.validate_method_family('static-decompile')
    assert ok and msg == ''


def test_validate_rejects_missing_or_blank():
    for bad in (None, '', '   '):
        ok, msg = mf.validate_method_family(bad)
        assert not ok, bad
        assert 'method_family' in msg or 'missing' in msg.lower()


def test_validate_rejects_unregistered_token():
    ok, msg = mf.validate_method_family('crypto-magic')
    assert not ok
    assert 'unregistered' in msg
    assert 'other(' in msg, 'guidance must name the escape hatch'


def test_validate_rejects_bare_other():
    """other without its one-line detail is a vocabulary dodge."""
    ok, msg = mf.validate_method_family('other')
    assert not ok
    assert 'one-line' in msg


def test_validate_accepts_other_with_one_line():
    ok, _msg = mf.validate_method_family('other(neat uncode trick)')
    assert ok


def test_validate_rejects_malformed_other():
    ok, _ = mf.validate_method_family('other()')
    assert not ok
    ok, _ = mf.validate_method_family('other(   )')
    assert not ok
    ok, _ = mf.validate_method_family('other(' + 'x' * 200 + ')')
    assert not ok
    ok, _ = mf.validate_method_family('other(two\nlines)')
    assert not ok


def test_parse_other_detail_roundtrip():
    assert mf.parse_other_detail('other(neat trick)') == 'neat trick'
    assert mf.parse_other_detail('static-decompile') is None


def test_registry_corruption_is_fail_closed(monkeypatch, tmp_path):
    """A registry the validator cannot read must not wave tokens through."""
    def _boom():
        raise mf.RegistryError('registry unreadable')
    monkeypatch.setattr(mf, 'load_registry', _boom)
    ok, msg = mf.validate_method_family('static-decompile')
    assert not ok and 'unreadable' in msg


# ---------------------------------------------------------------------------
# C. the single validation chokepoint: worker_budget_sinks pre_check
# ---------------------------------------------------------------------------

def test_pre_check_rejects_missing_method_family(tmp_path, capsys):
    """#432: a dispatch envelope WITHOUT method_family never leaves
    pre_check (fail-closed missing)."""
    ws = tmp_path / 'ws'
    rc = sinks.pre_check(_dispatch_payload(_full_prompt(family=None)),
                         _min_paths(ws))
    assert rc == 2
    assert 'REJECT methodfamily' in _stderr(capsys)


def test_pre_check_rejects_unregistered_token(tmp_path, capsys):
    ws = tmp_path / 'ws'
    rc = sinks.pre_check(
        _dispatch_payload(_full_prompt(family='crypto-magic')),
        _min_paths(ws))
    assert rc == 2
    err = _stderr(capsys)
    assert 'REJECT methodfamily' in err
    assert 'unregistered' in err


def test_pre_check_rejects_bare_other(tmp_path, capsys):
    ws = tmp_path / 'ws'
    rc = sinks.pre_check(_dispatch_payload(_full_prompt(family='other')),
                         _min_paths(ws))
    assert rc == 2
    assert 'one-line' in _stderr(capsys)


def test_pre_check_accepts_registered_token_and_records_usage(tmp_path, capsys):
    """ALLOW face: the validated token lands in the countable usage log
    (runs/method-family-log.jsonl), cell = the claim (W2 re-keys cells to
    state signatures; the vocabulary/counting face lands first)."""
    ws = tmp_path / 'ws'
    rc = sinks.pre_check(
        _dispatch_payload(_full_prompt(family='static-decompile')),
        _min_paths(ws))
    assert rc == 0, _stderr(capsys)
    rows = [json.loads(ln) for ln in
            (ws / 'runs' / 'method-family-log.jsonl').read_text(
                encoding='utf-8').splitlines() if ln.strip()]
    assert len(rows) == 1
    assert rows[0]['family'] == 'static-decompile'
    assert rows[0]['cell'] == 'C-001'
    assert rows[0]['schema'] == 'method-family-usage/1'


def test_pre_check_accepts_other_and_quarantines(tmp_path, capsys):
    """ALLOW face for the escape hatch: the one-line reason lands in the
    quarantine (runs/method-family-quarantine.jsonl) for triage."""
    ws = tmp_path / 'ws'
    rc = sinks.pre_check(
        _dispatch_payload(_full_prompt(family='other(neat uncode trick)')),
        _min_paths(ws))
    assert rc == 0, _stderr(capsys)
    q = [json.loads(ln) for ln in
         (ws / 'runs' / 'method-family-quarantine.jsonl').read_text(
             encoding='utf-8').splitlines() if ln.strip()]
    assert len(q) == 1
    assert q[0]['detail'] == 'neat uncode trick'
    assert q[0]['claim'] == 'C-001'


def test_pre_check_accepts_v0_prose_marker(tmp_path, capsys):
    """v0 dispatches declare the same field as a prose marker — one
    contract, two declaration faces (the #105 intent precedent)."""
    ws = tmp_path / 'ws'
    prompt = ('{"kunglao_dispatch": {"version": 1, "claim": "C-001", '
              '"tier": 1, "tools": ["grep"]}}\n'
              'strings\n'
              'facts-snapshot: 1 facts\n'
              'method-family: static-decompile')
    rc = sinks.pre_check(_dispatch_payload(prompt), _min_paths(ws))
    assert rc == 0, _stderr(capsys)
    assert (ws / 'runs' / 'method-family-log.jsonl').exists()


def test_non_dispatch_prompts_are_not_gated(tmp_path, capsys):
    """The leg fires on recognized dispatch shapes only — a plain Agent
    prompt (no envelope, no v0 shape) keeps the pre-#432 behavior."""
    ws = tmp_path / 'ws'
    rc = sinks.pre_check(
        _dispatch_payload('facts-snapshot: 1 facts'),
        _min_paths(ws))
    assert rc == 0, _stderr(capsys)
    assert not (ws / 'runs' / 'method-family-log.jsonl').exists()


def test_registry_outage_rejects_fail_closed(tmp_path, capsys, monkeypatch):
    """Owner ruling 2026-09-28 posture: a gate that cannot see must not
    wave the action through — registry unreadable -> REJECT."""
    def _boom():
        raise mf.RegistryError('registry unreadable')
    monkeypatch.setattr(mf, 'load_registry', _boom)
    ws = tmp_path / 'ws'
    rc = sinks.pre_check(
        _dispatch_payload(_full_prompt(family='static-decompile')),
        _min_paths(ws))
    assert rc == 2
    assert 'REJECT methodfamily' in _stderr(capsys)


def test_unified_log_dispatch_row_carries_the_family(tmp_path, capsys):
    """Replay re-index face: the ALLOW-tail lifecycle row embeds
    method_family=<token> so the unified log is re-indexable."""
    ws = tmp_path / 'ws'
    rc = sinks.pre_check(
        _dispatch_payload(_full_prompt(family='dynamic-trace')),
        _min_paths(ws))
    assert rc == 0, _stderr(capsys)
    logs = ws / 'runs' / 'logs'
    rows = []
    for p in sorted(logs.glob('kunglao-*.jsonl')):
        for ln in p.read_text(encoding='utf-8').splitlines():
            if ln.strip():
                rows.append(json.loads(ln))
    hits = [r for r in rows if r.get('action') == 'dispatch'
            and 'method_family=dynamic-trace' in str(r.get('detail'))]
    assert hits, 'lifecycle dispatch row lacks method_family=<token>'


def test_single_validation_chokepoint_is_the_battery():
    """#432 spec: ONE chokepoint, documented. The battery (worker_budget
    sinks pre_check) owns the field validation; dispatch_gate.py must not
    grow a second leg (source-scan pin, freeze-test style)."""
    sinks_src = (_ROOT / 'hooks' / 'worker_budget_sinks.py').read_text(
        encoding='utf-8')
    gate_src = (_ROOT / 'hooks' / 'dispatch_gate.py').read_text(
        encoding='utf-8')
    assert 'method_family' in sinks_src
    assert 'method_family' not in gate_src


# ---------------------------------------------------------------------------
# D. quarantine triage face (frequency report, NO auto-promote)
# ---------------------------------------------------------------------------

def _write_quarantine(ws: Path, details: list[str]) -> None:
    q = ws / 'runs' / 'method-family-quarantine.jsonl'
    q.parent.mkdir(parents=True, exist_ok=True)
    rows = [{'schema': 'method-family-quarantine/1', 'ts': f'2026-09-28T0{i}:00:00Z',
             'claim': f'C-00{i % 3 + 1:03d}', 'detail': d, 'agent': 'w-test'}
            for i, d in enumerate(details)]
    q.write_text('\n'.join(json.dumps(r) for r in rows) + '\n',
                 encoding='utf-8')


def test_triage_reports_frequencies_and_promotion_candidates(tmp_path):
    ws = tmp_path / 'ws'
    _write_quarantine(ws, ['unicorn-emulation', 'unicorn-emulation',
                           'unicorn-emulation', 'one-off probe'])
    report = mf.triage(ws)
    freqs = {row['detail']: row['count'] for row in report['frequencies']}
    assert freqs['unicorn-emulation'] == 3
    assert freqs['one-off probe'] == 1
    candidates = [c['detail'] for c in report['promotion_candidates']]
    assert 'unicorn-emulation' in candidates
    assert 'one-off probe' not in candidates


def test_triage_never_auto_promotes(tmp_path):
    """NO auto-promote: triage is advisory — the registry bytes are
    identical before and after (promotion is a reviewed diff)."""
    ws = tmp_path / 'ws'
    _write_quarantine(ws, ['unicorn-emulation'] * 5)
    before = mf.REGISTRY_PATH.read_bytes()
    mf.triage(ws)
    assert mf.REGISTRY_PATH.read_bytes() == before
    assert 'unicorn-emulation' not in mf.registered_tokens()


# ---------------------------------------------------------------------------
# E. replay re-index (EMBEDDED fixture: >= 3 cells with n >= 3)
# ---------------------------------------------------------------------------

def _write_usage(ws: Path, rows: list[dict]) -> None:
    p = ws / 'runs' / 'method-family-log.jsonl'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('\n'.join(json.dumps(r) for r in rows) + '\n',
                 encoding='utf-8')


def _usage_row(cell: str, family: str, ts: str = '2026-09-28T01:00:00Z',
               claim: str | None = None) -> dict:
    return {'schema': 'method-family-usage/1', 'ts': ts,
            'claim': claim or cell, 'cell': cell, 'family': family,
            'agent': 'w-test', 'tier': 1, 'tools': ['grep']}


def test_reindex_embedded_fixture_three_cells_n3(tmp_path):
    """Embedded compact fixture (no /kunglao-wt dependency): three cells,
    three dispatches each, plus one legacy log face counted as
    unattributed (honest gap, never fabricated)."""
    root = tmp_path / 'campaign'
    for cell in ('C-001', 'C-002', 'C-003'):
        ws = root / f'ws-{cell}'
        _write_usage(ws, [_usage_row(cell, 'static-decompile', claim=cell)
                          for _ in range(3)])
    # legacy face: a unified-log dispatch row WITHOUT method_family
    legacy = root / 'ws-legacy' / 'runs' / 'logs'
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / 'kunglao-2026-09-22.jsonl').write_text(json.dumps({
        'action': 'dispatch', 'actor': 'hook:worker_budget', 'claim': 'C-009',
        'detail': 'tier=1 tools=grep agent=w1 (#461 linkage)'}) + '\n',
        encoding='utf-8')
    # indexed face: a unified-log dispatch row WITH method_family (replay)
    replay = root / 'ws-replay' / 'runs' / 'logs'
    replay.mkdir(parents=True, exist_ok=True)
    (replay / 'kunglao-2026-09-23.jsonl').write_text(json.dumps({
        'action': 'dispatch', 'actor': 'hook:worker_budget', 'claim': 'C-010',
        'detail': 'tier=1 tools=node agent=web-re-worker '
                  'method_family=obfuscation-peeling'}) + '\n',
        encoding='utf-8')

    report = mf.reindex(root)
    cells = {c['cell']: c['n'] for c in report['cells']}
    assert sum(1 for n in cells.values() if n >= 3) >= 3, cells
    assert cells['C-001'] == 3
    assert report['unattributed'] == 1, 'legacy row must be counted, not fabricated'
    fams = {f['family']: f['count'] for f in report['families']}
    assert fams['obfuscation-peeling'] == 1


def test_reindex_empty_root_is_honest_zero(tmp_path):
    report = mf.reindex(tmp_path / 'nothing')
    assert report['cells'] == []
    assert report['unattributed'] == 0


# ---------------------------------------------------------------------------
# F. health signals rendered at the existing Q/report surface
# ---------------------------------------------------------------------------

def test_health_never_fills(tmp_path):
    """Registered vocabulary with zero usage is dead weight — surfaced."""
    ws = tmp_path / 'ws'
    _write_usage(ws, [_usage_row('C-001', 'static-decompile')])
    health = mf.family_health(ws)
    used = {'static-decompile'}
    assert health['never_fills']
    assert set(health['never_fills']) == mf.registered_tokens() - used


def test_health_dominates_all(tmp_path):
    ws = tmp_path / 'ws'
    rows = ([_usage_row(f'C-00{i}', 'static-decompile') for i in range(1, 10)]
            + [_usage_row('C-010', 'dynamic-trace')])
    _write_usage(ws, rows)
    health = mf.family_health(ws)
    assert health['dominates_all']['family'] == 'static-decompile'
    ws2 = tmp_path / 'ws2'
    _write_usage(ws2, [_usage_row(f'C-00{i}', 'static-decompile')
                       for i in (1, 2)]
                 + [_usage_row('C-003', 'dynamic-trace')
                    for _ in range(2)])
    assert mf.family_health(ws2)['dominates_all'] is None


def test_health_other_share_persistent(tmp_path):
    ws = tmp_path / 'ws'
    rows = ([_usage_row(f'C-00{i}', 'other(x)'.replace('x', 'gap reason'))
             for i in (1, 2, 3)]
            + [_usage_row(f'C-00{i}', 'static-decompile')
               for i in (4, 5, 6, 7, 8, 9, 10, 11, 12)])
    _write_usage(ws, rows)
    health = mf.family_health(ws)
    assert health['other_share_persistent'] is not None
    # NOT persistent: same share concentrated in ONE cell
    ws2 = tmp_path / 'ws2'
    _write_usage(ws2, [_usage_row('C-001', 'other(gap reason)')
                       for _ in range(3)]
                 + [_usage_row(f'C-00{i}', 'static-decompile')
                    for i in range(2, 12)])
    assert mf.family_health(ws2)['other_share_persistent'] is None


def test_q_report_renders_family_health(tmp_path):
    """The existing Q/report surface (experience_triples.q_report) carries
    the health block — additive key, Q arithmetic untouched."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    doc = xt.q_report(ws)
    assert doc['schema'] == 'q-report/1'
    assert 'method_family_health' in doc
    _write_usage(ws, [_usage_row('C-001', 'static-decompile')])
    doc2 = xt.q_report(ws)
    assert doc2['method_family_health']['never_fills']


# ---------------------------------------------------------------------------
# G. kunglao-init envelope template doc face (minimal)
# ---------------------------------------------------------------------------

def test_init_scaffold_names_the_envelope_field():
    """kunglao-init.py's scaffold teaches the v1 envelope WITH the field."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'kunglao_init_432', _ROOT / 'scripts' / 'kunglao-init.py')
    init = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(init)
    for kind in ('windows', 'linux', 'android', 'web', 'macos'):
        text = init.quick_start_scaffold(kind)
        assert 'method_family' in text, kind
        assert 'method_families.yaml' in text, kind
