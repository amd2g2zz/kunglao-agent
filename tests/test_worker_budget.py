# -*- coding: utf-8 -*-
"""Tests for hooks/worker_budget.py — Pre+Post ToolUse on Agent (DESIGN §11).

Hook enforces 5 dispatch gates + worker accounting:
  (a) <=3 concurrent workers
  (b) target claim promotion_attempts < 3
  (c) intended_tools subset of task_spec.constraints (vm)
  (d) now < deadline_ts (time budget)
  (e) tier gate (§8.5): tier=N needs all open claims at evidence_tier_attempted >= N-1

TDD RED phase. Functions take explicit paths so tests can use tmp_path.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / 'hooks'))
from worker_budget import (  # noqa: E402
    parse_dispatch,
    tool_to_constraint,
    read_active_workers,
    register_worker,
    remove_worker,
    read_claim,
    check_workers_lt_3,
    check_promotion_attempts,
    check_tools_allowed,
    check_deadline,
    check_tier_gate,
    scan_actual_tools,
    check_worker_plan,
    check_tool_first,
    pre_check,
    REJECT_FIXES,
)

import yaml


# ---------- helpers ----------

def _write_state(path: Path, workers=None, deadline=None):
    """Write an analysis_state.txt with optional active_workers segment + deadline."""
    lines = ['[current_task]', 'sample=488d2dd8', '[/current_task]', '']
    if deadline is not None:
        lines.append(f'deadline_ts: {deadline}')
        lines.append('')
    if workers:
        lines.append('[active_workers]')
        for w in workers:
            tools = ','.join(w.get('tools', []))
            lines.append(
                f"worker_id={w['worker_id']} | claim_id={w['claim_id']} | "
                f"dispatched_at={w.get('dispatched_at', 0)} | tier={w.get('tier', 1)} | "
                f"tools={tools}"
            )
        lines.append('[/active_workers]')
    path.write_text('\n'.join(lines), encoding='utf-8')


def _write_register(path: Path, claims):
    """Write claim-register.yaml with given claim list."""
    path.write_text(yaml.safe_dump({'claims': claims}, allow_unicode=True), encoding='utf-8')


def _write_task_spec(path: Path, constraints):
    """Write task_spec.yaml with given constraints."""
    path.write_text(yaml.safe_dump({'constraints': constraints}, allow_unicode=True), encoding='utf-8')


def _write_status(ws: Path, name: str, last_status: str, prior=None):
    """Write runs/worker-status-<name>.md whose LAST status: line is last_status.

    Issue #37: the gate counts workers from these files (single source of truth),
    mirroring convergence_check._scan_active_workers. `prior` is a list of earlier
    status strings to exercise the last-line-decides rule (worktree snapshots carry
    historical files). Creates ws/runs/ if needed.
    """
    runs = ws / 'runs'
    runs.mkdir(parents=True, exist_ok=True)
    lines = [f"# worker-status-{name}", ""]
    ts = 0
    if prior:
        for st in prior:
            lines.append(f"[2026-08-11T12:00:{ts:02d}Z] step | status: {st}")
            ts += 1
    lines.append(f"[2026-08-11T12:00:{ts:02d}Z] step | status: {last_status}")
    (runs / f"worker-status-{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------- parse_dispatch ----------

def test_parse_dispatch_full():
    desc = '[T2 tools=vmr-shell,mcp__ghidra__*] claim C-007 promotion'
    tier, tools, cid = parse_dispatch(desc)
    assert tier == 2
    assert tools == ['vmr-shell', 'mcp__ghidra__*']
    assert cid == 'C-007'


def test_parse_dispatch_t1():
    tier, tools, cid = parse_dispatch('[T1 tools=grep,xxd] claim C-001 strings')
    assert tier == 1 and tools == ['grep', 'xxd'] and cid == 'C-001'


def test_parse_dispatch_no_claim():
    tier, tools, cid = parse_dispatch('[T1 tools=grep] general triage')
    assert tier == 1 and tools == ['grep'] and cid is None


def test_parse_dispatch_malformed():
    tier, tools, cid = parse_dispatch('just a plain description')
    assert tier == 0 and tools == [] and cid is None


# ---------- tool_to_constraint ----------

def test_tool_to_constraint_vm():
    assert tool_to_constraint('vmr-shell') == 'vm_detonation'
    assert tool_to_constraint('rev-frida') == 'vm_detonation'


def test_tool_to_constraint_cti_removed():
    # VT tools no longer map to any constraint (B4-5: CTI/OSINT out of scope).
    assert tool_to_constraint('mcp__virustotal__get_file_report') is None
    assert tool_to_constraint('mcp__virustotal__search_vt') is None


def test_tool_to_constraint_no_constraint():
    assert tool_to_constraint('mcp__ghidra__connect_instance') is None
    assert tool_to_constraint('grep') is None


# ---------- active_workers IO ----------

def test_read_active_workers_empty(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_state(p)
    assert read_active_workers(p) == []


def test_read_active_workers_entries(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_state(p, workers=[{'worker_id': 'w1', 'claim_id': 'C-001', 'tier': 1, 'tools': ['grep']}])
    aw = read_active_workers(p)
    assert len(aw) == 1
    assert aw[0]['worker_id'] == 'w1'
    assert aw[0]['claim_id'] == 'C-001'
    assert aw[0]['tier'] == 1


def test_register_then_read(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_state(p)
    register_worker(p, {'worker_id': 'w1', 'claim_id': 'C-001', 'dispatched_at': 123, 'tier': 1, 'tools': ['grep']})
    aw = read_active_workers(p)
    assert len(aw) == 1 and aw[0]['worker_id'] == 'w1'


def test_remove_worker(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_state(p, workers=[
        {'worker_id': 'w1', 'claim_id': 'C-001', 'tier': 1, 'tools': []},
        {'worker_id': 'w2', 'claim_id': 'C-002', 'tier': 1, 'tools': []},
    ])
    removed = remove_worker(p, 'w1')
    assert removed is not None and removed['worker_id'] == 'w1'
    aw = read_active_workers(p)
    assert len(aw) == 1 and aw[0]['worker_id'] == 'w2'


def test_remove_worker_missing(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_state(p)
    assert remove_worker(p, 'nonexistent') is None


# ---------- read_claim ----------

def test_read_claim_found(tmp_path):
    p = tmp_path / 'claim-register.yaml'
    _write_register(p, [
        {'id': 'C-001', 'promotion_attempts': 0, 'evidence_tier_attempted': 0, 'status': 'OPEN'},
        {'id': 'C-002', 'promotion_attempts': 2, 'evidence_tier_attempted': 1, 'status': 'OPEN'},
    ])
    c = read_claim(p, 'C-002')
    assert c['promotion_attempts'] == 2 and c['evidence_tier_attempted'] == 1


def test_read_claim_missing(tmp_path):
    p = tmp_path / 'claim-register.yaml'
    _write_register(p, [{'id': 'C-001', 'promotion_attempts': 0, 'evidence_tier_attempted': 0, 'status': 'OPEN'}])
    assert read_claim(p, 'C-999') is None


# ---------- checks ----------

def test_check_workers_lt_3_ok(tmp_path):
    """#37: gate counts status files (single source of truth), not the state cache."""
    ws = tmp_path / 'ws'
    _write_status(ws, 'w1', 'in-progress')
    _write_status(ws, 'w2', 'in-progress')
    ok, msg = check_workers_lt_3({'workspace': str(ws)})
    assert ok, msg


