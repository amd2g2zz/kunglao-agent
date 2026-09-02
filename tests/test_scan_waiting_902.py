# -*- coding: utf-8 -*-
"""WAIT/UNWAIT worker state — scan-face contract tests.

A worker that delivered its claim is no longer stopped: it enters a real
sleep-poll WAIT state whose status file keeps renewing (the file mtime IS
the heartbeat) until a dispatch signal arrives. That state needs its own
liveness semantics:

  - the status vocabulary gains a 4th NON-terminal token: ``waiting``
    (TERMINAL_WORKER_STATUSES stays exactly {done, failed, blocked, error});
  - ``scan_active_workers`` EXEMPTS ``waiting`` files from both the active
    count and the stuck list (a waiting worker holds no claim and must not
    jam the capacity gate), while the ``(active, stuck)`` return shape stays
    FROZEN for its consumers;
  - the new ``scan_waiting_workers`` lists the worker ids (file stems) whose
    LAST status token is ``waiting`` — the set the dispatch gate signals and
    the idle-breaker consults;
  - the capacity gate is unjammed by a pool of waiting-only workers.

Hooks-side lib is loaded by explicit path under the repo-canonical unique
name (bare ``import lib_kunglao`` is ambiguous under pytest — the scripts
twin shares the name).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "hooks" / "lib_kunglao.py"

_PROTOCOL_NAME = "lib_kunglao_hooks_scan_waiting"


def load_protocol():
    lib = sys.modules.get(_PROTOCOL_NAME)
    if lib is None:
        spec = importlib.util.spec_from_file_location(_PROTOCOL_NAME, CANONICAL)
        lib = importlib.util.module_from_spec(spec)
        sys.modules[_PROTOCOL_NAME] = lib
        spec.loader.exec_module(lib)
    return lib


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _write_status(ws: Path, name: str, last_status: str,
                  age_min: float | None = None) -> Path:
    p = ws / "runs" / f"worker-status-{name}.md"
    p.write_text(
        f"[12:00] step: started task | status: in-progress\n"
        f"[12:30] wait: awaiting signal | status: {last_status}\n",
        encoding="utf-8")
    if age_min is not None:
        old = time.time() - age_min * 60
        os.utime(p, (old, old))
    return p


# ---------- vocabulary ----------

class TestWaitingVocabulary:
    def test_waiting_is_not_terminal(self):
        lib = load_protocol()
        assert "waiting" not in lib.TERMINAL_WORKER_STATUSES

    def test_terminal_vocab_unchanged(self):
        lib = load_protocol()
        assert lib.TERMINAL_WORKER_STATUSES == frozenset(
            {"done", "failed", "blocked", "error"})

    def test_waiting_named_constant(self):
        lib = load_protocol()
        assert lib.WAITING_WORKER_STATUS == "waiting"


# ---------- scan_active_workers exemption ----------

class TestScanActiveExemption:
    def test_in_progress_still_counts_active(self, tmp_path):
        lib = load_protocol()
        ws = _mk_ws(tmp_path)
        _write_status(ws, "w-live", "in-progress")
        active, stuck = lib.scan_active_workers(ws)
        assert active == 1
        assert stuck == []

    def test_waiting_fresh_counts_neither_active_nor_stuck(self, tmp_path):
        lib = load_protocol()
        ws = _mk_ws(tmp_path)
        _write_status(ws, "w-wait", "waiting")
        active, stuck = lib.scan_active_workers(ws)
        assert active == 0
        assert stuck == []

    def test_waiting_stale_never_enters_stuck_list(self, tmp_path):
        lib = load_protocol()
        ws = _mk_ws(tmp_path)
        _write_status(ws, "w-wait", "waiting", age_min=120)
        active, stuck = lib.scan_active_workers(ws)
        assert active == 0
        assert stuck == []

    def test_in_progress_stale_control_is_stuck(self, tmp_path):
        lib = load_protocol()
        ws = _mk_ws(tmp_path)
        _write_status(ws, "w-stale", "in-progress", age_min=120)
        active, stuck = lib.scan_active_workers(ws)
        assert active == 1
        assert len(stuck) == 1
        assert stuck[0]["worker"] == "worker-status-w-stale"

    def test_done_counts_as_terminal(self, tmp_path):
        lib = load_protocol()
        ws = _mk_ws(tmp_path)
        _write_status(ws, "w-done", "done")
        active, stuck = lib.scan_active_workers(ws)
        assert active == 0
        assert stuck == []

    def test_mixed_pool_counts_only_non_waiting(self, tmp_path):
        lib = load_protocol()
        ws = _mk_ws(tmp_path)
        _write_status(ws, "w-a", "in-progress")
        _write_status(ws, "w-b", "waiting")
        _write_status(ws, "w-c", "done")
        active, _stuck = lib.scan_active_workers(ws)
        assert active == 1

    def test_return_shape_frozen_int_list(self, tmp_path):
        lib = load_protocol()
        ws = _mk_ws(tmp_path)
        _write_status(ws, "w-a", "in-progress")
        res = lib.scan_active_workers(ws)
        assert isinstance(res, tuple)
        assert len(res) == 2
        assert isinstance(res[0], int)
        assert isinstance(res[1], list)


# ---------- scan_waiting_workers ----------

class TestScanWaitingWorkers:
    def test_lists_only_waiting_stems(self, tmp_path):
        lib = load_protocol()
        ws = _mk_ws(tmp_path)
        _write_status(ws, "w-a", "in-progress")
        _write_status(ws, "w-b", "waiting")
        _write_status(ws, "w-c", "done")
        _write_status(ws, "w-d", "waiting")
        assert sorted(lib.scan_waiting_workers(ws)) == [
            "worker-status-w-b", "worker-status-w-d"]

    def test_empty_when_no_waiting(self, tmp_path):
        lib = load_protocol()
        ws = _mk_ws(tmp_path)
        _write_status(ws, "w-a", "done")
        assert lib.scan_waiting_workers(ws) == []

    def test_states_reuse_parameter(self, tmp_path):
        lib = load_protocol()
        ws = _mk_ws(tmp_path)
        _write_status(ws, "w-b", "waiting")
        states = lib.iter_worker_states(ws)
        assert lib.scan_waiting_workers(ws, states=states) == [
            "worker-status-w-b"]

    def test_missing_runs_dir_is_empty(self, tmp_path):
        lib = load_protocol()
        ws = tmp_path / "bare"
        ws.mkdir()
        assert lib.scan_waiting_workers(ws) == []


# ---------- capacity gate unjam ----------

class TestBudgetGateUnjammed:
    def test_three_waiting_workers_allow_dispatch(self, tmp_path):
        from worker_budget_gates import check_workers_lt_3
        ws = _mk_ws(tmp_path)
        for i in range(3):
            _write_status(ws, f"w-{i}", "waiting")
        allowed, msg = check_workers_lt_3({"workspace": str(ws)})
        assert allowed is True, f"waiting-only pool must not jam the gate: {msg}"

    def test_three_in_progress_control_blocks(self, tmp_path):
        from worker_budget_gates import check_workers_lt_3
        ws = _mk_ws(tmp_path)
        for i in range(3):
            _write_status(ws, f"w-{i}", "in-progress")
        allowed, _msg = check_workers_lt_3({"workspace": str(ws)})
        assert allowed is False
