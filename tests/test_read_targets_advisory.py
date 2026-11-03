# -*- coding: utf-8 -*-
"""read_targets advisory — coordinates-first dispatch.

The v1 dispatch envelope grows an ADVISORY ``read_targets`` block: the
orchestrator resolves each task target to ``path`` + (``symbol`` or
``lines``) and declares a ``read_fallback`` strategy for the case where
the coordinates no longer match at execution time (file revised, heading
moved, path gone). Enforcement is version-scoped: v1 envelopes stay
ADVISORY (a ``read_targets_advisory`` row, no reject), while v2 envelopes —
the action-tuple protocol — REJECT a missing/malformed block unless the
orchestrator declares ``"read_targets": "none (reasoning: ...)"``.

Contract under test:
  - ``lib_kunglao.read_targets_status(meta, workspace)`` — the single
    validator (status + human-readable errors).
  - ``hooks/worker_budget_sinks.pre_check`` — emits the advisory row after
    the last rejecting gate, never rejects.
  - ``hooks/recall_inject._guidance`` — the injected block carries the
    fallback rule (anchors can drift between dispatch and execution).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

from _path_hygiene import load_hooks_lib  # noqa: E402
from worker_budget import pre_check  # noqa: E402

import recall_inject  # noqa: E402


# ---------- helpers ----------

def _env(**fields) -> dict:
    """A minimal v1 envelope meta dict (the 4th element of parse_dispatch_json)."""
    meta = {"version": 1, "claim": "C-001", "tier": 1,
            "tools": ["grep"], "agent": "w-test",
            "method_family": "static-decompile"}
    meta.update(fields)
    return meta


def _env_v2(**fields) -> dict:
    """A v2 envelope meta dict — the action-tuple protocol requires the
    four action fields, and read_targets is ENFORCED at this version."""
    meta = {"version": 2, "claim": "C-001", "tier": 1,
            "tools": ["grep"], "agent": "w-test",
            "method_family": "static-decompile",
            "action_type": "dispatch", "context_recipe": "default",
            "verification_mode": "static", "control": "budget=1"}
    meta.update(fields)
    return meta


def _dispatch_payload(prompt: str, description: str = '') -> dict:
    return {'tool_input': {'name': 'w-test',
                           'description': description,
                           'prompt': prompt}}


def _min_paths(ws: Path) -> dict:
    return {
        'workspace': str(ws),
        'state': ws / 'analysis_state.txt',
        'register': ws / 'claim-register.yaml',
        'deps': ws / 'claim_deps.yaml',
        'task_spec': ws / 'task_spec.yaml',
    }


def _ledger_actions(ws: Path) -> list[str]:
    logs = ws / 'runs' / 'logs'
    if not logs.is_dir():
        return []
    return [json.loads(ln).get('action')
            for p in logs.glob('kunglao-*.jsonl')
            for ln in p.read_text(encoding='utf-8').splitlines() if ln.strip()]


def _prompt(meta: dict) -> str:
    return json.dumps({"kunglao_dispatch": meta}) + '\nfacts-snapshot: 1 facts'


# ---------- validator: missing / opt-out / valid ----------

def test_absent_read_targets_is_missing_not_malformed():
    status, errors = load_hooks_lib().read_targets_status(_env())
    assert status == 'missing'
    assert errors == []


def test_no_envelope_is_not_dispatch():
    """Role/non-claim dispatches carry no v1 envelope — the advisory does
    not apply and must not be logged as a defect. parse_dispatch_json
    returns None on failure."""
    status, errors = load_hooks_lib().read_targets_status(None)
    assert status == 'not_dispatch'
    assert errors == []


def test_empty_meta_is_missing_not_dispatch():
    """A LEGAL minimal envelope (tools/agent optional) yields an empty meta
    dict — that is an envelope without the key, not 'no dispatch'."""
    status, errors = load_hooks_lib().read_targets_status({})
    assert status == 'missing'
    assert errors == []


def test_explicit_none_opt_out_is_accepted():
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets='none (reasoning: single-file prose task)'))
    assert status == 'opt_out'
    assert errors == []


def test_valid_line_target_is_ok(tmp_path):
    (tmp_path / 'hooks').mkdir()
    (tmp_path / 'hooks' / 'demo.py').write_text(
        'line1\nline2\nline3\nline4\n', encoding='utf-8')
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'hooks/demo.py', 'lines': [2, 3],
                            'why': 'the function body'}],
             read_fallback='symbol-first'), tmp_path)
    assert status == 'ok', errors


def test_valid_symbol_target_is_ok(tmp_path):
    (tmp_path / 'hooks').mkdir()
    (tmp_path / 'hooks' / 'demo.py').write_text('def f():\n    pass\n',
                                                encoding='utf-8')
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'hooks/demo.py', 'symbol': 'f'}],
             read_fallback='symbol-first'), tmp_path)
    assert status == 'ok', errors


# ---------- validator: malformed shapes ----------

def test_lines_out_of_range_is_malformed(tmp_path):
    (tmp_path / 'a.py').write_text('one\ntwo\n', encoding='utf-8')
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'a.py', 'lines': [1, 99]}],
             read_fallback='symbol-first'), tmp_path)
    assert status == 'malformed'
    assert any('lines' in e for e in errors)


def test_inverted_lines_is_malformed():
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'a.py', 'lines': [5, 2]}],
             read_fallback='symbol-first'))
    assert status == 'malformed'


def test_target_needs_symbol_or_lines():
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'a.py'}], read_fallback='symbol-first'))
    assert status == 'malformed'
    assert any('symbol' in e or 'lines' in e for e in errors)


def test_unknown_fallback_is_malformed():
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'a.py', 'symbol': 'f'}],
             read_fallback='search-the-tree'))
    assert status == 'malformed'
    assert any('read_fallback' in e for e in errors)


def test_semantic_decide_is_a_legal_relevance_fallback():
    """Relevance failure (content read fine but does not fit the question) is
    delegated to the worker's LLM — a declared decision, not a search."""
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'a.py', 'symbol': 'f'}],
             read_fallback='symbol-first',
             relevance_fallback='semantic-decide'))
    assert status == 'ok', errors