def test_check_workers_lt_3_reject(tmp_path):
    """#37: 3 in-progress status files fill the cap regardless of the state cache."""
    ws = tmp_path / 'ws'
    for i in range(1, 4):
        _write_status(ws, f'w{i}', 'in-progress')
    ok, msg = check_workers_lt_3({'workspace': str(ws)})
    assert not ok and '3' in msg


def test_check_workers_lt_3_from_status_files(tmp_path):
    """#37: the gate counts status files (single source of truth), not state cache."""
    ws = tmp_path / 'ws'
    _write_status(ws, 'w1', 'in-progress')
    _write_status(ws, 'w2', 'in-progress')
    _write_status(ws, 'w3', 'in-progress')
    ok, msg = check_workers_lt_3({'workspace': str(ws)})
    assert not ok and '3' in msg


def test_check_workers_lt_3_empty_state_cache(tmp_path):
    """#37: an empty [active_workers] cache must NOT fool the gate into over-allowing."""
    ws = tmp_path / 'ws'
    _write_status(ws, 'w1', 'in-progress')
    _write_state(ws / 'analysis_state.txt')  # no active_workers segment
    ok, msg = check_workers_lt_3({'workspace': str(ws)})
    assert ok  # 1 active via status file, < 3


def test_check_workers_lt_3_ignores_done(tmp_path):
    """#37: a status file whose last line is done does NOT occupy a slot."""
    ws = tmp_path / 'ws'
    _write_status(ws, 'w1', 'in-progress')
    _write_status(ws, 'w2', 'done')
    ok, msg = check_workers_lt_3({'workspace': str(ws)})
    assert ok


def test_check_workers_lt_3_last_status_line_decides(tmp_path):
    """#37: a file whose LAST status line is done is not active, even if an earlier
    line said in-progress (worktree snapshots carry historical files)."""
    ws = tmp_path / 'ws'
    _write_status(ws, 'w1', 'done', prior=['in-progress'])
    ok, msg = check_workers_lt_3({'workspace': str(ws)})
    assert ok  # last line done -> not counted -> 0 active


def test_check_workers_lt_3_missing_workspace_fails_open():
    """#37: no workspace key -> FAIL_OPEN (allow) — scan failure never blocks dispatch."""
    ok, msg = check_workers_lt_3({})
    assert ok and msg == ''


def test_check_promotion_attempts_ok(tmp_path):
    reg = tmp_path / 'claim-register.yaml'
    _write_register(reg, [{'id': 'C-001', 'promotion_attempts': 2, 'evidence_tier_attempted': 0, 'status': 'OPEN'}])
    ok, _ = check_promotion_attempts(reg, 'C-001')
    assert ok


def test_check_promotion_attempts_reject(tmp_path):
    reg = tmp_path / 'claim-register.yaml'
    _write_register(reg, [{'id': 'C-001', 'promotion_attempts': 3, 'evidence_tier_attempted': 0, 'status': 'OPEN'}])
    ok, msg = check_promotion_attempts(reg, 'C-001')
    assert not ok


