# -*- coding: utf-8 -*-
"""tests/test_value_reconciliation_133.py — #133 value-currency reconciliation.

Two value currencies never reconciled. v_m (mission_ledger.value_m) measures
PLAN progress: a PQ marked "answered" contributed full w*coverage regardless
of acceptance. The oracle's red/green face (runs/oracle-status.json, schema
oracle-status/1, written by oracle_runner.write_status) measures ACCEPTANCE
fact. They could diverge: narrative-answered PQs maxed v_m while every armed
oracle case was red — fake progress invisible to the value model, and
mission_stall's reference frame (v_m history) agent-influenceable in exactly
the way the drift audit flagged.

#133 closes the value layer (the wiring layer closed in #108):

1. Coverage credit gate: an answered PQ's contribution requires its armed
   oracle cases green. The PQ->case linkage is the SAME one the #107
   Thompson case face consumes (oracle/cases/*.yaml `target_pq`, read via
   priority_ratio._load_oracle_cases), so the value gate and the ranker can
   never disagree about which cases belong to a PQ. Green -> full w*coverage
   (unchanged); any armed case not green (fail / pending / not yet judged /
   unreadable verdict file) -> damped to the blocked-tier credit (beta*w) —
   the PQ is "claimed but unproven", priced accordingly. Answered PQs with
   NO armed cases keep current behavior (nothing to reconcile against —
   Phase 0/1 tasks).
2. Aligned projection: v_oracle / v_oracle_norm credit ONLY oracle-green
   PQs (answered AND all-armed-cases-green). The v_norm - v_oracle gap is a
   standing fake-progress indicator: v_norm high + v_oracle low = narrative
   inflation. Additive everywhere: raw v_m math, raw return keys, and the
   raw history fields are untouched (the module's #10/#14 additive
   convention, byte-identical guards in test_vm_normalization_10).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import mission_ledger as ml  # noqa: E402
import oracle_runner as orun  # noqa: E402  (real status-face producer)

BETA = ml.BETA  # 0.3 — the blocked-tier credit the damped tier prices at


# ------------------------------------------------------------------ fixtures

def _pq(pid, state="answered", cov=1.0, weight=1.0):
    return {"id": pid, "question": pid, "state": state, "coverage": cov,
            "answered_by": [], "blocker": None, "wake": None,
            "weight": weight}


def _write_led(ws, pqs):
    """Hand-seeded ledger (mirrors the live schema; direct write)."""
    (Path(ws) / "runs" / "mission_ledger.yaml").write_text(
        yaml.safe_dump({"mission": {"pqs": pqs, "beta": BETA,
                                    "history": [], "feature_used": True}},
                       allow_unicode=True), encoding="utf-8")


def _write_case(ws, case_id, target_pq):
    """One armed oracle case (oracle/cases/*.yaml `target_pq` linkage)."""
    cdir = Path(ws) / "oracle" / "cases"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / f"{case_id.lower()}.yaml").write_text(
        yaml.safe_dump({"id": case_id, "target_pq": target_pq},
                       allow_unicode=True), encoding="utf-8")


def _write_status(ws, statuses):
    """Write runs/oracle-status.json through the REAL producer face
    (oracle_runner.write_status): statuses = {case_id: pass|fail|pending}."""
    report = {
        "cases": {cid: {"status": st, "pending_entries": 0,
                        "instrumented": True}
                  for cid, st in statuses.items()},
        "counts": {"red": sum(1 for s in statuses.values() if s == "fail"),
                   "green": sum(1 for s in statuses.values()
                                if s == "pass"),
                   "pending": sum(1 for s in statuses.values()
                                  if s == "pending")},
        "mutation": None,
    }
    orun.write_status(ws, report)


def _mk_ws(tmp_path, name, pqs, cases=(), statuses=None):
    """Workspace with a seeded ledger, optional armed cases, optional
    runner verdicts. cases: [(case_id, target_pq)]; statuses: {cid: st}."""
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    _write_led(ws, pqs)
    for case_id, target_pq in cases:
        _write_case(ws, case_id, target_pq)
    if statuses is not None:
        _write_status(ws, statuses)
    return ws


# ------------------------------------- 1. the coverage credit gate (v_m)

def test_answered_with_red_case_damps_to_blocked_tier(tmp_path):
    """Narrative-answered + red armed case: full coverage credit DENIED,
    the blocked-tier credit (beta*w) applies instead."""
    ws = _mk_ws(tmp_path, "ws_red", [_pq("q1")],
                cases=[("CASE-1", "q1")], statuses={"CASE-1": "fail"})
    v = ml.value_m(ws)
    assert v["v_m"] == pytest.approx(BETA)  # damped, NOT 1.0
    assert v["per_pq"]["q1"]["contrib"] == pytest.approx(BETA)


def test_answered_with_green_case_keeps_full_credit(tmp_path):
    """Every armed case green: full w*coverage — unchanged."""
    ws = _mk_ws(tmp_path, "ws_green", [_pq("q1")],
                cases=[("CASE-1", "q1")], statuses={"CASE-1": "pass"})
    v = ml.value_m(ws)
    assert v["v_m"] == pytest.approx(1.0)
    assert v["per_pq"]["q1"]["contrib"] == pytest.approx(1.0)


def test_answered_with_no_armed_case_unchanged(tmp_path):
    """No armed cases on the PQ -> nothing to reconcile against: current
    behavior (full credit) preserved — the Phase 0/1 exemption."""
    ws = _mk_ws(tmp_path, "ws_nocase", [_pq("q1")],
                cases=[("CASE-OTHER", "q2")], statuses={"CASE-OTHER": "fail"})
    v = ml.value_m(ws)
    assert v["v_m"] == pytest.approx(1.0)  # CASE-OTHER targets q2, not q1


def test_answered_with_pending_case_damps(tmp_path):
    """Pending on live instrumentation is not green ("unknown" is never
    "pass", #108 A) -> damped. An uninstrumented pending is damped too:
    the gate requires green, and a runner that never observed anything
    proved nothing."""
    ws_pend = _mk_ws(tmp_path, "ws_pend", [_pq("q1")],
                     cases=[("CASE-1", "q1")],
                     statuses={"CASE-1": "pending"})
    assert ml.value_m(ws_pend)["v_m"] == pytest.approx(BETA)

    # uninstrumented pending: rewrite the verdict with instrumented=False
    ws_raw = _mk_ws(tmp_path, "ws_pend_raw", [_pq("q1")],
                    cases=[("CASE-1", "q1")])
    (ws_raw / "runs" / "oracle-status.json").write_text(
        '{"schema": "oracle-status/1", "cases": {"CASE-1": {"status": '
        '"pending", "pending_entries": 2, "instrumented": false}}, '
        '"counts": {"red": 0, "green": 0, "pending": 1}}\n',
        encoding="utf-8")
    assert ml.value_m(ws_raw)["v_m"] == pytest.approx(BETA)


def test_answered_mixed_cases_any_non_green_damps(tmp_path):
    """ALL armed cases must be green: one green + one red -> damped."""
    ws = _mk_ws(tmp_path, "ws_mixed", [_pq("q1")],
                cases=[("CASE-1", "q1"), ("CASE-2", "q1")],
                statuses={"CASE-1": "pass", "CASE-2": "fail"})
    assert ml.value_m(ws)["v_m"] == pytest.approx(BETA)


def test_armed_case_missing_from_status_damps(tmp_path):
    """A case in the armed set with no verdict yet (added after the last
    runner run) is unproven, not green -> damped."""
    ws = _mk_ws(tmp_path, "ws_unjudged", [_pq("q1")],
                cases=[("CASE-1", "q1"), ("CASE-2", "q1")],
                statuses={"CASE-1": "pass"})  # CASE-2 never judged
    assert ml.value_m(ws)["v_m"] == pytest.approx(BETA)


def test_unreadable_status_damps_fail_closed(tmp_path):
    """A corrupt verdict file never grants full credit (the
    contradiction-gate posture: corrupt acceptance evidence cannot silently
    re-enable the value it is supposed to check)."""
    ws = _mk_ws(tmp_path, "ws_corrupt", [_pq("q1")],
                cases=[("CASE-1", "q1")])
    (ws / "runs" / "oracle-status.json").write_text("{not json",)
    assert ml.value_m(ws)["v_m"] == pytest.approx(BETA)


def test_case_without_target_pq_belongs_to_no_pq(tmp_path):
    """A case file with no target_pq is linked to nothing: the answered PQ
    keeps current behavior (the Thompson reader skips empty target_pq)."""
    ws = _mk_ws(tmp_path, "ws_unlinked", [_pq("q1")],
                cases=[("CASE-1", "")], statuses={"CASE-1": "fail"})
    assert ml.value_m(ws)["v_m"] == pytest.approx(1.0)


# ------------------------------------- 2. the aligned v_oracle projection

def test_v_oracle_credits_only_oracle_green_pqs(tmp_path):
    """Inflation fixture: q1 answered+green-armed, q2 answered+red-armed.
    v_m keeps the damped-plan currency (1.0 + beta), v_oracle credits only
    the oracle-green PQ (1.0) — the gap surfaces the narrative half."""
    ws = _mk_ws(tmp_path, "ws_gap",
                [_pq("q1"), _pq("q2")],
                cases=[("CASE-1", "q1"), ("CASE-2", "q2")],
                statuses={"CASE-1": "pass", "CASE-2": "fail"})
    v = ml.value_m(ws)
    assert v["v_m"] == pytest.approx(1.0 + BETA)      # plan currency
    assert v["v_norm"] == pytest.approx((1.0 + BETA) / 2.0)
    assert "v_oracle" in v and "v_oracle_norm" in v
    assert v["v_oracle"] == pytest.approx(1.0)        # green PQ only
    assert v["v_oracle_norm"] == pytest.approx(0.5)
    assert v["v_oracle"] < v["v_m"]                   # the gap exists
    assert v["v_oracle_norm"] < v["v_norm"]


def test_v_oracle_all_green_equals_v_m(tmp_path):
    """Every answered PQ oracle-green: the two currencies coincide."""
    ws = _mk_ws(tmp_path, "ws_allgreen",
                [_pq("q1"), _pq("q2")],
                cases=[("CASE-1", "q1"), ("CASE-2", "q2")],
                statuses={"CASE-1": "pass", "CASE-2": "pass"})
    v = ml.value_m(ws)
    assert v["v_oracle"] == pytest.approx(v["v_m"])
    assert v["v_oracle_norm"] == pytest.approx(v["v_norm"])


def test_v_oracle_unarmed_answered_pq_not_credited(tmp_path):
    """An answered PQ with NO armed cases keeps full v_m (nothing to
    reconcile against) but earns NO oracle credit: v_norm full +
    v_oracle zero IS the standing inflation marker."""
    ws = _mk_ws(tmp_path, "ws_unarmed", [_pq("q1")])
    v = ml.value_m(ws)
    assert v["v_m"] == pytest.approx(1.0)    # plan face unchanged
    assert v["v_oracle"] == pytest.approx(0.0)  # acceptance face: unproven
    assert v["v_oracle_norm"] == pytest.approx(0.0)


def test_v_oracle_blocked_and_unattempted_contribute_zero(tmp_path):
    """Only answered-and-green PQs enter v_oracle; blocked keeps its
    beta*w in v_m and nothing in v_oracle."""
    ws = _mk_ws(tmp_path, "ws_tiers",
                [_pq("q1", "blocked", 0.0), _pq("q2", "unattempted", 0.0),
                 _pq("q3")],
                cases=[("CASE-3", "q3")], statuses={"CASE-3": "pass"})
    v = ml.value_m(ws)
    assert v["v_m"] == pytest.approx(BETA + 1.0)
    assert v["v_oracle"] == pytest.approx(1.0)  # only q3 is oracle-green


# ------------------------------------- 3. additive history + raw preservation

def test_history_rows_carry_v_oracle_additive_raw_intact(tmp_path):
    """History rows gain v_oracle / v_oracle_norm ADDITIVELY: the raw
    {ts, v_m, v_norm} shape is untouched (the #10 guard's intent)."""
    ws = _mk_ws(tmp_path, "ws_hist",
                [_pq("q1"), _pq("q2")],
                cases=[("CASE-1", "q1"), ("CASE-2", "q2")],
                statuses={"CASE-1": "pass", "CASE-2": "fail"})
    ml.value_m(ws)
    hist = ml.load(ws)["mission"]["history"]
    assert len(hist) == 1
    row = hist[-1]
    assert "ts" in row and "v_m" in row and "v_norm" in row  # raw keys
    assert row["v_m"] == pytest.approx(1.0 + BETA)
    assert row["v_norm"] == pytest.approx((1.0 + BETA) / 2.0)
    assert row["v_oracle"] == pytest.approx(1.0)             # additive
    assert row["v_oracle_norm"] == pytest.approx(0.5)


def test_no_oracle_artifacts_behavior_identical_to_pre_133(tmp_path):
    """A workspace with no oracle/ dir and no status file: value_m output
    is byte-identical to the pre-#133 contract (raw face preserved)."""
    ws = _mk_ws(tmp_path, "ws_plain", [_pq("q1"), _pq("q2", "unattempted",
                                                       0.0)])
    v = ml.value_m(ws)
    assert {k: v[k] for k in ("v_m", "prev_v_m", "a_t", "per_pq",
                              "answered", "blocked", "unattempted")} == {
        "v_m": 1.0, "prev_v_m": 0.0, "a_t": 1.0,
        "per_pq": {"q1": {"state": "answered", "contrib": 1.0},
                   "q2": {"state": "unattempted", "contrib": 0.0}},
        "answered": 1, "blocked": 0, "unattempted": 1}
    assert v["v_oracle"] == pytest.approx(0.0)
    assert v["v_oracle_norm"] == pytest.approx(0.0)


def test_weights_respected_in_both_currencies(tmp_path):
    """The gate and the projection are weighted identically to the #10
    normalization: damped and credited amounts scale with the PQ weight."""
    ws = _mk_ws(tmp_path, "ws_weights",
                [_pq("q1", weight=3.0), _pq("q2", weight=1.0)],
                cases=[("CASE-1", "q1"), ("CASE-2", "q2")],
                statuses={"CASE-1": "fail", "CASE-2": "pass"})
    v = ml.value_m(ws)
    assert v["v_m"] == pytest.approx(BETA * 3.0 + 1.0 * 1.0)
    assert v["v_oracle"] == pytest.approx(1.0)  # only q2 (green) credited
