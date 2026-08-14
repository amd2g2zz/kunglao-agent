# -*- coding: utf-8 -*-
"""tests/test_orchestration_priority_cost.py — #309 priority.py estimator integration.

rank_claims gains an optional sample_features input; when present the
cheapness term uses the blended estimate (tier heuristic stays the cap).
Without features the output is VALUE-LEVEL compatible with pre-#309: all
pre-existing keys keep their pre-change values; the new keys
(cheapness_tier / est_tokens / est_calls) are additive extensions, and all
consumers (worker_budget / worker_pulse / external_kicker / test_rank_claims)
read only pre-existing keys. The --json payload gains cost_estimation /
sample_features keys — value-level, not byte-level, compatibility.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import priority


def _reg(*claims):
    return {"claims": list(claims)}


def _deps():
    return {"depends_on": {}}


def _claim(cid, **kw):
    c = {"id": cid, "status": "OPEN", "statement": cid,
         "evidence_tier_attempted": 0, "promotion_attempts": 0,
         "answers_question": True}
    c.update(kw)
    return c


SMALL_FEATURES = {"n_functions": 10, "decompiled_chars": 4000}
BIG_FEATURES = {"n_functions": 500, "decompiled_chars": 500000}


def test_no_features_behavior_unchanged():
    rows = priority.rank_claims(_reg(_claim("C-1")), _deps(),
                                dict(priority.DEFAULT_WEIGHTS))
    assert rows[0]["cheapness"] == pytest.approx(1.0)
    assert rows[0].get("cheapness_tier") == pytest.approx(1.0)
    assert rows[0].get("est_tokens") is None
    assert rows[0].get("est_calls") is None


def test_features_blend_cheapness_with_tier_cap():
    rows = priority.rank_claims(_reg(_claim("C-1")), _deps(),
                                dict(priority.DEFAULT_WEIGHTS),
                                sample_features=BIG_FEATURES)
    r = rows[0]
    assert r["cheapness_tier"] == pytest.approx(1.0)
    assert r["cheapness"] < 1.0
    assert r["est_tokens"] > 0
    assert r["est_calls"] > 0


def test_deep_tier_claim_keeps_tier_cap_with_features():
    rows = priority.rank_claims(
        _reg(_claim("C-1", evidence_tier_attempted=2)), _deps(),
        dict(priority.DEFAULT_WEIGHTS), sample_features=SMALL_FEATURES)
    assert rows[0]["cheapness_tier"] == pytest.approx(0.2)
    assert rows[0]["cheapness"] == pytest.approx(0.2)


def test_big_batch_features_lower_score_than_small():
    """Features are sample-wide: the same claim scores lower against a big
    decompile batch than against a small one (cost in the cheapness term)."""
    reg = _reg(_claim("C-1"))
    small = priority.rank_claims(reg, _deps(), dict(priority.DEFAULT_WEIGHTS),
                                 sample_features=SMALL_FEATURES)[0]
    big = priority.rank_claims(reg, _deps(), dict(priority.DEFAULT_WEIGHTS),
                               sample_features=BIG_FEATURES)[0]
    assert big["cheapness"] < small["cheapness"]
    assert small["score"] > big["score"]


def test_score_uses_blended_cheapness_weight():
    """score = ... + w_cheapness * cheapness_blended — recomputed by hand."""
    rows = priority.rank_claims(_reg(_claim("C-1")), _deps(),
                                dict(priority.DEFAULT_WEIGHTS),
                                sample_features=BIG_FEATURES)
    r = rows[0]
    w = priority.DEFAULT_WEIGHTS
    expected = (w["value"] * 1.0 + w["leverage"] * r["leverage"]
                + w["cheapness"] * r["cheapness"]
                + w["novelty"] * r["novelty"]
                + w["outcome"] * r["outcome"])
    assert r["score"] == pytest.approx(expected, abs=1e-3)


def test_main_loads_sample_features_from_workspace(tmp_path, capsys, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  statement: x\n  status: OPEN\n"
        "  evidence_tier_attempted: 0\n  promotion_attempts: 0\n"
        "  answers_question: true\n", encoding="utf-8")
    (ws / "claim_deps.yaml").write_text("depends_on: {}\n", encoding="utf-8")
    (ws / "sample_features.yaml").write_text(
        "n_functions: 500\ndecompiled_chars: 500000\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["priority.py", str(ws), "--json"])
    rc = priority.main()
    assert rc == 0
    import json
    payload = json.loads(capsys.readouterr().out)
    row = payload["dispatchable"][0]
    assert row["est_tokens"] > 0
    assert row["cheapness"] < row["cheapness_tier"]
    assert payload["cost_estimation"]["enabled"] is True
