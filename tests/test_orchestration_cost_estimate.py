# -*- coding: utf-8 -*-
"""tests/test_orchestration_cost_estimate.py — #309 pre-dispatch cost estimator.

Absorbed idea (Dryxio/auto-re-agent cmd_estimate.py:34-47), re-implemented for
kunglao claim-driven dispatch:
  - tokens per tier pass = decompiled_chars / 4 + 3000 base overhead
  - calls = n_functions * (tiers_left + investigation_calls)
  - cheapness blending keeps the tier heuristic as the CAP (conservative):
    blended = min(tier_cheapness, estimated_cheapness) — an estimate can only
    make a claim look MORE expensive, never cheaper than the tier says.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import cost_estimate as ce


def _claim(**kw):
    c = {"id": "C-1", "statement": "identify packer", "evidence_tier_attempted": 0,
         "promotion_attempts": 0}
    c.update(kw)
    return c


def _features(**kw):
    f = {"n_functions": 10, "decompiled_chars": 4000}
    f.update(kw)
    return f


def test_formula_matches_absorbed_reference():
    """tokens = (chars/4 + 3000) * tiers_left; calls = n_funcs * (tiers_left + 2)."""
    est = ce.estimate_claim(_claim(evidence_tier_attempted=0), _features())
    assert est["tokens_per_tier"] == pytest.approx(4000.0)  # 4000/4 + 3000
    assert est["tiers_left"] == 3
    assert est["est_tokens"] == pytest.approx(12000.0)
    assert est["est_calls"] == 50  # 10 * (3 + 2)


def test_tier_is_cap_on_cheapness():
    """Deep-tier claim with tiny features: estimator says cheap, tier caps it."""
    est = ce.estimate_claim(_claim(evidence_tier_attempted=2),
                            _features(decompiled_chars=10, n_functions=1))
    assert est["cheapness_est"] > 0.2
    assert ce.blended_cheapness(0.2, est) == pytest.approx(0.2)


def test_estimator_discounts_large_batches():
    """A big decompile batch must look more expensive than a small one."""
    big = ce.estimate_claim(_claim(), _features(decompiled_chars=40000, n_functions=500))
    small = ce.estimate_claim(_claim(), _features())
    assert big["cheapness_est"] < small["cheapness_est"]
    assert ce.blended_cheapness(1.0, big) < 1.0


def test_more_decompiled_chars_never_cheaper():
    cheapness = [ce.estimate_claim(_claim(), _features(decompiled_chars=c))["cheapness_est"]
                 for c in (0, 1000, 4000, 16000, 64000)]
    assert cheapness == sorted(cheapness, reverse=True)


def test_estimate_is_deterministic():
    a = ce.estimate_claim(_claim(), _features())
    b = ce.estimate_claim(_claim(), _features())
    assert a == b


def test_load_features_missing_returns_none(tmp_path):
    assert ce.load_features(tmp_path) is None


def test_load_features_reads_yaml(tmp_path):
    (tmp_path / "sample_features.yaml").write_text(
        "n_functions: 142\ndecompiled_chars: 48000\n", encoding="utf-8")
    assert ce.load_features(tmp_path) == {"n_functions": 142, "decompiled_chars": 48000}


def test_cli_json(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "- id: C-1\n"
        "  statement: packer detect\n"
        "  status: OPEN\n"
        "  evidence_tier_attempted: 0\n"
        "  promotion_attempts: 0\n", encoding="utf-8")
    (ws / "sample_features.yaml").write_text(
        "n_functions: 20\ndecompiled_chars: 8000\n", encoding="utf-8")
    rc = ce.main([str(ws), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["claim_id"] == "C-1"
    est = payload["estimate"]
    assert est["est_tokens"] == pytest.approx(15000.0)  # (8000/4 + 3000) * 3
    assert est["est_calls"] == 100  # 20 * (3 + 2)


def test_cli_reproduce_prints_field_value(tmp_path, capsys):
    """--reproduce emits field=value input lines (kunglao_verify parseable);
    the executable command form stays in the --json payload's reproduce key."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  statement: x\n  status: OPEN\n"
        "  evidence_tier_attempted: 0\n  promotion_attempts: 0\n", encoding="utf-8")
    (ws / "sample_features.yaml").write_text(
        "n_functions: 1\ndecompiled_chars: 10\n", encoding="utf-8")
    rc = ce.main([str(ws), "--reproduce"])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"workspace={ws}" in out
    assert "claim=first-open" in out
    assert "features_file=" in out
    for line in out.strip().splitlines():
        assert re.match(r"^\w+\s*[:=]\s*.+$", line), line