def test_relevance_fallback_defaults_when_absent():
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'a.py', 'symbol': 'f'}],
             read_fallback='symbol-first'))
    assert status == 'ok', errors


def test_semantic_decide_is_not_a_locate_fallback():
    """The two classes are orthogonal: semantic-decide answers a content
    mismatch, not a moved line range."""
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'a.py', 'symbol': 'f'}],
             read_fallback='semantic-decide'))
    assert status == 'malformed'
    assert any('read_fallback' in e for e in errors)


def test_unknown_relevance_fallback_is_malformed():
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'a.py', 'symbol': 'f'}],
             read_fallback='symbol-first',
             relevance_fallback='search-some-more'))
    assert status == 'malformed'
    assert any('relevance_fallback' in e for e in errors)


def test_missing_fallback_is_malformed():
    """Coordinates without a failure rule are the exact half-contract this
    advisory exists to catch."""
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'a.py', 'symbol': 'f'}]))
    assert status == 'malformed'
    assert any('read_fallback' in e for e in errors)


def test_absent_path_is_malformed(tmp_path):
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'does_not_exist.py', 'symbol': 'f'}],
             read_fallback='symbol-first'), tmp_path)
    assert status == 'malformed'
    assert any('does not exist' in e for e in errors)


def test_declared_missing_file_is_ok(tmp_path):
    """A to-be-created file is a legal target when declared."""
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'runs/plan-C001.md', 'lines': [1, 5],
                            'missing': True}],
             read_fallback='exact-or-gap'), tmp_path)
    assert status == 'ok', errors


def test_documented_example_validates(tmp_path):
    """The contract doc's own example must validate — a doc that teaches an
    invalid shape makes every dispatch log malformed."""
    (tmp_path / 'hooks').mkdir()
    (tmp_path / 'hooks' / 'recall_inject.py').write_text(
        'def _section_anchor():\n    pass\n', encoding='utf-8')
    meta = _env(
        read_targets=[
            {'path': 'hooks/recall_inject.py', 'symbol': '_section_anchor',
             'why': 'the anchor rule under change'},
            {'path': 'runs/plan-C409.md', 'lines': [1, 40], 'missing': True},
        ],
        read_fallback='symbol-first',
        relevance_fallback='semantic-decide')
    status, errors = load_hooks_lib().read_targets_status(meta, tmp_path)
    assert status == 'ok', errors


