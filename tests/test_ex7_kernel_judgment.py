# -*- coding: utf-8 -*-
"""tests/test_ex7_kernel_judgment.py — EX-7 harness pins (the
kernel-judgment experiment's own regression wall).

Pins (openspec change kernel-judgment-experiment, design Decision 7/9):
  - world determinism: same pre-registered constants => byte-identical
    ground truth; 8 distinct class signature hashes; R1 shares one
    strong set, R2/R3 differ per class;
  - env pairing: the outcome RNG carries no policy term, so the same
    (regime, seed, step, class, family) yields the same outcome under
    every arm;
  - a micro-run (seeds 9000-9001, horizon 5 — OUTSIDE the real seed
    range 0..199 per design Decision 9, so no test ever observes a
    real grid cell before the single pre-registered run) executes the
    REAL kernel end-to-end and returns the results-JSON shape;
  - the sign test's known-answer behavior and the discriminator
    routing (D1 gated on kernel-g1; D4 needs >=2 BETTER; the D3/D3'
    sign flip).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import method_families  # noqa: E402
from experiments import ex7_kernel_judgment as ex  # noqa: E402
from rlvr import q_cells  # noqa: E402 — the store-protocol face under the pin

CHECKPOINTS = (5, 10, 25, 50, 100)


def test_world_determinism_and_regime_structure():
    vocab = method_families.registered_tokens()
    for regime in ex.REGIMES:
        t1, s1 = ex.ground_truth(regime, vocab)
        t2, s2 = ex.ground_truth(regime, vocab)
        assert t1 == t2 and s1 == s2
        cfg = ex.REGIMES[regime]
        for cls in ex.CLASSES:
            assert len(s1[cls]) == cfg["n_strong"]
            assert set(t1[cls].values()) == {cfg["p_strong"],
                                             cfg["p_weak"]}
        sets = {tuple(s1[c]) for c in ex.CLASSES}
        assert (len(sets) == 1) == (regime == "R1")


def test_class_signature_hashes_are_distinct_and_stable():
    sigs = ex.class_signatures()
    assert len(sigs) == len(ex.CLASSES) == 8
    assert len(set(sigs.values())) == 8
    assert sigs == ex.class_signatures()


def test_env_pairing_has_no_policy_term():
    a = ex.env_success("R2", 11, 4, "smc-x86", "static-decompile", 0.55)
    b = ex.env_success("R2", 11, 4, "smc-x86", "static-decompile", 0.55)
    assert a == b  # identical (t, class, family) => identical outcome


def test_sign_test_known_answers():
    decisive = ex.sign_test([1.0] * 10, [2.0] * 10)
    assert decisive["verdict"] == "A_BETTER" and decisive["p_value"] <= 0.05
    reverse = ex.sign_test([2.0] * 10, [1.0] * 10)
    assert reverse["verdict"] == "A_WORSE"
    tied = ex.sign_test([1.0] * 10, [1.0] * 10)
    assert tied["verdict"] == "NO_SEPARATION" and tied["n"] == 0
    assert ex.sign_test([0.0], [1.0])["p_value"] == 1.0  # 1/2*2


def test_kernel_arm_feeds_store_and_learns():
    """The run-1 deviation pin: the kernel arm's observations MUST
    reach the fold (InMemoryStore copies its constructor argument, so
    the store is rebuilt per act from the grown rows). World shaped
    like the real grid — the chosen family 30-for-30, every other
    family observed failing — so enrichment must be strong (>0.25 of
    draws vs the 1/12 uniform rate)."""
    vocab = method_families.registered_tokens()
    sig = ex.class_signatures()["arm-kdf"]
    family = sorted(vocab)[0]
    fed = ex.KernelArm("R1", 9502, "kernel", vocab, 1.0)
    for _ in range(30):
        fed.observe(sig, family, 1.0)
    for other in sorted(vocab):
        if other != family:
            for _ in range(5):
                fed.observe(sig, other, 0.0)
    assert len(q_cells.InMemoryStore(fed.rows).observations()) == 85
    hits = sum(1 for _ in range(60) if fed.act(sig) == family)
    assert hits / 60 > 0.25, f"no enrichment: {hits}/60 for {family}"


def test_micro_run_real_kernel_end_to_end():
    # seeds 9000-9001 are OUTSIDE the real range 0..199 (Decision 9)
    out = ex.run_regime("R3", seeds=(9000, 9001), horizon=5,
                        checkpoints=(5,))
    assert out["seed_count"] == 2 and out["horizon"] == 5
    for arm in ex.ARMS:
        assert arm in out["arms"]
        assert math.isfinite(out["arms"][arm]["regret"][5])
    for pair in ("kernel_vs_uniform", "kernel-g1_vs_uniform",
                 "eps-greedy_vs_uniform"):
        assert pair in out["pairs"]
        cell = out["pairs"][pair]["regret"][5]
        assert cell["verdict"] in ("A_BETTER", "A_WORSE",
                                   "NO_SEPARATION")


def _fake_results(verdicts=None):
    """Minimal results shape for discriminator routing: every cell
    NO_SEPARATION except the overrides in `verdicts` keyed
    (regime, pair, metric, n) -> verdict."""
    verdicts = verdicts or {}
    pairs = ("kernel_vs_uniform", "kernel-g1_vs_uniform",
             "eps-greedy_vs_uniform")
    regimes = {}
    for regime in ex.REGIMES:
        pair_doc = {}
        for pair in pairs:
            metric_doc = {}
            for metric in ("regret", "waste"):
                metric_doc[metric] = {
                    n: {"verdict": verdicts.get(
                        (regime, pair, metric, n), "NO_SEPARATION")}
                    for n in CHECKPOINTS}
            pair_doc[pair] = metric_doc
        regimes[regime] = {"pairs": pair_doc}
    return {"regimes": regimes}


def test_discriminator_routing():
    # D1 requires kernel-g1 to ALSO fail in R3 at n=100 (review A1):
    d = ex.evaluate_discriminators(_fake_results({
        ("R3", "kernel_vs_uniform", "regret", 100): "NO_SEPARATION",
        ("R3", "kernel-g1_vs_uniform", "regret", 100): "NO_SEPARATION",
        ("R3", "eps-greedy_vs_uniform", "regret", 10): "A_BETTER",
    }))
    assert "D1" in d["fired"] and d["headline"] == "D1"
    # ...but a γ=1 kernel separating routes AWAY from D1 into D2:
    d = ex.evaluate_discriminators(_fake_results({
        ("R3", "kernel_vs_uniform", "regret", 100): "NO_SEPARATION",
        ("R3", "kernel-g1_vs_uniform", "regret", 100): "A_BETTER",
        ("R3", "eps-greedy_vs_uniform", "regret", 10): "A_BETTER",
    }))
    assert "D1" not in d["fired"] and "D2" in d["fired"]
    assert d["detail"]["D2_gamma_drag_dominant_clause"] is True
    # D4 needs kernel BETTER at n=100 in >=2 regimes, worse nowhere:
    d = ex.evaluate_discriminators(_fake_results({
        ("R1", "kernel_vs_uniform", "regret", 100): "A_BETTER",
        ("R3", "kernel_vs_uniform", "regret", 100): "A_BETTER",
    }))
    assert "D4" in d["fired"] and d["headline"] == "D4"
    # D3' sign flip at the γ=1 face:
    d = ex.evaluate_discriminators(_fake_results({
        ("R1", "kernel-g1_vs_uniform", "regret", 25): "A_BETTER",
        ("R2", "kernel-g1_vs_uniform", "regret", 25): "A_WORSE",
    }))
    assert "D3'" in d["fired"] and "D3" not in d["fired"]
    # nothing fires on the all-null world:
    d = ex.evaluate_discriminators(_fake_results())
    assert d["fired"] == [] and d["headline"] is None
