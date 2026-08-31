# -*- coding: utf-8 -*-
"""B7 (#823): bench_analyze — statistics pipeline (stdlib: exact McNemar,
normal-approx Wilcoxon with tie correction, least-squares slopes).
scipy/duckdb deliberately not added; numerics equivalent at n=30.
"""
import sys
from pathlib import Path

import pytest

import bench_analyze as ba


def test_mcnemar_exact_known_table():
    # exact two-sided binomial: 2·Σ_{i≤k} C(n,i)/2ⁿ; b=1,c=5 → 2·(1+6)/64
    assert ba.mcnemar_exact(b=1, c=5) == pytest.approx(0.21875)


def test_mcnemar_exact_balanced_is_one():
    assert ba.mcnemar_exact(b=5, c=5) == 1.0


def test_wilcoxon_no_effect():
    p, w = ba.wilcoxon_signed_rank([5, 3, 8, 2], [5, 3, 8, 2])
    assert p == 1.0


def test_wilcoxon_consistent_improvement_significant():
    x = [100, 110, 120, 130, 140, 150, 160, 170]
    y = [v - 30 for v in x]  # N arm saves 30 every pair
    p, w = ba.wilcoxon_signed_rank(x, y)
    assert p < 0.05


def test_slope_sign():
    assert ba._slope([1, 2, 3, 4], [100, 90, 80, 70]) == -10.0
    assert ba._slope([1, 2, 3], [5, 5, 5]) == 0.0


def _runs_fixture():
    rows = []
    for i in range(4):
        rows.append({"sample": f"s{i}", "stratum": "S1", "seq_in_stratum": i,
                     "arm": "O", "success": True, "partial_score": 1.0,
                     "z_self": 1, "tokens": 1000, "wall_s": 3600,
                     "timeout": False, "zero_output_share": 0.4,
                     "stall_s": 0, "pq_score": 0.8, "contaminated": False})
        rows.append({"sample": f"s{i}", "stratum": "S1", "seq_in_stratum": i,
                     "arm": "N", "success": True, "partial_score": 1.0,
                     "z_self": 1, "tokens": 600, "wall_s": 3000,
                     "timeout": False, "zero_output_share": 0.1,
                     "stall_s": 0, "pq_score": 0.8, "contaminated": False})
    return rows


def test_pairing_and_arm_stats():
    stats = ba.summarize(_runs_fixture())
    assert stats["pairs"] == 4
    o, n = stats["arms"]["O"], stats["arms"]["N"]
    assert o["success_rate"] == 1.0 and n["success_rate"] == 1.0
    assert n["token_median"] < o["token_median"]
    assert n["timeout_rate"] == 0.0


def test_h1_h4_verdicts_present_and_direction():
    verdicts = ba.hypotheses(_runs_fixture())
    assert set(verdicts) == {"H1", "H2", "H3", "H4"}
    assert verdicts["H1"]["verdict"] == "PASS"   # 0.1 < 0.4/2
    assert "p" in verdicts["H1"]


def test_timeout_dual_lens():
    rows = _runs_fixture()
    rows[1]["timeout"] = True   # the N run of pair s0
    rows[1]["success"] = False
    stats = ba.summarize(rows)
    assert "success_rate_done_only" in stats["arms"]["N"]
    assert stats["arms"]["N"]["timeout_rate"] == 0.25


def test_demo_deterministic_p_values(tmp_path):
    r1 = ba.run_demo(seed=7)
    r2 = ba.run_demo(seed=7)
    assert r1["report"] == r2["report"]
    assert "wilcoxon" in r1["report"] and "McNemar" in r1["report"]
