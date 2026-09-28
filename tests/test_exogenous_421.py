#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_exogenous_421.py — exogenous-failure settlement classification.

Pins #421: a lane-required component DOWN at action time reclassifies a
failed settlement as "<kind>/exogenous" — environment-neutral (feeds no
beta: the advisory anti-pollution wall construction, unchanged), visible
for audit, carrying a #634-precedent wake_condition. Component-up (or no
component evidence at all) settles normally; mixed-run statistics
separate over the prior feed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import reward_settlement as rs  # noqa: E402
import rollout_ledger as rl  # noqa: E402
import exogenous  # noqa: E402
from harness_common import utc_now_z  # noqa: E402

NOW = utc_now_z()


def _env_state(ws: Path, status: str, *, ts: str = NOW,
               cap: str = "vm_reachable") -> None:
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    (ws / "runs" / "env-state.json").write_text(json.dumps({
        "per_capability": {cap: {
            "status": status, "last_probe_ts": ts,
            "detail": f"probe face for #421 ({status})"}},
        "written_by": "test", "ts": ts}, indent=2), encoding="utf-8")


def _analysis_state(ws: Path, project_type: str = "windows") -> None:
    (ws / "analysis_state.txt").write_text(
        f"project_type={project_type}\n", encoding="utf-8")


def _record_red(ws: Path, rollout_id: str = "ro-1") -> None:
    """A failed task rollout: oracle red + NEGATIVE terminal (the exact
    machine-signal pair the rules table maps to SETTLED_RED)."""
    rl.register_kind("task")
    signals = [
        {"type": "oracle_verdict", "value": "fail",
         "source": "runs/oracle-status.json", "ts": NOW},
        {"type": "claim_terminal", "value": "NEGATIVE",
         "source": "claim-register.yaml", "ts": NOW},
    ]
    res = rl.record(ws, "task", "C-001", signals,
                    rollout_id=rollout_id, ts=NOW)
    assert res.get("appended"), res


def test_component_down_classifies_exogenous(tmp_path):
    """component-down at action time -> exogenous row: band <kind>/exogenous,
    reward 0.0, audit evidence + #634 wake_condition in the settlement."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _analysis_state(ws)
    _env_state(ws, "fail")  # vm_reachable DOWN at action time
    _record_red(ws)
    report = rs.settle_workspace(ws)
    assert report["settled"] == 1
    rows = rl.settled(ws)
    s = rows[0]["settlement"]
    assert s["band"] == "task/exogenous", s
    assert s["reward"] == 0.0
    assert s["exogenous"]["component"] == "vm_reachable"
    assert s["wake_condition"].startswith("component:vm_reachable")
    # prior feed: the exogenous band feeds NO beta (anti-pollution wall)
    alpha, beta = rs.prior_observations(ws)
    assert (alpha, beta) == (0, 0), "exogenous rows must feed no prior"


def test_component_up_settles_normally(tmp_path):
    """component-up -> the normal rules table decides (SETTLED_RED feeds
    beta exactly as before — no regression)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _analysis_state(ws)
    _env_state(ws, "pass")  # component healthy at action time
    _record_red(ws)
    rs.settle_workspace(ws)
    s = rl.settled(ws)[0]["settlement"]
    assert s["band"] == "SETTLED_RED", s
    assert s["reward"] == 0.0
    alpha, beta = rs.prior_observations(ws)
    assert beta == 1, "a real RED with a healthy component feeds beta"


def test_stale_snapshot_is_not_evidence(tmp_path):
    """A probe far from the action time cannot classify — conservative:
    normal settlement (no invented exogeneity)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _analysis_state(ws)
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(hours=6)) \
        .isoformat().replace("+00:00", "Z")
    _env_state(ws, "fail", ts=old)
    _record_red(ws)
    rs.settle_workspace(ws)
    s = rl.settled(ws)[0]["settlement"]
    assert s["band"] == "SETTLED_RED", "stale probe must not classify"


def test_absent_env_state_settles_normally(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _analysis_state(ws)
    _record_red(ws)
    rs.settle_workspace(ws)
    s = rl.settled(ws)[0]["settlement"]
    assert s["band"] == "SETTLED_RED"


def test_lane_mismatch_does_not_classify(tmp_path):
    """A component the action's lane does not require (adb on windows)
    failing never classifies the failure exogenous."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _analysis_state(ws, project_type="windows")
    _env_state(ws, "fail", cap="adb")
    _record_red(ws)
    rs.settle_workspace(ws)
    s = rl.settled(ws)[0]["settlement"]
    assert s["band"] == "SETTLED_RED", s


def test_mixed_run_statistics_separate(tmp_path):
    """Statistical separation: two workspaces, same action signals —
    component-down run feeds no beta; component-up run feeds beta. The
    prior feed separates the environments over multiple observations."""
    down = tmp_path / "down"
    up = tmp_path / "up"
    for ws, status in ((down, "fail"), (up, "pass")):
        ws.mkdir()
        _analysis_state(ws)
        _env_state(ws, status)
        for i in range(3):
            _record_red(ws, f"ro-{i}")
    rs.settle_workspace(down)
    rs.settle_workspace(up)
    assert rs.prior_observations(down) == (0, 0), \
        "the exogenous run must feed no beta at all"
    assert rs.prior_observations(up) == (0, 3), \
        "the component-up run's real reds all feed beta"
