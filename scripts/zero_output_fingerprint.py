#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zero_output_fingerprint.py — P3 same-type action thrash circuit (#823 A4).

A "same-type action" = (tool, target_type) hash. N=3 consecutive
checkpoints with ZERO belief change (facts/_INDEX.md + claim-register
content hash) on the same fingerprint → circuit breaks: callers are told
to interrupt the worker and inject a failure_analysis step (#634 design).

SHADOW POSTURE: this module counts, persists state, and emits the
"zero_output_break" event — it does NOT block anything. Enforcement
wiring in the worker_budget gates graduates only after A5 canary gates
pass (four-stage promotion, AUDIT_REPORT §14).

State: runs/zero-output-fingerprint.json {"belief_hash": str,
"streaks": {fingerprint: count}}. Any belief move resets ALL streaks —
a workspace that just learned something is not thrashing.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import kunglao_log

STATE_FILE = "runs/zero-output-fingerprint.json"
ZERO_OUTPUT_N = 3

_INJECT_MSG = ("zero-output circuit: {n} consecutive same-type actions "
               "({tool} on {target_type}) with no belief change — interrupt "
               "and run failure_analysis before retrying this action family")


def fingerprint(tool: str, target_type: str) -> str:
    raw = f"{tool}|{target_type}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def belief_hash(ws: Path) -> str:
    """Content hash over the two belief carriers; missing files hash as
    empty so a fresh workspace still has a stable baseline."""
    h = hashlib.sha256()
    for rel in ("facts/_INDEX.md", "claim-register.yaml"):
        p = Path(ws) / rel
        try:
            h.update(p.read_bytes())
        except OSError:
            h.update(b"")
    return h.hexdigest()[:16]


def _load_state(ws: Path) -> dict:
    p = Path(ws) / STATE_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("streaks"), dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"belief_hash": None, "streaks": {}}


def _save_state(ws: Path, state: dict) -> None:
    p = Path(ws) / STATE_FILE
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    except OSError:
        pass  # state loss degrades to a reset streak, never a crash


def record_action(ws: Path, tool: str, target_type: str) -> dict:
    """Count one action against its fingerprint under the CURRENT belief
    hash. Pure library — arm gating happens at the mount point (A5)."""
    ws = Path(ws)
    state = _load_state(ws)
    cur = belief_hash(ws)
    if state.get("belief_hash") != cur:
        state["streaks"] = {}
        state["belief_hash"] = cur
    fp = fingerprint(tool, target_type)
    n = int(state["streaks"].get(fp, 0)) + 1
    state["streaks"][fp] = n
    _save_state(ws, state)
    broken = n >= ZERO_OUTPUT_N
    if broken:
        kunglao_log.emit(ws, actor="zero_output_fingerprint",
                         action="zero_output_break", tool=tool,
                         detail=f"streak={n} target_type={target_type}")
    return {"fingerprint": fp, "streak": n, "circuit_broken": broken,
            "inject": _INJECT_MSG.format(n=n, tool=tool, target_type=target_type)
            if broken else None}


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
