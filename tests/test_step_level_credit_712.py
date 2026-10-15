# -*- coding: utf-8 -*-
"""tests/test_step_level_credit_712.py — step-level ladder credit (#712):
dense reward at step boundaries (TIPS/TRACE-style turn-level credit).

The card's four pins (issue acceptance):

  1. banked at SubagentStop — a step's credit lands in the Q-cell Beta at
     the step boundary, BEFORE claim-terminal (settle -> update -> decide
     now includes the learning update).
  2. O(step) learning — a 10-step rollout produces 10 credit observations
     (and 10 transitions), not 1 claim-terminal signal.
  3. claim-terminal calibration — the residual
     ``ladder_credit - sum(step_credit)`` corrects the cumulative Beta:
     over-credit is clawed back, under-credit is topped up, and the
     post-terminal endpoint equals the step-less (legacy) endpoint —
     dense credit changes the PATH, not the DESTINATION.
  4. evidence-quality weighted — cross-validated=1.0 / unverified=0.3 /
     refuted=0.0 (× source-reliability weight when provenance carries an
     Admiralty credibility letter), never a uniform per-step constant.

Plus the backward-compatibility acceptance: a claim that settles with NO
step credit banks the legacy settlement row byte-identically.

All window arithmetic is explicit (fixture timestamps, settle ``now=``
injection) — no wall-clock sleeps anywhere.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (SCRIPTS, SCRIPTS.parent / "tests", ROOT / "hooks"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from rlvr import incremental_reward as ir  # noqa: E402
from rlvr import q_cells as qc  # noqa: E402
from rlvr import step_grain as sg  # noqa: E402

T0 = datetime(2026, 10, 15, 8, 0, 0, tzinfo=timezone.utc)
FAM = "static-symbolic"


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ws(tmp_path: Path, claims: list[dict]) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}), encoding="utf-8")
    return ws


def _dispatch(ws: Path, claim: str) -> dict:
    """The pending dispatch row (credit=None) the settlement faces match."""
    return qc.record_dispatch_observation(
        ws, "dispatch envelope",
        envelope_meta={"method_family": FAM, "action_type": "dispatch",
                       "context_recipe": "facts_snapshot",
                       "verification_mode": "none", "tier": 0},
        claim=claim)


def _launch(ws: Path, claim: str, ts: datetime) -> None:
    """A launch stash stamped at the fixture time (the window's first
    boundary for step 1 — record_launch writes real-now, we rewrite ts)."""
    doc = ir.record_launch(ws, claim, "static-first")
    assert doc is not None
    p = ws / "runs" / f"dispatch-launch-{claim}.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["ts"] = _ts(ts)
    p.write_text(json.dumps(raw), encoding="utf-8")


def _fact(ws: Path, name: str, *, status: str, verify_status: str,
          claim_id: str, creator: str | None = None,
          credibility: str | None = None,
          mtime: datetime | None = None) -> Path:
    meta = {
        "id": name,
        "type": "fact",
        "status": status,
        "verify_status": verify_status,
        "claim_id": claim_id,
        "creator": creator if creator is not None else claim_id,
    }
    if credibility:
        meta["provenance"] = [{"role": "sample_raw",
                               "path": "bins/x",
                               "content_sha256": "0" * 64,
                               "credibility": credibility}]
    path = ws / "facts" / f"{name}.md"
    path.write_text(
        "---\n" + yaml.safe_dump(meta, sort_keys=False) + "---\n\nbody\n",
        encoding="utf-8")
    if mtime is not None:
        epoch = mtime.timestamp()
        os.utime(path, (epoch, epoch))
    return path


def _step_rows(ws: Path) -> list[dict]:
    return [r for r in qc.JSONLQStore(ws).observations()
            if r.get("credit_kind") == "step"]


def _calibration_rows(ws: Path) -> list[dict]:
    return [r for r in qc.JSONLQStore(ws).observations()
            if r.get("credit_kind") == "step_calibration"]


def _cell(ws: Path, gamma=1.0):
    """The dispatch-opened cell's counts under the given γ face."""
    disp = next(r for r in qc.JSONLQStore(ws).observations()
                if r.get("source") == "dispatch")
    view = qc.fold(qc.JSONLQStore(ws), gamma=gamma)
    return view.cells[(disp["signature_hash"], disp["arm_key"])]


# ---------------------------------------------- 1. banked at the stop --

def test_step_credit_banked_at_subagent_stop(tmp_path):
    """A step's evidence-quality credit banks into the Q-cell at
    SubagentStop — the row exists BEFORE any claim-terminal settlement,
    so the posterior moves during the rollout, not only at the end."""
    from rlvr import ledger as rl
    ws = _ws(tmp_path, [{"id": "C-71", "status": "IN_PROGRESS"}])
    _dispatch(ws, "C-71")
    _launch(ws, "C-71", ts=T0)
    _fact(ws, "F710-proven", status="PROVEN", verify_status="passes",
          claim_id="C-71", mtime=T0 + timedelta(seconds=9))
    out = sg.settle_step(ws, "sess-a", now=T0 + timedelta(seconds=60))

    rows = _step_rows(ws)
    assert len(rows) == 1, "the step boundary must bank one credit row"
    assert rows[0]["credit"] == pytest.approx(1.0)
    assert rows[0]["source"] == "settlement"
    assert (str(rows[0].get("dispatch_id")) == "C-71"
            or str(rows[0].get("claim")) == "C-71")
    assert (out or {}).get("step_credit") == pytest.approx(1.0)
    # NOT claim-terminal: no round-credit ledger settlement exists yet
    assert rl.fold(ws, "round_credit/C-71") is None, (
        "step credit must land at the stop, before claim-terminal")


# ----------------------------------- 2. O(step) — ten steps, ten signals --

def test_ten_step_rollout_produces_ten_signals(tmp_path):
    """Ten subagent completions produce ten credit observations AND ten
    transitions: the learning signal count is O(steps), never O(claims).
    Each banked step visibly moves the cell's success mass (γ=1 read)."""
    from rlvr import ledger as rl
    ws = _ws(tmp_path, [{"id": "C-72", "status": "IN_PROGRESS"}])
    _dispatch(ws, "C-72")
    successes: list[float] = []
    for k in range(1, 11):
        step_now = T0 + timedelta(seconds=10 * k)
        _launch(ws, "C-72", ts=step_now - timedelta(seconds=5))
        _fact(ws, f"F72{k}-step", status="PROVEN", verify_status="passes",
              claim_id="C-72", mtime=step_now - timedelta(seconds=1))
        sg.settle_step(ws, "sess-b", now=step_now)
        successes.append(_cell(ws).success)

    assert len(_step_rows(ws)) == 10, (
        "a 10-step rollout must produce 10 step_credit observations")
    assert len(ir.read_transitions(ws)) == 10, "one transition per step"
    # O(step): every step moved the Beta (strictly increasing, γ=1)
    assert all(b > a for a, b in zip(successes, successes[1:])), (
        f"success mass must accrue per step, got {successes}")
    assert successes[-1] == pytest.approx(10.0)
    # still before claim-terminal — the dense signals are not one signal
    assert rl.fold(ws, "round_credit/C-72") is None