def test_check_tools_allowed_ok(tmp_path):
    ts = tmp_path / 'task_spec.yaml'
    _write_task_spec(ts, {'vm_detonation': 'allowed'})
    ok, _ = check_tools_allowed(['mcp__ghidra__*', 'grep'], ts)
    assert ok


def test_check_tools_allowed_vm_forbidden(tmp_path):
    ts = tmp_path / 'task_spec.yaml'
    _write_task_spec(ts, {'vm_detonation': 'forbidden'})
    ok, msg = check_tools_allowed(['vmr-shell'], ts)
    assert not ok and 'vm' in msg.lower()


def test_check_deadline_ok(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_state(p, deadline=int(time.time()) + 3600)
    ok, _ = check_deadline(p)
    assert ok


def test_check_deadline_expired(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_state(p, deadline=int(time.time()) - 10)
    ok, msg = check_deadline(p)
    assert not ok


def test_check_deadline_none_ok(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_state(p)
    ok, _ = check_deadline(p)
    assert ok


# ---------- tier gate ----------

def test_check_tier_gate_t2_ok(tmp_path):
    reg = tmp_path / 'claim-register.yaml'
    _write_register(reg, [
        {'id': 'C-001', 'promotion_attempts': 0, 'evidence_tier_attempted': 1, 'status': 'OPEN'},
        {'id': 'C-002', 'promotion_attempts': 0, 'evidence_tier_attempted': 2, 'status': 'OPEN'},
    ])
    ok, _ = check_tier_gate(reg, 2)
    assert ok


def test_check_tier_gate_t2_reject(tmp_path):
    reg = tmp_path / 'claim-register.yaml'
    _write_register(reg, [
        {'id': 'C-001', 'promotion_attempts': 0, 'evidence_tier_attempted': 1, 'status': 'OPEN'},
        {'id': 'C-002', 'promotion_attempts': 0, 'evidence_tier_attempted': 0, 'status': 'OPEN'},
    ])
    ok, msg = check_tier_gate(reg, 2)
    assert not ok


def test_check_tier_gate_t1_always_ok(tmp_path):
    reg = tmp_path / 'claim-register.yaml'
    _write_register(reg, [{'id': 'C-001', 'promotion_attempts': 0, 'evidence_tier_attempted': 0, 'status': 'OPEN'}])
    ok, _ = check_tier_gate(reg, 1)
    assert ok


def test_check_tier_gate_ignores_terminal_claims(tmp_path):
    reg = tmp_path / 'claim-register.yaml'
    _write_register(reg, [
        {'id': 'C-001', 'promotion_attempts': 0, 'evidence_tier_attempted': 0, 'status': 'PROVEN'},
        {'id': 'C-002', 'promotion_attempts': 0, 'evidence_tier_attempted': 1, 'status': 'OPEN'},
    ])
    ok, _ = check_tier_gate(reg, 2)
    assert ok


# ---------- plan-to-execute gate (issue #239) ----------

def _min_paths(ws: Path) -> dict:
    """Minimal pre_check paths dict for a tmp workspace — all other gates
    fail-open on it (no register / no state / no task_spec / 0 active).

    Only the ws DIRECTORY is created, never the files: pre_check's final
    register_worker atomic-write needs the dir, while file absence keeps the
    heartbeat/deadline gates fail-open.
    """
    ws.mkdir(parents=True, exist_ok=True)
    return {
        'workspace': str(ws),
        'state': ws / 'analysis_state.txt',
        'register': ws / 'claim-register.yaml',
        'deps': ws / 'claim_deps.yaml',
        'task_spec': ws / 'task_spec.yaml',
    }


def _dispatch_payload(prompt: str) -> dict:
    return {
        'tool_input': {
            'name': 'w-test',
            'description': '[T1 tools=grep] claim C-001 strings',
            'prompt': prompt,
        },
    }


def test_check_worker_plan_missing_rejects(tmp_path):
    """#239: a claim dispatch with NO runs/plan-C<NN>*.md and no plan path in
    the prompt is REJECTED — PLAN FIRST (kunglao-worker.md golden rule #3)."""
    ws = tmp_path / 'ws'
    ok, msg = check_worker_plan({'workspace': str(ws)}, 'C-001')
    assert not ok and 'plan' in msg.lower()


def test_check_worker_plan_exists_accepts(tmp_path):
    """#239: the plan file already on disk (orchestrator wrote it pre-dispatch)."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    (ws / 'runs' / 'plan-C001-strings.md').write_text(
        'goal: decode strings\npreflight:\nsteps:\nfallback:\n', encoding='utf-8')
    ok, msg = check_worker_plan({'workspace': str(ws)}, 'C-001')
    assert ok, msg


def test_check_worker_plan_empty_steps_rejects(tmp_path):
    """#294: an empty-shell plan (every field label bare, no content) does NOT
    satisfy the gate — existence without content is the Swiss-army-test gap."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    (ws / 'runs' / 'plan-C001-strings.md').write_text(
        'goal:\npreflight:\nsteps:\nfallback:\n', encoding='utf-8')
    ok, msg = check_worker_plan({'workspace': str(ws)}, 'C-001')
    assert not ok
    assert 'empty-shell' in msg.lower()


def test_check_worker_plan_partial_content_accepts(tmp_path):
    """#294: ONE filled field (goal has real text) is a real plan, not a
    shell — only an ALL-bare plan is rejected."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    (ws / 'runs' / 'plan-C001-strings.md').write_text(
        'goal: decode the xor-add layer\npreflight:\nsteps:\nfallback:\n',
        encoding='utf-8')
    ok, msg = check_worker_plan({'workspace': str(ws)}, 'C-001')
    assert ok, msg


def test_check_worker_plan_bom_template_rejects(tmp_path):
    """#294 H1: a UTF-8 BOM before `goal:` (PowerShell/Notepad utf8 output)
    must NOT turn an empty-shell template into 'content' — the byte-level
    bypass is closed by the utf-8-sig read + explicit lstrip."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    (ws / 'runs' / 'plan-C001-strings.md').write_bytes(
        '﻿goal:\npreflight:\nsteps:\nfallback:\n'.encode('utf-8'))
    ok, msg = check_worker_plan({'workspace': str(ws)}, 'C-001')
    assert not ok
    assert 'empty-shell' in msg.lower()


def test_check_worker_plan_unreadable_fails_open(tmp_path):
    """#294: an unreadable plan (a directory shadowing the plan name) is a
    system error — fail OPEN with an honest note instead of a misleading
    empty-shell reject blaming the worker."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    (ws / 'runs' / 'plan-C001.md').mkdir()  # directory, not a file
    ok, msg = check_worker_plan({'workspace': str(ws)}, 'C-001')
    assert ok, msg
    assert 'unreadable' in msg


def test_check_worker_plan_exact_name_accepts(tmp_path):
    """#239: plan-C001.md / plan-c001.md (claim only, no task suffix) also
    satisfies the gate — the real-world orchestrator plans are plan-c005.md."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    (ws / 'runs' / 'plan-c001.md').write_text('goal: x\n', encoding='utf-8')
    ok, msg = check_worker_plan({'workspace': str(ws)}, 'C-001')
    assert ok, msg


def test_check_worker_plan_prompt_path_accepts(tmp_path):
    """#239 timing relaxation: a dispatch prompt carrying the plan path passes
    even before the file exists (plan written in the same turn)."""
    ws = tmp_path / 'ws'
    prompt = 'facts-snapshot: 1 facts; write runs/plan-C001-strings.md per golden rule #3'
    ok, msg = check_worker_plan({'workspace': str(ws)}, 'C-001', prompt)
    assert ok, msg


def test_check_worker_plan_prompt_wrong_claim_rejects(tmp_path):
    """#239: a plan path for a DIFFERENT claim in the prompt does not relax."""
    ws = tmp_path / 'ws'
    prompt = 'facts-snapshot: 1 facts; plan: runs/plan-C002-strings.md'
    ok, msg = check_worker_plan({'workspace': str(ws)}, 'C-001', prompt)
    assert not ok


def test_check_worker_plan_no_claim_accepts(tmp_path):
    """#239: a dispatch without a target claim cannot be plan-checked — allow."""
    ok, msg = check_worker_plan({'workspace': str(tmp_path / 'ws')}, None)
    assert ok


def test_check_worker_plan_missing_workspace_fails_open():
    """#239: no workspace key -> FAIL_OPEN (mirrors the other dispatch gates)."""
    ok, msg = check_worker_plan({}, 'C-001')
    assert ok and msg == ''


def test_pre_check_rejects_dispatch_without_plan(tmp_path, capsys):
    """#239 e2e: dispatching claim C-001 with no plan file and no plan path in
    the prompt is REJECTED by the 12th pre_check gate."""
    ws = tmp_path / 'ws'
    payload = _dispatch_payload('facts-snapshot: 1 facts')
    rc = pre_check(payload, _min_paths(ws))
    captured = capsys.readouterr()
    assert rc == 2
    assert 'REJECT plan' in captured.err


def test_pre_check_accepts_dispatch_with_plan_file(tmp_path, capsys):
    """#239 e2e: plan file written first -> the dispatch passes the plan gate."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    (ws / 'runs' / 'plan-C001-strings.md').write_text(
        'goal: decode strings\nsteps:\nfallback:\n', encoding='utf-8')
    payload = _dispatch_payload('facts-snapshot: 1 facts')
    rc = pre_check(payload, _min_paths(ws))
    assert rc == 0, capsys.readouterr().err


def test_pre_check_accepts_plan_path_in_prompt(tmp_path, capsys):
    """#239 e2e timing relaxation: prompt referencing the plan path passes
    even when the file is not on disk yet."""
    ws = tmp_path / 'ws'
    payload = _dispatch_payload(
        'facts-snapshot: 1 facts; write runs/plan-C001-strings.md first, then execute')
    rc = pre_check(payload, _min_paths(ws))
    assert rc == 0, capsys.readouterr().err


# ---------- issue #294: tool-first gate ----------

def test_check_tool_first_no_keyword_match_accepts():
    """#294: dispatch text with no tools/_INDEX.yaml keyword hit passes silently
    (avoids false positives on unrelated claims)."""
    ok, msg = check_tool_first({}, '[T1 tools=grep] claim C-001 strings',
                               'facts-snapshot: 1 facts')
    assert ok, msg


def test_check_tool_first_keyword_match_without_marker_rejects():
    """#294: dispatch text matching a registered tool's category/capability
    keyword ('crypto' -> crypto-tool) with no `tool-catalog:` marker is
    REJECTED — closes the Swiss-army-test gap (worker hand-rolled a script
    instead of trying crypto-tool.py)."""
    ok, msg = check_tool_first(
        {}, '[T1 tools=grep] claim C-001 decode the crypto layer',
        'facts-snapshot: 1 facts')
    assert not ok
    assert 'crypto-tool' in msg
    assert 'tool-catalog' in msg


def test_check_tool_first_marker_present_accepts():
    """#294: a `tool-catalog: <name>` marker satisfies the gate even when the
    text matches a registered tool's keyword."""
    ok, msg = check_tool_first(
        {}, '[T1 tools=grep] claim C-001 decode the crypto layer',
        'facts-snapshot: 1 facts; tool-catalog: crypto-tool')
    assert ok, msg


def test_check_tool_first_opt_out_with_reasoning_accepts():
    """#294: an explicit `tool-catalog: none (reasoning: ...)` opt-out passes —
    the worker is not forced to use a tool that genuinely doesn't apply."""
    ok, msg = check_tool_first(
        {}, '[T1 tools=grep] claim C-001 decode the crypto layer',
        'facts-snapshot: 1 facts; tool-catalog: none (reasoning: custom scheme, no algorithm match)')
    assert ok, msg


def test_check_tool_first_diagnostic_marker_exempts():
    """#294: a one-off diagnostic marker exempts the dispatch (not every crypto
    mention is a full decode task worth cataloging a tool for)."""
    ok, msg = check_tool_first(
        {}, '[T1 tools=grep] claim C-001 一次性诊断 crypto string layout',
        'facts-snapshot: 1 facts')
    assert ok, msg


def test_check_tool_first_stopword_no_false_positive():
    """#294 H2: generic category words ('static'/'pipeline'/'aux') must NOT
    trigger the gate — 'static overview of imports' is an adjective, not a
    disasm-constant-check dispatch."""
    ok, msg = check_tool_first(
        {}, '[T1 tools=grep] claim C-001 static overview of imports',
        'facts-snapshot: 1 facts')
    assert ok, msg


def test_check_tool_first_operation_stopword_no_false_positive():
    """#294 H2: the 'decode' capability op is also routine prose — stopworded."""
    ok, msg = check_tool_first(
        {}, '[T1 tools=grep] claim C-001 decode the string layout',
        'facts-snapshot: 1 facts')
    assert ok, msg


def test_check_tool_first_cjk_adjacent_keyword_rejects():
    """#294: a keyword glued to CJK text (解码crypto层) must still match —
    ASCII-only boundaries, because Python's \b treats CJK chars as word chars
    and would silently bypass the gate."""
    ok, msg = check_tool_first(
        {}, '[T1 tools=grep] claim C-001 解码crypto层',
        'facts-snapshot: 1 facts')
    assert not ok
    assert 'crypto-tool' in msg


def test_check_tool_first_keyword_inside_longer_word_ignored():
    """#294: 'crypto' inside 'cryptography' must NOT match (ASCII boundary
    rejects the trailing ASCII letter)."""
    ok, msg = check_tool_first(
        {}, '[T1 tools=grep] claim C-001 uses cryptography library for hashing',
        'facts-snapshot: 1 facts')
    assert ok, msg


def test_check_tool_first_negated_diagnostic_not_exempt():
    """#294: 'not a one-off diagnostic' must NOT count as an exemption — the
    diagnostic marker is negation-aware."""
    ok, msg = check_tool_first(
        {}, '[T1 tools=grep] claim C-001 not a one-off diagnostic — decode the crypto layer',
        'facts-snapshot: 1 facts')
    assert not ok
    assert 'crypto-tool' in msg


def test_check_tool_first_diagnostic_case_insensitive():
    """#294: 'One-off' (capitalised) is still an exemption."""
    ok, msg = check_tool_first(
        {}, '[T1 tools=grep] claim C-001 One-off diagnostic — inspect crypto section',
        'facts-snapshot: 1 facts')
    assert ok, msg


def test_check_tool_first_marker_case_insensitive():
    """#294: the `tool-catalog:` marker is recognised case-insensitively."""
    ok, msg = check_tool_first(
        {}, '[T1 tools=grep] claim C-001 decode the crypto layer',
        'facts-snapshot: 1 facts; TOOL-CATALOG: crypto-tool')
    assert ok, msg


def test_pre_check_rejects_dispatch_matching_tool_without_marker(tmp_path, capsys):
    """#294 e2e: a dispatch whose description matches a registered tool's
    keyword ('crypto') with no `tool-catalog:` marker is REJECTED by the 13th
    pre_check gate, even when the plan gate itself passes."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    (ws / 'runs' / 'plan-C001-crypto.md').write_text(
        'goal: decode the crypto layer\nsteps: try known algorithms\nfallback: brute force\n',
        encoding='utf-8')
    payload = _dispatch_payload('facts-snapshot: 1 facts')
    payload['tool_input']['description'] = '[T1 tools=grep] claim C-001 decode the crypto layer'
    rc = pre_check(payload, _min_paths(ws))
    captured = capsys.readouterr()
    assert rc == 2
    assert 'REJECT toolfirst' in captured.err


def test_pre_check_accepts_dispatch_with_tool_catalog_marker(tmp_path, capsys):
    """#294 e2e: adding `tool-catalog: crypto-tool` to the prompt clears the
    tool-first gate for the same crypto-matching dispatch."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    (ws / 'runs' / 'plan-C001-crypto.md').write_text(
        'goal: decode the crypto layer\nsteps: try crypto-tool xor-add\nfallback: brute force\n',
        encoding='utf-8')
    payload = _dispatch_payload('facts-snapshot: 1 facts; tool-catalog: crypto-tool')
    payload['tool_input']['description'] = '[T1 tools=grep] claim C-001 decode the crypto layer'
    rc = pre_check(payload, _min_paths(ws))
    assert rc == 0, capsys.readouterr().err


