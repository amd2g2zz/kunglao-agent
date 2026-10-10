# -*- coding: utf-8 -*-
"""tests/test_factor_vector_12.py — per-round V factor-vector persistence.

The 2026-09-04 operator ruling: mission_ledger.mission.history
exists but nothing appends per-round. After the settlement each tick must
append the FULL factor vector, not just v_m:

    {ts, round: N, v_norm, oracle_pass, checks_impl,
     pq_cov: {pq: coverage}, events: {dispatch, verify, confirmed_with_diff,
     toss}, cost_tokens, cost_rounds}

Additive discipline (the normalization/reconciliation/progress
precedents): the legacy history keys
(ts, v_m, v_norm, v_oracle, v_oracle_norm) are untouched — byte-identical
values, new keys appended after.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import mission_ledger as ml  # noqa: E402
import signals_stream as ss  # noqa: E402

TASK_SPEC = {
    "primary_questions": [
        {"id": "q1", "question": "first"},
        {"id": "q2", "question": "second"},
    ],
}

VECTOR_KEYS = ("round", "v_norm", "oracle_pass", "checks_impl", "pq_cov",
               "events", "cost_tokens", "cost_rounds")
LEGACY_KEYS = ("ts", "v_m", "v_norm", "v_oracle", "v_oracle_norm")
EVENT_KEYS = ("dispatch", "verify", "confirmed_with_diff", "toss")


@pytest.fixture
def ws(tmp_path):
    """Workspace with an initialized mission ledger (2 PQs)."""
    ml.init(tmp_path, TASK_SPEC)
    return tmp_path


def test_value_m_appends_full_factor_shape(ws):
    v = ml.value_m(ws)
    assert v["v_norm"] == 0.0  # nothing settled — sanity
    led = ml.load(ws)
    hist = led["mission"]["history"]
    assert len(hist) == 1
    row = hist[-1]
    for k in VECTOR_KEYS:
        assert k in row, f"factor vector missing {k!r}"
    for k in LEGACY_KEYS:
        assert k in row, f"legacy key {k!r} dropped (additive discipline)"
    assert set(row["events"]) == set(EVENT_KEYS)
    assert all(isinstance(n, int) and n >= 0 for n in row["events"].values())
    assert row["pq_cov"] == {"q1": 0.0, "q2": 0.0}
    assert row["round"] == 0  # no convergence ledger -> round 0
    assert row["cost_rounds"] == 1
    assert row["cost_tokens"] == 0.0  # no cost_events.jsonl


def test_each_tick_appends_one_row(ws):
    ml.value_m(ws)
    ml.value_m(ws)
    hist = ml.load(ws)["mission"]["history"]
    assert len(hist) == 2
    assert all("round" in h for h in hist)


def test_oracle_faces_land_in_vector(ws, monkeypatch):
    """oracle_pass = armed cases green; checks_impl = armed cases declared
    (implemented, not yet passing — the D_t w_impl face)."""
    oracle_dir = ws / "oracle" / "cases"
    oracle_dir.mkdir(parents=True)
    (oracle_dir / "case-1.yaml").write_text(
        "id: case-1\ntarget_pq: q1\n", encoding="utf-8")
    (oracle_dir / "case-2.yaml").write_text(
        "id: case-2\ntarget_pq: q2\n", encoding="utf-8")
    (ws / "runs").mkdir(exist_ok=True)
    (ws / "runs" / "oracle-status.json").write_text(
        '{"cases": {"case-1": {"status": "pass"}, '
        '"case-2": {"status": "fail"}}}',
        encoding="utf-8")
    ml.value_m(ws)
    row = ml.load(ws)["mission"]["history"][-1]
    assert row["checks_impl"] == 2
    assert row["oracle_pass"] == 1


def test_events_window_counts_only_new_signals(ws):
    """The events block windows the signal stream by append-order cursor
    (signals_rows) — a second tick counts only rows landed since the
    previous vector (machine-independent, no wall clock)."""
    ss.append(ws, ss.KIND_DISPATCH, claim="C-1")
    ss.append(ws, ss.KIND_DELIVER, claim="C-1")
    ml.value_m(ws)
    row1 = ml.load(ws)["mission"]["history"][-1]
    assert row1["events"]["dispatch"] == 1

    ss.append(ws, ss.KIND_DISPATCH, claim="C-2")  # never delivered -> toss
    ml.value_m(ws)
    row2 = ml.load(ws)["mission"]["history"][-1]
    assert row2["events"]["dispatch"] == 1  # only the NEW dispatch
    assert row2["events"]["toss"] == 1
    assert row2["signals_rows"] == 3


def test_pq_cov_reflects_answered_coverage(ws):
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: PROVEN\n  answers_question: q1\n",
        encoding="utf-8")
    ml.update(ws)
    ml.value_m(ws)
    row = ml.load(ws)["mission"]["history"][-1]
    assert row["pq_cov"] == {"q1": 1.0, "q2": 0.0}
    assert row["v_norm"] == 0.5


def test_vector_survives_dirty_signal_stream(ws):
    (ws / "runs").mkdir(exist_ok=True)
    (ws / "runs" / "signals.jsonl").write_text(
        'garbage line\n{"kind": "dispatch", "claim": "C-1"}\n',
        encoding="utf-8")
    ml.value_m(ws)  # fail-open: a dirty stream never breaks settlement
    row = ml.load(ws)["mission"]["history"][-1]
    assert row["events"]["dispatch"] == 1


def test_cost_tokens_reads_cost_events(ws):
    (ws / "runs").mkdir(exist_ok=True)
    (ws / "cost_events.jsonl").write_text(
        '{"amount": 1.5}\n{"amount": 2.5}\n', encoding="utf-8")
    ml.value_m(ws)
    row = ml.load(ws)["mission"]["history"][-1]
    assert row["cost_tokens"] == 4.0
