# -*- coding: utf-8 -*-
"""tests/test_scheduling_selection_685.py — the wake sampler's pure math.

Three derived quantities carry the wake decision's width and weights, and
all three are pure functions (scripts/scheduling_selection.py):

  1. k = min(free_slots, f(entropy)) — derived from two state quantities,
     never a threshold trigger;
  2. the Gumbel top-k WITHOUT replacement — an ordered draw of distinct
     members;
  3. the exact Plackett-Luce propensity of that draw — the sampling
     probability the decision log carries, so the wake decision is
     off-policy evaluable.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import scheduling_selection as sel  # noqa: E402

FLAT_FIVE = {name: 0.0
             for name in ("sleep", "wake_on", "probe", "close_loop", "none")}


class TestAdaptiveWidth:

    def test_k_adapts_to_entropy_and_free_slots(self):
        # the demand grows with the frontier entropy; the slot room caps it
        assert sel.adapt_k(2.0, 3) == 2    # f(2 bits) = 2, room 3
        assert sel.adapt_k(2.0, 1) == 1    # room caps the demand
        assert sel.adapt_k(0.0, 3) == 1    # the floor: one action minimum
        assert sel.adapt_k(None, 3) == 1   # unknown entropy -> conservative
        assert sel.adapt_k(1.5, 0) == 0    # no slot room -> no action
        assert sel.adapt_k(2.0, None) == 2  # unknown room -> demand stands

    def test_f_entropy_is_a_derived_amount_not_a_trigger(self):
        assert sel.f_entropy(0.0) == 1
        assert sel.f_entropy(1.0) == 1
        assert sel.f_entropy(1.01) == 2      # ceil, not round
        assert sel.f_entropy(2.0) == 2
        assert sel.f_entropy(None) == sel.K_MIN
        assert sel.f_entropy("two") == sel.K_MIN  # non-numbers are unknown
        assert sel.f_entropy(True) == sel.K_MIN   # bool is not entropy
        # non-finite floats are unknown too: the floor, never a raise
        assert sel.f_entropy(float("nan")) == sel.K_MIN
        assert sel.f_entropy(float("inf")) == sel.K_MIN


class TestGumbelTopK:

    def test_wide_selection_rides_a_gumbel_topk_without_replacement(self):
        # the sampled object is an ORDERED k-subset (no replacement): k
        # distinct members come back, whatever the seed
        for seed in range(8):
            picked = sel.gumbel_topk(FLAT_FIVE, 3, random.Random(seed))
            assert len(picked) == 3
            assert len(set(picked)) == 3
            assert set(picked) <= set(FLAT_FIVE)
        # replay is deterministic for an injected rng stream
        a = sel.gumbel_topk(FLAT_FIVE, 2, random.Random(42))
        b = sel.gumbel_topk(FLAT_FIVE, 2, random.Random(42))
        assert a == b
        # k is clamped to the candidate count; k <= 0 selects nothing
        assert len(sel.gumbel_topk(FLAT_FIVE, 99, random.Random(1))) == 5
        assert sel.gumbel_topk(FLAT_FIVE, 0, random.Random(1)) == []

    def test_heavy_logits_win_almost_surely(self):
        heavy = {name: -50.0 for name in FLAT_FIVE}
        heavy["probe"] = 50.0
        for seed in range(8):
            assert sel.gumbel_topk(heavy, 1, random.Random(seed)) == ["probe"]

    def test_the_draw_actually_samples_and_tracks_its_pl_propensity(self):
        # every structural pin above is passed by a plain sort-by-logit —
        # this is the honesty face: across seeds the draw VARIES, and its
        # empirical frequency tracks the exact Plackett-Luce propensity
        # the decision log carries (flat logits -> 1/5 each)
        trials = 1500
        firsts: dict[str, int] = {}
        for seed in range(trials):
            (first,) = sel.gumbel_topk(FLAT_FIVE, 1, random.Random(seed))
            firsts[first] = firsts.get(first, 0) + 1
        assert len(firsts) == len(FLAT_FIVE), (
            f"the draw is not sampling (deterministic sort?): {firsts}")
        for name in FLAT_FIVE:
            freq = firsts.get(name, 0) / trials
            assert abs(freq - sel.pl_propensity([name], FLAT_FIVE)) < 0.05, (
                name, freq)


class TestPlackettLuce:

    def test_pl_propensity_is_exact(self):
        # flat logits: one ordered draw of a single action is 1/5, of a
        # pair is 1/(5*4) — the exact propensity the log carries
        assert abs(sel.pl_propensity(["sleep"], FLAT_FIVE) - 0.2) < 1e-12
        assert abs(sel.pl_propensity(["sleep", "probe"], FLAT_FIVE)
                   - 1.0 / 20.0) < 1e-12

    def test_pl_propensity_refuses_non_candidates_and_degenerate_mass(self):
        assert sel.pl_propensity(["teleport"], FLAT_FIVE) == 0.0
        assert sel.pl_propensity(["sleep", "sleep"], FLAT_FIVE) == 0.0
        zeros = {name: -float("inf") for name in FLAT_FIVE}
        assert sel.pl_propensity(["sleep"], zeros) == 0.0

    def test_pl_terms_stay_finite_on_extreme_logits(self):
        extreme = {name: -1000.0 for name in FLAT_FIVE}
        extreme["probe"] = 1000.0
        p = sel.pl_propensity(["probe"], extreme)
        assert 0.0 < p <= 1.0
        terms = sel.pl_terms(["probe", "sleep"], extreme)
        assert len(terms) == 2 and all(0.0 <= t <= 1.0 for t in terms)
