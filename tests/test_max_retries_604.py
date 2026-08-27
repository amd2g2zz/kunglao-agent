# -*- coding: utf-8 -*-
"""Tests for #604: worker_budget MAX_RETRIES circuit breaker.

Distinct from #520 promotion_attempts (which only tracks claim-level PROVEN
attempts): #604 tracks WORKER-level silent-failure retries — when the same
worker_id silently fails (no progress, dies, hangs) and gets re-dispatched
on the same claim, the counter increments. At MAX_RETRIES=3 the gate
escalates to BLOCKED + a failure-analysis artifact is REQUIRED.

Reference: .claude/PRPs/plans/v013-milestone.plan.md → Round 1 → #604.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

import pytest  # noqa: E402

from worker_budget import (  # noqa: E402
    MAX_RETRIES,
    check_max_retries,
    record_retry,
    reset_retry_counter,
    read_retry_counter,
)


# ---------- helpers ----------

def _write_retry_counter(ws: Path, entries: dict[str, int]) -> Path:
    """Write runs/.retry-counter.yaml with the given {key: count} entries."""
    runs = ws / 'runs'
    runs.mkdir(parents=True, exist_ok=True)
    import yaml as _y
    p = runs / '.retry-counter.yaml'
    p.write_text(_y.safe_dump({'counters': entries}, allow_unicode=True), encoding='utf-8')
    return p


def _write_register(path: Path, claims) -> None:
    """Write a minimal claim-register.yaml."""
    import yaml as _y
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_y.safe_dump({'claims': claims}, allow_unicode=True), encoding='utf-8')


# ---------- MAX_RETRIES constant ----------

def test_max_retries_constant_is_three():
    """The plan mandates MAX_RETRIES=3 — distinct from MAX_PROMOTION_ATTEMPTS=3."""
    assert MAX_RETRIES == 3
    # Ensure the constant is module-level (not a function attribute)
    from worker_budget_core import MAX_RETRIES as CORE_MAX_RETRIES
    assert CORE_MAX_RETRIES == 3


# ---------- check_max_retries (the gate) ----------

def test_check_max_retries_ok_under_threshold(tmp_path):
    """Count < MAX_RETRIES → gate passes (dispatch allowed)."""
    ws = tmp_path / 'ws'
    _write_retry_counter(ws, {'w1:C-001': 2})
    reg = ws / 'claim-register.yaml'
    _write_register(reg, [{'id': 'C-001', 'status': 'OPEN'}])
    ok, msg = check_max_retries(str(ws), worker_id='w1', claim_id='C-001')
    assert ok is True
    assert 'retry=2' in msg


def test_check_max_retries_blocks_at_threshold(tmp_path):
    """Count == MAX_RETRIES (3) → gate REJECTS, escalates to BLOCKED + failure-analysis."""
    ws = tmp_path / 'ws'
    _write_retry_counter(ws, {'w1:C-001': 3})
    reg = ws / 'claim-register.yaml'
    _write_register(reg, [{'id': 'C-001', 'status': 'OPEN'}])
    ok, msg = check_max_retries(str(ws), worker_id='w1', claim_id='C-001')
    assert ok is False
    # The gate must reference BLOCKED and request the failure-analysis artifact
    assert 'BLOCKED' in msg
    assert 'failure-analysis' in msg.lower() or 'failure_analysis' in msg.lower()


def test_check_max_retries_above_threshold_also_blocks(tmp_path):
    """Count > MAX_RETRIES (e.g. 5) → still rejects."""
    ws = tmp_path / 'ws'
    _write_retry_counter(ws, {'w1:C-001': 5})
    reg = ws / 'claim-register.yaml'
    _write_register(reg, [{'id': 'C-001', 'status': 'OPEN'}])
    ok, msg = check_max_retries(str(ws), worker_id='w1', claim_id='C-001')
    assert ok is False
    assert 'BLOCKED' in msg


def test_check_max_retries_no_record_passes(tmp_path):
    """A worker with zero recorded retries → gate passes (no info, no block)."""
    ws = tmp_path / 'ws'
    # No .retry-counter.yaml present
    reg = ws / 'claim-register.yaml'
    _write_register(reg, [{'id': 'C-001', 'status': 'OPEN'}])
    ok, msg = check_max_retries(str(ws), worker_id='w1', claim_id='C-001')
    assert ok is True
    # Either ok=True with explicit "0" or silent ok=True is acceptable
    assert 'retry' in msg.lower() or msg == ''


def test_check_max_retries_different_worker_independent(tmp_path):
    """Counter is keyed by worker_id — a different worker on the same claim is not blocked."""
    ws = tmp_path / 'ws'
    _write_retry_counter(ws, {'w1:C-001': 3, 'w2:C-001': 0})
    reg = ws / 'claim-register.yaml'
    _write_register(reg, [{'id': 'C-001', 'status': 'OPEN'}])
    # w2 (fresh) passes; w1 (exhausted) blocks
    ok_w2, _ = check_max_retries(str(ws), worker_id='w2', claim_id='C-001')
    ok_w1, _ = check_max_retries(str(ws), worker_id='w1', claim_id='C-001')
    assert ok_w2 is True
    assert ok_w1 is False


def test_check_max_retries_different_claim_independent(tmp_path):
    """Counter is keyed by claim_id too — different claims are tracked separately."""
    ws = tmp_path / 'ws'
    _write_retry_counter(ws, {'w1:C-001': 3})
    reg = ws / 'claim-register.yaml'
    _write_register(reg, [{'id': 'C-002', 'status': 'OPEN'}])
    ok, _ = check_max_retries(str(ws), worker_id='w1', claim_id='C-002')
    assert ok is True


# ---------- record_retry (the increment side) ----------

def test_record_retry_creates_counter_file(tmp_path):
    """First silent failure retry → counter file is created with count=1."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    assert not (ws / 'runs' / '.retry-counter.yaml').exists()
    record_retry(str(ws), worker_id='w1', claim_id='C-001')
    counter_path = ws / 'runs' / '.retry-counter.yaml'
    assert counter_path.exists()
    counters = read_retry_counter(str(ws))
    assert counters.get('w1:C-001') == 1


