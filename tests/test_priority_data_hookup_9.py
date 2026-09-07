# -*- coding: utf-8 -*-
"""tests/test_priority_data_hookup_9.py — #107: the ranker consumes the
#106 probability objects (runs/posteriors.yaml + oracle/cases/*.yaml).

History: issue #9 wired the OLD weighted formula to mission_ledger /
difficulty / strategy-log feeds. Issue #107 discarded that formula ("之前的
不要了") — those feeds died WITH it. This suite now pins the rebuilt data
hookup: the workspace's case posteriors (Bernoulli) and PQ categoricals
reach the Thompson composite, missing feeds stay NEUTRAL with an explicit
reason, and corruption degrades fail-open (never fakes a signal).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import priority_ratio as pr  # noqa: E402
from posteriors import CasePosterior, PQCategorical, PosteriorLedger  # noqa: E402
from posteriors import PosteriorSchemaError  # noqa: E402


def _claim(cid, status="OPEN", answers_question=None, statement=""):
    c = {"id": cid, "status": status, "evidence_tier_attempted": 0,
         "promotion_attempts": 0, "statement": statement or cid}
    if answers_question is not None:
        c["answers_question"] = answers_question
    return c


def _mk_ws(tmp_path, name="ws", claims=()):
    ws = tmp_path / name
    ws.mkdir(parents=True)
    (ws / "oracle" / "cases").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": list(claims)}, allow_unicode=True),
        encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"primary_questions": {}}, allow_unicode=True),
        encoding="utf-8")
    return ws


def _write_ledger(ws, cases=(), pqs=()):
    led = PosteriorLedger()
    for case_id, a, b in cases:
        led.cases[case_id] = CasePosterior(case_id, alpha=a, beta=b)
    for pq_id, candidates in pqs:
        led.pqs[pq_id] = PQCategorical(pq_id, candidates)
    led.save(ws)
    return led


def _oracle_case(ws, case_id, target_pq):
    (ws / "oracle" / "cases" / f"{case_id}.yaml").write_text(
        yaml.safe_dump({"id": case_id, "target_pq": target_pq}),
        encoding="utf-8")


def _prior_sample(cid, alpha=1.0, beta=1.0):
    """Replica of the ranker's default-seed fork (Random(0) base, claim-keyed
    child) — lets tests assert the exact draw a cold-start case produces."""
    import random
    base = random.Random(0).getrandbits(64)
    return random.Random(f"thompson/{base}/{cid}").betavariate(alpha, beta)


# ---------- case posterior -> Thompson sample ----------

def test_case_posterior_feeds_thompson_sample(tmp_path):
    """GREEN prior (Beta(6,1)) vs RED prior (Beta(1,6)): the same claim's
    Thompson sample moves with the posterior — the runner verdict IS the
    reward signal (owner ruling, #106/#107)."""
    ws_green = _mk_ws(tmp_path, "green", claims=[_claim("C-1", answers_question="q1")])
    ws_red = _mk_ws(tmp_path, "red", claims=[_claim("C-1", answers_question="q1")])
    for ws, a, b in ((ws_green, 6.0, 1.0), (ws_red, 1.0, 6.0)):
        _oracle_case(ws, "case-1", "q1")
        _write_ledger(ws, cases=[("case-1", a, b)])
    green = pr.priority_ratio([_claim("C-1", answers_question="q1")], {},
                              pr.EvidenceView.from_workspace(ws_green))[0]
    red = pr.priority_ratio([_claim("C-1", answers_question="q1")], {},
                            pr.EvidenceView.from_workspace(ws_red))[0]
    assert green.score > red.score, (
        "a case the runner keeps passing must sample above one it keeps "
        "failing (Thompson over the Bernoulli posterior)")
    assert "case-1" in green.feeds["thompson_sample"]
    assert "case-1" in red.feeds["thompson_sample"]


def test_pq_categorical_feeds_dh(tmp_path):
    """A PQ categorical in the ledger carries ΔH: the entropy the categorical
    still carries (the updatable quantity) enters the score mechanically."""
    claims = [_claim("C-1", answers_question="q1")]
    ws = _mk_ws(tmp_path, claims=claims)
    _write_ledger(ws, pqs=[("q1", {"plain-md5": 1.0, "salted-composite": 1.0})])
    ev = pr.EvidenceView.from_workspace(ws)
    a = pr.priority_ratio(claims, {}, ev)[0]
    cat = PosteriorLedger.load(ws).pqs["q1"]
    assert a.feeds["dh_pq"] == f"PQ 'q1' categorical H={round(cat.entropy(), 6)} bit"
    bare = pr.priority_ratio(claims, {}, pr.EvidenceView())[0]
    assert a.score == round(bare.score + pr.LAMBDA_DH * cat.entropy(), 6)


def test_peaked_categorical_has_little_left_to_flip(tmp_path):
    """A near-decided PQ (one candidate holds ~all mass) has ΔH≈0 — an
    observation there buys almost nothing (the entropy admission quantity)."""
    claims = [_claim("C-1", answers_question="q1")]
    ws = _mk_ws(tmp_path, claims=claims)
    _write_ledger(ws, pqs=[("q1", {"plain-md5": 99.0, "salted-composite": 1.0})])
    a = pr.priority_ratio(claims, {}, pr.EvidenceView.from_workspace(ws))[0]
    assert "dH=0" not in a.feeds["dh_pq"]
    assert "H=0.08" in a.feeds["dh_pq"]


# ---------- neutral fallbacks (fail-open discipline) ----------

def test_cold_start_neutral_no_posteriors(tmp_path):
    """No posteriors.yaml / no oracle cases → Beta(1,1) prior sample +
    explicit 0.3 fallback on the flip potential (absence is never signal)."""
    claims = [_claim("C-1", answers_question="q1")]
    ws = _mk_ws(tmp_path, claims=claims)
    ev = pr.EvidenceView.from_workspace(ws)
    assert ev.ws == ws
    a = pr.priority_ratio(claims, {}, ev)[0]
    assert "Beta(1,1) prior" in a.feeds["thompson_sample"]
    assert f"{pr.FLIP_POTENTIAL_FALLBACK} fallback" in a.feeds["case_flip_potential"]
    assert "no PQ categorical" in a.feeds["dh_pq"]


def test_oracle_case_without_verdict_uses_prior(tmp_path):
    """A scaffolded case (targets pinned, expected pending, zero runner
    rounds) is exactly the cold-start shape: Beta(1,1) sample."""
    claims = [_claim("C-1", answers_question="q1")]
    ws = _mk_ws(tmp_path, claims=claims)
    _oracle_case(ws, "case-1", "q1")  # no runs/posteriors.yaml entry
    a = pr.priority_ratio(claims, {}, pr.EvidenceView.from_workspace(ws))[0]
    assert "case-1" in a.feeds["thompson_sample"]


def test_bare_view_no_ws_still_ranks():
    """EvidenceView() with no ws (pure-function contract §1) ranks with
    prior samples and zero ΔH — never a crash, never a fake feed."""
    a = pr.priority_ratio([_claim("C-1")], {}, pr.EvidenceView())[0]
    assert "Beta(1,1) prior" in a.feeds["thompson_sample"]
    assert a.feeds["dh_pq"].endswith("-> dH=0")


def test_corrupt_ledger_fails_open(tmp_path):
    """Garbage posteriors.yaml → degraded EMPTY ledger (fail-open, #103
    layering): the linked case falls back to its Beta(1,1) prior — not a
    crash, not a faked signal."""
    claims = [_claim("C-1", answers_question="q1")]
    ws = _mk_ws(tmp_path, claims=claims)
    _oracle_case(ws, "case-1", "q1")
    (ws / "runs").mkdir(exist_ok=True)
    (ws / "runs" / "posteriors.yaml").write_text("{not: [valid: yaml",
                                                 encoding="utf-8")
    ev = pr.EvidenceView.from_workspace(ws)
    a = pr.priority_ratio(claims, {}, ev)[0]
    assert "case-1" in a.feeds["thompson_sample"]
    assert a.score == round(_prior_sample("C-1"), 6)


def test_unknown_ledger_schema_raises_loud(tmp_path):
    """The #106 version wall: an unknown schema version raises
    PosteriorSchemaError out of the ranker — DECIDE lands conservative
    BLOCKED, the dispatch gate fails open with a trace. Never a silent
    wrong-schema read (no-backcompat policy)."""
    claims = [_claim("C-1", answers_question="q1")]
    ws = _mk_ws(tmp_path, claims=claims)
    _oracle_case(ws, "case-1", "q1")
    (ws / "runs").mkdir(exist_ok=True)
    (ws / "runs" / "posteriors.yaml").write_text(
        "schema: posteriors-schema/999\ncases: {}\npqs: {}\n", encoding="utf-8")
    with pytest.raises(PosteriorSchemaError):
        pr.priority_ratio(claims, {}, pr.EvidenceView.from_workspace(ws))


def test_unreadable_oracle_case_is_skipped(tmp_path):
    """A corrupt oracle case file is not signal — skipped, the claim falls
    back to the prior sample (fail-open per file)."""
    claims = [_claim("C-1", answers_question="q1")]
    ws = _mk_ws(tmp_path, claims=claims)
    (ws / "oracle" / "cases" / "bad.yaml").write_text("{broken", encoding="utf-8")
    a = pr.priority_ratio(claims, {}, pr.EvidenceView.from_workspace(ws))[0]
    assert "bad" not in a.feeds["thompson_sample"]


def test_no_ws_dir_at_all_no_crash(tmp_path):
    """A workspace without runs/ or oracle/ at all — from_workspace must not
    raise and the ranking stays fully cold-start."""
    ws = tmp_path / "bare"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [_claim("C-1")]}, allow_unicode=True),
        encoding="utf-8")
    ev = pr.EvidenceView.from_workspace(ws)
    out = pr.priority_ratio([_claim("C-1")], {}, ev)
    assert len(out) == 1
    assert ev.ws == ws


