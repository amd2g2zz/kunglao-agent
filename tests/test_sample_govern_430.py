# -*- coding: utf-8 -*-
"""tests/test_sample_govern_430.py — silent coercion sites speak.

The #430 sweep (2026-10-16 verified site list) found state-handling
sites that coerce corrupt/unreadable input to a default (0 / None /
{} / [] / False) with NO governed trace — no warn, no contract
comment. The honest posture (issue 275 batch-3 canonical face) is
fail-open + ONE rate-limited kunglao_log.warn; a docstring contract is
the weaker-but-accepted marker.

Pins here cover each family:

  - the three named sites (challenge_ledger active-round, worker_death
    ts parse, write_gate worker-id register);
  - the two guard faces (write_guard status-first state, write_gate
    signoff);
  - the cold-start split: a MISSING log is the honest empty (silent —
    every fresh workspace would otherwise spam), an EXISTS-but-
    unreadable log warns (q_cells._read_jsonl, consolidated_ledger);
  - the step-grain inner-counter branch (mirroring the worker-budget
    retry-counter precedent);
  - the shared activation face (lib_kunglao corrupt state → all gates
    silently sleep — the strongest silent site in the sweep).

Every pin asserts the RETURN VALUE is unchanged (the fail-open posture
stays) and the warn fired exactly for the corrupt/unreadable class.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (SCRIPTS, ROOT / "hooks"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import kunglao_log  # noqa: E402


@pytest.fixture
def warn_spy(monkeypatch):
    """Capture kunglao_log.warn calls (op, reason). Sites reach warn two
    ways — a lazy import at call time (patching the module attribute
    reaches those) and a module-level ``from kunglao_log import warn``
    binding (that binding must be patched too)."""
    calls: list[tuple[str, str]] = []

    def _spy(op, reason):
        calls.append((op, reason))

    monkeypatch.setattr(kunglao_log, "warn", _spy)
    import rlvr.q_cells as _qc            # force the module bindings
    import rlvr.consolidated_ledger as _cl
    import rlvr.step_grain as _sg
    import challenge_ledger as _clead
    import worker_death as _wd
    import write_gate as _wg
    import write_guard as _wguard
    import lib_kunglao as _lk
    import dispatch_gate as _dg
    import state_anchor as _sa
    import worker_budget_gates as _wbg
    for mod in (_qc, _cl, _sg, _clead, _wd, _wg, _wguard, _lk, _dg, _sa,
                _wbg):
        if hasattr(mod, "warn"):
            monkeypatch.setattr(mod, "warn", _spy)
    return calls


# ---------- the named sites -------------------------------------------------

def test_challenge_active_round_corrupt_warns(tmp_path, warn_spy):
    import challenge_ledger
    from challenge_ledger import _read_active_round, _active_round_path
    ws = tmp_path
    p = _active_round_path(ws, "C-1")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not-a-number", encoding="utf-8")
    assert challenge_ledger is not None
    assert _read_active_round(ws, "C-1") == 0      # posture unchanged
    assert warn_spy and warn_spy[0][0] == "challenge_active_round_read"


def test_worker_death_ts_unparseable_warns(tmp_path, warn_spy):
    import worker_death
    assert worker_death._parse_ts("garbage") is None   # posture unchanged
    assert warn_spy and warn_spy[0][0] == "worker_death_ts_parse"


def test_worker_death_ts_format_probe_stays_silent(warn_spy):
    """The multi-format probe loop is control flow, not corruption — a
    well-formed-but-alternate-format ts must not warn (the final
    fromisoformat failure is the governed branch)."""
    import worker_death
    assert worker_death._parse_ts("2026-10-16T08:00:00") is not None
    assert warn_spy == []


# ---------- the guard faces -------------------------------------------------

def test_write_gate_register_unreadable_warns(tmp_path, warn_spy, monkeypatch):
    import write_gate
    ws = tmp_path
    (ws / "claim-register.yaml").write_text("claims: []",
                                            encoding="utf-8")

    def _refuse(self, *a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("pathlib.Path.read_text", _refuse)
    out = write_gate._register_worker_id(ws, "C-1")
    assert out is None                          # posture unchanged
    assert warn_spy and warn_spy[0][0] == "write_gate_register_read"


def test_write_guard_status_first_corrupt_warns(tmp_path, warn_spy):
    import write_guard
    ws = tmp_path
    (ws / "runs").mkdir(parents=True)
    (ws / write_guard.STATUS_FIRST_STATE).write_text(
        "{corrupt", encoding="utf-8")
    out = write_guard._load_status_first_state(ws)
    assert out == {}                                # posture unchanged
    assert warn_spy and warn_spy[0][0] == "write_guard_status_first_read"


# ---------- the cold-start split --------------------------------------------

def test_qcell_read_missing_log_is_silent_cold_start(tmp_path, warn_spy):
    """A MISSING observation log is the honest empty (every fresh
    workspace) — the #430 sweep explicitly excludes it from warning."""
    from rlvr import q_cells as qc
    assert qc._read_jsonl(tmp_path / "absent.jsonl") == []
    assert warn_spy == []


def test_qcell_read_unreadable_log_warns(tmp_path, warn_spy, monkeypatch):
    from rlvr import q_cells as qc
    p = tmp_path / "log.jsonl"
    p.write_text("{}", encoding="utf-8")            # exists...

    def _refuse(self, *a, **k):
        raise PermissionError(13, "Permission denied")  # ...unreadable

    monkeypatch.setattr("pathlib.Path.read_text", _refuse)
    assert qc._read_jsonl(p) == []
    assert warn_spy and warn_spy[0][0] == "qcell_log_read"


def test_consolidated_ledger_unreadable_warns(tmp_path, warn_spy, monkeypatch):
    from rlvr import consolidated_ledger as cl
    p = tmp_path / "experience.jsonl"
    p.write_text("{}", encoding="utf-8")            # exists...

    def _refuse(self, *a, **k):
        raise PermissionError(13, "Permission denied")  # ...unreadable

    monkeypatch.setattr("pathlib.Path.read_text", _refuse)
    assert cl._read_rows(p) == []
    assert warn_spy and warn_spy[0][0] == "ledger_rows_read"


# ---------- the inner-counter precedent -------------------------------------

def test_step_grain_inner_counter_corrupt_warns(tmp_path, warn_spy):
    """The exact shape the worker-budget retry-counter fix (issue 472)
    already governs: the outer read warns, the inner counter branch was
    silent."""
    from rlvr import step_grain
    ws = tmp_path
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  dispatch_count: not-a-number\n",
        encoding="utf-8")
    assert step_grain.dispatch_count(ws, "C-1") == 0
    assert any("step_grain" in op for op, _ in warn_spy)


# ---------- the shared activation face --------------------------------------

def test_lib_kunglao_corrupt_state_warns(tmp_path, warn_spy):
    import lib_kunglao
    (tmp_path / ".hook_state.json").write_text(
        "{corrupt", encoding="utf-8")
    assert lib_kunglao.is_active(tmp_path, "w-1") is False  # posture
    assert warn_spy and warn_spy[0][0] == "activation_state_read"
