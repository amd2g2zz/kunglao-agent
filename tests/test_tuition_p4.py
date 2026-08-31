# -*- coding: utf-8 -*-
"""tests/test_tuition_p4.py — #823-P4 学习环收官测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import optimizer_core  # noqa: E402
import tuition_curve as tc  # noqa: E402
import tuition_refit as tr  # noqa: E402


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs" / "logs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n  - q1\n  - q2\n", encoding="utf-8")
    return ws


def _seed_pairs(ws, rows):
    """rows: (rho, z, duration_ms)；z=None 不计对。"""
    p = ws / "runs" / "logs" / "kunglao-2026-09-01.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for rho, z, dur in rows:
            f.write(json.dumps({
                "ts": "2026-09-01T00:00:00Z", "actor": "rho_verifier",
                "action": "rho_pair", "claim": None, "tool": None,
                "artifact": None, "duration_ms": dur, "exit": None,
                "detail": json.dumps({"rho": rho, "z": z}),
            }, ensure_ascii=False) + "\n")


def _good_pairs(n=12):
    return ([(0.9, 1.0, 100000.0)] * (n // 2)
            + [(0.1, 0.0, 400000.0)] * (n - n // 2))


def test_refit_direction_and_constitutional_proposal(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_pairs(ws, _good_pairs())
    r = tr.refit(ws)
    assert r["ok"] is True
    prop = r["proposal"]
    assert prop["schema_version"] == optimizer_core.SCHEMA_VERSION
    assert prop["kind"] == "theta_tuning"
    new = prop["theta_new"]
    assert new["platt_w"] > 0.5
    assert set(new) <= optimizer_core.PARAM_NAMES
    assert not (set(new) & optimizer_core.CONSTITUTIONAL_KEYS)


def test_refit_insufficient_pairs(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_pairs(ws, [(0.9, 1.0, 1000.0)] * 3)
    r = tr.refit(ws)
    assert r["ok"] is False
    assert r["reason"] == "insufficient_pairs"
    assert "proposal" not in r


def test_refit_writes_proposal_file(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_pairs(ws, _good_pairs())
    out = tmp_path / "prop.json"
    tr.refit(ws, out_path=out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["kind"] == "theta_tuning"
    assert loaded["theta_new"]["platt_w"] > 0.5


def test_curve_got_cheaper_and_insufficient(tmp_path):
    recs = [{"stratum": "s", "ordinal": i, "cost": 100.0, "passed": True}
            for i in range(3)]
    recs += [{"stratum": "s", "ordinal": i, "cost": 10.0, "passed": True}
             for i in range(3, 6)]
    assert tc.got_cheaper(recs, "s") is True
    recs_rev = [{"stratum": "s", "ordinal": i, "cost": c, "passed": True}
                for i, c in enumerate([10.0] * 3 + [100.0] * 3)]
    assert tc.got_cheaper(recs_rev, "s") is False
    assert tc.got_cheaper(recs_rev, "s", min_side=10) is None


def test_curve_shapes_and_summarize(tmp_path):
    recs = [{"stratum": "s", "ordinal": i, "cost": c, "passed": p}
            for i, (c, p) in enumerate([(100.0, True), (80.0, True),
                                        (60.0, False), (40.0, True)])]
    data = tc.curve(recs)
    pts = data["strata"]["s"]["points"]
    assert [p["ordinal"] for p in pts] == [0, 1, 2, 3]
    assert data["strata"]["s"]["pass_rate_overall"] == 0.75
    text = tc.summarize(data)
    assert "s" in text


def test_missions_from_ledger(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_pairs(ws, [(0.9, 1.0, 200000.0), (0.1, 0.0, 100000.0),
                     (0.8, None, 1.0)])
    recs = tc.missions_from_ledger(ws)
    assert len(recs) == 2
    assert recs[0]["cost"] == 200000.0
    assert recs[0]["passed"] is True
    assert recs[1]["passed"] is False


def test_cockpit_summary_shape(tmp_path):
    import mission_ledger
    ws = _mk_ws(tmp_path)
    mission_ledger.init(ws, {"primary_questions": ["q1", "q2"]})
    mission_ledger.update(ws)
    mission_ledger.value_m(ws)
    s = tc.cockpit_summary(ws)
    assert s["answered"] == 0
    assert s["eta_checkpoints"] is None
    assert isinstance(s["d_slope"], float)
    assert s["tuition"]["got_cheaper"] is None


def test_cockpit_eta_positive_when_progressing(tmp_path):
    import mission_ledger
    ws = _mk_ws(tmp_path)
    mission_ledger.init(ws, {"primary_questions": ["q1", "q2"]})
    led = mission_ledger.load(ws)
    led["mission"]["pqs"][0]["state"] = "answered"
    led["mission"]["pqs"][0]["coverage"] = 1.0
    mission_ledger._save(ws, led)
    led["mission"]["history"].append({"ts": "x", "v_m": 0.0})
    mission_ledger._save(ws, led)
    mission_ledger.value_m(ws)
    s = tc.cockpit_summary(ws)
    assert s["v"] == 1.0
    assert s["total_weight"] == 2.0
    assert s["d_slope"] > 0.0
    assert abs(s["eta_checkpoints"] - 1.0) < 0.1
