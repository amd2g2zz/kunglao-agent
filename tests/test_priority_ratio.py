# -*- coding: utf-8 -*-
"""tests/test_priority_ratio.py — the #107 Thompson ranker (issue #97 formula).

RED: the weighted formula score = [0.45·L + 0.30·D + 0.25·N]/cost is
DISCARDED (owner ruling, issue #107). The rebuilt value function:

    score = (Thompson case face + LAMBDA_DH · ΔH_PQ) · worth
    rank by Thompson sample; stable tie-break claim_id

The candidate filter is UNCHANGED (OPEN + attempts<3 + terminal-fact
parents) — the demolition only replaced the VALUE function, not the
dispatch frontier.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import priority_ratio as pr  # noqa: E402


# ---------- synthetic fixtures ----------

def _claim(cid, status="OPEN", answers_question=None,
           eta=0, attempts=0, statement=""):
    c = {"id": cid, "status": status, "evidence_tier_attempted": eta,
         "promotion_attempts": attempts, "statement": statement or cid}
    if answers_question is not None:
        c["answers_question"] = answers_question
    return c


def _evidence(ws=None, terminal_claims=(), verified=0):
    ev = pr.EvidenceView(
        terminal_fact_claims=frozenset(terminal_claims),
        verified_fact_count=verified,
        ws=Path(ws) if ws else None,
    )
    return ev


def _deps(depends_on=None):
    return {"depends_on": depends_on or {}, "competitor_groups": {}}


def _replica_sample(cid, alpha=1.0, beta=1.0):
    """Recompute the ranker's Thompson draw from outside (same fork scheme:
    ONE base draw from Random(0), per-claim child keyed by claim_id)."""
    base = random.Random(0).getrandbits(64)
    child = random.Random(f"thompson/{base}/{cid}")
    return child.betavariate(alpha, beta)


def _posteriors_ws(base, name="ws", cases=(), pqs=None):
    """Workspace with runs/posteriors.yaml (+ optional oracle case files)."""
    ws = base / name
    (ws / "runs").mkdir(parents=True)
    (ws / "oracle" / "cases").mkdir(parents=True)
    led = {"schema": "posteriors-schema/1", "cases": {}, "pqs": pqs or {}}
    for case_id, target_pq, a, b in cases:
        led["cases"][case_id] = {"alpha": a, "beta": b, "pending_entries": 0}
        (ws / "oracle" / "cases" / f"{case_id}.yaml").write_text(
            yaml.safe_dump({"id": case_id, "target_pq": target_pq}),
            encoding="utf-8")
    (ws / "runs" / "posteriors.yaml").write_text(
        yaml.safe_dump(led, allow_unicode=True), encoding="utf-8")
    return ws


# ---------- the rebuilt formula ----------

def test_thompson_composite_formula_not_weighted():
    """score == (Thompson case face + LAMBDA_DH·ΔH)·worth exactly; the
    weighted-era term fields are gone (owner ruling: 之前的不要了)."""
    claims = [_claim("C-1", statement="c2 config extract")]
    out = pr.priority_ratio(claims, _deps(), _evidence())
    assert len(out) == 1
    a = out[0]
    expected = round(_replica_sample("C-1") + pr.LAMBDA_DH * 0.0, 6)
    assert a.score == expected
    assert a.weight == 1.0
    for stale in ("leverage", "discriminator", "novelty", "gap_bucket",
                  "delta_disc", "expected_unlock", "unc"):
        assert not hasattr(a, stale), f"Action must not carry {stale}"


def test_pq_categorical_entropy_enters_score():
    """ΔH is mechanical on the categorical: a uniform 2-candidate PQ has
    H=1 bit, so the score rises by exactly LAMBDA_DH over the ΔH=0 case
    (the Thompson sample is invariant — the seed digest covers cases only)."""
    claims = [_claim("C-1", answers_question="q1")]
    ws = _posteriors_ws(_tmp_base(), pqs={"q1": {"candidates": {"a": 1, "b": 1}}})
    a = pr.priority_ratio(claims, _deps(), _evidence(ws))[0]
    bare = pr.priority_ratio(claims, _deps(), _evidence())[0]
    assert "dh_pq" in a.feeds and "1.0 bit" in a.feeds["dh_pq"]
    assert a.score == round(bare.score + pr.LAMBDA_DH * 1.0, 6)


def _tmp_base():
    import tempfile
    return Path(tempfile.mkdtemp(prefix="pr107-"))


# ---------- candidate filter (UNCHANGED by #107) ----------

def test_dependency_gate_blocks_child_of_unproven_parent():
    """a parent without a terminal fact blocks its child (no phase gate
    changes this — the dispatch frontier is the same on both ranks)."""
    claims = [_claim("C-1"), _claim("C-2")]
    out = pr.priority_ratio(claims, _deps({"C-2": ["C-1"]}), _evidence())
    assert [a.claim_id for a in out] == ["C-1"]


def test_dependency_gate_allows_child_of_terminal_fact_parent():
    """a parent holding a terminal fact is a satisfied dependency."""
    claims = [_claim("C-1"), _claim("C-2")]
    out = pr.priority_ratio(
        claims, _deps({"C-2": ["C-1"]}),
        _evidence(terminal_claims=["C-1"]))
    assert {a.claim_id for a in out} == {"C-1", "C-2"}


def test_attempts_cap_third_retry_excluded():
    claims = [_claim("C-1"), _claim("C-3", attempts=3)]
    out = pr.priority_ratio(claims, _deps(), _evidence())
    assert [a.claim_id for a in out] == ["C-1"]


def test_terminal_status_claims_never_ranked():
    """ratio's own is_open TERMINAL exclusion, pinned at the pure-function
    layer (unchanged by #107). A terminal-status claim must never appear in
    the action list."""
    claims = [_claim("C-1"), _claim("C-2", status="PROVEN"),
              _claim("C-3", status="DEFERRED")]
    out = pr.priority_ratio(claims, _deps(), _evidence())
    assert [a.claim_id for a in out] == ["C-1"]
    assert not pr.is_open({"id": "C-9", "status": "PROVEN"})
    assert not pr.is_open({"id": "C-9", "status": "DEFERRED"})


# ---------- case posterior hookup (#106 objects) ----------

def test_case_posterior_linked_via_target_pq():
    """oracle/cases/*.yaml target_pq == claim answers_question links the
    case; its Beta posterior is the Thompson sampling distribution."""
    claims = [_claim("C-1", answers_question="q1")]
    ws = _posteriors_ws(_tmp_base(), cases=[("case-1", "q1", 6.0, 1.0)])
    a = pr.priority_ratio(claims, _deps(), _evidence(ws))[0]
    assert a.score == round(_replica_sample("C-1", 6.0, 1.0), 6)
    assert "case-1" in a.feeds["thompson_sample"]
    assert "P(flip)=0.5" in a.feeds["case_flip_potential"]


def test_case_posterior_without_ledger_entry_uses_prior():
    """An oracle case file with no runner verdict yet samples Beta(1,1)."""
    claims = [_claim("C-1", answers_question="q1")]
    ws = _posteriors_ws(_tmp_base())
    (ws / "oracle" / "cases" / "case-9.yaml").write_text(
        yaml.safe_dump({"id": "case-9", "target_pq": "q1"}), encoding="utf-8")
    a = pr.priority_ratio(claims, _deps(), _evidence(ws))[0]
    assert a.score == round(_replica_sample("C-1"), 6)
    assert "case-9" in a.feeds["thompson_sample"]


def test_flip_potential_decays_and_falls_back():
    """The conservative P(flip) diagnostic: 0.5 cold start, attempts-decayed
    when a case is linked, floored to 0.3 with no linkage at all."""
    fresh = pr.priority_ratio([_claim("C-1", answers_question="q1")], _deps(),
                              _evidence(_posteriors_ws(
                                  _tmp_base(), cases=[("c", "q1", 1, 1)])))[0]
    decayed = pr.priority_ratio([_claim("C-1", answers_question="q1",
                                        attempts=2)], _deps(),
                                _evidence(_posteriors_ws(
                                    _tmp_base(), cases=[("c", "q1", 1, 1)])))[0]
    orphan = pr.priority_ratio([_claim("C-1")], _deps(), _evidence())[0]
    assert "P(flip)=0.5" in fresh.feeds["case_flip_potential"]
    assert "P(flip)=0.167" in decayed.feeds["case_flip_potential"]
    assert f"{pr.FLIP_POTENTIAL_FALLBACK} fallback" in \
        orphan.feeds["case_flip_potential"]


def test_worth_weight_multiplies_the_composite():
    """#759 worth channel survives as the exogenous multiplier."""
    claims = [_claim("C-1", statement="rce chain")]
    worth = pr.priority_ratio(
        claims, _deps(), pr.EvidenceView(value_class_weights={"rce": 4.0}))[0]
    assert worth.weight == 4.0
    assert worth.score == round(_replica_sample("C-1") * 4.0, 6)


# ---------- ordering properties ----------

def test_sorted_by_sample_then_claim_id():
    """Thompson sample descending; the sort key is stable (-score, claim_id)
    even when rounding collides."""
    claims = [_claim(f"C-{i}", statement="work") for i in range(1, 8)]
    out = pr.priority_ratio(claims, _deps(), _evidence())
    keys = [(-a.score, a.claim_id) for a in out]
    assert keys == sorted(keys)


def test_register_reorder_never_reshuffles():
    """Same register content, different file order → identical ranking
    (the per-claim rng fork is keyed by claim_id, not list position)."""
    claims = [_claim("C-1", statement="work one"),
              _claim("C-2", statement="work two"),
              _claim("C-3", statement="work three", eta=1)]
    a = [x.to_dict() for x in pr.priority_ratio(claims, _deps(), _evidence())]
    b = [x.to_dict() for x in
         pr.priority_ratio(list(reversed(claims)), _deps(), _evidence())]
    assert a == b


def test_seed_injection_varies_the_sample():
    """A different tick seed may reorder arms (Thompson's intrinsic
    exploration) while staying self-consistent for that seed."""
    claims = [_claim(f"C-{i}", statement="work") for i in range(1, 7)]
    ev = _evidence()
    s0 = [x.to_dict() for x in pr.priority_ratio(
        claims, _deps(), ev, rng=random.Random(0))]
    s0b = [x.to_dict() for x in pr.priority_ratio(
        claims, _deps(), ev, rng=random.Random(0))]
    s7 = [x.to_dict() for x in pr.priority_ratio(
        claims, _deps(), ev, rng=random.Random(7))]
    assert s0 == s0b
    assert {d["claim_id"] for d in s7} == {d["claim_id"] for d in s0}


# ---------- pure function / zero LLM (unchanged intent) ----------

def test_scoring_is_deterministic_pure():
    """same input → same output (no hidden LLM/state; default seed pinned)."""
    claims = [_claim("C-1", statement="c2"), _claim("C-2", statement="家族 vidar")]
    deps = _deps({"C-2": ["C-1"]})
    ev = _evidence()
    o1 = pr.priority_ratio(claims, deps, ev)
    o2 = pr.priority_ratio(claims, deps, ev)
    assert [a.to_dict() for a in o1] == [a.to_dict() for a in o2]


def test_cost_field_is_tier_diagnostic_only():
    """cost still reports the tier price but no longer divides the score
    (cold-start cheapness spread died with the phase gate)."""
    claims = [_claim("C-cheap", eta=0), _claim("C-deep", eta=2)]
    out = {a.claim_id: a for a in pr.priority_ratio(claims, _deps(), _evidence())}
    assert out["C-cheap"].cost == 1.0 and out["C-deep"].cost == 10.0
    for a in out.values():
        assert a.score == round(_replica_sample(a.claim_id), 6)
