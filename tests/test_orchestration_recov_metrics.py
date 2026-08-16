# -*- coding: utf-8 -*-
"""tests/test_orchestration_recov_metrics.py — #309 symbol/type recovery eval metrics.

Absorbed idea (Dryxio/auto-re-agent metrics.py:71-218), re-implemented for the
kunglao eval harness:
  - naming tiers: exact 1.0 / same-set (synonym) 0.9 / superset 0.8 /
    recall-only 0.7 — greedy assignment, no reuse of recovered names or
    expected functions
  - type score per function: 0.4 return + 0.3 param count + 0.3 param types
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import recov_metrics as rm


def test_exact_match_scores_1():
    s = rm.naming_score({"func_a": ["func_a"]}, {"func_a": "func_a"})
    assert s["score"] == pytest.approx(1.0)
    assert s["matched"] == 1
    assert s["recall"] == pytest.approx(1.0)
    assert s["precision"] == pytest.approx(1.0)


def test_synonym_match_scores_09():
    s = rm.naming_score({"f_a": ["decrypt_payload", "decrypt"]}, {"f_a": "decrypt"})
    assert s["score"] == pytest.approx(0.9)


def test_superset_match_scores_08():
    """Recovered name is a superset of the expected name (suffix annotations)."""
    s = rm.naming_score({"f_a": ["decrypt"]}, {"f_a": "decrypt_0x401000"})
    assert s["score"] == pytest.approx(0.8)


def test_recall_only_match_scores_07():
    """Function recovered but name unrecognizable → recall tier."""
    s = rm.naming_score({"f_a": ["alloc_buf"]}, {"f_a": "sub_401000"})
    assert s["score"] == pytest.approx(0.7)


def test_unrecovered_function_scores_zero():
    s = rm.naming_score({"f_a": ["decrypt"], "f_b": ["pack"]}, {"f_a": "decrypt"})
    assert s["score"] == pytest.approx(0.5)
    assert s["matched"] == 1
    assert s["recall"] == pytest.approx(0.5)


def test_greedy_no_reuse_cross_function():
    """Best pairing is cross-function: naive same-func pairing scores 0.75,
    greedy global pairing scores 1.0."""
    expected = {"a": ["decrypt"], "b": ["decrypt_extra"]}
    recovered = {"a": "decrypt_extra", "b": "decrypt"}
    s = rm.naming_score(expected, recovered)
    assert s["score"] == pytest.approx(1.0)


def test_greedy_does_not_double_assign():
    """One recovered name cannot satisfy two expected functions: (a,a)=1.0,
    (b,b) falls to the recall tier 0.7 → (1.0 + 0.7) / 2."""
    expected = {"a": ["decrypt"], "b": ["decrypt"]}
    recovered = {"a": "decrypt", "b": "unrelated"}
    s = rm.naming_score(expected, recovered)
    assert s["score"] == pytest.approx((1.0 + 0.7) / 2)
    assert len(s["pairings"]) == 2


def test_extra_recovered_names_lower_precision_only():
    expected = {"a": ["decrypt"]}
    recovered = {"a": "decrypt", "zz": "noise"}
    s = rm.naming_score(expected, recovered)
    assert s["score"] == pytest.approx(1.0)
    assert s["precision"] == pytest.approx(0.5)


def test_naming_score_deterministic():
    expected = {"a": ["decrypt"], "b": ["pack", "packer"]}
    recovered = {"a": "decrypt_x", "b": "packer"}
    assert rm.naming_score(expected, recovered) == rm.naming_score(expected, recovered)


def test_type_score_perfect():
    expected = {"f": {"return": "void", "params": ["char *", "int"]}}
    recovered = {"f": {"return": "void", "params": ["char *", "int"]}}
    s = rm.type_score(expected, recovered)
    assert s["score"] == pytest.approx(1.0)


def test_type_score_formula_components():
    """0.4 return + 0.3 count + 0.3 params — each component independent."""
    expected = {"f": {"return": "int", "params": ["char *", "int"]}}
    wrong_return = rm.type_score(expected, {"f": {"return": "void", "params": ["char *", "int"]}})
    assert wrong_return["score"] == pytest.approx(0.6)  # 0 + 0.3 + 0.3
    wrong_count = rm.type_score(expected, {"f": {"return": "int", "params": ["char *"]}})
    assert wrong_count["score"] == pytest.approx(0.4)  # 0.4 + 0 + 0
    half_params = rm.type_score(expected, {"f": {"return": "int", "params": ["char *", "long"]}})
    assert half_params["score"] == pytest.approx(0.4 + 0.3 + 0.3 * 0.5)


def test_type_score_missing_function_zero():
    expected = {"f": {"return": "int", "params": []}, "g": {"return": "int", "params": []}}
    recovered = {"f": {"return": "int", "params": []}}
    s = rm.type_score(expected, recovered)
    assert s["score"] == pytest.approx(0.5)


def test_type_score_empty_expected_zero():
    assert rm.type_score({}, {})["score"] == pytest.approx(0.0)


def test_quality_dimension_shape():
    dim = rm.naming_dimension({"a": ["decrypt"]}, {"a": "decrypt"})
    assert dim["pass"] is True
    assert dim["score"] == pytest.approx(1.0)
    assert "naming_quality" in dim["detail"]
    dim = rm.naming_dimension({"a": ["decrypt"]}, {})
    assert dim["pass"] is False
