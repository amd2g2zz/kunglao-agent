# -*- coding: utf-8 -*-
"""A2 (#823): rho_checkpoint — ρ progress signal + V/D/ETA first-order terms.

Shadow posture: signal-only, decision table untouched. All pieces are
mechanical except the verifier call itself, which is stubbed here the way
the experiment runner will stub it (JSON response contract).
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rho_checkpoint as rc
import value_config


# ---------- V = σ(w·x+b) ----------

def test_sigmoid_extremes():
    assert rc.sigmoid(0.0) == pytest.approx(0.5)
    assert rc.sigmoid(20.0) == pytest.approx(1.0, abs=1e-6)
    assert rc.sigmoid(-20.0) == pytest.approx(0.0, abs=1e-6)


def test_fit_platt_separates_pairs():
    pairs = [{"score": s, "outcome": 1 if s > 5 else 0}
             for s in (1.0, 2.0, 3.0, 7.0, 8.0, 9.0)]
    w, b = rc.fit_platt(pairs)
    assert rc.sigmoid(w * 9.0 + b) > 0.8
    assert rc.sigmoid(w * 1.0 + b) < 0.2


# ---------- V prior fallback chain ----------

PRIORS = {"schema": "kunglao-value-priors/1", "buckets": {
    "deep|ghidra": {"n": 12, "p_complete": 0.75},
    "deep|*": {"n": 30, "p_complete": 0.5},
    "*|*": {"n": 100, "p_complete": 0.4},
}}


def test_v_fallback_chain():
    v, source, band = rc.v_from_priors(PRIORS, "deep", "ghidra")
    assert (v, source) == (0.75, "feature_bucket")
    v, source, band = rc.v_from_priors(PRIORS, "deep", "frida")
    assert (v, source) == (0.5, "depth_bucket")
    v, source, band = rc.v_from_priors(PRIORS, "standard", "frida")
    assert (v, source) == (0.4, "global")


def test_v_uninformative_when_no_priors():
    v, source, band = rc.v_from_priors({}, "deep", "ghidra")
    assert (v, source) == (0.5, "uninformative")
    assert band == pytest.approx(0.5)  # widest error bar


def test_v_band_narrows_with_n():
    _, _, band_small = rc.v_from_priors(
        {"buckets": {"d|f": {"n": 2, "p_complete": 0.5}}}, "d", "f")
    _, _, band_big = rc.v_from_priors(
        {"buckets": {"d|f": {"n": 50, "p_complete": 0.5}}}, "d", "f")
    assert band_big < band_small


# ---------- ρ progress signal ----------

def test_rho_from_distribution_expectation():
    # scoring-token / verbal distribution over grades → expectation
    rho = rc.rho_from_distribution([(0.0, 0.2), (0.5, 0.5), (1.0, 0.3)])
    assert rho == pytest.approx(0.55)


def test_rho_sequence_monotonic_on_progress():
    progress = [{"PQ1": {"grade": g}} for g in (0.1, 0.3, 0.5, 0.9)]
    idle = [{"PQ1": {"grade": 0.5}} for _ in range(4)]
    seq = rc.rho_sequence(progress)
    assert seq == sorted(seq)
    assert max(rc.rho_sequence(idle)) - min(rc.rho_sequence(idle)) < 1e-9


def test_parse_verifier_response():
    good = json.dumps({"per_pq": [{"pq_id": "PQ1", "grade": 0.7},
                                  {"pq_id": "PQ2", "grade": 0.2}]})
    per_pq = rc.parse_verifier_response(good)
    assert per_pq == {"PQ1": {"grade": 0.7}, "PQ2": {"grade": 0.2}}
    assert rc.parse_verifier_response("not json") is None


# ---------- D(t) triggers + ETA ----------

def test_update_difficulty_triggers():
    d0 = rc.update_difficulty(None, "t0", 0.6)
    assert d0 == pytest.approx(0.6)
    assert rc.update_difficulty(d0, "capability_flip", 0.2) == pytest.approx(0.4)
    assert rc.update_difficulty(d0, "wear", 0.3) == pytest.approx(0.9)
    assert rc.update_difficulty(0.95, "wear", 0.3) == 1.0  # clamped
    assert rc.update_difficulty(0.05, "capability_flip", 0.3) == 0.0


def test_eta_minutes():
    assert rc.eta_minutes(120, 0.5) == pytest.approx(60.0)


# ---------- decide() attach (flag-gated) ----------

def _mk_ws(ws: Path):
    (ws / "runs" / "logs").mkdir(parents=True)
    (ws / "runs" / "value-priors.yaml").write_text(
        yaml.safe_dump(PRIORS), encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"depth": "deep", "time_budget_minutes": 120}), encoding="utf-8")
    with (ws / "runs" / "logs" / "kunglao-2026-08-28.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-08-28T00:00:00Z", "actor": "worker",
                            "action": "tool_call", "claim": None,
                            "tool": "mcp__ghidra__import_file", "artifact": None,
                            "duration_ms": None, "exit": None, "detail": None}) + "\n")
    return ws


def test_attach_signals_flag_on_emits(tmp_path, monkeypatch):
    monkeypatch.setenv(value_config.ENV_NAME, "1")
    ws = _mk_ws(tmp_path / "ws")
    decision = {"decision": "DISPATCH"}
    out = rc.attach_signals(ws, decision)
    sig = out["value_signals"]
    assert sig["v"] == pytest.approx(0.75)
    assert sig["source"] == "feature_bucket"
    assert "d" in sig and "eta_min" in sig
    logs = list((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
    assert logs, "shadow emit missing"
    # emit writes to TODAY-dated file; search all ledgers for the rho row
    rows = [json.loads(line)
            for p in logs for line in p.read_text(encoding="utf-8").splitlines()]
    rho_rows = [r for r in rows if r.get("action") == "rho_checkpoint"]
    assert rho_rows, "rho_checkpoint row not found in any ledger"
    assert rho_rows[-1]["actor"] == "rho_checkpoint"


def test_attach_signals_flag_off_noop(tmp_path, monkeypatch):
    monkeypatch.delenv(value_config.ENV_NAME, raising=False)
    ws = _mk_ws(tmp_path / "ws")
    ledger = ws / "runs" / "logs" / "kunglao-2026-08-28.jsonl"
    before = ledger.read_text(encoding="utf-8")
    decision = {"decision": "DISPATCH"}
    out = rc.attach_signals(ws, decision)
    assert "value_signals" not in out
    assert ledger.read_text(encoding="utf-8") == before  # no shadow emit