# ---------- issue #270: every REJECT carries non-empty additionalContext ----------
# #235 fixed env_check_gate with corrective guidance; the 12 pre_check gates +
# snapshot + devreason REJECTed bare (stderr only). Now EVERY REJECT must also
# emit hookSpecificOutput.additionalContext (stdout JSON) with a concrete fix.
# REJECT semantics unchanged: exit 2, `REJECT <name>` on stderr.

REJECT_NAMES = [
    'workers', 'cap', 'tools', 'hostchan', 'deadline', 'tier',
    'selfcap', 'heartbeat', 'drift', 'health', 'backtrack', 'plan',
    'toolfirst', 'agenttype', 'snapshot', 'devreason',
]

# per-REJECT keyword that proves the guidance is concrete (names the mechanism),
# not boilerplate
REJECT_FIX_KEYWORDS = {
    'workers': 'TaskStop',
    'cap': 'promotion_attempts',
    'tools': 'vm_detonation',
    'hostchan': 'connect_remote',
    'deadline': 'deadline_ts',
    'tier': 'evidence_tier',
    'selfcap': 'time_budget_minutes',
    'heartbeat': 'heartbeat-on',
    'drift': 'plan_drift_detector',
    'health': 'convergence_health',
    'backtrack': 'backtrack',
    'plan': 'plan-C',
    'toolfirst': 'tool-catalog',
    'agenttype': 'agent-reasoning',
    'snapshot': 'facts-snapshot',
    'devreason': 'reasoning',
}


