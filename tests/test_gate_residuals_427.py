#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_gate_residuals_427.py — issue #427: gate fail-closed
residuals (split from #406 / PR #424, the two single-site conversions the
#424 batch deliberately left behind).

1. check_max_retries (#604 silent-failure circuit breaker) was LATENT —
   the threshold REJECT existed but no enforcement path called it. #427
   wires it into the pre_check battery (worker-health slot, right after
   ('workers', ...)). Pinned here at the SINK face: at MAX_RETRIES the
   dispatch REJECTs; below threshold / no counter file it passes.

2. check_worker_plan's unreadable-plan OSError leg flipped from fail-open
   ('plan file exists (unreadable, content not verified)' pass) to
   fail-closed (#406 ruling: gate error = REJECT with the recorded
   reason). The reject-path test uses a directory shadowing the plan name
   (IsADirectoryError is an OSError subclass) — the most robust
   cross-platform forced-error form (chmod 000 is unreliable as root /
   on Windows).

Mirrors the #424 conventions in tests/test_gate_failclosed.py: rejected
action + surfaced cause + recorded warn (gate_error:<op>), no silent pass.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import kunglao_log
import worker_budget_gates as gates
import worker_budget_sinks as sinks
import yaml

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))


def _stderr(capsys) -> str:
    return capsys.readouterr().err


# ---------------------------------------------------------------------------
# fixtures (same shapes as tests/test_worker_budget.py / test_gate_failclosed)
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
    """Dispatch payload whose tool_input.name IS the worker identity."""
    return {
        'tool_input': {
            'name': 'w-test',
            'description': '',
            'prompt': prompt,
        },
    }


def _dispatch_prompt() -> str:
    """Protocol v1 JSON envelope + facts-snapshot marker (the full-pass
    shape test_worker_budget.py::test_pre_check_accepts_first_dispatch
    _without_plan uses)."""
    return ('{"kunglao_dispatch": {"version": 1, "claim": "C-001", '
            '"tier": 1, "tools": ["grep"], "agent": "w-test", '
            '"method_family": "static-decompile"}}\n'
            'facts-snapshot: 1 facts')


def _write_retry_counter(ws: Path, entries: dict[str, int]) -> None:
    runs = ws / 'runs'
    runs.mkdir(parents=True, exist_ok=True)
    (runs / '.retry-counter.yaml').write_text(
        yaml.safe_dump({'counters': entries}, allow_unicode=True),
        encoding='utf-8')


def _seed_prior_dispatch(ws: Path, ts: str = '2026-09-10T01:00:00Z') -> None:
    """One prior approved dispatch for C-001 (approval-point anchor log) —
    arms the plan gate's re-dispatch leg."""
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    (ws / 'runs' / '.dispatch-anchor-C001.jsonl').write_text(
        json.dumps({'ts': ts, 'claim': 'C-001'}) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------------
# A. #427 conversion 1: max_retries wired into the pre_check battery
# ---------------------------------------------------------------------------

def test_pre_check_rejects_dispatch_at_max_retries(tmp_path, capsys):
    """#427: the #604 threshold REJECT is LIVE enforcement — a dispatch
    whose (worker_id, claim_id) silent-failure counter is at MAX_RETRIES
    never leaves pre_check."""
    ws = tmp_path / 'ws'
    _write_retry_counter(ws, {'w-test:C-001': 3})
    rc = sinks.pre_check(_dispatch_payload(_dispatch_prompt()),
                         _min_paths(ws))
    assert rc == 2  # (a) rejected by the battery
    err = _stderr(capsys)
    assert 'REJECT max_retries' in err  # the named gate entry
    assert 'BLOCKED' in err  # the #604 escalation message rides the reject


def test_pre_check_below_threshold_passes(tmp_path, capsys):
    """#427: counter at 2 (< MAX_RETRIES=3) — the battery entry passes and
    the dispatch is approved (no spurious breaker fire)."""
    ws = tmp_path / 'ws'
    _write_retry_counter(ws, {'w-test:C-001': 2})
    rc = sinks.pre_check(_dispatch_payload(_dispatch_prompt()),
                         _min_paths(ws))
    assert rc == 0, _stderr(capsys)


def test_pre_check_absent_counter_file_passes(tmp_path, capsys):
    """No counter file at all (the common face) — the entry fail-opens
    honestly (check_max_retries's documented scan semantics, unchanged)."""
    ws = tmp_path / 'ws'
    rc = sinks.pre_check(_dispatch_payload(_dispatch_prompt()),
                         _min_paths(ws))
    assert rc == 0, _stderr(capsys)


# ---------------------------------------------------------------------------
# B. #427 conversion 2: unreadable plan on RE-dispatch fail-closes
# ---------------------------------------------------------------------------

def test_worker_plan_unreadable_on_redispatch_rejects(tmp_path, capsys):
    """#427 (follows #406/#424): on a RE-dispatch, a plan that exists but
    cannot be READ (directory shadowing the name -> IsADirectoryError, an
    OSError) is a gate ERROR -> REJECT with the recorded cause. Was: a
    fail-open 'content not verified' pass."""
    ws = tmp_path / 'ws'
    _seed_prior_dispatch(ws)
    (ws / 'runs' / 'plan-C001.md').mkdir()  # directory shadowing the name
    kunglao_log._WARN_LAST.clear()
    ok, msg = gates.check_worker_plan({'workspace': str(ws)}, 'C-001')
    assert ok is False  # (a) rejected — no silent pass
    assert 'IsADirectoryError' in msg  # (b) the OSError cause is surfaced
    assert 'plan-C001.md' in msg  # the reject names the file
    assert 'unreadable' in msg
    assert 'gate_error:plan_read' in _stderr(capsys)  # (c) warn recorded


def test_worker_plan_unreadable_first_dispatch_still_passes(tmp_path):
    """Scoping pin: the conversion arms ONLY on re-dispatch — a first
    dispatch never reads the plan (post-#239 arming), so the unreadable
    shadow cannot reject the planning round."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    (ws / 'runs' / 'plan-C001.md').mkdir()  # unreadable shadow, no anchor
    ok, msg = gates.check_worker_plan({'workspace': str(ws)}, 'C-001')
    assert ok is True
    assert 'first dispatch' in msg.lower()
