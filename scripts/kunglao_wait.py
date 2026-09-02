#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao_wait.py — the WAIT/UNWAIT loop tool: the worker-side mechanism owner.

A kunglao worker that delivered its claim does NOT exit: it runs this tool,
which owns the entire wait mechanism so the agent holds none of it (no
hand-rolled polling, no per-agent sleep loops — the tool is the ONE
mechanism, every agent just invokes it).

Loop, one round (default cadence ~30 min total: 20 s x 90 rounds):
  1. sleep WAIT_POLL_INTERVAL_S (default 20, env KUNGLAO_WAIT_POLL_S)
  2. append one heartbeat line to ``runs/worker-status-<id>.md``:
     ``[ts] wait: awaiting signal | status: waiting``
     The append renews the file mtime — the mtime IS the worker heartbeat,
     so every scanner sees fresh state while the worker idles.
  3. poll ``runs/wait-signal-<id>.json`` (the dispatch gate writes it when
     a dispatch targets this waiting worker). Present -> parse, DELETE it
     (a signal is single-shot), append the UNWAIT face
     ``[ts] unwait: dispatch received (claim <cid>) | status: in-progress``,
     echo the consumed signal JSON on stdout (the file is gone — stdout is
     the context face for the agent), exit 0.

Timeout lives ONLY inside this loop. After WAIT_MAX_ROUNDS (default 90,
env KUNGLAO_WAIT_MAX_ROUNDS) signal-less rounds the worker is unscheduled:
append ``[ts] wait: no signal after N rounds | status: failed | note:
self-killed after N wait rounds`` and exit 3 (--claim given) / 4 (no
claim) — the caller TaskStops itself and frees its slot. Normal work and
post-UNWAIT paths have NO timeout.

NEVER raises: any crash lands a best-effort terminal status line and exits
3. Stdlib only; timestamps come from harness_common.utc_now_z when the
scripts sibling is importable. Direct file appends only — no imports from
the hooks side (the lib_kunglao name is a twin under pytest/CLI and the
wait tool needs none of it).

Usage: python scripts/kunglao_wait.py --worker <id> [--claim <claim-id>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    from harness_common import utc_now_z as _utc_now
except ImportError:  # standalone invocation outside the skill checkout
    from datetime import datetime, timezone

    def _utc_now() -> str:
        return (datetime.now(timezone.utc)
                .isoformat(timespec="seconds").replace("+00:00", "Z"))

# ---- defaults (env-overridable for tests) ----
WAIT_POLL_INTERVAL_S = 20
WAIT_MAX_ROUNDS = 90
POLL_ENV = "KUNGLAO_WAIT_POLL_S"
ROUNDS_ENV = "KUNGLAO_WAIT_MAX_ROUNDS"

# ---- named exit codes (the agent-facing contract) ----
EXIT_UNWAITED = 0          # signal consumed -> re-armed, keep working
EXIT_SELF_KILL_CLAIM = 3   # timed out unscheduled (claim context given)
EXIT_SELF_KILL_NO_CLAIM = 4  # timed out unscheduled (no claim context)

RUNS_DIR = Path("runs")

_WAIT_LINE = "[{ts}] wait: awaiting signal | status: waiting"
_UNWAIT_LINE = "[{ts}] unwait: dispatch received (claim {cid}) | status: in-progress"
_SELFKILL_LINE = ("[{ts}] wait: no signal after {n} rounds | status: failed | "
                  "note: self-killed after {n} wait rounds")
_CRASH_LINE = "[{ts}] wait: crashed ({kind}: {exc}) | status: failed"


def _poll_interval_s() -> float:
    raw = os.environ.get(POLL_ENV)
    if raw is None:
        return float(WAIT_POLL_INTERVAL_S)
    try:
        return max(0.05, float(raw))
    except (TypeError, ValueError):
        return float(WAIT_POLL_INTERVAL_S)


def _max_rounds() -> int:
    raw = os.environ.get(ROUNDS_ENV)
    if raw is None:
        return int(WAIT_MAX_ROUNDS)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return int(WAIT_MAX_ROUNDS)


def _append_status_line(worker: str, line: str) -> None:
    """Append-only status write (the W-15 file contract shape): one line,
    newline-terminated, file created on first append."""
    path = RUNS_DIR / f"worker-status-{worker}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _consume_signal(worker: str) -> dict | None:
    """Read-and-delete the wake signal. None = no signal this round.

    Read and unlink are separate on purpose: a signal that fails to parse
    is still consumed (deleted) — a corrupt file must not wedge the worker
    in WAIT forever, and a signal must never fire twice."""
    path = RUNS_DIR / f"wait-signal-{worker}.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        path.unlink()
    except OSError:
        pass
    try:
        payload = json.loads(raw)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _best_effort_terminal(worker: str, line: str) -> None:
    """Last-ditch status write — used on the crash path. Swallows everything:
    a failing status file must not turn a controlled exit into a traceback."""
    try:
        _append_status_line(worker, line)
    except Exception:  # noqa: BLE001 — by definition, this must not raise
        pass


def run_wait(worker: str, claim: str | None) -> int:
    """The loop. Returns the process exit code; never raises."""
    interval = _poll_interval_s()
    rounds = 0
    while True:
        try:
            time.sleep(interval)
            _append_status_line(worker, _WAIT_LINE.format(ts=_utc_now()))
            signal = _consume_signal(worker)
            if signal is not None:
                cid = signal.get("claim") or claim or "(no claim)"
                _append_status_line(
                    worker, _UNWAIT_LINE.format(ts=_utc_now(), cid=cid))
                print(json.dumps(signal, ensure_ascii=False))
                return EXIT_UNWAITED
        except Exception as exc:  # noqa: BLE001 — never raises, terminal write
            _best_effort_terminal(
                worker,
                _CRASH_LINE.format(ts=_utc_now(),
                                   kind=type(exc).__name__, exc=exc))
            return EXIT_SELF_KILL_CLAIM
        rounds += 1
        if rounds >= _max_rounds():
            _best_effort_terminal(
                worker, _SELFKILL_LINE.format(ts=_utc_now(), n=rounds))
            return EXIT_SELF_KILL_CLAIM if claim else EXIT_SELF_KILL_NO_CLAIM


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kunglao_wait",
        description="Worker WAIT/UNWAIT loop: heartbeat-poll for a dispatch "
                    "signal, self-kill when unscheduled.")
    parser.add_argument("--worker", required=True,
                        help="worker id (the worker-status file stem base)")
    parser.add_argument("--claim", default=None,
                        help="claim context of the delivered work (optional)")
    args = parser.parse_args(argv)
    return run_wait(args.worker, args.claim)


if __name__ == "__main__":
    sys.exit(main())
