# -*- coding: utf-8 -*-
"""tests/test_rank_claims.py — tests for priority.py rank_claims with OUTCOME factor (#122)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import priority


def _reg(claims):
    return {"claims": claims}


def _deps():
    return {"depends_on": {}}


def test_no_outcome_data_no_change():
    """Claims with no OUTCOME history should rank the same as before."""
    reg = _reg([
        {"id": "C-1", "status": "OPEN", "statement": "test", "answers_question": True},
    ])
    rows = priority.rank_claims(reg, _deps(), dict(priority.DEFAULT_WEIGHTS))
    assert len(rows) == 1
    assert rows[0]["outcome"] == 0.0


def test_outcome_zero_weight_disables():
    """When outcome weight is 0, outcome data doesn't affect ranking."""
    w = {"value": 0.4, "leverage": 0.3, "cheapness": 0.2, "novelty": 0.1, "outcome": 0.0}
    reg = _reg([
        {"id": "C-1", "status": "OPEN", "statement": "test", "answers_question": True},
    ])
    rows = priority.rank_claims(reg, _deps(), w)
    assert rows[0]["outcome"] == 0.0


def test_default_weights_include_outcome():
    """DEFAULT_WEIGHTS should have an 'outcome' key."""
    assert "outcome" in priority.DEFAULT_WEIGHTS
    assert priority.DEFAULT_WEIGHTS["outcome"] > 0