def test_reject_fixes_cover_all_reject_paths():
    """#270: every REJECT path has a non-empty additionalContext fix — no gate
    may REJECT bare. Set equality guards both directions (missing entry AND
    dead entry)."""
    assert set(REJECT_NAMES) == set(REJECT_FIXES), (
        f'missing/dead guidance: {set(REJECT_NAMES) ^ set(REJECT_FIXES)}')
    for name in REJECT_NAMES:
        ctx = REJECT_FIXES[name]['additionalContext']
        assert ctx and len(ctx.strip()) >= 30, f'REJECT {name}: guidance too thin'


def test_reject_fixes_are_actionable():
    """#270: each fix names its concrete repair mechanism (command / file /
    decision), never generic 'please fix it' phrasing."""
    for name, kw in REJECT_FIX_KEYWORDS.items():
        assert kw in REJECT_FIXES[name]['additionalContext'], \
            f'REJECT {name} fix must mention {kw!r}'


def _fresh_hb(ws: Path) -> None:
    """Write a live heartbeat (both timestamps = now) so the heartbeat gate
    passes unless a scenario explicitly removes it."""
    from datetime import datetime, timezone as _tz
    now = datetime.now(_tz.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    (ws / 'runs' / '.heartbeat.json').write_text(
        json.dumps({'last_tick_ts': now, 'activity_ts': now}), encoding='utf-8')


def _healthy_ws(tmp_path) -> Path:
    """A workspace where EVERY pre_check gate passes; scenarios toggle one off."""
    ws = tmp_path
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    _fresh_hb(ws)
    (ws / 'runs' / 'plan-C001-strings.md').write_text(
        'goal: strings\nsteps:\nfallback:\n', encoding='utf-8')
    (ws / 'analysis_state.txt').write_text(
        f'deadline_ts: {int(time.time()) + 3600}\n', encoding='utf-8')
    _write_register(ws / 'claim-register.yaml', [
        {'id': 'C-001', 'status': 'OPEN', 'promotion_attempts': 0,
         'evidence_tier_attempted': 1},
    ])
    (ws / 'claim_deps.yaml').write_text('deps: {}\n', encoding='utf-8')
    _write_task_spec(ws / 'task_spec.yaml', {'vm_detonation': 'allowed'})
    return ws


def _paths_for(ws: Path) -> dict:
    return {
        'workspace': str(ws),
        'state': ws / 'analysis_state.txt',
        'register': ws / 'claim-register.yaml',
        'deps': ws / 'claim_deps.yaml',
        'task_spec': ws / 'task_spec.yaml',
    }


def _budget_payload(prompt='facts-snapshot: 1 facts',
                    desc='[T1 tools=grep] claim C-001 strings') -> dict:
    return {'tool_input': {'name': 'w-test', 'description': desc, 'prompt': prompt}}


def _assert_reject_guidance(capsys, rc: int, name: str, keyword: str) -> None:
    """REJECT semantics unchanged (exit 2 + stderr) AND stdout JSON carries
    non-empty hookSpecificOutput.additionalContext naming the concrete fix."""
    captured = capsys.readouterr()
    assert rc == 2, f'{name}: REJECT must stay exit 2'
    assert f'REJECT {name}' in captured.err, f'{name}: stderr summary missing'
    out = json.loads(captured.out)
    assert out['hookSpecificOutput']['hookEventName'] == 'PreToolUse'
    ctx = out['hookSpecificOutput']['additionalContext']
    assert ctx and len(ctx.strip()) >= 30, f'{name}: additionalContext must be non-empty'
    assert keyword in ctx, f'{name}: guidance must mention {keyword!r}'


def test_e2e_every_reject_emits_guidance(tmp_path, capsys, monkeypatch):
    """#270 e2e: each REJECT path (11 direct gates + snapshot + devreason) exits
    2, prints REJECT on stderr AND emits hookSpecificOutput.additionalContext
    (stdout JSON) with the concrete fix — mirroring dispatch_gate /
    env_check_gate injection. drift/health/backtrack (subprocess gates) are
    covered in test_e2e_subprocess_gates_reject_emits_guidance."""
    import worker_budget as wb
    from types import SimpleNamespace

    # subprocess gates deterministic: all pass (rc 0)
    monkeypatch.setattr(wb, '_run_py',
                        lambda args, cwd=None: SimpleNamespace(
                            returncode=0, stderr='', stdout=''))
    # priority deviation forced for the devreason scenario (other scenarios
    # reject before priority is consulted, so the patch is harmless)
    monkeypatch.setattr(wb, 'check_priority',
                        lambda *a, **k: (True, 'ADVISORY: C-001 rank #2', True))

    scenarios = []

    # 1 workers — 3 in-progress status files fill the cap
    ws = _healthy_ws(tmp_path / 'workers')
    for i in range(1, 4):
        _write_status(ws, f'w{i}', 'in-progress')
    scenarios.append(('workers', 'TaskStop',
                      lambda ws=ws: wb.pre_check(_budget_payload(), _paths_for(ws))))

    # 2 cap — per-claim promotion cost cap reached
    ws = _healthy_ws(tmp_path / 'cap')
    _write_register(ws / 'claim-register.yaml', [
        {'id': 'C-001', 'status': 'OPEN', 'promotion_attempts': 3,
         'evidence_tier_attempted': 1}])
    scenarios.append(('cap', 'promotion_attempts',
                      lambda ws=ws: wb.pre_check(_budget_payload(), _paths_for(ws))))

    # 3 tools — vm tool dispatched while task_spec forbids vm_detonation
    ws = _healthy_ws(tmp_path / 'tools')
    _write_task_spec(ws / 'task_spec.yaml', {'vm_detonation': 'forbidden'})
    scenarios.append(('tools', 'vm_detonation',
                      lambda ws=ws: wb.pre_check(
                          _budget_payload(desc='[T1 tools=vmr-shell] claim C-001'),
                          _paths_for(ws))))

    # 4 hostchan — host-channel x64dbg tool (VM-only policy)
    ws = _healthy_ws(tmp_path / 'hostchan')
    scenarios.append(('hostchan', 'connect_remote',
                      lambda ws=ws: wb.pre_check(
                          _budget_payload(
                              desc='[T1 tools=mcp__x64dbg__start_session] claim C-001'),
                          _paths_for(ws))))

    # 5 deadline — time budget exhausted
    ws = _healthy_ws(tmp_path / 'deadline')
    (ws / 'analysis_state.txt').write_text(
        f'deadline_ts: {int(time.time()) - 10}\n', encoding='utf-8')
    scenarios.append(('deadline', 'deadline_ts',
                      lambda ws=ws: wb.pre_check(_budget_payload(), _paths_for(ws))))

    # 6 tier — tier-2 dispatch while an open claim lacks tier-1 evidence
    ws = _healthy_ws(tmp_path / 'tier')
    _write_register(ws / 'claim-register.yaml', [
        {'id': 'C-001', 'status': 'OPEN', 'promotion_attempts': 0,
         'evidence_tier_attempted': 0}])
    scenarios.append(('tier', 'evidence_tier',
                      lambda ws=ws: wb.pre_check(
                          _budget_payload(desc='[T2 tools=grep] claim C-001 strings'),
                          _paths_for(ws))))

    # 7 selfcap — self-imposed time cap with no authorised budget
    ws = _healthy_ws(tmp_path / 'selfcap')
    scenarios.append(('selfcap', 'time_budget_minutes',
                      lambda ws=ws: wb.pre_check(
                          _budget_payload(
                              desc='[T1 tools=grep] claim C-001 cap it at 30 min'),
                          _paths_for(ws))))

    # 8 heartbeat — no live heartbeat registered
    ws = _healthy_ws(tmp_path / 'heartbeat')
    (ws / 'runs' / '.heartbeat.json').unlink()
    scenarios.append(('heartbeat', 'heartbeat-on',
                      lambda ws=ws: wb.pre_check(_budget_payload(), _paths_for(ws))))

    # 9 plan — plan-first gate (#239)
    ws = _healthy_ws(tmp_path / 'plan')
    (ws / 'runs' / 'plan-C001-strings.md').unlink()
    scenarios.append(('plan', 'plan-C',
                      lambda ws=ws: wb.pre_check(_budget_payload(), _paths_for(ws))))

    # 10 snapshot — dispatch prompt lacks the facts-snapshot marker
    ws = _healthy_ws(tmp_path / 'snapshot')
    scenarios.append(('snapshot', 'facts-snapshot',
                      lambda ws=ws: wb.pre_check(
                          _budget_payload(prompt='dispatch C-001 now'),
                          _paths_for(ws))))

    # 11 devreason — priority deviation without a reasoning field
    ws = _healthy_ws(tmp_path / 'devreason')
    scenarios.append(('devreason', 'reasoning',
                      lambda ws=ws: wb.pre_check(_budget_payload(), _paths_for(ws))))

    # 12 agenttype — #310: claim statement recommends ghidra-light but the
    # dispatch sends kunglao-worker with no `agent-reasoning:` (specialist-first
    # as a mechanical gate; role agents and name-less payloads skip it)
    ws = _healthy_ws(tmp_path / 'agenttype')
    _write_register(ws / 'claim-register.yaml', [
        {'id': 'C-001', 'status': 'OPEN', 'promotion_attempts': 0,
         'evidence_tier_attempted': 1,
         'statement': 'decompile and disassemble the main function'}])
    payload = _budget_payload(desc='[T1 tools=grep] claim C-001 do the task')
    payload['tool_input']['name'] = 'kunglao-worker'
    scenarios.append(('agenttype', 'agent-reasoning',
                      lambda ws=ws: wb.pre_check(payload, _paths_for(ws))))

    assert len(scenarios) == 12
    for name, keyword, run in scenarios:
        _assert_reject_guidance(capsys, run(), name, keyword)


def test_e2e_subprocess_gates_reject_emits_guidance(tmp_path, capsys, monkeypatch):
    """#270 e2e for the 3 subprocess-backed gates (drift / health / backtrack):
    each rejects with exit 2, stderr REJECT and non-empty additionalContext."""
    import worker_budget as wb
    from types import SimpleNamespace

    cases = [
        ('drift', 'plan_drift_detector.py', 1, 'plan_drift_detector'),
        ('health', 'convergence_health.py', 1, 'convergence_health'),
        ('backtrack', 'backtrack_gate.py', 1, 'backtrack'),
    ]
    for name, script, rc_val, keyword in cases:
        ws = _healthy_ws(tmp_path / name)
        monkeypatch.setattr(
            wb, '_run_py',
            lambda args, cwd=None, s=script, rv=rc_val: SimpleNamespace(
                returncode=rv if (args and Path(args[0]).name == s) else 0,
                stderr='fake', stdout=''))
        _assert_reject_guidance(capsys, wb.pre_check(_budget_payload(), _paths_for(ws)),
                                name, keyword)


def test_main_stdin_reject_emits_context_json(tmp_path):
    """#270 wired shape (mirrors env_check_gate.test_main_stdin_reject_end_to_end):
    JSON payload on stdin -> exit 2, stderr REJECT, stdout hookSpecificOutput
    JSON with non-empty additionalContext."""
    ws = _healthy_ws(tmp_path / 'sub')
    (ws / 'runs' / 'plan-C001-strings.md').unlink()  # force the plan REJECT
    payload = {
        'hook_event_name': 'PreToolUse',
        'cwd': str(ws),
        'tool_input': {'name': 'w-test',
                       'description': '[T1 tools=grep] claim C-001 strings',
                       'prompt': 'facts-snapshot: 1 facts'},
    }
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / 'hooks'
                             / 'worker_budget.py')],
        input=json.dumps(payload), capture_output=True,
        encoding='utf-8', errors='replace',
        env={'PYTHONIOENCODING': 'utf-8', **os.environ},
        cwd=str(ws), timeout=60,
    )
    assert r.returncode == 2
    assert 'REJECT plan' in r.stderr
    out = json.loads(r.stdout)
    assert out['hookSpecificOutput']['hookEventName'] == 'PreToolUse'
    ctx = out['hookSpecificOutput']['additionalContext']
    assert ctx and 'plan-C' in ctx


