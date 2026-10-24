# -*- coding: utf-8 -*-
"""tests/test_ranker_determinism_792.py — ranker determinism + the
propensity-consistency pin (issue #792, R2 acceptance addition).

The defect (issue #792, live rank 2026-10 + the 2026-10-23 logs panel):

  1. round-seeded re-draw — random.Random(f"thompson/{base}/{cid}") makes
     the same claim's score CHANGE across rounds while no data changed:
     ordering noise injected into the value signal;
  2. Beta(1,1) fallback — an unlinked claim's PRIMARY value face is
     uniform noise (the 0.61-1.07 spread read as signal);
  3. R2 (production, android 2026-10-21): 6/16 sample_deviation rows
     carry propensity=0.0 while a deviation occurred — the recorded
     propensity of the executed arm is zero, ITT is broken at the root.

Design pins (all RED before the fix):

  - same (ledger, claims, weights) -> byte-identical ranking, ANY round;
  - unlinked claims rank BELOW every value-bearing claim; feeds say
    `unlinked — no value channel (arm oracle cases / set answers_question)`;
  - linked score is monotone in posterior evidence (the mean face:
    sum(alpha_i / (alpha_i + beta_i)));
  - the exploration slot is a DECLARED face: off by default; when on,
    the promoted arm is labeled `exploration_arm`, never conflated with
    the value column;
  - a recorded deviation to arm A carries propensity_A > 0 (the declared
    override channel's mass floor).

The determinism fixture is the SYNTHETIC android production-shape row
distillation (devkit/production_shapes/, Standard 12 — raw logs never
enter the repo).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEVKIT = ROOT / "devkit"
for p in (str(ROOT), str(ROOT / "scripts"), str(DEVKIT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import priority_ratio as pr  # noqa: E402
import kunglao_log  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "production_replay_gate", DEVKIT / "production_replay_gate.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

SHAPES = DEVKIT / "production_shapes"
RANK_FIXTURE = "android-2026-10-21-rank-shape"

CONV_LEDGER = ".convergence_ledger.jsonl"


# ---------- synthetic fixtures ----------

def _claim(cid, status="OPEN", answers_question=None,
           eta=0, attempts=0, statement=""):
    c = {"id": cid, "status": status, "evidence_tier_attempted": eta,
         "promotion_attempts": attempts, "statement": statement or cid}
    if answers_question is not None:
        c["answers_question"] = answers_question
    return c


def _deps(depends_on=None):
    return {"depends_on": depends_on or {}, "competitor_groups": {}}


def _evidence(ws=None):
    return pr.EvidenceView(terminal_fact_claims=frozenset(),
                           verified_fact_count=0,
                           ws=Path(ws) if ws else None)


def _posteriors_ws(base, cases=(), name="ws"):
    """Workspace with runs/posteriors.yaml + oracle case files."""
    ws = base / name
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    (ws / "oracle" / "cases").mkdir(parents=True, exist_ok=True)
    led = {"schema": "posteriors-schema/1", "cases": {}, "pqs": {}}
    for case_id, target_pq, a, b in cases:
        led["cases"][case_id] = {"alpha": a, "beta": b, "pending_entries": 0}
        (ws / "oracle" / "cases" / f"{case_id}.yaml").write_text(
            yaml.safe_dump({"id": case_id, "target_pq": target_pq}),
            encoding="utf-8")
    (ws / "runs" / "posteriors.yaml").write_text(
        yaml.safe_dump(led, allow_unicode=True), encoding="utf-8")
    return ws


def _append_round(ws, open_count=5, ts="2026-10-24T00:00:00"):
    """One convergence snapshot row (advances the round index)."""
    row = {"ts": ts, "decision": "DISPATCH", "open_count": open_count,
           "open_ids": [], "partial_count": 0, "active_workers": 0,
           "blockers": [], "facts_total": 1, "dispatched_ids": []}
    with (Path(ws) / CONV_LEDGER).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _capture_emit(monkeypatch):
    calls: list[dict] = []

    def _fake_emit(ws, actor, action, **kw):
        calls.append({"ws": ws, "actor": actor, "action": action, **kw})
        return True

    monkeypatch.setattr(kunglao_log, "emit", _fake_emit)
    return calls


def _rank_payloads(calls):
    return [json.loads(c["detail"]) for c in calls
            if c["action"] == "rank_feeds"]


# ---------- pin 1: same inputs -> byte-identical ranking, any round -------

LINKED_CASES = [  # (case_id, target_pq, alpha, beta) — means .667/.500/.250
    ("case-alpha", "pq.net", 4.0, 2.0),
    ("case-beta", "pq.crypto", 2.0, 2.0),
    ("case-gamma", "pq.pack", 1.0, 3.0),
]

MIXED_CLAIMS = [_claim("C1", answers_question="pq.net"),
                _claim("C2", answers_question="pq.crypto"),
                _claim("C3", answers_question="pq.pack"),
                _claim("C4", statement="unlinked work one"),
                _claim("C5", statement="unlinked work two")]


def _production_rank_call(claims, ws, rnd):
    """The production caller face, before/after: pre-fix callers thread the
    round's seed source (posterior_rng(ws) at round r); post-fix there is
    no seed axis at all. Either way the RANK must not move with it."""
    import inspect
    import random as _random
    kwargs = {"round_no": rnd}
    if "rng" in inspect.signature(pr.priority_ratio).parameters:
        kwargs["rng"] = _random.Random(rnd)   # what the round seed produced
    return pr.priority_ratio([dict(c) for c in claims], _deps(),
                             _evidence(ws), **kwargs)


def test_round_advance_never_moves_the_ranking(tmp_path):
    """#792 pin 1 (the round-seed test, INVERTED): static posteriors +
    advancing rounds -> the ranking is BYTE-IDENTICAL every round. The
    value column moves only when evidence moves; the round axis is not
    an input (the #251 round-seeded face is retired)."""
    ws = _posteriors_ws(tmp_path, cases=LINKED_CASES)
    ranks = []
    for rnd in range(5):
        _append_round(ws)
        out = _production_rank_call(MIXED_CLAIMS, ws, rnd)
        ranks.append(json.dumps([a.to_dict() for a in out], sort_keys=True))
    assert len(ranks) == 5
    assert len(set(ranks)) == 1, (
        "same inputs must rank identically across rounds "
        f"(got {len(set(ranks))} distinct rankings)")


def test_rank_payload_byte_identical_modulo_round(tmp_path, monkeypatch):
    """The rank_feeds payload is byte-identical across advancing rounds
    EXCEPT the round bookkeeping inside input_fingerprint: rng_base is
    retired (None) and a posterior_hash pins the ledger state."""
    calls = _capture_emit(monkeypatch)
    ws = _posteriors_ws(tmp_path, cases=LINKED_CASES)
    _append_round(ws)
    pr.priority_ratio([dict(c) for c in MIXED_CLAIMS], _deps(),
                      _evidence(ws), round_no=pr.round_index(ws))
    _append_round(ws)
    pr.priority_ratio([dict(c) for c in MIXED_CLAIMS], _deps(),
                      _evidence(ws), round_no=pr.round_index(ws))
    rows = _rank_payloads(calls)
    assert len(rows) == 2
    fp_a, fp_b = rows[0]["input_fingerprint"], rows[1]["input_fingerprint"]
    assert fp_a["round"] == 1 and fp_b["round"] == 2
    # the fingerprint hash COVERS the round key (replay bookkeeping), so
    # the hash itself may differ; the input doc minus bookkeeping may not.
    strip = lambda d: {k: v for k, v in d.items()
                       if k not in ("round", "fingerprint")}  # noqa: E731
    assert strip(fp_a) == strip(fp_b)
    assert fp_a["rng_base"] is None, "the per-round seed draw is retired"
    assert fp_a["posterior_hash"], "the ledger state must ride the fingerprint"
    canon = {k: v for k, v in fp_a.items() if k != "fingerprint"}
    assert fp_a["fingerprint"] == __import__("hashlib").sha256(json.dumps(
        canon, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def test_posterior_change_still_moves_the_ranking(tmp_path):
    """Determinism is NOT freezing: when the EVIDENCE moves (a runner
    verdict raises case-beta alpha 2 -> 6, mean .5 -> .75), the value
    column moves with it."""
    ws_a = _posteriors_ws(tmp_path, name="a", cases=LINKED_CASES)
    ws_b = _posteriors_ws(tmp_path, name="b", cases=[
        ("case-alpha", "pq.net", 4.0, 2.0),
        ("case-beta", "pq.crypto", 6.0, 2.0),
        ("case-gamma", "pq.pack", 1.0, 3.0)])
    s_a = {a.claim_id: a.score for a in pr.priority_ratio(
        [dict(c) for c in MIXED_CLAIMS], _deps(), _evidence(ws_a))}
    s_b = {a.claim_id: a.score for a in pr.priority_ratio(
        [dict(c) for c in MIXED_CLAIMS], _deps(), _evidence(ws_b))}
    assert s_b["C2"] > s_a["C2"], "a green verdict must raise the mean face"


# ---------- pin 2: unlinked claims never outrank value-bearing ones -------

def test_unlinked_claims_rank_below_value_bearing(tmp_path):
    """#792 pin 2: a claim with no oracle linkage has NO value channel —
    it ranks below every linked claim, ordered by the declared
    deterministic default, and its feeds carry the arm-oracle-cases hint."""
    ws = _posteriors_ws(tmp_path, cases=[("case-x", "pq.net", 6.0, 4.0)])
    claims = [_claim("C-LINKED", answers_question="pq.net")]
    claims += [_claim(f"C-UNL{i}", statement=f"work {i}") for i in range(4)]
    out = pr.priority_ratio(claims, _deps(), _evidence(ws))
    assert out[0].claim_id == "C-LINKED", (
        f"unlinked noise outranked the value face: "
        f"{[a.claim_id for a in out]}")
    unlinked_ids = [a.claim_id for a in out if a.claim_id != "C-LINKED"]
    assert unlinked_ids == sorted(unlinked_ids), (
        "unlinked order must follow the declared deterministic default")
    for a in out:
        if a.claim_id == "C-LINKED":
            continue
        assert "unlinked — no value channel" in a.feeds["case_value"]
        assert "arm oracle cases" in a.feeds["case_value"]
    assert "posterior mean" in out[0].feeds["case_value"]


def test_linked_score_is_monotone_in_posterior_evidence(tmp_path):
    """#792 pin 3: the value face is sum(alpha/(alpha+beta)) — score order
    follows posterior-mean order exactly (a draw cannot invert it)."""
    pairs = [("case-a", "q1", 1.0, 9.0),    # mean .10
             ("case-b", "q2", 1.0, 3.0),    # mean .25
             ("case-c", "q3", 2.0, 3.0),    # mean .40
             ("case-d", "q4", 11.0, 9.0),   # mean .55
             ("case-e", "q5", 7.0, 3.0),    # mean .70
             ("case-f", "q6", 17.0, 3.0)]   # mean .85
    means = [a / (a + b) for _, _, a, b in pairs]
    ws = _posteriors_ws(tmp_path, cases=pairs)
    claims = [_claim(f"C-{i}", answers_question=f"q{i}") for i in range(1, 7)]
    out = pr.priority_ratio(claims, _deps(), _evidence(ws))
    got = [a.score for a in out]
    assert got == sorted(got, reverse=True)
    assert got == [pytest.approx(m, abs=1e-6) for m in sorted(means,
                                                              reverse=True)]


def test_mean_face_reads_the_shared_posterior_store(tmp_path):
    """#792 design 5: the ranker's value column reads the SAME
    runs/posteriors.yaml case posteriors the sampler consumes — a cold
    (unobserved) linked case folds the neutral 0.5 prior mean, never a
    fabricated number."""
    ws = _posteriors_ws(tmp_path)   # ledger exists, zero observed cases
    (ws / "oracle" / "cases" / "case-9.yaml").write_text(
        yaml.safe_dump({"id": "case-9", "target_pq": "q1"}), encoding="utf-8")
    a = pr.priority_ratio([_claim("C-1", answers_question="q1")], _deps(),
                          _evidence(ws))[0]
    assert a.score == pytest.approx(0.5, abs=1e-6)
    assert "case-9" in a.feeds["case_value"]


# ---------- pin 4: the exploration slot is a declared, labeled face -------

def test_exploration_slot_default_off(tmp_path):
    """Default EXPLORE_EVERY_N_ROUNDS = 0: no exploration face exists and
    the ranking is the pure value order."""
    ws = _posteriors_ws(tmp_path, cases=LINKED_CASES)
    out = pr.priority_ratio([dict(c) for c in MIXED_CLAIMS], _deps(),
                            _evidence(ws), round_no=7)
    for a in out:
        assert "exploration_arm" not in a.feeds
    assert pr.EXPLORE_EVERY_N_ROUNDS == 0


def test_exploration_slot_enabled_is_logged_not_conflated(tmp_path,
                                                          monkeypatch):
    """#792 pin 4: with the slot enabled (every 2 rounds, round 4), the
    best unlinked claim is promoted and LABELED `exploration_arm`; the
    value scores of every row stay untouched (never conflated with the
    value column)."""
    monkeypatch.setattr(pr, "EXPLORE_EVERY_N_ROUNDS", 2)
    ws = _posteriors_ws(tmp_path, cases=LINKED_CASES)
    claims = [dict(c) for c in MIXED_CLAIMS]
    plain = pr.priority_ratio([dict(c) for c in claims], _deps(),
                              _evidence(ws), round_no=4)
    out = pr.priority_ratio(claims, _deps(), _evidence(ws), round_no=4)
    assert "exploration_arm" in out[0].feeds
    assert out[0].claim_id in {"C4", "C5"}, "the slot promotes unlinked cover"
    plain_scores = {a.claim_id: a.score for a in plain}
    assert out[0].score == plain_scores[out[0].claim_id]  # value untouched
    for a_promoted, a_plain in zip(out, plain):
        assert a_promoted.score == a_plain.score
    # non-slot rounds stay pure value order
    out_off = pr.priority_ratio(claims, _deps(), _evidence(ws), round_no=5)
    for a in out_off:
        assert "exploration_arm" not in a.feeds


# ---------- pin 5: the round-seed face is retired -------------------------

def test_round_seed_faces_are_retired():
    """#792 design 4: no case_face_seed / posterior_rng / posterior_seed_state
    and no rng parameter — determinism comes from inputs, not a counter."""
    assert not hasattr(pr, "case_face_seed")
    assert not hasattr(pr, "posterior_rng")
    assert not hasattr(pr, "posterior_seed_state")
    assert "rng" not in pr.priority_ratio.__code__.co_varnames


# ---------- R2 pin: deviation events carry propensity > 0 -----------------

FAM_A = "dynamic-trace"            # registered, has history
FAM_B = "static-decompile"         # registered, NO history (production face)
FAM_C = "red-team-verification"    # registered, has history


def _deviation_ws(tmp_path):
    """History-prior workspace: two declared families measured, one
    registered family absent — the production two-store split shape."""
    from rlvr import q_cells
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    q_cells.record_dispatch_observation(
        ws, "envelope", envelope_meta={"method_family": FAM_A}, claim="C-9")
    q_cells.record_dispatch_observation(
        ws, "envelope", envelope_meta={"method_family": FAM_C}, claim="C-9")
    return ws


def test_deviation_to_unsupported_arm_carries_positive_propensity(tmp_path):
    """R2 acceptance pin: a recorded deviation to arm A must carry
    propensity_A > 0. Production (android 2026-10-21): 6/16 deviation
    rows recorded 0.0 — ITT broken at the root."""
    from rlvr import strategy_store as ss
    ws = _deviation_ws(tmp_path)
    view = ss.reconcile_declaration(ws, FAM_B)
    assert view["deviates"] is True
    assert view["sampled_family"] in {FAM_A, FAM_C}
    assert view["propensity"] is not None and view["propensity"] > 0.0, (
        f"deviation recorded with propensity {view['propensity']!r}")


def test_in_support_declaration_propensity_unchanged(tmp_path):
    """The healthy face is byte-identical: a declared family inside the
    sampler's support keeps its exact share (the floor is additive, it
    never touches an in-support arm)."""
    from rlvr import strategy_store as ss
    from rlvr import state as rlvr_state
    ws = _deviation_ws(tmp_path)
    receipt = ss.PosteriorStrategyStore(ws).method_sample(
        rlvr_state.signature_hash(rlvr_state.snapshot(ws)))
    sampled = str(receipt["family"])
    weights = {str(f): float((c or {}).get("weight") or 0.0)
               for f, c in (receipt.get("candidates") or {}).items()}
    total = sum(weights.values())
    view = ss.reconcile_declaration(ws, sampled)
    assert view["deviates"] is False
    assert view["propensity"] > 0.0
    assert view["propensity"] == pytest.approx(
        weights[sampled] / total, abs=1e-6)


# ---------- the determinism fixture: android production-shape rows --------

def _rank_fixture():
    return rg.load_fixture(SHAPES / f"{RANK_FIXTURE}.json")


def test_fixture_is_synthetic_and_anchors_the_production_shape():
    fx = _rank_fixture()
    assert fx["synthetic"] is True
    shape = fx["shape"]
    assert shape["rank_feeds"] == 272
    assert shape["rank_feeds_entropy_zero"] == 111
    assert shape["rank_feeds_distinct_rng_base"] == 16
    assert shape["sample_deviation"] == 8
    assert shape["sample_deviation_propensity_zero"] == 3
    assert any(e.get("action") == "sample_deviation"
               for e in fx["events"])
    dev = [e for e in fx["events"] if e["action"] == "sample_deviation"]
    assert any(e["detail"]["propensity"] == 0.0 for e in dev), (
        "the fixture must anchor the observed propensity-0.0 defect")


def test_fixture_rank_face_is_byte_identical_across_rounds(tmp_path):
    """The android-shape rank face replayed through the ranker: same
    inputs at two advancing rounds -> identical (scores, order, feeds,
    view stats). The fixture's synthetic case material drives the ws."""
    fx = _rank_fixture()
    material = fx["shape"]["rank_face_material"]
    cases = [(c["case_id"], c["target_pq"], c["alpha"], c["beta"])
             for c in material["cases"]]
    ws = _posteriors_ws(tmp_path, cases=cases)
    claims = [_claim(c["id"], answers_question=c.get("answers_question"),
                     statement=c["id"]) for c in material["claims"]]
    seen = []
    for r in (1, 2):
        out = pr.priority_ratio([dict(c) for c in claims], _deps(),
                                _evidence(ws), round_no=r)
        seen.append(json.dumps([a.to_dict() for a in out], sort_keys=True))
    assert seen[0] == seen[1]
    assert fx["expectations"].get("ranker-round-determinism") == "PASS"


def test_fixture_deviation_face_replays_propensity_positive(tmp_path):
    """The fixture's deviation face (declared family outside the history
    candidate set — the production 0.0 rows) replays through the fixed
    reconciliation with propensity > 0."""
    fx = _rank_fixture()
    material = fx["shape"]["deviation_face_material"]
    from rlvr import q_cells
    from rlvr import strategy_store as ss
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    for fam in material["history_families"]:
        q_cells.record_dispatch_observation(
            ws, "envelope", envelope_meta={"method_family": fam},
            claim="C-9")
    view = ss.reconcile_declaration(ws, material["declared_absent"])
    assert view["deviates"] is True
    assert view["propensity"] is not None and view["propensity"] > 0.0
    assert fx["expectations"].get("deviation-propensity-positive") == "PASS"


def test_fixture_rank_shape_keys_are_stable():
    """The shape-only row contract: the rank_feeds/deviation detail key
    faces the fixture anchors keep their production key names."""
    fx = _rank_fixture()
    shape = fx["shape"]
    assert "input_fingerprint" in shape["rank_detail_keys"]
    assert "propensity" in shape["deviation_detail_keys"]
    assert "feeds" in shape["rank_detail_keys"]
