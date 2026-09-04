# -*- coding: utf-8 -*-
"""tests/test_vm_normalization_10.py — #10 V_m [0,1] normalization + per-round value density.

Two semantic defects fixed additively:

1. Normalization: value_m() gains ``v_norm`` = v_m / total PQ weight
   (guarded: no/zero weights -> 0.0) + ``a_t_norm`` = per-round delta of
   v_norm. Raw ``v_m``/``a_t``/``per_pq`` keys byte-identical (additive
   migration; issue #10 suggested-fix #1).
2. Unit: density is per SETTLEMENT ROUND (one value_m() call appends one
   history point == one round). ``d_slope_norm`` (cockpit + statusline) is
   the dimensionless per-round rate on the normalized history — invariant
   to wall-clock spacing of history timestamps. No wall-clock velocity is
   introduced (rho_checkpoint.eta_min / statusline tick cadence already
   own wall-clock; issue #10 suggested-fix #4).

Denominator = sum of PQ weights (ledger carries ``weight``, default 1.0;
unweighted workspaces -> len(pqs)). Precedent: rho_verifier._mission_level,
cockpit_summary.total_weight, statusline total_w — all already sum weights.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mission_ledger as ml  # noqa: E402
import tuition_curve  # noqa: E402
import statusline_snapshot as sls  # noqa: E402


def _mk_ws(tmp_path, pqs, claims, spec_extra=None):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    spec = {"primary_questions": pqs}
    if spec_extra:
        spec.update(spec_extra)
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True), encoding="utf-8")
    return ws


def _claim(cid, status="PROVEN", answers=None):
    c = {"id": cid, "status": status}
    if answers is not None:
        c["answers_question"] = answers
    return c


def _write_led(ws, pqs, hist):
    """Direct ledger write (hand-seeded shape, mirrors live schema)."""
    (ws / "runs" / "mission_ledger.yaml").write_text(
        yaml.safe_dump({"mission": {"pqs": pqs, "beta": 0.3,
                                    "history": hist, "feature_used": True}},
                       allow_unicode=True), encoding="utf-8")


def _pq(pid, state="unattempted", cov=0.0, weight=1.0):
    return {"id": pid, "question": pid, "state": state, "coverage": cov,
            "answered_by": [], "blocker": None, "wake": None,
            "weight": weight}


def _iso(base, offset_s):
    return (base + timedelta(seconds=offset_s)).isoformat()


# ---------- 1. v_norm present, in [0,1], == raw / total weight ----------

def test_v_norm_present_in_unit_range_equals_raw_over_total_weight(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "q1"}, {"id": "q2"}],
                [_claim("C-1", answers="q1")])
    ml.init(ws, None)
    ml.update(ws)
    v = ml.value_m(ws)
    assert "v_norm" in v
    assert 0.0 <= v["v_norm"] <= 1.0
    assert v["v_m"] == 1.0
    assert v["v_norm"] == pytest.approx(1.0 / 2.0)  # raw / max(pqs) unweighted


def test_v_norm_respects_pq_weights(tmp_path):
    ws = _mk_ws(tmp_path, [], [])
    _write_led(ws, [_pq("q1", "answered", 1.0, weight=3.0),
                    _pq("q2", weight=1.0)], [])
    v = ml.value_m(ws)
    assert v["v_m"] == 3.0
    assert v["v_norm"] == pytest.approx(3.0 / 4.0)  # weighted denominator


def test_v_norm_empty_no_pq_ledger_zero_no_div_by_zero(tmp_path):
    ws = _mk_ws(tmp_path, [], [])
    ml.init(ws, None)
    v = ml.value_m(ws)
    assert v["v_norm"] == 0.0  # no PQs -> 0.0, never ZeroDivisionError


def test_v_norm_zero_weight_ledger_zero_no_div_by_zero(tmp_path):
    ws = _mk_ws(tmp_path, [], [])
    _write_led(ws, [_pq("q1", "answered", 1.0, weight=0.0)], [])
    v = ml.value_m(ws)
    assert v["v_norm"] == 0.0  # total weight 0 -> guarded, not divided


def test_v_norm_all_answered_is_one(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "q1"}, {"id": "q2"}, {"id": "q3"}],
                [_claim("C-1", answers="q1"), _claim("C-2", answers="q2"),
                 _claim("C-3", answers="q3")])
    ml.init(ws, None)
    ml.update(ws)
    v = ml.value_m(ws)
    assert v["v_m"] == 3.0
    assert v["v_norm"] == 1.0


# ---------- 2. a_t_norm: per-round delta of v_norm ----------

def test_a_t_norm_is_per_round_delta_of_v_norm(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "q1"}, {"id": "q2"}], [])
    ml.init(ws, None)
    v1 = ml.value_m(ws)
    assert v1["a_t_norm"] == 0.0
    (Path(ws) / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [_claim("C-1", answers="q1")]},
                       allow_unicode=True), encoding="utf-8")
    ml.update(ws)
    v2 = ml.value_m(ws)
    assert v2["a_t"] == 1.0            # raw per-round delta unchanged
    assert v2["a_t_norm"] == pytest.approx(0.5)  # 1.0 / total weight 2.0
    v3 = ml.value_m(ws)
    assert v3["a_t_norm"] == 0.0       # flat round -> 0


# ---------- 3. history entries carry v_norm (additive) ----------

def test_history_entries_carry_v_norm_additive(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "q1"}, {"id": "q2"}],
                [_claim("C-1", answers="q1")])
    ml.init(ws, None)
    ml.value_m(ws)
    ml.update(ws)
    ml.value_m(ws)
    hist = ml.load(ws)["mission"]["history"]
    assert all("v_m" in h for h in hist)          # raw key intact
    assert all("v_norm" in h for h in hist)       # new normalized key
    assert hist[-1]["v_m"] == 1.0 and hist[-1]["v_norm"] == pytest.approx(0.5)


# ---------- 4. density is per-round, wall-clock irrelevant ----------

def _density_ws(tmp_path, base, gap_s):
    ws = tmp_path / f"ws_gap{gap_s}"
    (ws / "runs").mkdir(parents=True)
    # 4 PQs weight 1 -> total_w 4.0; history v_m [0, 1, 2] == v_norm [0, .25, .5]
    _write_led(ws, [_pq(f"q{i}") for i in range(4)],
               [{"ts": _iso(base, i * gap_s), "v_m": float(v),
                 "v_norm": v / 4.0}
                for i, v in enumerate([0.0, 1.0, 2.0])])
    return ws


def test_density_per_round_wall_clock_spacing_irrelevant(tmp_path):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fast = tuition_curve.cockpit_summary(_density_ws(tmp_path, base, 1))
    slow = tuition_curve.cockpit_summary(_density_ws(tmp_path, base, 3600))
    assert "d_slope_norm" in fast
    # same value deltas, wildly different wall-clock spacing -> same density
    assert fast["d_slope_norm"] == pytest.approx(slow["d_slope_norm"])
    assert fast["d_slope_norm"] == pytest.approx(0.25)  # per settlement round


def test_d_slope_norm_is_raw_slope_over_total_weight(tmp_path):
    ws = _density_ws(tmp_path, datetime(2026, 1, 1, tzinfo=timezone.utc), 60)
    cs = tuition_curve.cockpit_summary(ws)
    assert cs["d_slope"] == pytest.approx(1.0)            # raw unchanged
    assert cs["d_slope_norm"] == pytest.approx(cs["d_slope"] / 4.0)


def test_d_slope_norm_derives_norm_for_legacy_history(tmp_path):
    """Legacy history entries carry only v_m -> v_norm derived via total_w."""
    ws = tmp_path / "ws_legacy"
    (ws / "runs").mkdir(parents=True)
    _write_led(ws, [_pq(f"q{i}") for i in range(4)],
               [{"ts": "t0", "v_m": 0.0}, {"ts": "t1", "v_m": 2.0}])
    cs = tuition_curve.cockpit_summary(ws)
    assert cs["v_norm"] == pytest.approx(0.5)
    assert cs["d_slope_norm"] == pytest.approx(0.5)


def test_eta_checkpoints_scale_free_from_normalized_series(tmp_path):
    """eta = remaining normalized value / normalized slope (same numbers
    under stable weights; scale-free under repin weight changes)."""
    ws = _density_ws(tmp_path, datetime(2026, 1, 1, tzinfo=timezone.utc), 60)
    cs = tuition_curve.cockpit_summary(ws)
    assert cs["v_norm"] == pytest.approx(0.5)
    assert cs["eta_checkpoints"] == pytest.approx((1.0 - 0.5) / 0.25)


# ---------- 5. consumer migration: cockpit + statusline ----------

def test_cockpit_surfaces_v_norm_raw_v_unchanged(tmp_path):
    ws = _density_ws(tmp_path, datetime(2026, 1, 1, tzinfo=timezone.utc), 60)
    cs = tuition_curve.cockpit_summary(ws)
    assert cs["v"] == 2.0                    # raw display value unchanged
    assert cs["v_norm"] == pytest.approx(0.5)  # normalized alongside
    assert cs["total_weight"] == 4.0


def test_statusline_surfaces_v_norm(tmp_path):
    ws = tmp_path / "ws_sl"
    (ws / "runs").mkdir(parents=True)
    _write_led(ws, [_pq(f"q{i}") for i in range(4)],
               [{"ts": "t0", "v_m": 1.0, "v_norm": 0.25}])
    pq = sls._mission_state(ws)
    assert pq["v_m"] == 1.0                  # raw kept
    assert pq["v_norm"] == pytest.approx(0.25)
    assert "d_slope_norm" in pq
    snap = sls.build_snapshot(ws)
    assert snap["v_norm"] == pytest.approx(0.25)


# ---------- 6. regression: raw v_m byte-identical (additive) ----------

def test_raw_output_keys_and_values_unchanged(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "q1"}, {"id": "q2"}],
                [_claim("C-1", answers="q1")])
    ml.init(ws, None)
    ml.update(ws)
    v = ml.value_m(ws)
    # exact raw projection — byte-identical to the pre-#10 contract
    assert {k: v[k] for k in ("v_m", "prev_v_m", "a_t", "per_pq",
                              "answered", "blocked", "unattempted")} == {
        "v_m": 1.0, "prev_v_m": 0.0, "a_t": 1.0,
        "per_pq": {"q1": {"state": "answered", "contrib": 1.0},
                   "q2": {"state": "unattempted", "contrib": 0.0}},
        "answered": 1, "blocked": 0, "unattempted": 1}


def test_raw_blocked_contribution_unchanged(tmp_path):
    ws = _mk_ws(tmp_path, [], [])
    _write_led(ws, [_pq("q1", "blocked", 0.0), _pq("q2")], [])
    v = ml.value_m(ws)
    assert v["v_m"] == pytest.approx(0.3)    # beta * w, raw untouched
    assert v["v_norm"] == pytest.approx(0.3 / 2.0)


def test_raw_anti_stupid_zero_delta_unchanged(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "q1"}], [_claim("C-1")])  # no answers_question
    ml.init(ws, None)
    ml.update(ws)
    v = ml.value_m(ws)
    assert v["v_m"] == 0.0 and v["a_t"] == 0.0 and v["v_norm"] == 0.0


def test_emit_snapshot_detail_carries_v_norm_additive(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "q1"}], [_claim("C-1", answers="q1")])
    ml.init(ws, None)
    ml.update(ws)
    ml.emit_snapshot(ws, epoch=1, arm="N")
    rows = []
    for p in sorted((Path(ws) / "runs" / "logs").glob("kunglao-*.jsonl")):
        rows += [json.loads(line)
                 for line in p.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    snap = [r for r in rows if r["action"] == "mission_snapshot"]
    detail = json.loads(snap[0]["detail"])
    assert detail["v_m"] == 1.0 and detail["a_t"] == 1.0   # raw intact
    assert detail["v_norm"] == 1.0                          # additive
    assert detail["total_weight"] == 1.0