def test_record_retry_increments_on_each_call(tmp_path):
    """Each silent-failure re-dispatch increments the counter by exactly 1."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    record_retry(str(ws), worker_id='w1', claim_id='C-001')
    record_retry(str(ws), worker_id='w1', claim_id='C-001')
    record_retry(str(ws), worker_id='w1', claim_id='C-001')
    counters = read_retry_counter(str(ws))
    assert counters.get('w1:C-001') == 3


def test_record_retry_distinct_keys(tmp_path):
    """Different (worker_id, claim_id) keys are tracked independently."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    record_retry(str(ws), worker_id='w1', claim_id='C-001')
    record_retry(str(ws), worker_id='w2', claim_id='C-001')
    record_retry(str(ws), worker_id='w1', claim_id='C-002')
    counters = read_retry_counter(str(ws))
    assert counters == {
        'w1:C-001': 1,
        'w2:C-001': 1,
        'w1:C-002': 1,
    }


# ---------- reset_retry_counter (PROVEN completion only) ----------

def test_reset_retry_counter_clears_specific_entry(tmp_path):
    """reset_retry_counter(worker_id, claim_id) removes only that key."""
    ws = tmp_path / 'ws'
    _write_retry_counter(ws, {'w1:C-001': 2, 'w1:C-002': 1, 'w2:C-001': 1})
    reset_retry_counter(str(ws), worker_id='w1', claim_id='C-001')
    counters = read_retry_counter(str(ws))
    assert 'w1:C-001' not in counters
    assert counters['w1:C-002'] == 1
    assert counters['w2:C-001'] == 1


def test_reset_retry_counter_no_entry_is_noop(tmp_path):
    """Resetting an absent counter is silent (no exception)."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    reset_retry_counter(str(ws), worker_id='w1', claim_id='C-001')
    counters = read_retry_counter(str(ws))
    assert counters == {}


def test_reset_via_proven_status_only():
    """Contract: reset_retry_counter is intended for PROVEN-completion callers only.
    Partial completion (status: in_progress) MUST NOT call it.

    This test enforces the contract by asserting the helper's docstring/exports
    are limited — there is no `reset_on_partial` or similar back-door.
    """
    import worker_budget as wb
    public = {n for n in dir(wb) if not n.startswith('_')}
    # Reset is exported (PROVEN path); there is no partial/soft-reset helper
    assert 'reset_retry_counter' in public
    assert 'reset_on_partial' not in public
    assert 'soft_reset_retry' not in public


# ---------- end-to-end scenario ----------

def test_silent_failure_loop_three_retries_then_blocked(tmp_path):
    """End-to-end: 3 silent failures on the same worker_id+claim_id → BLOCKED."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    reg = ws / 'claim-register.yaml'
    _write_register(reg, [{'id': 'C-001', 'status': 'OPEN'}])
    # First dispatch: counter absent → allowed
    ok1, _ = check_max_retries(str(ws), worker_id='w1', claim_id='C-001')
    assert ok1 is True
    # Worker silently fails → record retry (count=1)
    record_retry(str(ws), worker_id='w1', claim_id='C-001')
    ok2, _ = check_max_retries(str(ws), worker_id='w1', claim_id='C-001')
    assert ok2 is True  # 1 < 3
    # Second silent fail → count=2
    record_retry(str(ws), worker_id='w1', claim_id='C-001')
    ok3, _ = check_max_retries(str(ws), worker_id='w1', claim_id='C-001')
    assert ok3 is True  # 2 < 3
    # Third silent fail → count=3 → BLOCKED
    record_retry(str(ws), worker_id='w1', claim_id='C-001')
    ok4, msg4 = check_max_retries(str(ws), worker_id='w1', claim_id='C-001')
    assert ok4 is False
    assert 'BLOCKED' in msg4
    # Failure-analysis artifact request must be explicit
    assert 'failure-analysis' in msg4.lower() or 'failure_analysis' in msg4.lower()


def test_proven_resets_and_dispatch_proceeds(tmp_path):
    """After PROVEN completion, the retry counter is cleared → next dispatch fresh."""
    ws = tmp_path / 'ws'
    _write_retry_counter(ws, {'w1:C-001': 2})
    reg = ws / 'claim-register.yaml'
    _write_register(reg, [{'id': 'C-001', 'status': 'PROVEN'}])
    # PROVEN completion → reset counter
    reset_retry_counter(str(ws), worker_id='w1', claim_id='C-001')
    # Now a fresh dispatch (e.g. retraction cycle) passes
    ok, msg = check_max_retries(str(ws), worker_id='w1', claim_id='C-001')
    assert ok is True
    assert 'retry=0' in msg or 'no record' in msg.lower() or msg == ''
