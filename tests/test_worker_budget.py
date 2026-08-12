"""Tests for hooks/worker_budget.py — Pre+Post ToolUse on Agent (DESIGN §11).

Hook enforces 5 dispatch gates + worker accounting:
  (a) <=3 concurrent workers
  (b) target claim promotion_attempts < 3
  (c) intended_tools subset of task_spec.constraints (vm)
  (d) now < deadline_ts (time budget)
  (e) tier gate (§8.5): tier=N needs all open claims at evidence_tier_attempted >= N-1

TDD RED phase. Functions take explicit paths so tests can use tmp_path.
"""
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
            else:
                t()
            print(f'  PASS  {name}')
            passed += 1
        except Exception as e:
            print(f'  FAIL  {name}: {type(e).__name__}: {e}')
            failed.append(name)
    print(f'\n{passed}/{len(tests)} passed')
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(_run())
