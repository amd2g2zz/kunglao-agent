#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zero_output_fingerprint.py — P3 same-type action thrash circuit (#823 A4).

A "same-type action" = (tool, target_type) hash. N=3 consecutive
checkpoints with ZERO belief change (facts/_INDEX.md + claim-register
content hash) on the same fingerprint → circuit breaks: callers are told
to interrupt the worker and inject a failure_analysis step (#634 design).

SHADOW -> PRODUCTION (issue 256): this module counts, persists state,
and emits the "zero_output_break" event. The A5 canary graduation
landed: post_check (worker_budget_sinks._record_zero_output_fingerprint)
feeds record_action at the real "worker action completed" face, and
worker_budget_gates.check_zero_output_circuit runs in the pre_check
battery — a tripped circuit REJECTs the next dispatch (fail-open on any
read failure; a broken gate must not deadlock the loop). The recorder
itself stays non-blocking: recording never blocks the completing action.

State: runs/zero-output-fingerprint.json {"belief_hash": str,
"streaks": {fingerprint: count}}. Any belief move resets ALL streaks —
a workspace that just learned something is not thrashing. Belief
movement is measured ONLY over facts/_INDEX.md + claim-register.yaml
(the two belief carriers): work whose progress lands elsewhere (plan
files, analyses, code) reads as no-progress by construction — accepted
coarse-grained v1, noted so nobody mistakes the streak for an output
content diff. The gate face re-derives belief freshness itself, so a
moved workspace can never stay blocked on a stale ledger.

Fingerprint = hash(tool_family(tool) | target_type): mcp tools collapse
to their server family (mcp__ghidra__* -> mcp__ghidra) so retrying the
same action family under a sibling operation still counts as thrash.
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


def tool_family(tool: str) -> str:
    """Collapse a tool to its action family: mcp__<server>__<op> ->
    mcp__<server> (retrying the family under a sibling operation is the
    same thrash); non-mcp tools are their own family."""
    if tool.startswith("mcp__"):
        parts = tool.split("__")
        if len(parts) >= 2 and parts[1]:
            return f"mcp__{parts[1]}"
    return tool


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
    hash. Pure library — the mount point is worker_budget_sinks
    post_check (issue 256); enforcement is the pre_check zerooutput
    gate."""
    ws = Path(ws)
    state = _load_state(ws)
    cur = belief_hash(ws)
    if state.get("belief_hash") != cur:
        state["streaks"] = {}
        state["belief_hash"] = cur
    fp = fingerprint(tool_family(tool), target_type)
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
