#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_rl_wiring_518.py — the reward loop closes (#518 PR-2, RC6).

Architect audit verdict (2026-10-04): OPEN LOOP — read sites live, write
sites dead. Every method_family envelope in the combat matrix showed
alpha=beta=1.0 forever because nothing records the dispatch observation
and nothing banks the settlement. This PR is the three-wire closure the
audit mapped to file:line:

  W1  _launch_dispatch opens the pending q-cell observation (the fold's
      dispatch row + the settlement's match target)
  W2  _land_dispatch banks the outcome credit (DISPATCHED=1.0, anything
      else=0.0) and emits the §4 posterior_updated audit row
  W3  a TIMEOUT act records an obstacle row (the termination floor's
      feed — repeat-offender families decay without any sampler change)
  W4  the frozen-posterior drift check: >=3 pending dispatch rows and
      zero settlements is observable (posterior_frozen audit warn)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr import q_cells  # noqa: E402

from e2e import checkpoints, llm_faces, model  # noqa: E402

ANCHORS = {"goal_verbatim": "g", "success_criterion": "s",
           "verification_method": "reproduction"}
FAMILY = "hypothesis-falsification"


class _FakeFace:
    """launch_dispatch seam: returns a handle, records the request."""

    def __init__(self):
        self.requests = []

    def launch_dispatch(self, request):
        self.requests.append(request)
        return f"handle-{request.claim}"


def _ctx(tmp_path: Path) -> checkpoints.RunContext:
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-004\n  status: OPEN\n", encoding="utf-8")
    (ws / "analysis_state.txt").write_text(
        "kunglao workspace\n", encoding="utf-8")
    ev = tmp_path / "ev"
    ev.mkdir()
    state = model.RunState(
        run_id="r1", unit="u1", family="release", repo=str(ROOT),
        task_dir=str(ROOT), ws=str(ws), evidence_dir=str(ev),
        budget_seconds=100, llm_mode="dry", started_ts="t",
        started_monotonic=0.0, anchors=dict(ANCHORS),
        method_family=FAMILY)
    return checkpoints.RunContext(
        state=state, runner=object(), face=_FakeFace(),
        clock=object(), sleep_fn=lambda _s: None)


def _obs(ctx) -> list[dict]:
    return [r for r in q_cells.JSONLQStore(str(ctx.ws)).observations()
            if isinstance(r, dict)]


def _act(claim: str, outcome: str) -> llm_faces.ActRecord:
    return llm_faces.ActRecord(claim=claim, mode="auto",
                               outcome=outcome, detail={})


def _ledger_rows(ctx, action: str) -> list[dict]:
    rows = []
    logs = ctx.ws / "runs" / "logs"
    for p in sorted(list(logs.glob("kunglao-*.jsonl"))
                    + list(logs.glob("e2e-audit.jsonl"))):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("action") == action:
                d = e.get("detail")
                if isinstance(d, str):  # the ledger double-encodes JSON
                    try:
                        d = json.loads(d)
                    except ValueError:
                        pass
                e["detail"] = d
                rows.append(e)
    return rows


def _obstacle_rows(ctx) -> list[dict]:
    d = ctx.ws / "runs" / "obstacles"
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("OBS-*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return out


# ------------------------------------------------------------------ W1+W2

def test_launch_opens_pending_and_land_banks(tmp_path):
    ctx = _ctx(tmp_path)
    dispatched: set[str] = set()
    request, _ = checkpoints._launch_dispatch(ctx, "C-004", dispatched)
    assert request is not None
    pend = [r for r in _obs(ctx) if r.get("credit") is None
            and str(r.get("source")) == "dispatch"]
    assert len(pend) == 1, pend
    assert pend[0]["method_family"] == FAMILY
    assert pend[0]["claim"] == "C-004"

    checkpoints._land_dispatch(ctx, "C-004", _act("C-004", "DISPATCHED"),
                               dispatched, {"acts": []})
    sett = [r for r in _obs(ctx) if r.get("credit") is not None]
    assert len(sett) == 1 and sett[0]["credit"] == 1.0, sett


def test_timeout_banks_zero_and_floors_obstacle(tmp_path):
    ctx = _ctx(tmp_path)
    dispatched: set[str] = set()
    checkpoints._launch_dispatch(ctx, "C-004", dispatched)
    checkpoints._land_dispatch(ctx, "C-004", _act("C-004", "TIMEOUT"),
                               dispatched, {"acts": []})
    sett = [r for r in _obs(ctx) if r.get("credit") is not None]
    assert sett and sett[0]["credit"] == 0.0, sett
    assert "C-004" not in dispatched  # rollback still frees the claim

    rows = _obstacle_rows(ctx)
    assert any(r.get("kind") == "other" and
               "act-timeout" in str(r.get("cause", "")) and
               r.get("method_family") == FAMILY and
               r.get("claim") == "C-004" for r in rows), rows


def test_banked_settlement_emits_posterior_update(tmp_path):
    ctx = _ctx(tmp_path)
    dispatched: set[str] = set()
    checkpoints._launch_dispatch(ctx, "C-004", dispatched)
    checkpoints._land_dispatch(ctx, "C-004", _act("C-004", "DISPATCHED"),
                               dispatched, {"acts": []})
    rows = _ledger_rows(ctx, "posterior_updated")
    assert rows, "the §4 kernel hook must fire at the bank site"
    assert rows[-1]["detail"]["counts"]["credit"] == 1.0


# ------------------------------------------------------------------ W4

def test_frozen_posterior_drift_is_observable(tmp_path):
    ctx = _ctx(tmp_path)
    for claim in ("C-004", "C-005", "C-006"):
        d: set[str] = set()
        checkpoints._launch_dispatch(ctx, claim, d)
    checkpoints._posterior_drift_check(ctx)
    assert _ledger_rows(ctx, "posterior_frozen"), \
        "3+ pending with zero settled must be a named audit row"


def test_drift_check_silent_when_settled(tmp_path):
    ctx = _ctx(tmp_path)
    d: set[str] = set()
    checkpoints._launch_dispatch(ctx, "C-004", d)
    checkpoints._land_dispatch(ctx, "C-004", _act("C-004", "DISPATCHED"),
                               d, {"acts": []})
    checkpoints._posterior_drift_check(ctx)
    assert not _ledger_rows(ctx, "posterior_frozen")


def test_sampler_fold_sees_the_observation(tmp_path):
    """The read site needs zero changes: after one banked success the
    store carries a real settlement row (the fold's input)."""
    ctx = _ctx(tmp_path)
    d: set[str] = set()
    checkpoints._launch_dispatch(ctx, "C-004", d)
    checkpoints._land_dispatch(ctx, "C-004", _act("C-004", "DISPATCHED"),
                               d, {"acts": []})
    obs = _obs(ctx)
    assert any(r.get("credit") == 1.0 and r.get("method_family") == FAMILY
               for r in obs), obs
