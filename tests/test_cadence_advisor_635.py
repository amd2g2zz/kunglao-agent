# -*- coding: utf-8 -*-
"""tests/test_cadence_advisor_635.py — the #635 adaptive registration
advisor + loop holds: the 3-tick evaluation cycle, busy/quiet stepping
within [5,25], the advice artifact, the kind=cadence RL signal emission,
and the hold surface the situation brief reads. Synthetic fixtures."""
from __future__ import annotations

import json

import yaml


def _ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-1", "status": "OPEN"}]}),
        encoding="utf-8")
    return ws


def _worker(ws, wid="C001"):
    (ws / "runs" / f"worker-status-{wid}.md").write_text(
        f"[2026-10-10T00:00Z] step: x | status: in-progress\n",
        encoding="utf-8")


def test_three_tick_cycle_then_quiet_steps_up(tmp_path):
    import cadence_advisor as ca
    ws = _ws(tmp_path)
    o1 = ca.advise(ws)
    o2 = ca.advise(ws)
    assert o1["ticks_since_eval"] == 1 and o2["ticks_since_eval"] == 2
    assert o1["evaluation_due"] is False  # holds until the cycle is due
    o3 = ca.advise(ws)
    assert o3["ticks_since_eval"] == 0
    assert o3["recommended_interval_min"] == 10  # quiet: 5 -> +5
    assert o3["evaluation_due"] is True


def test_busy_worker_steps_down_to_floor(tmp_path):
    import cadence_advisor as ca
    ws = _ws(tmp_path)
    _worker(ws)
    for _ in range(3):
        out = ca.advise(ws)
    assert "busy" in out["reason"]
    assert out["recommended_interval_min"] == 5  # floor clamp


def test_ceiling_clamp(tmp_path):
    import cadence_advisor as ca
    ws = _ws(tmp_path)
    (ws / "runs" / ".heartbeat.json").write_text(
        json.dumps({"interval_min": 25}), encoding="utf-8")
    for _ in range(3):
        out = ca.advise(ws)
    assert out["recommended_interval_min"] == 25


def test_own_cadence_signal_never_reads_back_as_activity(tmp_path):
    """The advisor's own kind=cadence row must not flip the next cycle to
    busy (self-feedback guard)."""
    import cadence_advisor as ca
    ws = _ws(tmp_path)
    for _ in range(3):
        ca.advise(ws)  # emits the cadence row
    assert ca.recent_signal(ws) is False


def test_advice_artifact_and_signal_row(tmp_path):
    import cadence_advisor as ca
    ws = _ws(tmp_path)
    for _ in range(3):
        ca.advise(ws)
    adv = json.loads((ws / "runs" / ".cadence-advice.json").read_text(
        encoding="utf-8"))
    assert adv["recommended_interval_min"] == 10 and adv["state_hash"]
    rows = [json.loads(ln) for ln in
            (ws / "runs" / "signals.jsonl").read_text(
                encoding="utf-8").splitlines()]
    assert rows and rows[-1]["kind"] == "cadence"
    assert rows[-1]["interval"] == 10


def test_holds_surface_and_hash_drift(tmp_path):
    import cadence_advisor as ca
    import loop_holds as lh
    ws = _ws(tmp_path)
    h0 = ca.state_hash(ws)
    assert lh.main([str(ws), "add", "do not auto-resume T2"]) == 0
    assert ca.holds(ws) == ["do not auto-resume T2"]
    assert ca.state_hash(ws) != h0
    assert lh.main([str(ws), "list"]) == 0
    assert lh.main([str(ws), "clear", "--all"]) == 0
    assert ca.holds(ws) == []
