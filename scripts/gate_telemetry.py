# -*- coding: utf-8 -*-
"""gate_telemetry.py — gate trigger telemetry (experiment 1: keep/cut decision data).

Each gate's check() is decorated with @telemetry; every call appends one
line to runs/gate-telemetry.jsonl:
  {ts, gate, rc, rc_meaning, workspace}
rc=0 passes; rc=1/2 intercepted. Without a runs/ directory the write is
skipped (test environments are not instrumented).

Usage:
  from gate_telemetry import telemetry
  @telemetry('reuse_gate')
  def check(...): ...
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path


def telemetry(gate_name: str):
    """Decorate a gate's check function; record each call's rc (telemetry never affects the gate itself)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            rc = None
            try:
                rc = fn(*args, **kwargs)
                return rc
            finally:
                try:
                    _record(gate_name, rc, args, kwargs)
                except Exception:
                    pass

        return wrapper

    return deco


def _record(gate_name: str, rc, args, kwargs) -> None:
    ws = args[0] if args else kwargs.get("workspace")
    if not isinstance(ws, (str, Path)):
        return
    runs = Path(ws) / "runs"
    if not runs.exists():
        return
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gate": gate_name,
        "rc": rc,
        "rc_meaning": _meaning(rc),
    }
    with open(runs / "gate-telemetry.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _meaning(rc) -> str:
    if rc is None:
        return "exception"
    if rc == 0:
        return "pass"
    if rc == 1:
        return "reject"
    if rc == 2:
        return "hard_block"
    return f"rc={rc}"
