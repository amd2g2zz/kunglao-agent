# -*- coding: utf-8 -*-
"""tests/test_orchestration_eval_quality.py — #309 eval quality dimensions.

kunglao_eval gains naming/type recovery quality dimensions: episodes collect
recovered symbols/types from symbol_recovery evidence facts, and
score_episode adds naming_quality/type_quality dimensions when the oracle
carries expected_symbols/expected_types. Oracles without those keys keep the
exact pre-change dimension set (backward compatible).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import kunglao_eval


def _sym_case(recovered_name: str = "decrypt_payload",
              recovered_type: dict | None = None) -> dict:
    if recovered_type is None:
        recovered_type = {"return": "void", "params": ["char *"]}
    return {
        "case_id": "sym-case",
        "claims": [{"id": "C-1", "status": "OPEN", "statement": "recover symbols"}],
        "deps": {},
        "budget": {"max_steps": 4, "tool_calls_max": 16, "tokens_max": 2000},
        "transcript": {"C-1": [{
            "tool": "ghidra-recon", "args": {},
            "result": {"ok": True, "payload": {"facts": [
                {"fact_id": "F-1", "conclusion": "recovered names and types",
                 "anchors": ["0x401000"], "category": "symbol_recovery",
                 "symbols": {"f1": recovered_name},
                 "types": {"f1": recovered_type}},
            ]}},
        }]},
    }


def _sym_oracle(overrides: dict | None = None) -> dict:
    o = {"expected_verdicts": {"C-1": "PROVEN"},
         "completion": "solvable",
         "expected_symbols": {"f1": ["decrypt_payload"]},
         "expected_types": {"f1": {"return": "void", "params": ["char *"]}}}
    if overrides:
        o.update(overrides)
    return o


def test_episode_collects_recovered_symbols_and_types():
    result = kunglao_eval.run_episode(_sym_case(), "A")
    assert result["recovered_symbols"] == {"f1": "decrypt_payload"}
    assert result["recovered_types"]["f1"]["return"] == "void"


def test_score_episode_adds_quality_dimensions():
    result = kunglao_eval.run_episode(_sym_case(), "A")
    scored = kunglao_eval.score_episode(_sym_case(), _sym_oracle(), result)
    dims = scored["oracle"]["dimensions"]
    assert "naming_quality" in dims
    assert dims["naming_quality"]["score"] == pytest.approx(1.0)
    assert dims["naming_quality"]["pass"] is True
    assert "type_quality" in dims
    assert dims["type_quality"]["score"] == pytest.approx(1.0)


def test_poor_recovery_scores_low_and_fails():
    result = kunglao_eval.run_episode(_sym_case(recovered_name="sub_401000"), "A")
    scored = kunglao_eval.score_episode(_sym_case(), _sym_oracle(), result)
    dims = scored["oracle"]["dimensions"]
    assert dims["naming_quality"]["score"] == pytest.approx(0.7)  # recall tier
    assert dims["naming_quality"]["pass"] is False


def test_oracle_without_expected_symbols_has_no_quality_dims():
    """Backward compat: an oracle without expected_symbols/expected_types
    produces the exact pre-change dimension set."""
    case = _sym_case()
    result = kunglao_eval.run_episode(case, "A")
    oracle = {"expected_verdicts": {"C-1": "PROVEN"}, "completion": "solvable"}
    scored = kunglao_eval.score_episode(case, oracle, result)
    dims = scored["oracle"]["dimensions"]
    assert "naming_quality" not in dims
    assert "type_quality" not in dims
    # pre-existing dimensions still present
    assert "correctness" in dims and "overclaims" in dims


def test_overall_pass_requires_quality_dims_to_pass():
    case = _sym_case(recovered_name="sub_401000")
    result = kunglao_eval.run_episode(case, "A")
    scored = kunglao_eval.score_episode(case, _sym_oracle(), result)
    # naming_quality dim exists with pass=False → overall must not be PASS
    assert scored["oracle"]["dimensions"]["naming_quality"]["pass"] is False
    assert scored["oracle"]["overall"] == "FAIL"
