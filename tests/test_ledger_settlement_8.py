# -*- coding: utf-8 -*-
"""tests/test_ledger_settlement_8.py — #8 mission_ledger settlement wiring.

Root cause (#8): mission_ledger.py ships a complete settlement API
(update / value_m) but NOTHING calls it at runtime — runs/mission_ledger.yaml
stays at init state, so V_m / coverage / d_slope are permanently stale and the
statusline renders empty metrics (0/0, V=0).

This suite pins the two mount points:
  1. rollup.run_rollup()  — terminal transitions settle PQ coverage
     (mission_ledger.update; idempotent; only _TERMINAL_STAMPED statuses
     stamp, fail-open: a settlement error never breaks the transition).
  2. heartbeat_tick cockpit block — update() every tick, value_m() gated to
     one history point per MISSION_SETTLE_MINUTES window (value_m appends
     history on EVERY call; un-gated 5-min ticks would spam the history that
     d_slope's last-5 window reads).
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest.mock
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mission_ledger as ml  # noqa: E402
import rollup as rollup_mod  # noqa: E402
import heartbeat_tick  # noqa: E402
import tuition_curve  # noqa: E402
from status_defs import TERMINAL  # noqa: E402


def _mk_ws(tmp_path, claims):
    """Workspace with a mapping-shape PQ spec (deterministic PQ-1 id),
    an initialized mission ledger, and a claim register."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"primary_questions": {"PQ-1": "which family?"}},
                       allow_unicode=True), encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True),
        encoding="utf-8")
    ml.init(ws)
    return ws


def _pq(led_or_ws):
    led = ml.load(led_or_ws) if isinstance(led_or_ws, Path) else led_or_ws
    return led["mission"]["pqs"][0]


def _vm_points(ws):
    led = ml.load(ws)
    return [h for h in (led["mission"].get("history") or []) if "v_m" in h]


def _rollup_rows(ws):
    p = ws / ".convergence_ledger.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip()]


PROVEN_CLAIM = {"id": "C-001", "status": "PROVEN", "answers_question": "PQ-1"}


# ---------- 1. terminal settlement (rollup mount) ----------

def test_rollup_to_proven_settles_pq(tmp_path):
    """RED on dev: nothing settles. After this fix, run_rollup to PROVEN maps
    the claim's answers_question -> PQ answered / coverage 1.0."""
    ws = _mk_ws(tmp_path, [PROVEN_CLAIM])
    res = rollup_mod.run_rollup(ws, "C-001", "PROVEN")
    assert res["fired"] is True
    pq = _pq(ws)
    assert pq["state"] == "answered"
    assert pq["coverage"] == 1.0
    assert pq["answered_by"] == ["C-001"]


def test_rollup_settlement_idempotent(tmp_path):
    """rollup twice -> PQ state unchanged, no duplicate answered_by entries,
    and history (value_m's exclusive append surface) untouched by update."""
    ws = _mk_ws(tmp_path, [PROVEN_CLAIM])
    rollup_mod.run_rollup(ws, "C-001", "PROVEN")
    res2 = rollup_mod.run_rollup(ws, "C-001", "PROVEN")
    assert res2["fired"] is False
    assert res2["reason"] == "already-rolled-up"
    ml.update(ws)  # even a direct re-settle must be a no-op
    pq = _pq(ws)
    assert pq["state"] == "answered"
    assert pq["answered_by"] == ["C-001"]
    assert _vm_points(ws) == []  # update never appends history


def test_rollup_deferred_does_not_stamp_pq(tmp_path):
    """_TERMINAL_STAMPED = {PROVEN}: non-PROVEN terminal closures fire the
    rollup (and settlement runs) but must NOT stamp PQ coverage."""
    assert "DEFERRED" in TERMINAL
    ws = _mk_ws(tmp_path, [dict(PROVEN_CLAIM, status="DEFERRED")])
    res = rollup_mod.run_rollup(ws, "C-001", "DEFERRED")
    assert res["fired"] is True
    assert res["mission_settlement"] == "ok"
    pq = _pq(ws)
    assert pq["state"] == "unattempted"
    assert pq["coverage"] == 0.0
    assert pq["answered_by"] == []


