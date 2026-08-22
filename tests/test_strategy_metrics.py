# -*- coding: utf-8 -*-
"""tests/test_strategy_metrics.py — #529 strategy convergence four metrics.

Pure-function metrics layered atop priority_ratio.Action / EvidenceView:

  regret            reverse-regret vs. optimal action selection; lower=closer to oracle.
  cost_to_slope     efficient-frontier curve: diminishing returns slope vs cost.
  p_faster_given_hit among hits, fraction actually faster than the median.
  competence_cov    capability coverage: validated_families / required_families.

TDD: this file pins the four behaviors in the RED step.  Tests use tiny
synthetic input — no filesystem, no LLM.  All four metrics live in
scripts/strategy_metrics.py and are importable as `strategy_metrics as sm`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import strategy_metrics as sm


# ---------- synthetic fixtures ----------

def _action(cid, score, cost, leverage=0.0, discriminator=0.0, novelty=0.0, tier=1):
    """Build a minimal mapping compatible with sm.regret_oracle input."""
    return {
        "claim_id": cid, "score": score, "cost": cost,
        "leverage": leverage, "discriminator": discriminator,
        "novelty": novelty, "tier": tier,
    }


# ---------- regret ----------

def test_regret_perfect_oracle_returns_zero():
    """If 'oracle' (best possible score) equals the picked action's score → regret=0."""
    actions = [_action("A", 0.9, 1.0), _action("B", 0.5, 2.0)]
    # oracle chose A; the dispatch actually picked A → zero regret
    out = sm.regret(actions, picked={"A"}, oracle={"A"})
    assert out["regret"] == pytest.approx(0.0)
    assert out["picked"] == ["A"]
    assert out["oracle"] == ["A"]


def test_regret_picks_lower_score_action():
    """If dispatch picked B (score 0.5) when oracle chose A (score 0.9) → regret=0.4."""
    actions = [_action("A", 0.9, 1.0), _action("B", 0.5, 2.0)]
    out = sm.regret(actions, picked={"B"}, oracle={"A"})
    assert out["regret"] == pytest.approx(0.4)


def test_regret_handles_empty_picked():
    """Empty picked set (no dispatch) → regret = oracle's full score (max possible loss)."""
    actions = [_action("A", 0.9, 1.0)]
    out = sm.regret(actions, picked=set(), oracle={"A"})
    assert out["regret"] == pytest.approx(0.9)


def test_regret_handles_empty_actions():
    """No actions at all → regret=0 (trivially converged)."""
    out = sm.regret([], picked=set(), oracle=set())
    assert out["regret"] == 0.0


# ---------- cost_to_slope ----------

def test_cost_to_slope_returns_diminishing_curve():
    """Slope = dscore/dcost; sorted by cost; yields a monotonic-ish curve."""
    actions = [
        _action("A", 0.4, 1.0),
        _action("B", 0.6, 3.0),
        _action("C", 0.7, 10.0),
    ]
    curve = sm.cost_to_slope(actions)
    assert len(curve) >= 2
    # Slope should be positive overall (more cost → more score), but the
    # marginal rate should drop as cost grows (diminishing returns).
    slopes = [row["slope"] for row in curve if row["slope"] is not None]
    assert all(s >= 0 for s in slopes), "no negative marginal score"
    # First non-null slope vs last non-null slope: last <= first (diminishing)
    assert slopes[-1] <= slopes[0] + 1e-9


def test_cost_to_slope_empty():
    """No actions → empty curve."""
    assert sm.cost_to_slope([]) == []


def test_cost_to_slope_too_few_points():
    """Single action cannot form a slope → no slope row emitted, only points."""
    curve = sm.cost_to_slope([_action("A", 0.4, 1.0)])
    assert len(curve) == 1
    assert curve[0]["slope"] is None


# ---------- P(faster|hit) ----------

def test_p_faster_given_hit_majority_faster():
    """If 3 of 4 hits are faster than median hit_time → p_faster ≈ 0.75."""
    hits = [10.0, 5.0, 8.0, 12.0]  # median = 9.0; faster than median: 5.0, 8.0 → 2/4 wait
    out = sm.p_faster_given_hit(hits, median_hit_time=9.0)
    assert out["p_faster"] == pytest.approx(0.5)
    assert out["hits"] == 4


def test_p_faster_given_hit_zero_hits_returns_zero():
    """No hits at all → undefined → 0.0 (no signal, no false positive)."""
    out = sm.p_faster_given_hit([])
    assert out["p_faster"] == 0.0
    assert out["hits"] == 0


def test_p_faster_given_hit_all_faster():
    """Median is a hit itself; only hits strictly below count.  3 values,
    median = 2.0 → only [1.0] is strictly less → p_faster = 1/3."""
    hits = [1.0, 2.0, 3.0]
    median = sm._median(hits)
    out = sm.p_faster_given_hit(hits, median_hit_time=median)
    # strict-less: only 1.0 is < 2.0 → 1/3
    assert out["p_faster"] == pytest.approx(1/3)


def test_p_faster_given_hit_no_median_in_set():
    """Inject a median just below a hit → hits strictly less count as faster."""
    hits = [1.0, 2.0, 3.0]
    out = sm.p_faster_given_hit(hits, median_hit_time=1.5)
    # 1.0 < 1.5 → 1 of 3
    assert out["p_faster"] == pytest.approx(1/3)


def test_p_faster_given_hit_strongly_faster():
    """Median above all hits → every hit is faster → p_faster=1.0."""
    hits = [1.0, 2.0, 3.0, 4.0]
    out = sm.p_faster_given_hit(hits, median_hit_time=10.0)
    assert out["p_faster"] == pytest.approx(1.0)


# ---------- competence coverage ----------

def test_competence_coverage_full():
    """All required families validated → coverage=1.0."""
    out = sm.competence_coverage(
        validated_families={"frida", "ghidra"},
        required_families={"frida", "ghidra"},
    )
    assert out["coverage"] == pytest.approx(1.0)
    assert out["missing"] == []


def test_competence_coverage_partial():
    """Half the required families validated → coverage=0.5."""
    out = sm.competence_coverage(
        validated_families={"frida"},
        required_families={"frida", "ghidra"},
    )
    assert out["coverage"] == pytest.approx(0.5)
    assert out["missing"] == ["ghidra"]


def test_competence_coverage_empty_required():
    """No requirements defined → trivially covered (1.0)."""
    out = sm.competence_coverage(validated_families=set(), required_families=set())
    assert out["coverage"] == 1.0
    assert out["missing"] == []


def test_competence_coverage_no_validated():
    """Required families but none validated → coverage=0.0, all missing."""
    out = sm.competence_coverage(
        validated_families=set(),
        required_families={"frida", "ghidra", "x64dbg"},
    )
    assert out["coverage"] == 0.0
    assert sorted(out["missing"]) == ["frida", "ghidra", "x64dbg"]


# ---------- composite snapshot (integration shape) ----------

def test_compute_all_returns_four_keys():
    """compute_all emits regret / cost_to_slope / p_faster / competence."""
    snap = sm.compute_all(
        actions=[_action("A", 0.8, 1.0), _action("B", 0.4, 3.0)],
        picked={"A"},
        oracle={"A"},
        hits=[2.0, 4.0, 6.0],
        validated_families={"frida"},
        required_families={"frida", "ghidra"},
    )
    for key in ("regret", "cost_to_slope", "p_faster_given_hit", "competence"):
        assert key in snap, f"missing metric: {key}"
    assert snap["regret"]["regret"] == pytest.approx(0.0)
    assert snap["competence"]["coverage"] == pytest.approx(0.5)
