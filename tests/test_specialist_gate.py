# -*- coding: utf-8 -*-
"""tests/test_specialist_gate.py — issue #310: agenttype gate (specialist-first
as a MECHANICAL check).

Behavior #2 "specialist-first" was an orchestrator soft constraint — a
kunglao-worker could silently take a ghidra-type claim and complete it with
the full tool rack, diluting the specialist's dedicated prompt/strategy/
evidence format with no failure signal. The agenttype gate closes it the same
way devreason closed priority spoofing: dispatch agent type vs
route_capability recommendation (claim task domain x sample features x the
mechanical trigger table parsed from agents/*.md frontmatter).

Gate semantics:
  - no claim id / no agent name / router unavailable / register unreadable
    -> FAIL_OPEN (a broken gate must not block dispatch)
  - dispatched agent is a role agent (kunglao-redteam / kunglao-init-worker)
    -> silent (role dispatches are protocol-position, not claim routing)
  - recommendation is None (no specialist fits)      -> silent
  - dispatched agent == recommendation               -> pass
  - dispatched agent != recommendation               -> REJECT unless the
    prompt carries `agent-reasoning:` (deviation recorded, not silent)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent / 'hooks'))
sys.path.insert(0, str(_HERE.parent / 'scripts'))
import yaml  # noqa: E402
from worker_budget import check_agent_type, pre_check  # noqa: E402


# ---------- fixtures ----------

def _paths(ws: Path) -> dict:
    return {
        'workspace': str(ws),
        'state': ws / 'analysis_state.txt',
        'register': ws / 'claim-register.yaml',
        'deps': ws / 'claim_deps.yaml',
        'task_spec': ws / 'task_spec.yaml',
    }


def _register(ws: Path, statement: str) -> Path:
    p = ws / 'claim-register.yaml'
    p.write_text(yaml.safe_dump(
        {'claims': [{'id': 'C-001', 'status': 'OPEN', 'statement': statement}]},
        allow_unicode=True), encoding='utf-8')
    return p


def _desc(task: str = 'do the task') -> str:
    return f'[T1 tools=grep] claim C-001 {task}'


PROMPT = 'facts-snapshot: 1 facts'


# ---------- the four acceptance cases ----------

def test_match_agent_passes(tmp_path):
    """dispatch agent == recommended specialist -> pass."""
    ws = tmp_path
    _register(ws, 'decompile and disassemble the main function')
    ok, msg = check_agent_type(_paths(ws), _desc(), PROMPT, 'ghidra-light')
    assert ok, msg
    assert 'ghidra-light' in msg


def test_mismatch_with_reasoning_passes(tmp_path):
    """deviation with a recorded `agent-reasoning:` -> pass (recorded, not
    silent — the reasoning lives in the dispatch prompt itself)."""
    ws = tmp_path
    _register(ws, 'decompile and disassemble the main function')
    prompt = PROMPT + '\nagent-reasoning: kunglao-worker does the raw xref pass first'
    ok, msg = check_agent_type(_paths(ws), _desc(), prompt, 'kunglao-worker')
    assert ok, msg
    assert 'recorded' in msg


def test_mismatch_without_reasoning_rejects(tmp_path):
    """kunglao-worker for a ghidra-type claim with no agent-reasoning ->
    REJECT (the acceptance case from issue #310)."""
    ws = tmp_path
    _register(ws, 'decompile and disassemble the main function')
    ok, msg = check_agent_type(_paths(ws), _desc(), PROMPT, 'kunglao-worker')
    assert not ok
    assert 'agent-reasoning' in msg
    assert 'ghidra-light' in msg


def test_no_specialist_recommended_silent(tmp_path):
    """recommendation is None -> kunglao-worker silently allowed (pass with
    no REJECT; the informational msg is not emitted on ok)."""
    ws = tmp_path
    _register(ws, 'analyze the file structure')
    ok, msg = check_agent_type(_paths(ws), _desc(), PROMPT, 'kunglao-worker')
    assert ok and 'kunglao-worker allowed' in msg


# ---------- fail-open + role agents ----------

def test_role_agent_dispatch_skipped(tmp_path):
    """kunglao-redteam / kunglao-init-worker are dispatched by protocol
    position (verify phase), not claim routing — the gate must not fire."""
    ws = tmp_path
    _register(ws, 'decompile and disassemble the main function')
    for role in ('kunglao-redteam', 'kunglao-init-worker', 'verdict-redteam'):
        ok, msg = check_agent_type(_paths(ws), _desc(), PROMPT, role)
        assert ok, f'{role}: {msg}'


def test_no_claim_dispatch_fails_open(tmp_path):
    ws = tmp_path
    _register(ws, 'decompile the main function')
    ok, msg = check_agent_type(_paths(ws), 'no claim prefix here', PROMPT,
                               'kunglao-worker')
    assert ok


def test_missing_register_fails_open(tmp_path):
    ok, msg = check_agent_type(_paths(tmp_path), _desc(), PROMPT, 'kunglao-worker')
    assert ok


def test_unknown_claim_fails_open(tmp_path):
    ws = tmp_path
    _register(ws, 'decompile the main function')
    desc = '[T1 tools=grep] claim C-999 do the task'
    ok, msg = check_agent_type(_paths(ws), desc, PROMPT, 'kunglao-worker')
    assert ok


# ---------- sample features dimension ----------

def test_workspace_features_route_go_sample(tmp_path):
    """features from runs/feature-probe.json (die.json language=Go shape) ->
    go-symbols recommended even when the claim text itself carries no Go
    keyword; a ghidra-light dispatch for it deviates -> reasoning required."""
    ws = tmp_path
    (ws / 'runs').mkdir(parents=True)
    (ws / 'runs' / 'feature-probe.json').write_text(
        json.dumps({'language': 'Go', 'machine': 'AMD64'}), encoding='utf-8')
    _register(ws, 'identify the main function and its callees')
    ok, msg = check_agent_type(_paths(ws), _desc(), PROMPT, 'ghidra-light')
    assert not ok
    assert 'go-symbols' in msg


def test_feature_probe_file_unparseable_does_not_crash(tmp_path):
    """a broken runs/feature-probe.json must not crash the gate — claim text
    alone still drives the recommendation (ghidra-light) -> reject path."""
    ws = tmp_path
    (ws / 'runs').mkdir(parents=True)
    (ws / 'runs' / 'feature-probe.json').write_text('{broken', encoding='utf-8')
    _register(ws, 'decompile the main function')
    ok, msg = check_agent_type(_paths(ws), _desc(), PROMPT, 'kunglao-worker')
    assert not ok  # claim text alone still recommends ghidra-light
    assert 'agent-reasoning' in msg


def test_explicit_agent_type_declaration_matches_gate(tmp_path):
    """#310 prompt template: the orchestrator injects `agent_type:` from the
    route output — when it equals the recommendation the gate passes."""
    ws = tmp_path
    _register(ws, 'decompile and disassemble the main function')
    prompt = PROMPT + '\nagent_type: ghidra-light'
    ok, msg = check_agent_type(_paths(ws), _desc(), prompt, 'ghidra-light')
    assert ok, msg


# ---------- pre_check e2e ----------

def _healthy_ws(tmp_path) -> Path:
    from datetime import datetime, timezone
    ws = tmp_path
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    import datetime as _dtm
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat(timespec='seconds').replace('+00:00', 'Z')
    prev = (now_dt - _dtm.timedelta(minutes=5)).isoformat(
        timespec='seconds').replace('+00:00', 'Z')
    (ws / 'runs' / '.heartbeat.json').write_text(
        json.dumps({'last_tick_ts': now, 'activity_ts': now, 'started_ts': prev,
                    'tick_history': [prev, now]}), encoding='utf-8')
    (ws / 'runs' / 'plan-C001-strings.md').write_text(
        'goal: strings\nsteps:\nfallback:\n', encoding='utf-8')
    (ws / 'analysis_state.txt').write_text(
        f'deadline_ts: {int(time.time()) + 3600}\n', encoding='utf-8')
    _register(ws, 'decompile and disassemble the main function')
    (ws / 'claim_deps.yaml').write_text('deps: {}\n', encoding='utf-8')
    (ws / 'task_spec.yaml').write_text(
        yaml.safe_dump({'constraints': {'vm_detonation': 'allowed'}}), encoding='utf-8')
    return ws


def _payload(agent: str, prompt: str, desc: str) -> dict:
    return {'tool_input': {'name': agent, 'description': desc, 'prompt': prompt}}


def test_pre_check_rejects_specialist_mismatch_without_reasoning(tmp_path, capsys):
    ws = _healthy_ws(tmp_path)
    rc = pre_check(_payload('kunglao-worker', PROMPT, _desc()), _paths(ws))
    captured = capsys.readouterr()
    assert rc == 2
    assert 'REJECT agenttype' in captured.err
    out = json.loads(captured.out)
    ctx = out['hookSpecificOutput']['additionalContext']
    assert 'agent-reasoning' in ctx


def test_pre_check_accepts_mismatch_with_reasoning(tmp_path, capsys):
    ws = _healthy_ws(tmp_path)
    prompt = PROMPT + '\nagent-reasoning: worker first pass, specialist after'
    rc = pre_check(_payload('kunglao-worker', prompt, _desc()), _paths(ws))
    assert rc == 0, capsys.readouterr().err


def test_pre_check_accepts_recommended_specialist(tmp_path, capsys):
    ws = _healthy_ws(tmp_path)
    rc = pre_check(_payload('ghidra-light', PROMPT, _desc()), _paths(ws))
    assert rc == 0, capsys.readouterr().err