def test_rollup_without_ledger_unchanged(tmp_path):
    """Old workspaces have no runs/mission_ledger.yaml — the terminal
    transition must fire exactly as before (#8 must not regress #524)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [PROVEN_CLAIM]}, allow_unicode=True),
        encoding="utf-8")
    res = rollup_mod.run_rollup(ws, "C-001", "PROVEN")
    assert res["fired"] is True
    assert res["mission_settlement"] == "skipped:no-ledger"
    assert any(r.get("action") == "rollup" for r in _rollup_rows(ws))


def test_rollup_settlement_fail_open(tmp_path):
    """A settlement crash is captured as a mission_settlement error note on
    the result AND the ledger row — the terminal transition still fires."""
    ws = _mk_ws(tmp_path, [PROVEN_CLAIM])
    with unittest.mock.patch.object(ml, "update",
                                    side_effect=RuntimeError("boom")):
        res = rollup_mod.run_rollup(ws, "C-001", "PROVEN")
    assert res["fired"] is True  # transition NOT broken
    assert str(res["mission_settlement"]).startswith("error")
    rows = [r for r in _rollup_rows(ws)
            if r.get("type") == "operator_action" and r.get("action") == "rollup"]
    assert rows and str(rows[-1]["mission_settlement"]).startswith("error")


# ---------- 2. heartbeat settlement (cadence mount) ----------

def _tick(ws):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "heartbeat_tick.py"), str(ws)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180)


def _cockpit_samples(ws):
    rows = [json.loads(ln)
            for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
            for ln in p.read_text(encoding="utf-8",
                                  errors="replace").splitlines() if ln.strip()]
    return [r for r in rows if r.get("action") == "cockpit_sample"]


def test_tick_settles_and_appends_history_once(tmp_path):
    """One tick: PROVEN claim settles the PQ AND value_m appends exactly one
    V_m history point; an immediate second tick must NOT append another
    (MISSION_SETTLE_MINUTES cadence gate)."""
    ws = _mk_ws(tmp_path, [PROVEN_CLAIM])
    r1 = _tick(ws)
    assert r1.returncode in (0, 1), r1.stderr
    assert len(_vm_points(ws)) == 1  # history grew by exactly 1
    pq = _pq(ws)
    assert pq["state"] == "answered" and pq["coverage"] == 1.0
    samples = _cockpit_samples(ws)
    assert samples, "cockpit_sample must still land"
    d = samples[-1]["detail"]
    if isinstance(d, str):
        d = json.loads(d)
    assert d["v"] == 1.0 and d["answered"] == 1  # settled values surface

    r2 = _tick(ws)  # immediate second tick
    assert r2.returncode in (0, 1), r2.stderr
    assert len(_vm_points(ws)) == 1  # gate held: no second point


def test_history_gate_unit():
    """_mission_history_due: empty history -> due; fresh ts -> not due;
    undated newest entry -> not due (unknown cadence, zero-noise);
    corrupt ledger -> not due (fail-open for the tick)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "task_spec.yaml").write_text(
            yaml.safe_dump({"primary_questions": {"PQ-1": "q"}}),
            encoding="utf-8")
        ml.init(ws)
        assert heartbeat_tick._mission_history_due(ws) is True  # empty history
        ml.value_m(ws)  # appends a dated point
        assert heartbeat_tick._mission_history_due(ws) is False  # fresh
        # undated newest entry (hand-seeded fixture shape): unknown cadence
        led = ml.load(ws)
        led["mission"]["history"].append({"v_m": 0.75})
        ml._save(ws, led)
        assert heartbeat_tick._mission_history_due(ws) is False
        # corrupt ledger: never break the tick
        (ws / "runs" / "mission_ledger.yaml").write_text(
            "\t: : [broken", encoding="utf-8")
        assert heartbeat_tick._mission_history_due(ws) is False


def test_tick_settlement_fail_open(tmp_path):
    """A settlement crash inside the tick must not fail the tick: main()
    completes and the report still lands."""
    ws = _mk_ws(tmp_path, [PROVEN_CLAIM])
    with unittest.mock.patch.object(ml, "update",
                                    side_effect=RuntimeError("boom")):
        rc = heartbeat_tick.main([str(ws)])  # must not raise
    assert rc in (0, 1, 2)
    assert (ws / "runs" / ".heartbeat-tick.json").exists()


# ---------- 3. cockpit regression ----------

def test_cockpit_summary_unchanged_for_settled_ledger(tmp_path):
    """Settlement wiring does not change the cockpit_summary contract: same
    keys, and a settled ledger surfaces its real V_m (not 0)."""
    ws = _mk_ws(tmp_path, [PROVEN_CLAIM])
    ml.update(ws)
    ml.value_m(ws)
    out = tuition_curve.cockpit_summary(ws)
    for key in ("v", "d_slope", "eta_checkpoints", "total_weight", "answered",
                "blocked", "unattempted", "cost", "burn", "tuition"):
        assert key in out, key
    assert out["v"] == 1.0
    assert out["answered"] == 1 and out["unattempted"] == 0
