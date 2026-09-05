# -*- coding: utf-8 -*-
"""Issue #3: a crashed convergence_health exits 1, which the dispatch gate
misreads as STALLED.

main() had no crash guard: any unexpected exception propagates and Python
exits 1. iter_jsonl only skips UNPARSEABLE lines — a valid-JSON row with a
wrong value shape (open_count as a string, null, ...) flows straight into
assess() and raises. hooks/worker_budget_core.check_convergence_health
reads rc==1 as "convergence STALLED - diagnose before dispatching" and
blocks all dispatch: a broken gate masquerades as a stalled mission.

Fix: EXIT_CRASHED = 4 (next free value; the 0/1/2/3 protocol is untouched),
a minimal guard in main() around the assess/print section (argparse and the
explicit no-ledger exit-3 path stay outside), and the consumer FAILS OPEN
on rc==4 with a visible message — mirroring worker_budget_core's existing
fail-open posture for broken gates.

Covers:
  RED1: corrupt ledger (valid JSON, wrong value shape) -> exit 4, not 1
  RED2: monkeypatched assess() crash -> main() exits 4, stderr diagnostic
  RED3: consumer rc=4 -> (True, visible fail-open message)
  PINS: rc protocol 0/1/2/3 unchanged; consumer rc=1/rc=2 reject pins;
        no-ledger path still exits 3 on its own
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import convergence_health as ch  # noqa: E402
# worker_budget_core resolves via pytest.ini pythonpath (hooks root);
# a toplevel hooks/ sys.path.insert is forbidden here (#671/#770 guard).
import worker_budget_core as wbc  # noqa: E402

BASE = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)
SCRIPT = ROOT / "scripts" / "convergence_health.py"


def _snap(i, open_count, open_ids, facts_total=5) -> dict:
    return {
        "ts": (BASE + timedelta(seconds=60 * i)).isoformat(),
        "decision": "DISPATCH",
        "open_count": open_count,
        "open_ids": open_ids,
        "partial_count": 0,
        "active_workers": 1,
        "blockers": [],
        "facts_total": facts_total,
    }


def _write_ledger(ws: Path, rows: list[dict]) -> None:
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    (ws / ".convergence_ledger.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def _run(ws: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(ws)],
        capture_output=True, text=True, timeout=60)


# =====================================================================
# RED1: corrupt ledger (valid JSON, wrong value shape) -> exit 4, not 1
# =====================================================================

def test_corrupt_ledger_exits_4_not_1(tmp_path):
    """open_count "3" (string) passes the snapshot filter and raises
    TypeError inside assess(). Before the fix the traceback exited 1 —
    exactly the STALLED masquerade the dispatch gate acts on."""
    ws = tmp_path / "corrupt"
    ws.mkdir()
    _write_ledger(ws, [
        _snap(0, "3", ["C-1"]),
        _snap(1, "3", ["C-1"]),
        _snap(2, "3", ["C-1"]),
        _snap(3, "3", ["C-1"]),
    ])
    r = _run(ws)
    assert r.returncode == 4, (
        f"a crashed health check must exit 4 (crashed), not 1 (STALLED "
        f"masquerade); got rc={r.returncode}, stderr: {r.stderr[:300]}")
    assert "convergence_health crashed" in r.stderr, \
        f"crash must print a one-line diagnostic, got: {r.stderr[:300]}"


# =====================================================================
# RED2: monkeypatched assess() crash -> main() exits 4 with diagnostic
# =====================================================================

def test_assess_crash_exits_4_with_stderr_diagnostic(tmp_path, monkeypatch, capsys):
    ws = tmp_path / "synthetic"
    ws.mkdir()
    _write_ledger(ws, [_snap(i, 2, ["C-1"]) for i in range(4)])

    def boom(_ledger):
        raise RuntimeError("synthetic assess failure (#3)")

    monkeypatch.setattr(ch, "assess", boom)
    monkeypatch.setattr(sys, "argv", ["convergence_health.py", str(ws)])
    rc = ch.main()
    assert rc == 4, f"main() must return EXIT_CRASHED (4), got {rc}"
    err = capsys.readouterr().err
    assert "convergence_health crashed" in err, f"missing diagnostic, got: {err}"
    assert "RuntimeError" in err, "diagnostic must carry the exception repr"


# =====================================================================
# RED3: consumer rc=4 -> fail open with a visible message
# =====================================================================

def test_consumer_rc4_fails_open_with_visible_message(monkeypatch):
    monkeypatch.setattr(
        wbc, "_run_py",
        lambda args, cwd=None: SimpleNamespace(returncode=4, stdout="", stderr="boom"))
    ok, msg = wbc.check_convergence_health({"workspace": "/tmp/whatever-ws"})
    assert ok is True, "rc=4 is a crashed gate, not a stalled mission — fail OPEN"
    assert "crashed (rc=4)" in msg
    assert "failing open" in msg
    assert "convergence_health.py" in msg, \
        "the message must point the operator at the broken script"


# =====================================================================
# consumer pins: rc=1 / rc=2 reject behavior unchanged
# =====================================================================

def test_consumer_rc1_rc2_reject_pins(monkeypatch):
    monkeypatch.setattr(
        wbc, "_run_py",
        lambda args, cwd=None: SimpleNamespace(returncode=1, stdout="", stderr=""))
    ok, msg = wbc.check_convergence_health({"workspace": "/tmp/whatever-ws"})
    assert ok is False
    assert "STALLED" in msg

    monkeypatch.setattr(
        wbc, "_run_py",
        lambda args, cwd=None: SimpleNamespace(returncode=2, stdout="", stderr=""))
    ok, msg = wbc.check_convergence_health({"workspace": "/tmp/whatever-ws"})
    assert ok is False
    assert "SPINNING" in msg


# =====================================================================
# protocol pin: exit codes 0/1/2/3 unchanged, 4 is new and distinct
# =====================================================================

def test_exit_code_constants_protocol():
    assert (ch.EXIT_HEALTHY, ch.EXIT_STALLED, ch.EXIT_SPINNING,
            ch.EXIT_NO_DATA) == (0, 1, 2, 3)
    assert ch.EXIT_CRASHED == 4
    assert ch.EXIT_CRASHED not in (ch.EXIT_HEALTHY, ch.EXIT_STALLED,
                                   ch.EXIT_SPINNING, ch.EXIT_NO_DATA)


def test_rc_pins_healthy_stalled_spinning_no_data(tmp_path):
    # HEALTHY: converging
    ws = tmp_path / "h"
    ws.mkdir()
    _write_ledger(ws, [_snap(0, 4, ["C-1", "C-2"]),
                       _snap(1, 3, ["C-1"]),
                       _snap(2, 1, [])])
    assert _run(ws).returncode == 0

    # STALLED: flatline 6 (old-format rows — also re-pins #2 fallback)
    ws = tmp_path / "s"
    ws.mkdir()
    _write_ledger(ws, [_snap(i, 2, ["C-1"]) for i in range(6)])
    assert _run(ws).returncode == 1

    # SPINNING: facts grow while open_count holds
    ws = tmp_path / "sp"
    ws.mkdir()
    _write_ledger(ws, [_snap(i, 2, ["C-1"], facts_total=10 + i) for i in range(8)])
    assert _run(ws).returncode == 2

    # NO_DATA: no ledger — explicit early path stays outside the guard
    ws = tmp_path / "n"
    ws.mkdir()
    r = _run(ws)
    assert r.returncode == 3
    assert "no .convergence_ledger.jsonl" in (r.stderr + r.stdout)
