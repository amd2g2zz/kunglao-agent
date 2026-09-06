# -*- coding: utf-8 -*-
"""tests/test_priority_value_terms.py — the worth channel on the rebuilt
#107 Thompson ranker.

History: A3 (#823) fed the weighted formula's cost side (prior_p_complete
inflation) and a capability bonus multiplier. Issue #107 discarded that
formula ("之前的不要了") — those two terms died WITH it. What survives is
the SANCTIONED worth channel (#711 E2 / #759 H2: runs/value-weights.yaml),
which multiplies the rebuilt composite exogenously. #51 removed the
KUNGLAO_VALUE_ALGO switch: the unified path is pinned here on a default
environment.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import priority_ratio as pr  # noqa: E402


def _claim(cid, tier=1, **extra):
    c = {"id": cid, "status": "OPEN", "statement": "rce chain via c2",
         "evidence_tier_attempted": tier, "promotion_attempts": 0}
    c.update(extra)
    return c


def test_dead_a3_terms_are_gone():
    """prior_p_complete (cost inflation) and the capability bonus multiplied
    the DELETED formula — the fields/multipliers are gone with it."""
    assert "prior_p_complete" not in pr.EvidenceView.__dataclass_fields__
    assert not hasattr(pr, "CAPABILITY_BONUS")
    assert not hasattr(pr, "_resolve_prior_p")


def test_worth_class_weight_multiplies_score():
    import random
    claims = [_claim("C-001")]
    base = random.Random(0).getrandbits(64)
    raw = random.Random(f"thompson/{base}/C-001").betavariate(1.0, 1.0)
    worth = pr.priority_ratio(
        claims, {}, pr.EvidenceView(value_class_weights={"rce": 4.0}))[0]
    assert worth.weight == 4.0
    assert worth.score == round(raw * 4.0, 6)  # exact: no cost, no dh


def test_worth_claim_override_wins_over_class():
    claims = [_claim("C-001")]
    view = pr.EvidenceView(value_class_weights={"rce": 4.0},
                           value_claim_overrides={"C-001": 2.5})
    a = pr.priority_ratio(claims, {}, view)[0]
    assert a.weight == 2.5


def test_missing_weights_file_is_neutral():
    """No file → every action weight 1.0 and scores byte-identical."""
    out = pr.priority_ratio([_claim("C-001"), _claim("C-002", tier=2)],
                            {}, pr.EvidenceView())
    assert all(a.weight == 1.0 for a in out)


def test_illegal_weight_entries_dropped_per_entry():
    """Fail-open per entry (the load-time filter): a bad row must not
    neutralize the file, and a non-positive weight is not signal."""
    assert pr._positive_weights(
        {"rce": -3, "dos": 0, "c2_extract": "hi", "sandbox_escape": 2.5}
    ) == {"sandbox_escape": 2.5}
    assert pr.claim_value_weight(_claim("C-2", statement="dos dos"),
                                 {"dos": 2.0}, {}) == 2.0
