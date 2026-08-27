"""RED tests for #38 stuck-worker-gate wiring.

Covers two pieces:
  - worker_budget.check_backtrack_gate  (hard REJECT on rc 1/2, FAIL_OPEN)
  - worker_pulse._check_stale_workers   (soft additionalContext, never aborts)

These tests FAIL until the GREEN step adds the two functions.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

# scripts/ -> kunglao-agent/ ; hooks/ sits beside scripts/
_SKILL = Path(__file__).resolve().parent.parent

import worker_budget as wb  # noqa: E402
import worker_pulse as wp   # noqa: E402


# ---------- fake subprocess result ----------
class _FakeProc:
    def __init__(self, rc, out=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = ""


# ============================================================
# check_backtrack_gate  (worker_budget)
# ============================================================

def test_backtrack_gate_clean_rc0(monkeypatch):
    monkeypatch.setattr(wb, "_run_py", lambda args, cwd=None: _FakeProc(0, "OK: no stuck workers"))
    ok, msg = wb.check_backtrack_gate({"workspace": Path("/tmp/ws")})
    assert ok is True
    assert msg == ''


def test_backtrack_gate_stuck_rc1(monkeypatch):
    monkeypatch.setattr(wb, "_run_py", lambda args, cwd=None: _FakeProc(1, "REJECT: 1 stuck"))
    ok, msg = wb.check_backtrack_gate({"workspace": Path("/tmp/ws")})
    assert ok is False
    assert "backtrack" in msg.lower()


def test_backtrack_gate_stuck_rc2(monkeypatch):
    monkeypatch.setattr(wb, "_run_py", lambda args, cwd=None: _FakeProc(2, "HARD_PAUSE"))
    ok, msg = wb.check_backtrack_gate({"workspace": Path("/tmp/ws")})
    assert ok is False
    assert ("escalate" in msg.lower()) or ("redispatch" in msg.lower())


def test_backtrack_gate_failopen_none(monkeypatch):
    monkeypatch.setattr(wb, "_run_py", lambda args, cwd=None: None)
    ok, msg = wb.check_backtrack_gate({"workspace": Path("/tmp/ws")})
    assert ok is True
    assert msg == ''


def test_backtrack_gate_failopen_no_workspace():
    ok, msg = wb.check_backtrack_gate({})
    assert ok is True
    assert msg == ''


def test_backtrack_gate_failopen_unknown_rc(monkeypatch):
    monkeypatch.setattr(wb, "_run_py", lambda args, cwd=None: _FakeProc(99, "weird"))
    ok, msg = wb.check_backtrack_gate({"workspace": Path("/tmp/ws")})
    assert ok is True
    assert msg == ''


# ============================================================
# _check_stale_workers  (worker_pulse)
# ============================================================

def _make_status(ws, name, status, age_min):
    """Write a worker-status file and backdate its mtime by age_min minutes."""
    p = ws / "runs" / f"worker-status-{name}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# worker {name}\nstatus: {status}\n", encoding="utf-8")
    old = time.time() - age_min * 60
    os.utime(p, (old, old))
    return p


def test_stale_detect_in_progress_old():
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        _make_status(ws, "w1", "in-progress", age_min=25)  # > STUCK_MIN(20)
        msg = wp._check_stale_workers(ws)
        assert msg != ''
        assert "w1" in msg


def test_stale_fresh_in_progress_not_flagged():
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        _make_status(ws, "w1", "in-progress", age_min=2)  # < STUCK_MIN
        msg = wp._check_stale_workers(ws)
        assert msg == ''


def test_stale_completed_not_flagged():
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        _make_status(ws, "w1", "done", age_min=40)  # old but completed
        msg = wp._check_stale_workers(ws)
        assert msg == ''


def test_stale_no_runs_dir():
    with tempfile.TemporaryDirectory() as td:
        msg = wp._check_stale_workers(Path(td))
        assert msg == ''
