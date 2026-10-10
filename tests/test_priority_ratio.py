# -*- coding: utf-8 -*-
"""tests/test_priority_ratio.py — the #107 Thompson ranker (issue #97 formula).

RED: the weighted formula score = [0.45·L + 0.30·D + 0.25·N]/cost is
DISCARDED (owner ruling, issue #107). The rebuilt value function:

    score = (Thompson case face + W_DOWNSTREAM · downstream_term) · worth
    rank by Thompson sample; stable tie-break claim_id

(#295 governed removal, ADR-001 docs/adr-001-strategy-parameter-
governance.md: the LAMBDA_DH·ΔH_PQ face is GONE — EXP-B proved ΔH ≡ 0 on
612/612 real rank events and #294 proved λ-invariance byte-identical, so
the removal is a runtime no-op on history. A PQ categorical in the
ledger no longer lifts any score.)

The candidate filter is UNCHANGED (OPEN + attempts<3 + terminal-fact
parents) — the demolition only replaced the VALUE function, not the
dispatch frontier.
"""
from __future__ import annotations

import hashlib
import json
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
    """score == (Thompson case face + W_DOWNSTREAM·downstream_term)·worth
    exactly (no ΔH face — #295 removal); the weighted-era term fields are
    gone (owner ruling: 之前的不要了)."""
    claims = [_claim("C-1", statement="c2 config extract")]
    out = pr.priority_ratio(claims, _deps(), _evidence())
    assert len(out) == 1
    a = out[0]
    expected = round(_replica_sample("C-1"), 6)
    assert a.score == expected
    assert a.weight == 1.0
    for stale in ("leverage", "discriminator", "novelty", "gap_bucket",
                  "delta_disc", "expected_unlock", "unc"):
        assert not hasattr(a, stale), f"Action must not carry {stale}"


def test_pq_categorical_entropy_is_rank_inert():
    """#295 removal pin: a populated PQ categorical (uniform 2-candidate,
    H=1 bit) does NOT move the score — the ΔH face is gone (ADR-001).
    The Thompson sample is invariant (the seed digest covers cases only),
    so the score is byte-identical to the no-categorical case."""
    claims = [_claim("C-1", answers_question="q1")]
    ws = _posteriors_ws(_tmp_base(), pqs={"q1": {"candidates": {"a": 1, "b": 1}}})
    a = pr.priority_ratio(claims, _deps(), _evidence(ws))[0]
    bare = pr.priority_ratio(claims, _deps(), _evidence())[0]
    assert "dh_pq" not in a.feeds, "the dh_pq feed was removed by #295"
    assert a.score == bare.score, "no ΔH lift may survive the #295 removal"


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


# ---------- Thompson seed contract (EXP-1: seed = f(posterior_state, round)) ----------

CASES_251 = [   # (case_id, target_pq, alpha, beta) — means .667 / .500 / .250
    ("case-alpha", "pq.net", 4.0, 2.0),
    ("case-beta", "pq.crypto", 2.0, 2.0),
    ("case-gamma", "pq.pack", 1.0, 3.0),
]

CLAIMS_251 = [_claim("C1", answers_question="pq.net"),
              _claim("C2", answers_question="pq.crypto"),
              _claim("C3", answers_question="pq.pack")]

CONV_LEDGER = ".convergence_ledger.jsonl"   # == convergence_check.LEDGER_NAME


def _append_round(ws, open_count=3, ts="2026-09-18T00:00:00"):
    """One convergence_check snapshot row (the writer's row shape,
    convergence_check._append_ledger) — advances the round index by 1."""
    row = {"ts": ts, "decision": "DISPATCH", "open_count": open_count,
           "open_ids": ["C1", "C2", "C3"], "partial_count": 0,
           "active_workers": 0, "blockers": [], "facts_total": 1,
           "dispatched_ids": []}
    with (Path(ws) / CONV_LEDGER).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _rank_with_rng(ws, rng):
    """Rank the three linked claims through the real production ranker."""
    return tuple(a.claim_id for a in pr.priority_ratio(
        [dict(c) for c in CLAIMS_251], _deps(), _evidence(ws=ws), rng=rng))


def test_251_round_index_counts_convergence_snapshots_only(tmp_path):
    """Accessor: round := RAW snapshot rows (no "type", has "open_count" —
    the convergence_health.assess snapshot filter); OPERATOR_ACTION/event
    rows and unparseable dirty lines are skipped; absent ledger -> 0."""
    ws = tmp_path
    ws.joinpath(CONV_LEDGER).write_text(
        json.dumps({"ts": "t1", "decision": "DISPATCH", "open_count": 3,
                    "open_ids": ["C1"], "facts_total": 1}) + "\n"
        + json.dumps({"type": "OPERATOR_ACTION", "action": "defer",
                      "open_count": 3}) + "\n"
        + "not json at all\n"
        + json.dumps({"ts": "t2", "decision": "DISPATCH", "open_count": 3,
                      "open_ids": ["C1"], "facts_total": 1}) + "\n",
        encoding="utf-8")
    assert pr.round_index(ws) == 2
    assert pr.round_index(tmp_path / "absent-ws") == 0


def test_251_round_index_is_raw_count_not_dedup_rounds(tmp_path):
    """The ruling's edge: two same-open_count snapshots inside the dedup
    wall-clock window collapse in convergence_health (rounds=1) but MUST
    advance the raw round (2) — wiring assess()["rounds"] would leak the
    clock into the seed and break machine-independent replay."""
    import convergence_health as ch
    ws = tmp_path
    for i in range(2):
        _append_round(ws, ts=f"2026-09-18T00:00:0{i}")
    assert pr.round_index(ws) == 2
    ledger = [json.loads(ln) for ln
              in (ws / CONV_LEDGER).read_text(encoding="utf-8").splitlines()
              if ln.strip()]
    assert ch.assess(ledger)["rounds"] == 1