# ---------- scan_actual_tools ----------

def test_scan_actual_tools_extracts_names():
    transcript = """
    dispatched: T2 worker
    called: vmr-shell restore-snapshot
    called: mcp__ghidra__connect_instance
    result: ok
    """
    tools = scan_actual_tools(transcript)
    assert 'vmr-shell' in tools
    assert 'mcp__ghidra__connect_instance' in tools


def test_scan_actual_tools_empty():
    assert scan_actual_tools('no tools here') == []


# ---------- runner ----------

def _run():
    import inspect
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    failed = []
    for name, t in tests:
        sig = inspect.signature(t)
        try:
            if 'tmp_path' in sig.parameters:
                import tempfile
                with tempfile.TemporaryDirectory() as td:
                    t(Path(td))
            elif not sig.parameters:
                t()
            else:
                # pytest-only fixtures (capsys/monkeypatch) — the legacy
                # standalone runner cannot provide them; run under pytest.
                print(f'  SKIP  {name}: needs pytest fixture(s) {list(sig.parameters)}')
                continue
            print(f'  PASS  {name}')
            passed += 1
        except Exception as e:
            print(f'  FAIL  {name}: {type(e).__name__}: {e}')
            failed.append(name)
    print(f'\n{passed}/{len(tests)} passed')
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(_run())