def test_missing_flag_does_not_bypass_containment(tmp_path):
    """`missing: true` skips existence/line checks, never containment."""
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': '/etc/passwd', 'symbol': 'root',
                            'missing': True}],
             read_fallback='symbol-first'), tmp_path)
    assert status == 'malformed'
    assert any('escapes the workspace' in e for e in errors)


def test_absolute_path_escapes_workspace(tmp_path):
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': '/etc/passwd', 'symbol': 'root'}],
             read_fallback='symbol-first'), tmp_path)
    assert status == 'malformed'
    assert any('escapes the workspace' in e for e in errors)


def test_traversal_escapes_workspace(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    (tmp_path / 'secret.txt').write_text('x\n', encoding='utf-8')
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': '../secret.txt', 'lines': [1, 1]}],
             read_fallback='symbol-first'), ws)
    assert status == 'malformed'
    assert any('escapes the workspace' in e for e in errors)


def test_symlink_outside_workspace_escapes(tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    outside = tmp_path / 'outside.txt'
    outside.write_text('x\n', encoding='utf-8')
    (ws / 'link.txt').symlink_to(outside)
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'link.txt', 'lines': [1, 1]}],
             read_fallback='symbol-first'), ws)
    assert status == 'malformed'
    assert any('escapes the workspace' in e for e in errors)


def test_directory_target_is_malformed(tmp_path):
    (tmp_path / 'somedir').mkdir()
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets=[{'path': 'somedir', 'symbol': 'f'}],
             read_fallback='symbol-first'), tmp_path)
    assert status == 'malformed'
    assert any('regular file' in e for e in errors)


def test_non_integer_lines_are_malformed():
    for bad in ([True, 2], [1.0, 2.0], ['1', '2']):
        status, errors = load_hooks_lib().read_targets_status(
            _env(read_targets=[{'path': 'a.py', 'lines': bad}],
                 read_fallback='symbol-first'))
        assert status == 'malformed', bad


def test_non_list_read_targets_is_malformed():
    status, errors = load_hooks_lib().read_targets_status(
        _env(read_targets={'path': 'a.py'}, read_fallback='symbol-first'))
    assert status == 'malformed'


# ---------- hook integration: advisory, never a reject ----------

