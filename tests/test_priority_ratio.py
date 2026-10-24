# -*- coding: utf-8 -*-
"""tests/test_priority_ratio.py — the deterministic evidence ranker
(#792: value = posterior mean; exploration explicit).

HISTORY: the weighted formula score = [0.45·L + 0.30·D + 0.25·N]/cost was
DISCARDED (owner ruling, issue #107); #792 retired the round-seeded
Thompson draw face and the Beta(1,1) unlinked fallback. The live value
function:

    score = (posterior-mean case value + W_DOWNSTREAM · downstream_term) · worth
    rank value-bearing claims by score; unlinked claims DEMOTED below every
    value-bearing one by the declared default (downstream_term, tier, worth);
    stable tie-break claim_id; same inputs -> byte-identical ranking, ANY round

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

import json
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

def test_composite_formula_not_weighted():
    """score == (posterior-mean case value + W_DOWNSTREAM·downstream_term)·worth
    exactly (no ΔH face — #295 removal; no draw face — #792); the
    weighted-era term fields are gone (owner ruling: 之前的不要了)."""
    claims = [_claim("C-1", answers_question="q1")]
    ws = _posteriors_ws(_tmp_base(), cases=[("case-1", "q1", 6.0, 1.0)])
    out = pr.priority_ratio(claims, _deps(), _evidence(ws))
    assert len(out) == 1
    a = out[0]
    expected = round((6.0 / 7.0 + pr.W_DOWNSTREAM * 0.0) * 1.0, 6)
    assert a.score == expected
    assert a.weight == 1.0
    for stale in ("leverage", "discriminator", "novelty", "gap_bucket",
                  "delta_disc", "expected_unlock", "unc"):
        assert not hasattr(a, stale), f"Action must not carry {stale}"


def test_unlinked_claim_has_no_fabricated_value():
    """#792: a claim with no oracle linkage has NO value channel — its
    score is exactly 0.0 (the Beta(1,1) fallback draw is retired), and the
    feeds say so with the arm-oracle-cases hint."""
    claims = [_claim("C-1", statement="c2 config extract")]
    a = pr.priority_ratio(claims, _deps(), _evidence())[0]
    assert a.score == 0.0
    assert "unlinked — no value channel" in a.feeds["case_value"]
    assert "arm oracle cases" in a.feeds["case_value"]
    a2 = pr.priority_ratio(claims, _deps(), _evidence())[0]
    assert a2.score == 0.0


def test_pq_categorical_entropy_is_rank_inert():
    """#295 removal pin (kept under #792): a populated PQ categorical
    (uniform 2-candidate, H=1 bit) does NOT move the score — the ΔH face
    is gone (ADR-001) and the #792 mean face never reads the categorical
    either, so the score is byte-identical to the no-categorical case."""
    claims = [_claim("C-1", answers_question="q1")]
    cases = [("case-1", "q1", 6.0, 1.0)]
    ws_cat = _posteriors_ws(_tmp_base(), cases=cases,
                            pqs={"q1": {"candidates": {"a": 1, "b": 1}}})
    ws_bare = _posteriors_ws(_tmp_base(), cases=cases)
    a = pr.priority_ratio(claims, _deps(), _evidence(ws_cat))[0]
    bare = pr.priority_ratio(claims, _deps(), _evidence(ws_bare))[0]
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
    case; its Beta posterior MEAN is the value face (#792)."""
    claims = [_claim("C-1", answers_question="q1")]
    ws = _posteriors_ws(_tmp_base(), cases=[("case-1", "q1", 6.0, 1.0)])
    a = pr.priority_ratio(claims, _deps(), _evidence(ws))[0]
    assert a.score == round(6.0 / 7.0, 6)
    assert "case-1" in a.feeds["case_value"]
    assert "posterior mean" in a.feeds["case_value"]
    assert "P(flip)=0.5" in a.feeds["case_flip_potential"]


def test_case_posterior_without_ledger_entry_uses_prior():
    """An oracle case file with no runner verdict yet folds the NEUTRAL
    prior mean 0.5 — a declared prior, never a fabricated draw (#792)."""
    claims = [_claim("C-1", answers_question="q1")]
    ws = _posteriors_ws(_tmp_base())
    (ws / "oracle" / "cases" / "case-9.yaml").write_text(
        yaml.safe_dump({"id": "case-9", "target_pq": "q1"}), encoding="utf-8")
    a = pr.priority_ratio(claims, _deps(), _evidence(ws))[0]
    assert a.score == 0.5
    assert "case-9" in a.feeds["case_value"]


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
    claims = [_claim("C-1", answers_question="q1", statement="rce chain")]
    ws = _posteriors_ws(_tmp_base(), cases=[("case-1", "q1", 6.0, 1.0)])
    worth = pr.priority_ratio(
        claims, _deps(),
        pr.EvidenceView(value_class_weights={"rce": 4.0}, ws=ws))[0]
    assert worth.weight == 4.0
    assert worth.score == round((6.0 / 7.0) * 4.0, 6)


# ---------- ordering properties ----------

def test_sorted_by_value_then_claim_id():
    """Value-bearing claims by score descending; the sort key is stable
    (-score, claim_id) even when rounding collides. All-linked register:
    means differ, so the order must follow the means exactly."""
    cases = [(f"case-{i}", f"q{i}", 1.0 + i, 1.0) for i in range(1, 8)]
    claims = [_claim(f"C-{i}", answers_question=f"q{i}", statement="work")
              for i in range(1, 8)]
    ws = _posteriors_ws(_tmp_base(), cases=cases)
    out = pr.priority_ratio(claims, _deps(), _evidence(ws))
    keys = [(-a.score, a.claim_id) for a in out]
    assert keys == sorted(keys)
    scores = [a.score for a in out]
    assert scores == sorted(scores, reverse=True)


def test_unlinked_band_orders_by_declared_default():
    """#792: within the demoted unlinked band the order is the declared
    deterministic default (downstream_term, tier, worth) — here tier and
    worth differentiate (all dterms are 0 with no deps)."""
    claims = [_claim("C-hub", statement="work", eta=2),
              _claim("C-leaf", statement="rce chain"),
              _claim("C-mid", statement="work", eta=1)]
    out = pr.priority_ratio(claims, _deps(),
                            pr.EvidenceView(value_class_weights={"rce": 4.0}))
    tiers = {a.claim_id: a.tier for a in out}
    ids = [a.claim_id for a in out]
    assert set(ids) == {"C-hub", "C-leaf", "C-mid"}
    # tier ascending then worth descending (dterm ties at 0): C-leaf (tier1,
    # worth 4) first; C-mid (tier2) before C-hub (tier3)
    assert ids == ["C-leaf", "C-mid", "C-hub"], ids
    assert tiers["C-leaf"] == 1


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


def test_no_seed_axis_exists():
    """#792 (the retired #107 face): there is no rng parameter and no
    Thompson draw — a ranking column may not move because a counter or a
    seed moved. The cross-round identity is pinned by
    tests/test_ranker_determinism_792.py on linked and mixed registers."""
    import inspect
    assert "rng" not in inspect.signature(pr.priority_ratio).parameters
    claims = [_claim(f"C-{i}", statement="work") for i in range(1, 7)]
    ev = _evidence()
    s0 = [x.to_dict() for x in pr.priority_ratio(claims, _deps(), ev)]
    s0b = [x.to_dict() for x in pr.priority_ratio(claims, _deps(), ev)]
    assert s0 == s0b


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
        assert a.score == 0.0  # unlinked: no value channel (#792)
        assert a.cost in (1.0, 10.0)


# ---------- the retired seed contract (#251 -> #792 inversion) ----------

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


def _rank_at(ws, rnd):
    """Rank the three linked claims through the real production ranker."""
    return json.dumps(
        [a.to_dict() for a in pr.priority_ratio(
            [dict(c) for c in CLAIMS_251], _deps(), _evidence(ws=ws),
            round_no=rnd)],
        sort_keys=True)


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
    advance the raw round (2) — the round axis stays an append-order
    counter, machine-independent (it is bookkeeping under #792, never a
    rank input)."""
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


def test_792_p1_same_inputs_same_ranking(tmp_path):
    """P1 (inverted from the seed face): same inputs give the identical
    ranking — twice in a row, at the same round or any other."""
    ws = _posteriors_ws(tmp_path, cases=CASES_251)
    r1 = _rank_at(ws, 7)
    r2 = _rank_at(ws, 7)
    r3 = _rank_at(ws, 8)
    assert r1 == r2 == r3


def test_792_p2_static_posteriors_advancing_round_is_byte_identical(tmp_path):
    """P2 INVERTED (#792 — the #251 seed-liveness pin is retired): STATIC
    posteriors + advancing rounds -> BYTE-IDENTICAL ranking every round.
    A ranking column whose numbers move because the round counter moved
    was ordering noise, not signal (issue #792 diagnosis 1)."""
    ws = _posteriors_ws(tmp_path, cases=CASES_251)
    ranks = []
    for _ in range(5):
        _append_round(ws)
        ranks.append(_rank_at(ws, pr.round_index(ws)))
    assert len(set(ranks)) == 1


def test_792_p3_posterior_change_moves_the_ranking(tmp_path):
    """P3 (inverted from the seed face): a runner verdict (case-beta
    alpha 2 -> 6, mean .5 -> .75) moves the VALUE at the same round —
    evidence, not the round axis, is what moves the rank."""
    ws_a = _posteriors_ws(tmp_path, name="a", cases=CASES_251)
    ws_b = _posteriors_ws(tmp_path, name="b", cases=[
        ("case-alpha", "pq.net", 4.0, 2.0),
        ("case-beta", "pq.crypto", 6.0, 2.0),   # green verdict: mean .5 -> .75
        ("case-gamma", "pq.pack", 1.0, 3.0)])
    s_a = {a.claim_id: a.score for a in pr.priority_ratio(
        [dict(c) for c in CLAIMS_251], _deps(), _evidence(ws=ws_a))}
    s_b = {a.claim_id: a.score for a in pr.priority_ratio(
        [dict(c) for c in CLAIMS_251], _deps(), _evidence(ws=ws_b))}
    assert s_b["C2"] > s_a["C2"]