# ---------- differentiation (the loop closes on posterior dynamics) ----------

def test_posterior_state_changes_the_rank(tmp_path):
    """Two workspaces identical except one case posterior: the rank order
    follows the runner verdicts — same posterior state → same rank
    (determinism clause); different state → the sample moves."""
    claims = [_claim("C-1", answers_question="q1"),
              _claim("C-2", answers_question="q2")]
    ws1 = _mk_ws(tmp_path, "ws1", claims=claims)
    ws2 = _mk_ws(tmp_path, "ws2", claims=claims)
    for ws in (ws1, ws2):
        _oracle_case(ws, "case-1", "q1")
        _oracle_case(ws, "case-2", "q2")
    _write_ledger(ws1, cases=[("case-1", 6.0, 1.0), ("case-2", 1.0, 6.0)])
    _write_ledger(ws2, cases=[("case-1", 1.0, 6.0), ("case-2", 6.0, 1.0)])
    top1 = pr.priority_ratio(claims, {}, pr.EvidenceView.from_workspace(ws1))[0]
    top2 = pr.priority_ratio(claims, {}, pr.EvidenceView.from_workspace(ws2))[0]
    assert top1.claim_id == "C-1" and top2.claim_id == "C-2", (
        "the runner verdicts must drive which arm ranks first (the value "
        "loop closes on posterior dynamics)")