def test_pre_check_emits_missing_advisory_and_proceeds(tmp_path, capsys):
    ws = tmp_path / 'ws'
    rc = pre_check(_dispatch_payload(_prompt(_env())), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    assert 'read_targets_advisory' in _ledger_actions(ws)


def test_pre_check_emits_ok_advisory_and_proceeds(tmp_path, capsys):
    ws = tmp_path / 'ws'
    (ws / 'hooks').mkdir(parents=True)
    (ws / 'hooks' / 'demo.py').write_text('one\ntwo\n', encoding='utf-8')
    meta = _env(read_targets=[{'path': 'hooks/demo.py', 'lines': [1, 2]}],
                read_fallback='symbol-first')
    rc = pre_check(_dispatch_payload(_prompt(meta)), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    rows = [json.loads(ln)
            for p in (ws / 'runs' / 'logs').glob('kunglao-*.jsonl')
            for ln in p.read_text(encoding='utf-8').splitlines() if ln.strip()]
    rows = [r for r in rows if r.get('action') == 'read_targets_advisory']
    assert rows and json.loads(rows[-1]['detail'])['status'] == 'ok'


def test_pre_check_emits_malformed_advisory_and_proceeds(tmp_path, capsys):
    ws = tmp_path / 'ws'
    meta = _env(read_targets=[{'path': 'a.py'}], read_fallback='symbol-first')
    rc = pre_check(_dispatch_payload(_prompt(meta)), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    rows = [json.loads(ln)
            for p in (ws / 'runs' / 'logs').glob('kunglao-*.jsonl')
            for ln in p.read_text(encoding='utf-8').splitlines() if ln.strip()]
    rows = [r for r in rows if r.get('action') == 'read_targets_advisory']
    assert rows and json.loads(rows[-1]['detail'])['status'] == 'malformed'


def test_advisory_emit_failure_still_proceeds(tmp_path, capsys, monkeypatch):
    """Observability never gates: a broken ledger emit must not reject."""
    import kunglao_log
    monkeypatch.setattr(kunglao_log, 'emit',
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError('boom')))
    ws = tmp_path / 'ws'
    rc = pre_check(_dispatch_payload(_prompt(_env())), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err


# ---------- version-scoped enforcement: v2 gates, v1 stays advisory ----------

def test_dispatch_protocol_version_reads_both_versions():
    lib = load_hooks_lib()
    assert lib.dispatch_protocol_version(_prompt(_env())) == 1
    assert lib.dispatch_protocol_version(_prompt(_env_v2())) == 2
    assert lib.dispatch_protocol_version("no envelope here") is None


def test_dispatch_protocol_version_rejects_unknown_versions():
    lib = load_hooks_lib()
    assert lib.dispatch_protocol_version(_prompt(_env(version=3))) is None
    assert lib.dispatch_protocol_version(
        _prompt(_env(version="two"))) is None


def test_v1_with_action_tuple_stays_advisory(tmp_path, capsys):
    """The boundary is the VERSION, not the presence of the action fields."""
    ws = tmp_path / 'ws'
    meta = _env(action_type='dispatch', context_recipe='default',
                verification_mode='static', control='budget=1')
    rc = pre_check(_dispatch_payload(_prompt(meta)), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    assert 'read_targets_advisory' in _ledger_actions(ws)


def test_v2_malformed_opt_out_rejects(tmp_path, capsys):
    ws = tmp_path / 'ws'
    for bad in ('none', 'none (no reasoning)'):
        rc = pre_check(_dispatch_payload(_prompt(_env_v2(read_targets=bad))),
                       _min_paths(ws))
        assert rc == 2, bad
        assert 'REJECT readtargets' in capsys.readouterr().err


def test_v2_missing_read_targets_rejects(tmp_path, capsys):
    ws = tmp_path / 'ws'
    rc = pre_check(_dispatch_payload(_prompt(_env_v2())), _min_paths(ws))
    err = capsys.readouterr().err
    assert rc == 2
    assert 'REJECT readtargets' in err
    rows = [json.loads(ln)
            for p in (ws / 'runs' / 'logs').glob('kunglao-*.jsonl')
            for ln in p.read_text(encoding='utf-8').splitlines() if ln.strip()]
    rows = [r for r in rows if r.get('action') == 'read_targets_gate']
    assert rows and json.loads(rows[-1]['detail'])['status'] == 'missing'
    assert json.loads(rows[-1]['detail'])['version'] == 2


def test_v2_malformed_read_targets_rejects(tmp_path, capsys):
    ws = tmp_path / 'ws'
    meta = _env_v2(read_targets=[{'path': 'a.py'}],
                   read_fallback='symbol-first')
    rc = pre_check(_dispatch_payload(_prompt(meta)), _min_paths(ws))
    assert rc == 2
    assert 'REJECT readtargets' in capsys.readouterr().err


def test_v2_valid_targets_pass(tmp_path, capsys):
    ws = tmp_path / 'ws'
    (ws / 'hooks').mkdir(parents=True)
    (ws / 'hooks' / 'demo.py').write_text('one\ntwo\n', encoding='utf-8')
    meta = _env_v2(read_targets=[{'path': 'hooks/demo.py', 'lines': [1, 2]}],
                   read_fallback='symbol-first')
    rc = pre_check(_dispatch_payload(_prompt(meta)), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err


def test_v2_opt_out_passes(tmp_path, capsys):
    ws = tmp_path / 'ws'
    meta = _env_v2(read_targets='none (reasoning: prose-only task)')
    rc = pre_check(_dispatch_payload(_prompt(meta)), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err


def test_v1_missing_read_targets_stays_advisory(tmp_path, capsys):
    """The version boundary is the rollout lever: v1 keeps phase-1
    behaviour (a row, no reject) while v2 is enforced."""
    ws = tmp_path / 'ws'
    rc = pre_check(_dispatch_payload(_prompt(_env())), _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    assert 'read_targets_advisory' in _ledger_actions(ws)


# ---------- injected recall carries the fallback rule ----------

def test_recall_guidance_carries_fallback_rule():
    block = recall_inject._guidance(['demo'], ['re-library/demo.md'])
    assert 'Before dispatching, read:' in block
    assert 're-anchor' in block
    assert 'GAP' in block
    assert len(block) <= recall_inject.MAX_INJECT_CHARS
