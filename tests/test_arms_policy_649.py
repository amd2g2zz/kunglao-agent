# -*- coding: utf-8 -*-
"""tests/test_arms_policy_649.py — the comparison-arm-set policy pins
(#649 owner rulings 2026-10-10): floor 3 / default 5 / ceiling 8, their
ordering, the dispatch_gate single-source alias, and the expansion-admit
ceiling clamp. Synthetic fixtures."""
from __future__ import annotations


def test_policy_trio_and_ordering():
    import arms_policy as ap
    assert ap.MIN_COMPARISON_ARMS == 3
    assert ap.DEFAULT_COMPARISON_ARMS == 5
    assert ap.MAX_COMPARISON_ARMS == 8
    assert (ap.MIN_COMPARISON_ARMS <= ap.DEFAULT_COMPARISON_ARMS
            <= ap.MAX_COMPARISON_ARMS)


def test_dispatch_gate_reads_the_single_source():
    import arms_policy as ap
    import dispatch_gate as dg
    assert dg.MIN_ADMITTED_CANDIDATES == ap.MIN_COMPARISON_ARMS


def test_expansion_admit_clamps_to_the_ceiling():
    from arms_policy import MAX_COMPARISON_ARMS
    from rlvr import expansion as ex
    hyps = [{"id": f"H-{i:02d}", "features": {f"tok{i}": 1},
             "p_llm": 0.5, "policy": 0.5} for i in range(12)]
    out = ex.admit(hyps, existing_features=[], n=99)
    assert len(out) == MAX_COMPARISON_ARMS  # the #649 pool-ceiling clamp


def test_library_split_and_ordering():
    import arms_policy as ap
    assert ap.LIBRARY_MAX_COMPARISON_ARMS == 16
    assert ap.MAX_COMPARISON_ARMS <= ap.LIBRARY_MAX_COMPARISON_ARMS


def test_family_live_arms_counts_non_terminal(tmp_path):
    """The library-cap read face (#649): minted OPEN arms count; the
    active/library split rides on it."""
    from hypothesis_bridge import family_live_arms, mint_family_arms
    from test_hypothesis_bridge_252 import _mk_hyp
    ws = tmp_path / "ws"
    (ws / "hypotheses").mkdir(parents=True)
    (ws / "runs").mkdir()
    (ws / "claim-register.yaml").write_text("claims: []\n",
                                            encoding="utf-8")
    _mk_hyp(ws, "H-001")
    r = mint_family_arms(ws, "H-001",
                         [f"cand-{i:02d}" for i in range(4)],
                         answers_question="q1")
    assert r["refused"] is None
    assert family_live_arms(ws, "H-001") == 4
