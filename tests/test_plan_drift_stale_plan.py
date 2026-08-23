#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TDD RED — issue #497, drift semantics flip: STALE_PLAN_ON_NEW_EVIDENCE.

The existing 6 drift classes ask whether the plan files AGREE with each other
(plan vs register, plan vs deps, plan vs status, register vs reality-check).
None asks the #498 question: the plan is a DERIVED VIEW of the current world
model — when new evidence lands (a failure analysis recorded, an obstacle
claim promoted per #495) and the plan is NOT re-derived, the plan is stale
even though it may be perfectly consistent with an outdated DAG.

Whitelist inversion (#497 What 4): deviating from the plan after the model
changed is the NORM (re-derivation); the drift worth flagging is
stale-plan-on-new-evidence. This class is WARN-level (observe-first): it is
printed but never counted toward the drift exit codes (no rc=1, no HARD).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import plan_drift_detector as pdd  # noqa: E402


def write_register(ws: Path, claims: list[dict]) -> None:
    import yaml
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def write_analysis(ws: Path, cid: str) -> Path:
    import yaml
    adir = ws / "analyses"
    adir.mkdir(exist_ok=True)
    p = adir / f"failure-{cid}.yaml"
    p.write_text(yaml.safe_dump({
        "claim": cid, "covers_attempt": 1,
        "method_assumption": "a", "assumption_validity": "not-justified",
        "next_method": "b", "next_method_source": "lesson-hit",
        "validated_capability": "c", "identified_obstacle": "d",
        "candidates": [],
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def set_mtime(path: Path, ts: float) -> None:
    os.utime(path, (ts, ts))


T0 = 1_700_000_000.0


# ---------- WARN fires: evidence newer than the plan --------------------

def test_failure_analysis_newer_than_plan_warns(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    plan = ws / "global_plan.txt"
    plan.write_text("plan mentions C-1\n", encoding="utf-8")
    analysis = write_analysis(ws, "C-1")
    set_mtime(plan, T0)
    set_mtime(analysis, T0 + 100)

    rc = pdd.check(ws, active_only=True)
    assert rc == 0  # WARN-level: observe, do not block
    out = capsys.readouterr().out
    assert "STALE_PLAN_ON_NEW_EVIDENCE" in out
    assert "WARN" in out


def test_obstacle_claim_promotion_newer_than_plan_warns(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    # phase-level plan (no shared claim-id namespace) — the WARN is
    # namespace-independent: evidence newer than plan is a fact either way
    plan = ws / "global_plan.txt"
    plan.write_text("phase A plan, no claim ids here\n", encoding="utf-8")
    write_register(ws, [
        {"id": "C-1", "status": "OPEN", "promotion_attempts": 1},
        {"id": "C-2", "status": "OPEN", "origin": "failure-obstacle",
         "obstacle_for": "C-1"},
    ])
    reg = ws / "claim-register.yaml"
    set_mtime(plan, T0)
    set_mtime(reg, T0 + 100)

    rc = pdd.check(ws, active_only=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "STALE_PLAN_ON_NEW_EVIDENCE" in out


# ---------- WARN does not fire -------------------------------------------

def test_plan_newer_than_analysis_no_warn(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    plan = ws / "global_plan.txt"
    plan.write_text("plan mentions C-1\n", encoding="utf-8")
    analysis = write_analysis(ws, "C-1")
    set_mtime(analysis, T0)
    set_mtime(plan, T0 + 100)  # plan re-derived AFTER the evidence landed

    assert pdd.check(ws, active_only=True) == 0
    assert "STALE_PLAN_ON_NEW_EVIDENCE" not in capsys.readouterr().out


def test_plain_register_change_does_not_warn(tmp_path, capsys):
    """Only promoted obstacle claims (#495) are evidence — an ordinary
    register touch (status flip, attempt bump) is not new evidence."""
    ws = tmp_path / "ws"
    ws.mkdir()
    plan = ws / "global_plan.txt"
    plan.write_text("plan mentions C-1\n", encoding="utf-8")
    write_register(ws, [{"id": "C-1", "status": "OPEN"}])
    set_mtime(plan, T0)
    set_mtime(ws / "claim-register.yaml", T0 + 100)

    rc = pdd.check(ws, active_only=True)
    assert rc == 0
    assert "STALE_PLAN_ON_NEW_EVIDENCE" not in capsys.readouterr().out


def test_no_plan_file_no_warn(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [{"id": "C-1", "status": "OPEN"}])
    write_analysis(ws, "C-1")

    assert pdd.check(ws, active_only=True) == 0
    assert "STALE_PLAN_ON_NEW_EVIDENCE" not in capsys.readouterr().out


# ---------- WARN stays observation-level ---------------------------------

def test_many_warns_never_escalate_to_hard(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    plan = ws / "global_plan.txt"
    plan.write_text("plan mentions C-1\n", encoding="utf-8")
    set_mtime(plan, T0)
    for i in range(5):
        set_mtime(write_analysis(ws, f"C-{i}"), T0 + 100 + i)

    rc = pdd.check(ws, active_only=True)
    assert rc == 0  # 5 warnings, still no rc=1 / rc=2
    out = capsys.readouterr().out
    assert "REJECT" not in out


def test_warn_coexists_with_hard_drift(tmp_path, capsys):
    """Hard drift decides the exit code; the WARN is still printed."""
    ws = tmp_path / "ws"
    ws.mkdir()
    plan = ws / "global_plan.txt"
    plan.write_text("plan mentions C-1\n", encoding="utf-8")
    write_register(ws, [
        {"id": "C-1", "status": "OPEN"},
        {"id": "C-2", "status": "OPEN", "origin": "failure-obstacle",
         "obstacle_for": "C-1"},
    ])
    set_mtime(plan, T0)
    set_mtime(ws / "claim-register.yaml", T0 + 100)

    rc = pdd.check(ws, active_only=True)
    assert rc == 1  # ORPHAN_CLAIM (C-2 not in plan) is the hard drift
    out = capsys.readouterr().out
    assert "STALE_PLAN_ON_NEW_EVIDENCE" in out
    assert "ORPHAN_CLAIM" in out
