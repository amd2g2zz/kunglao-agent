# -*- coding: utf-8 -*-
"""#704: dispatch must be fire-and-continue — the SKILL contract forbids
foreground-blocking dispatch language and requires the background-launch
protocol at every DISPATCH site.

Root cause (#704): the parallel machinery (worker_budget ≤3 via
scan_active_workers on status files, smart ping, Delivery=TaskStop) is built
for background workers, but the SKILL prose said "dispatch the top — this
turn" without ever saying NOT to await the Task inline — so the orchestrator
foreground-blocks on each worker and the whole monitoring loop idles.

This test pins the prose contract so a future edit cannot silently reintroduce
foreground dispatch.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "kunglao-agent" / "SKILL.md"
MECHANICS = ROOT / "references" / "operational-mechanics.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_skill_has_fire_and_continue_protocol():
    s = _read(SKILL)
    assert "fire-and-continue" in s, (
        "SKILL.md must state the fire-and-continue dispatch protocol (#704)")
    assert "BACKGROUND task" in s, (
        "SKILL.md must instruct launching workers as BACKGROUND tasks (#704)")


def test_dispatch_decision_row_carries_no_wait_semantics():
    s = _read(SKILL)
    row = next((ln for ln in s.splitlines()
                if ln.startswith("| `DISPATCH` | 1 |")), "")
    assert row, "DISPATCH decision row missing from SKILL.md"
    assert "fire-and-continue" in row, (
        "the DISPATCH decision row must carry fire-and-continue (#704)")


def test_dispatch_contract_explains_why_foreground_is_forbidden():
    s = _read(SKILL)
    m = re.search(r"\*\*Dispatch is fire-and-continue\*\*.*?catch it\.",
                  s, re.DOTALL)
    assert m, (
        "the dispatch contract must carry the fire-and-continue block explaining why a "
        "foreground Task call collapses monitoring (parallelism, tick loop, "
        "smart pings) and why status-file-first matters for the ≤3 gate")
    body = m.group(0)
    for phrase in ("NEVER wait inline",
                   "TaskOutput",
                   "scan_active_workers",
                   "status file FIRST"):
        assert phrase in body, f"#704 block missing phrase: {phrase!r}"


def test_no_serial_after_worker_returns_prose():
    """The old serial loop language ('After a worker returns: read both files,
    classify, ... dispatch the new top') is removed — completion is discovered
    on a later tick, not by returning from an awaited Task call."""
    s = _read(SKILL)
    assert "After a worker returns: read both files" not in s, (
        "serial 'After a worker returns' prose must not reappear (#704)")


def test_operational_mechanics_tick_opens_with_background_rule():
    s = _read(MECHANICS)
    m = re.search(r"## Active workers heartbeat \(the tick loop\)(.*?)EACH TICK:",
                  s, re.DOTALL)
    assert m, "tick loop section missing from operational-mechanics.md"
    head = m.group(1)
    assert "never awaited inline" in head and "BACKGROUND" in head, (
        "the tick loop header must state workers are launched in the "
        "BACKGROUND and never awaited inline before describing the tick (#704)")


def test_worker_agent_status_file_first_rule_referenced():
    """The #704 block leans on the worker-side status-file-first rule; the
    worker agent definition must actually carry it (W-15 / §1c)."""
    w = _read(ROOT / "agents" / "kunglao-worker.md")
    assert "**FIRST**" in w and "worker-status" in w and "in-progress" in w, (
        "worker agent must keep the status-file-first (in-progress on start) "
        "rule — the ≤3 gate and the tick loop depend on it (#704)")
