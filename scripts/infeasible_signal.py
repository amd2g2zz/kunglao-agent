#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""infeasible_signal.py — P3 doomed-trajectory early-stop signal (#823 A4).

Fires `infeasible_candidate` (event only) when BOTH hold:
  - V <= V_FLOOR for the last K consecutive rho_checkpoint rounds, AND
  - marginal discovery rate is 0 (terminal-fact count unchanged since the
    previous evaluation).

Declaring a channel infeasible (obstacle +3 pruning semantics) is the
SKILL layer's decision; this module is the mechanical #815 signal behind
it. Shadow posture — no interception anywhere.

State: runs/infeasible-state.json {"terminal_count": int}.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import kunglao_log
from kunglao_log import iter_jsonl  # noqa: E402  (#863 Family K single source)

STATE_FILE = "runs/infeasible-state.json"
K_ROUNDS = 3
V_FLOOR = 0.1
_TERMINAL = ("PROVEN", "VERIFIED")


def _v_series_from_ledger(ws: Path) -> list[float]:
    out: list[float] = []
    logs = Path(ws) / "runs" / "logs"
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for row in iter_jsonl(text.splitlines()):
            if not isinstance(row, dict) or row.get("action") != "rho_checkpoint":
                continue
            try:
                detail = json.loads(row.get("detail") or "{}")
                out.append(float(detail.get("v")))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    return out


def _terminal_count(ws: Path) -> int:
    index = Path(ws) / "facts" / "_INDEX.md"
    if not index.exists():
        index = Path(ws) / "_INDEX.md"
    n = 0
    try:
        for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3 and parts[0].startswith("F") \
                    and any(t in parts[1].upper() for t in _TERMINAL):
                n += 1
    except OSError:
        pass
    return n


def _load_state(ws: Path) -> dict:
    try:
        data = json.loads((Path(ws) / STATE_FILE).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def evaluate(ws: Path, v_series: list[float] | None = None,
             prev_terminal_count: int | None = None,
             *, persist: bool = True) -> dict:
    """Judge the doomed-trajectory condition. Explicit args override the
    ledger/state sources (test injection). Pure library — arm gating
    happens at the mount point (A5).

    persist=False is the diagnostic/read-only face (resume's #466
    contract): the judgement is computed identically — same ledger reads,
    same returned dict — but NOTHING is written (no runs/infeasible-state.json
    checkpoint, no infeasible_candidate event row). A diagnostic must not
    clobber the terminal_count state the live loop compares against."""
    ws = Path(ws)
    vs = v_series if v_series is not None else _v_series_from_ledger(ws)
    flat = 0
    for v in reversed(vs):
        if v <= V_FLOOR:
            flat += 1
        else:
            break
    cur = _terminal_count(ws)
    if prev_terminal_count is None:
        prev_terminal_count = _load_state(ws).get("terminal_count", cur)
    discovery_zero = int(prev_terminal_count) == cur
    if persist:
        try:
            (ws / STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
            (ws / STATE_FILE).write_text(
                json.dumps({"terminal_count": cur}, sort_keys=True), encoding="utf-8")
        except OSError:
            pass
    fire = flat >= K_ROUNDS and discovery_zero
    if fire and persist:
        kunglao_log.emit(ws, actor="infeasible_signal",
                         action="infeasible_candidate",
                         detail=f"v_flat_rounds={flat} terminal_count={cur}")
    return {"infeasible_candidate": fire, "v_flat_rounds": flat,
            "discovery_rate": 0 if discovery_zero else 1}


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
