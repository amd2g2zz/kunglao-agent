# -*- coding: utf-8 -*-
"""Tests for scripts/reconcile_workers.py — [active_workers] rebuild from
worker status files + plan files (issue #239 plan-to-execute visibility).

A worker writes runs/plan-<task>.md FIRST (kunglao-worker.md golden rule #3
— PLAN FIRST, execute second), then its worker-status-<name>.md. A runs dir
whose status files account for ZERO workers while plan files exist means the
worker(s) started but never wrote a status file (crash / PostToolUse
remove_worker never fired) — reconcile must keep those slots visible so the
3-worker budget is not silently overshot.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent / 'scripts'))
from reconcile_workers import reconcile_workers  # noqa: E402


def _make_ws(tmp_path: Path, files: dict[str, str]) -> Path:
    """Build a workspace: runs/<files> + an analysis_state.txt with an empty
    [active_workers] segment (as the reconcile target)."""
    ws = tmp_path / 'ws'
    runs = ws / 'runs'
    runs.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (runs / name).write_text(content, encoding='utf-8')
    (ws / 'analysis_state.txt').write_text(
        '[active_workers]\n[/active_workers]\n', encoding='utf-8')
    return ws


def _active_ids(ws: Path) -> set[str]:
    """Parse the rebuilt [active_workers] segment back out of analysis_state.txt."""
    ids = set()
    in_seg = False
    for line in (ws / 'analysis_state.txt').read_text(encoding='utf-8').splitlines():
        if line.strip() == '[active_workers]':
            in_seg = True
            continue
        if line.strip() == '[/active_workers]':
            break
        if in_seg and 'worker_id=' in line:
            ids.add(line.strip().split('worker_id=', 1)[1].split(' |', 1)[0])
    return ids


def test_reconcile_empty_workspace(tmp_path):
    ws = _make_ws(tmp_path, {})
    assert reconcile_workers(ws) == 0
    assert _active_ids(ws) == set()


def test_reconcile_worker_plan_marks_active(tmp_path):
    """#239: a plan-C001-*.md with NO status file marks the worker active
    (crashed before writing worker-status — slot must stay visible)."""
    ws = _make_ws(tmp_path, {'plan-C001-strings.md': 'goal: x\nsteps:\n'})
    n = reconcile_workers(ws)
    assert n == 1
    assert _active_ids(ws) == {'worker-plan-C001-strings'}


def test_reconcile_worker_plan_lowercase_claim(tmp_path):
    """#239: real-world orchestrator plan naming plan-c005.md is covered."""
    ws = _make_ws(tmp_path, {'plan-c005.md': 'goal: x\n'})
    assert reconcile_workers(ws) == 1
    assert _active_ids(ws) == {'worker-plan-c005'}


def test_reconcile_worker_plan_skipped_when_status_exists(tmp_path):
    """#239: a runs dir with worker-status files is accounted by the status
    scan — plans there are NOT double-counted as extra active workers."""
    ws = _make_ws(tmp_path, {
        'plan-C001-strings.md': 'goal: x\n',
        'worker-status-w1.md': '[00:00Z] started | status: in-progress\n',
    })
    n = reconcile_workers(ws)
    assert n == 1
    assert _active_ids(ws) == {'worker-status-w1'}


def test_reconcile_plan_after_done_is_not_active(tmp_path):
    """#239: a completed worker (status file says done) leaves its plan on
    disk — the plan must NOT resurrect it as active."""
    ws = _make_ws(tmp_path, {
        'plan-C001-strings.md': 'goal: x\n',
        'worker-status-w1.md': '[00:00Z] done | status: done\n',
    })
    n = reconcile_workers(ws)
    assert n == 0
    assert _active_ids(ws) == set()


def test_reconcile_redteam_plan_still_works(tmp_path):
    """Existing behavior preserved: plan-redteam-* without its verify report
    marks the verifier active (regression guard)."""
    ws = _make_ws(tmp_path, {'plan-redteam-C001.md': 'goal: x\n'})
    n = reconcile_workers(ws)
    assert n == 1
    assert _active_ids(ws) == {'verifier-redteam-C001'}


def test_reconcile_redteam_plan_with_verify_inactive(tmp_path):
    """Existing behavior preserved: redteam plan + verify report -> not active."""
    ws = _make_ws(tmp_path, {
        'plan-redteam-C001.md': 'goal: x\n',
        'verify-redteam-C001.md': 'verdict: CONFIRMED\n',
    })
    assert reconcile_workers(ws) == 0
    assert _active_ids(ws) == set()


def test_reconcile_mixed_plans(tmp_path):
    """#239: worker + redteam plans are both visible and distinct."""
    ws = _make_ws(tmp_path, {
        'plan-C002-entry.md': 'goal: x\n',
        'plan-redteam-C001.md': 'goal: x\n',
    })
    n = reconcile_workers(ws)
    assert n == 2
    assert _active_ids(ws) == {'worker-plan-C002-entry', 'verifier-redteam-C001'}


def test_reconcile_in_progress_status_counts(tmp_path):
    """Existing behavior preserved: in-progress status file marks the worker."""
    ws = _make_ws(tmp_path, {
        'worker-status-w2.md': '[00:00Z] step1 | status: in-progress\n',
    })
    assert reconcile_workers(ws) == 1
    assert _active_ids(ws) == {'worker-status-w2'}


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
