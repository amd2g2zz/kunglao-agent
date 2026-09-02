# -*- coding: utf-8 -*-
"""kunglao_wait.py — the WAIT/UNWAIT sleep-poll loop tool (subprocess-driven).

The tool owns the whole wait mechanism; agents only invoke it. Contract
pinned here (tiny env intervals keep every case well under 10 s wall):

  - loop = sleep(KUNGLAO_WAIT_POLL_S) -> append one
    ``[ts] wait: awaiting signal | status: waiting`` heartbeat line to
    ``runs/worker-status-<id>.md`` -> poll ``runs/wait-signal-<id>.json``;
    the status file mtime renewal IS the worker heartbeat, so the count of
    waiting tokens grows while no signal arrives;
  - signal present -> parse it, DELETE it (single-shot), append the UNWAIT
    face (LAST status becomes ``in-progress``), print the consumed signal
    on stdout, exit 0;
  - WAIT_MAX_ROUNDS rounds with no signal -> append the self-kill terminal
    line (``status: failed | note: self-killed after N wait rounds``) and
    exit 3 (``--claim`` given) or 4 (no claim) — the agent TaskStops
    itself and frees its slot;
  - the slot is observably freed: after the self-kill the last status is
    terminal, so scan_active_workers counts zero;
  - default constants: WAIT_POLL_INTERVAL_S=20, WAIT_MAX_ROUNDS=90, and
    named exit-code constants 0/3/4; NEVER raises (a crash lands a
    best-effort terminal line + exit 3).

Subprocess only: the loop is the mechanism under test, not an importable
helper. The protocol lib is loaded by explicit path (scripts twin shares
the module name).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "kunglao_wait.py"

POLL_S = "0.2"
MAX_ROUNDS = "10"  # 10 * 0.2 s = 2 s hard ceiling per runaway run

STATUS_TOKEN = re.compile(r"status:\s*(\S+)")


def _env(**over: str) -> dict:
    e = dict(os.environ)
    e["KUNGLAO_WAIT_POLL_S"] = POLL_S
    e["KUNGLAO_WAIT_MAX_ROUNDS"] = MAX_ROUNDS
    e["PYTHONIOENCODING"] = "utf-8"
    e.update(over)
    return e


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _status_file(ws: Path, worker: str = "w1") -> Path:
    return ws / "runs" / f"worker-status-{worker}.md"


def _signal_file(ws: Path, worker: str = "w1") -> Path:
    return ws / "runs" / f"wait-signal-{worker}.json"


def _last_status(p: Path) -> str | None:
    toks = STATUS_TOKEN.findall(p.read_text(encoding="utf-8"))
    return toks[-1] if toks else None


def _args(ws: Path, worker: str = "w1", claim: str | None = None) -> list:
    args = [sys.executable, str(TOOL), "--worker", worker]
    if claim:
        args += ["--claim", claim]
    return args


def _run_foreground(ws: Path, claim: str | None = None,
                    timeout: float = 15.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        _args(ws, claim=claim), cwd=str(ws), capture_output=True,
        text=True, encoding="utf-8", errors="replace", env=_env(),
        timeout=timeout)


def _wait_for(predicate, timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _popen(ws: Path, claim: str | None = None) -> subprocess.Popen:
    return subprocess.Popen(
        _args(ws, claim=claim), cwd=str(ws), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8",
        errors="replace", env=_env())


# ---------- UNWAIT: signal -> rc 0 ----------

class TestUnwait:
    def test_signal_consumed_rc0_last_in_progress(self, tmp_path):
        ws = _mk_ws(tmp_path)
        proc = _popen(ws)
        try:
            assert _wait_for(
                lambda: _status_file(ws).exists()
                and _last_status(_status_file(ws)) == "waiting"), (
                "wait tool must append its first waiting heartbeat promptly")
            _signal_file(ws).write_text(
                json.dumps({"claim": "C-7", "ts": "2026-09-03T00:00:00Z"}),
                encoding="utf-8")
            rc = proc.wait(timeout=10)
        finally:
            if proc.poll() is None:  # pragma: no cover — runaway guard
                proc.kill()
        assert rc == 0, f"UNWAIT must exit 0, got rc={rc}"
        assert _last_status(_status_file(ws)) == "in-progress", (
            "UNWAIT face must flip the LAST status token to in-progress")
        assert not _signal_file(ws).exists(), (
            "the signal file must be consumed (deleted) — single-shot")

    def test_unwait_stdout_carries_signal_context(self, tmp_path):
        ws = _mk_ws(tmp_path)
        proc = _popen(ws)
        try:
            assert _wait_for(
                lambda: _status_file(ws).exists()
                and _last_status(_status_file(ws)) == "waiting")
            _signal_file(ws).write_text(
                json.dumps({"claim": "C-9", "ts": "2026-09-03T00:00:00Z"}),
                encoding="utf-8")
            proc.wait(timeout=10)
        finally:
            if proc.poll() is None:  # pragma: no cover — runaway guard
                proc.kill()
        out = proc.stdout.read() if proc.stdout and not proc.stdout.closed else ""
        # the file is deleted on consumption, so stdout is the context face
        assert "C-9" in out, (
            f"UNWAIT stdout must echo the consumed signal for the agent; "
            f"got {out!r}")


# ---------- self-kill: rounds exhausted ----------

class TestSelfKill:
    def test_rounds_exhausted_with_claim_rc3(self, tmp_path):
        ws = _mk_ws(tmp_path)
        r = _run_foreground(ws, claim="C-9")
        assert r.returncode == 3, f"self-kill with claim must exit 3, got {r.returncode}"
        body = _status_file(ws).read_text(encoding="utf-8")
        assert _last_status(_status_file(ws)) == "failed"
        assert "self-killed" in body
        assert f"note: self-killed after {MAX_ROUNDS} wait rounds" in body

    def test_rounds_exhausted_no_claim_rc4(self, tmp_path):
        ws = _mk_ws(tmp_path)
        r = _run_foreground(ws)
        assert r.returncode == 4, f"self-kill without claim must exit 4, got {r.returncode}"
        assert _last_status(_status_file(ws)) == "failed"

    def test_slot_freed_after_self_kill(self, tmp_path):
        ws = _mk_ws(tmp_path)
        r = _run_foreground(ws, claim="C-9")
        assert r.returncode == 3
        spec = importlib.util.spec_from_file_location(
            "lib_kunglao_hooks_wait_tool", ROOT / "hooks" / "lib_kunglao.py")
        lib = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lib)
        active, stuck = lib.scan_active_workers(ws)
        assert active == 0, "a self-killed worker must not hold a slot"
        assert stuck == []


# ---------- heartbeat renewal ----------

class TestHeartbeat:
    def test_waiting_tokens_grow_while_polling(self, tmp_path):
        ws = _mk_ws(tmp_path)
        proc = _popen(ws)
        try:
            assert _wait_for(
                lambda: _status_file(ws).exists()
                and _last_status(_status_file(ws)) == "waiting")
            first = _status_file(ws).read_text(encoding="utf-8").count(
                "status: waiting")
            time.sleep(float(POLL_S) * 3)  # >= 2 more poll rounds
            body = _status_file(ws).read_text(encoding="utf-8")
            assert proc.poll() is None, "still waiting — no signal, no exit"
        finally:
            proc.kill()
            proc.wait(timeout=5)
        grown = body.count("status: waiting")
        assert grown > first >= 1, (
            f"the wait loop must keep renewing its heartbeat "
            f"(first={first}, after={grown})")


# ---------- constants / CLI contract ----------

class TestConstants:
    def _mod(self):
        spec = importlib.util.spec_from_file_location(
            "kunglao_wait_constants", TOOL)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_default_intervals(self):
        mod = self._mod()
        assert mod.WAIT_POLL_INTERVAL_S == 20
        assert mod.WAIT_MAX_ROUNDS == 90

    def test_named_exit_codes(self):
        mod = self._mod()
        assert mod.EXIT_UNWAITED == 0
        assert mod.EXIT_SELF_KILL_CLAIM == 3
        assert mod.EXIT_SELF_KILL_NO_CLAIM == 4

    def test_missing_worker_arg_rejected(self, tmp_path):
        ws = _mk_ws(tmp_path)
        r = subprocess.run(
            [sys.executable, str(TOOL)], cwd=str(ws), capture_output=True,
            text=True, encoding="utf-8", env=_env(), timeout=15)
        assert r.returncode != 0