def test_251_accessor_ledger_name_matches_the_writer():
    """The accessor reads the convergence_check writer's file, by name."""
    import convergence_check
    assert pr.CONV_LEDGER_NAME == convergence_check.LEDGER_NAME


def test_251_p1_same_posteriors_same_round_is_replayable(tmp_path):
    """P1: f(posterior_state, round) is deterministic — same inputs give
    the identical seed, identical rng base draw AND identical ranking."""
    ws = _posteriors_ws(tmp_path, cases=CASES_251)
    s1 = pr.case_face_seed(pr.PosteriorLedger.load(ws), 7)
    s2 = pr.case_face_seed(pr.PosteriorLedger.load(ws), 7)
    assert s1 == s2
    assert random.Random(s1).getrandbits(64) == random.Random(s2).getrandbits(64)
    assert _rank_with_rng(ws, random.Random(s1)) == _rank_with_rng(ws, random.Random(s2))


def test_251_p2_static_posteriors_advancing_round_moves_rng_base(tmp_path):
    """P2 seed liveness (the hard, deterministic half): STATIC posteriors +
    advancing round -> every posterior_rng base draw distinct. v1 froze
    5/5 rounds onto ONE rng_base (the frozen defect; 53 consecutive in the
    wild)."""
    ws = _posteriors_ws(tmp_path, cases=CASES_251)
    bases = []
    for _ in range(5):
        _append_round(ws)
        bases.append(pr.posterior_rng(ws).getrandbits(64))
    assert len(set(bases)) == 5


def test_251_p2_static_posteriors_advancing_round_unfreezes_ranking(tmp_path):
    """P2 ranking liveness (the separate observable — seed liveness does
    not imply ranking liveness on a coarse register): the ranking
    trajectory over advancing rounds is not one frozen order."""
    ws = _posteriors_ws(tmp_path, cases=CASES_251)
    ranks = []
    for _ in range(5):
        _append_round(ws)
        ranks.append(_rank_with_rng(ws, pr.posterior_rng(ws)))
    assert len(set(ranks)) >= 2


def test_251_p3_posterior_change_moves_seed_and_ranking(tmp_path):
    """P3: a runner verdict (case-beta alpha 2 -> 6, mean .5 -> .75) moves
    the seed AND the ranking at the same round."""
    ws_a = _posteriors_ws(tmp_path, name="a", cases=CASES_251)
    ws_b = _posteriors_ws(tmp_path, name="b", cases=[
        ("case-alpha", "pq.net", 4.0, 2.0),
        ("case-beta", "pq.crypto", 6.0, 2.0),   # green verdict: mean .5 -> .75
        ("case-gamma", "pq.pack", 1.0, 3.0)])
    s_a = pr.case_face_seed(pr.PosteriorLedger.load(ws_a), 0)
    s_b = pr.case_face_seed(pr.PosteriorLedger.load(ws_b), 0)
    assert s_a != s_b
    assert _rank_with_rng(ws_a, random.Random(s_a)) != _rank_with_rng(ws_b, random.Random(s_b))


def test_251_cold_start_seed_moves_with_round():
    """Cold start unfreeze (direct seed face): the empty cases doc hashes
    WITH the round — v1's docstring presented the constant cold seed as a
    feature ("no clock and no counter file")."""
    assert pr.case_face_seed(pr.PosteriorLedger(), 0) != \
        pr.case_face_seed(pr.PosteriorLedger(), 1)
    assert len({pr.case_face_seed(pr.PosteriorLedger(), r)
                for r in range(5)}) == 5


def test_251_cold_start_production_rng_not_constant(tmp_path):
    """Cold start unfreeze (production face): posterior_rng must not
    short-circuit to Random(0) on an empty/absent posteriors ledger — a
    workspace with a live convergence ledger but no verdicts yet still
    moves its Thompson base draw every round."""
    ws = _posteriors_ws(tmp_path)   # posteriors.yaml exists, zero cases
    frozen = random.Random(0).getrandbits(64)
    bases = []
    for _ in range(5):
        _append_round(ws)
        bases.append(pr.posterior_rng(ws).getrandbits(64))
    assert len(set(bases)) == 5
    assert frozen not in bases


def test_251_rank_feeds_fingerprint_carries_round(tmp_path, monkeypatch):
    """Frozen sampling OBSERVABLE (owner ruling): the rank_feeds
    input_fingerprint doc carries the round next to rng_base — a tail
    reader detects frozen sampling as equal rng_base across advancing
    rounds in a one-line delta. The fingerprint hash covers the round."""
    import kunglao_log
    calls: list[dict] = []

    def _fake_emit(ws, actor, action, **kw):
        calls.append({"ws": ws, "actor": actor, "action": action, **kw})
        return True

    monkeypatch.setattr(kunglao_log, "emit", _fake_emit)
    ws = _posteriors_ws(tmp_path, cases=CASES_251)
    _append_round(ws)
    _append_round(ws)
    _rank_with_rng(ws, pr.posterior_rng(ws))
    rows = [json.loads(c["detail"]) for c in calls if c["action"] == "rank_feeds"]
    assert len(rows) == 1
    fp = rows[0]["input_fingerprint"]
    assert fp["round"] == 2
    canon = {k: v for k, v in fp.items() if k != "fingerprint"}
    assert fp["fingerprint"] == hashlib.sha256(json.dumps(
        canon, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
