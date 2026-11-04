# -*- coding: utf-8 -*-
"""tests/test_reward_base_v2_production.py — production-form pins for the
#932 measured-progress reward base.

The #930 mock-tier battery (simulated judge profiles, planted hack
probes) was a one-shot research instrument — retired to the local unit
home per the eval-not-in-repo ruling; its GO/NO-GO numbers are recorded
on issue #930. What remains here are the PRODUCTION regression pins:
the pricing face's measured-progress semantics driven directly through
``price_dispatch`` with planted deltas — no mock machinery.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) in sys.path:
        continue
    sys.path.insert(0, str(_p))

from rlvr import step_credit
from settlement import per_dispatch


def test_measured_credit_is_span_normalized():
    """credit = clamp(ΔP / LADDER_SPAN, 0, PASS_CREDIT): the span is
    derived from the ladder's own table (never mirrored) and a full
    ladder climb banks exactly PASS_CREDIT."""
    span = (step_credit.CREDIT_BY_CLASS[step_credit.CROSS_VALIDATED]
            - step_credit.CREDIT_BY_CLASS[step_credit.UNVERIFIED])
    assert per_dispatch.LADDER_SPAN == span
    assert per_dispatch.measured_credit(span, gate_pass=True) \
        == pytest.approx(per_dispatch.PASS_CREDIT)
    assert per_dispatch.measured_credit(span / 2, gate_pass=True) \
        == pytest.approx(per_dispatch.PASS_CREDIT / 2)


def test_non_saturating_ordering_preserved_in_the_clamp_free_domain():
    """Two raw deltas strictly inside the span rank identically after
    normalization (the positive-scale invariance)."""
    assert per_dispatch.measured_credit(0.7, gate_pass=True) \
        > per_dispatch.measured_credit(0.35, gate_pass=True)


def test_clamp_collapse_is_the_designed_asymmetry():
    """Clawback deltas clamp to 0.0 — the anti-hack rail: over a
    clawback trajectory the credits deliberately do NOT telescope."""
    assert per_dispatch.measured_credit(-per_dispatch.LADDER_SPAN,
                                        gate_pass=True) == 0.0


def test_cold_start_falls_back_to_the_ladder_prior():
    """progress_delta=None (no transition rows yet) → the fixed ladder
    prices; the measured path arms at the first recorded transition."""
    priced = per_dispatch.price_dispatch(
        "ro-cs", "d-1", 0.1,
        {"mechanical": True, "scope_verifier": True, "redteam": True},
        progress_delta=None, ts="t0")
    assert priced["credit"] == pytest.approx(per_dispatch.PASS_CREDIT)
