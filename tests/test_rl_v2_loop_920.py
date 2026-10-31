# -*- coding: utf-8 -*-
"""tests/test_rl_v2_loop_920.py — real-loop telemetry + entry guard.

Pins for the unified decision loop's audit follow-ups, mirroring the
SIM loop's semantics onto ``loop.run_loop`` (the real loop):

  TELEMETRY  the assigner seam's receipts land through the real loop —
             one ``assigner.ASSIGN_ASSIGNED`` per durable
             ``assign_step`` row, ``assigner.ASSIGN_WIDENED`` when the
             draw ran on more than one candidate — and the receipts
             sit AFTER the durable row (a failed ledger append must
             not leave a phantom assignment receipt behind);
  PRIOR      ``selector.SELECT_PRIOR_MOVED`` lands at the lap
             (batch) boundary when the banked task-posterior mass
             grows — the first lap is the baseline, never a mover;
  GUARD      one workspace, one run: a ``run_loop`` over a workspace
             that already carries ledger rows raises a NAMED
             ``LoopError`` (the workspace path + what exists + the
             rule) BEFORE any mutation — a crash-residual workspace
             never re-enters, and a fresh workspace runs clean.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import loop as loop913  # noqa: E402
from rlvr import learning_seal as seal  # noqa: E402
from rlvr import q_cells  # noqa: E402
from state import telemetry  # noqa: E402


@pytest.fixture(autouse=True)
def _unarmed_seal(monkeypatch, tmp_path):
    """The suite's default seal posture (rows pass through unsigned)."""
    monkeypatch.setattr(seal, "KEY_PATH", tmp_path / "absent.key")
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})


@pytest.fixture(autouse=True)
def _isolated_store_root(monkeypatch, tmp_path):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))


def _codes(ws) -> list[str]:
    return [str(r.get("event")) for r in telemetry.events(ws)]


def _assign_step_count(ws) -> int:
    return sum(1 for r in q_cells.trajectory_rows(ws)
               if r.get("schema") == q_cells.SCHEMA_ACTION_V2
               and r.get("kind") == "assign_step")


# ------------------------------------------------ the assigner seam

def test_real_loop_lands_the_assigner_codes(tmp_path):
    """The real loop's assign seam lands both assigner codes — the SIM
    loop's telemetry registry is wired here too, not only in the sim."""
    ws = tmp_path / "ws"
    ws.mkdir()
    loop913.run_loop(ws, laps=2, seed=7)
    codes = _codes(ws)
    assert "assigner.ASSIGN_ASSIGNED" in codes
    assert "assigner.ASSIGN_WIDENED" in codes


def test_assign_receipts_match_the_durable_rows(tmp_path):
    """Exactly one assignment receipt per durable ``assign_step`` row,
    one widening receipt per draw (every real-loop draw runs on more
    than one candidate), each stamped with its lap and rollout."""
    ws = tmp_path / "ws"
    ws.mkdir()
    loop913.run_loop(ws, laps=2, seed=7)
    n_assign = _assign_step_count(ws)
    assert n_assign >= 2
    evs = telemetry.events(ws)
    assigned = [r for r in evs
                if r.get("event") == "assigner.ASSIGN_ASSIGNED"]
    widened = [r for r in evs
               if r.get("event") == "assigner.ASSIGN_WIDENED"]
    assert len(assigned) == n_assign
    assert len(widened) == n_assign
    for row in assigned + widened:
        assert isinstance(row.get("lap"), int) and row["lap"] >= 1
        assert str(row.get("rollout_id") or "").startswith("ro-core-lap")


def test_assign_telemetry_follows_the_durable_row(tmp_path, monkeypatch):
    """The assign emits sit AFTER the durable ``assign_step`` row: when
    that row's append fails, the telemetry must not describe a phantom
    assignment. The harness proves it reached the assign seam — the
    spawn row (which precedes it) landed."""
    ws = tmp_path / "ws"
    ws.mkdir()
    real = q_cells.append_action

    def boom(ws_, *a, **k):
        if k.get("kind") == "assign_step":
            raise ValueError("assign row unavailable")
        return real(ws_, *a, **k)

    monkeypatch.setattr(q_cells, "append_action", boom)
    with pytest.raises(ValueError, match="assign row unavailable"):
        loop913.run_loop(ws, laps=1, seed=7)
    assert any(r.get("kind") == "spawn_candidate"
               for r in q_cells.trajectory_rows(ws)), \
        "the harness reached the assign seam (the spawn row landed)"
    assert "assigner.ASSIGN_ASSIGNED" not in _codes(ws), \
        "a failed ledger append must not leave an assignment receipt"


# --------------------------------------------------- the selector seam

def test_select_prior_moved_at_the_lap_boundary(tmp_path):
    """The banked task-posterior mass grows every completed lap (each
    rollout banks one terminal return), so the prior-move code lands
    at every lap boundary AFTER the baseline lap — never inside a lap,
    never on the first lap."""
    ws = tmp_path / "ws"
    ws.mkdir()
    loop913.run_loop(ws, laps=3, seed=7)
    moved = [r for r in telemetry.events(ws)
             if r.get("event") == "selector.SELECT_PRIOR_MOVED"]
    assert moved, "the banked posterior mass moved across the laps"
    assert sorted(r["lap"] for r in moved) == [2, 3]
    for row in moved:
        assert "mass" in str(row.get("detail") or "")


# ------------------------------------------------ the entry guard

def test_rerun_on_a_used_workspace_raises_named_loop_error(tmp_path):
    """One workspace, one run: a second run_loop over a workspace with
    residual rows (here: the crash residual a settle fault leaves)
    raises a NAMED LoopError carrying the workspace path, what exists,
    and the rule — before any mutation. Never a bare StopIteration
    from a residual-draft join."""
    ws = tmp_path / "ws"
    ws.mkdir()
    first, _ = loop913.run_loop(ws, laps=2, seed=7,
                                faults={"settle": "crash_mid_rollout"})
    assert first["report"]["chain_stopped_lap"] is None
    rows_before = q_cells.trajectory_rows(ws)
    assert rows_before
    with pytest.raises(loop913.LoopError) as excinfo:
        loop913.run_loop(ws, laps=2, seed=7)
    msg = str(excinfo.value)
    assert str(ws) in msg
    assert str(len(rows_before)) in msg
    assert "one workspace, one run" in msg
    assert len(q_cells.trajectory_rows(ws)) == len(rows_before), \
        "the guard fires before any mutation"


def test_fresh_workspace_still_runs(tmp_path):
    """The guard's converse: a workspace with no ledger rows enters
    cleanly and completes its laps."""
    run, _ws = (loop913.run_loop(tmp_path / "fresh", laps=2, seed=7))
    report = run["report"]
    assert report["chain_stopped_lap"] is None
    assert [lap["lap"] for lap in report["per_lap"]] == [1, 2]
