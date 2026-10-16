# -*- coding: utf-8 -*-
"""tests/test_reward_source_678.py — the reward channel's trusted data
source (issue #678).

Every settlement banks 0.0 and the credit-to-mass mapping turns that into
a pure failure unit — the sampler is trained to AVOID the method families
that produced the only verified work. Three provenance links are missing
at once; this suite is the RED-first contract for closing them plus the
S9-spike Φ non-degeneracy fix:

  1. a fact with no creator is untraced AND explicitly marked
     non-creditable in the settlement path (T3 creator backfill);
  2. ``cited_ids`` gains a producer: deliverable documents naming an
     F<NNN> id mark that fact ``cited_by_deliverable`` (T2);
  3. verification facts (answers_question=None) cited by deliverables
     earn FULL credit, not the TRACE 0.01 (D-678.4b — the citation leg
     for red-team/verification work);
  4. a properly credited fact settles a NONZERO row reward through the
     real ws-level settlement (the live defect: credited: [] every row);
  5. TRACE-band credit (0 < r <= TRACE rail top) is OBSERVATION ONLY in
     the Beta fold — it adds neither success nor failure mass
     (D-678.4a: 0.01 credit was banking 0.99 failure against successes);
  6. Φ(s) is non-degenerate: graded fact weights (certified terminal
     1.0 / non-terminal present 0.5 / draft 0.25) give intermediate
     potentials where the binary verified-count gave only 0.0 or 1.0
     (D-678.5), and transition rows carry an explicit phi_delta +
     claim_ref/action_key provenance;
  7. armed oracle cases (channel/hypothesis_ref/update_map/expected.
     evidence_refs/mutations filled) drive record_case_settlements into
     runs/posteriors.yaml — the silent "posteriors never generated" gap
     becomes a counted, warned field (T5).

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import rollout_ledger as rl  # noqa: E402
import scalar_settlement as ss  # noqa: E402
from rlvr import incremental_reward as ir  # noqa: E402
from rlvr import q_cells  # noqa: E402
from rlvr import state as rl_state  # noqa: E402
import settle_round_credit as src  # noqa: E402


# ---------- synthetic fixture helpers --------------------------------------

def _grammar_fact(ws: Path, fid: str, status: str, *,
                  claim_id: str | None = None, creator: str | None = None,
                  confidence: str | None = None,
                  bare: bool = False) -> None:
    """A fact fixture (the #539/#651 fixture shape): the front-matter
    id carries the mandatory ``<FNNN>-<slug>`` grammar (the file is
    ``<FNNN>.md``). With ``claim_id`` and the default confidence the
    shape is lint-clean; WITHOUT ``claim_id`` it carries the
    MISSING_CLAIM_ID grammar error on purpose — such fixtures feed only
    certification-blind faces (the round-credit ladder keys on status +
    citation, never on certification). ``bare=True`` omits source/
    confidence for OPEN/DEFERRED (the status matrix forbids both)."""
    if bare:
        conf = None
    else:
        conf = confidence or ("high" if status in ("PROVEN", "VERIFIED",
                                                   "REFUTED") else "medium")
    sha = hashlib.sha256(f"{fid}:{status}".encode()).hexdigest()
    lines = ["---", f"id: {fid}-fact", "type: fact", f"title: {fid}",
             "created: 2026-10-11", "last_reviewed: 2026-10-11",
             "boundary_type: confirmed", "promotion_gate:",
             "provenance:", "  - role: public_doc",
             f"    path: facts/{fid}.md",
             f"    content_sha256: {sha}", "    credibility: B2",
             "claim: claim statement", "reproduce: cmd",
             "expected: out", "verified: pending",
             "source: public-osint" if not bare else None,
             f"confidence: {conf}" if conf else None,
             f"status: {status}"]
    lines = [ln for ln in lines if ln is not None]
    if claim_id:
        lines.append(f"claim_id: {claim_id}")
    if creator:
        lines.append(f"creator: {creator}")
    lines += ["---", "", "body", ""]
    (ws / "facts").mkdir(parents=True, exist_ok=True)
    (ws / "facts" / f"{fid}.md").write_text(
        "\n".join(lines), encoding="utf-8")


def _register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True),
        encoding="utf-8")


def _ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    return ws


# ---------- 1. T3: creator backfill / creditable marking -------------------

def test_fact_without_creator_is_untraced(tmp_path):
    """A creator-less fact with no claim linkage counts toward no
    dispatch — and the settlement path marks it ``creditable: false``
    instead of silently dropping it (the live F001-F007 residue)."""
    ws = _ws(tmp_path)
    _grammar_fact(ws, "F301", "PROVEN")
    artifacts = ss.fact_artifacts(ws)
    doc = ss.round_credit([{"dispatch_id": "C-001", "round": 1}],
                          artifacts, [])
    assert doc["untraced"] == ["F301-fact"]
    assert doc["rows"][0]["credited"] == []
    assert doc["rows"][0]["r"] == 0.0

    backed = ss.backfill_artifact_creators(artifacts, ["C-001"])
    assert backed[0]["creator"] is None
    assert backed[0]["creditable"] is False


def test_creatorless_fact_on_a_settled_claim_backfills_the_creator(
        tmp_path):
    """The backfill leg: a creator-less fact whose claim_id names a
    dispatch in THIS settlement round attributes to that claim (the
    claim id IS the dispatch identity in the settlement path) — the
    fact stops being permanently untraced."""
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-001", "status": "PROVEN",
                    "answers_question": "pq-main", "question": "q"}])
    _grammar_fact(ws, "F302", "PROVEN", claim_id="C-001")
    artifacts = ss.fact_artifacts(ws)
    assert artifacts[0]["creator"] is None  # the defect: no producer

    backed = ss.backfill_artifact_creators(artifacts, ["C-001"])
    assert backed[0]["creator"] == "C-001"
    assert backed[0]["creditable"] is True


# ---------- 2. T2: the cited_ids producer ----------------------------------

def test_cited_ids_producer_marks_deliverable_refs(tmp_path):
    """A deliverable document naming F008 marks that fact
    ``cited_by_deliverable`` — the citation leg had NO producer, so the
    flag was permanently False for every live workspace. Both scanned
    trees are exercised: notes/ names F008, analyses/ names F009."""
    ws = _ws(tmp_path)
    _grammar_fact(ws, "F008", "PROVEN", creator="tr-rt-1")
    _grammar_fact(ws, "F009", "PROVEN", creator="tr-rt-1")
    (ws / "notes").mkdir(exist_ok=True)
    (ws / "notes" / "n-summary.md").write_text(
        "# summary\n\nThe key schedule lives in F008.\n", encoding="utf-8")
    (ws / "analyses").mkdir(exist_ok=True)
    (ws / "analyses" / "a-deep-dive.md").write_text(
        "cross-fact synthesis citing F009.\n", encoding="utf-8")

    cited = ss.cited_ids_from_deliverables(ws)
    assert "F008" in cited
    assert "F009" in cited

    rows = {r["id"]: r for r in ss.fact_artifacts(ws)}
    assert rows["F008-fact"]["cited_by_deliverable"] is True
    assert rows["F009-fact"]["cited_by_deliverable"] is True


# ---------- 3. D-678.4b: the verification citation leg ----------------------

def test_redteam_facts_cited_by_deliverable_earn_full_credit(tmp_path):
    """Verification facts (answers_question=None — red-team confirmations
    answer no primary question) settle FULL when a deliverable cites
    them, not the TRACE 0.01 that fed 0.99 failure mass against
    successes."""
    ws = _ws(tmp_path)
    _grammar_fact(ws, "F400", "PROVEN", creator="tr-rt-1")
    (ws / "notes").mkdir(exist_ok=True)
    (ws / "notes" / "n-redteam.md").write_text(
        "red-team confirmed F400 (HMAC over mutated SHA-256).\n",
        encoding="utf-8")
    doc = ss.round_credit(
        [{"dispatch_id": "tr-rt-1", "round": 1}],
        ss.fact_artifacts(ws), [])
    row = doc["rows"][0]
    assert row["credited"] == ["F400-fact"]
    assert row["demoted"] == []
    assert row["r"] == ss.ROUND_CREDIT_FULL


# ---------- 4. the live settlement banks nonzero ----------------------------

def test_settlement_with_credited_fact_banks_nonzero_r(tmp_path):
    """Through the REAL ws-level settlement face: a terminal claim whose
    creator-less fact is backfilled banks reward > 0 — the live defect
    was 60 rows of reward 0.0 with credited: []."""
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-001", "status": "PROVEN",
                    "answers_question": "pq-main", "question": "q"}])
    _grammar_fact(ws, "F100", "PROVEN", claim_id="C-001")
    dispatches = [{"dispatch_id": "C-001", "round": 1}]
    res = ss.settle_round_credit(
        ws, dispatches, ss.fact_artifacts(ws), [])
    assert res["settled"] == 1
    assert res["untraced"] == []
    row = rl.fold(ws, "round_credit/C-001")
    assert row["settlement"]["reward"] > 0.0
    assert row["settlement"]["credited"] == ["F100-fact"]


# ---------- 5. D-678.4a: TRACE credit is observation-only -------------------

def _q_row(sig: str, fam: str, credit, source="settlement") -> dict:
    return {"schema": q_cells.OBS_SCHEMA, "ts": "2026-10-14T00:00:00Z",
            "source": source, "signature_hash": sig, "method_family": fam,
            "claim": None, "agent": None, "credit": credit}


def test_trace_credit_does_not_bank_as_failure_mass(tmp_path):
    """The credit-to-mass fold: a TRACE-band credit (0 < credit <= the
    TRACE rail top) adds NO Beta mass — success and failure stay put.
    A genuine 0.0 still trains failure; a full credit still trains
    success."""
    trace_store = q_cells.InMemoryStore([
        _q_row("sig1", "red-team-verification", None, source="dispatch"),
        _q_row("sig1", "red-team-verification", ss.TRACE_CANONICAL),
    ])
    cell = q_cells.fold(trace_store, gamma=1.0).cells[("sig1",
                                                       "red-team-verification")]
    assert cell.success == 0.0, "TRACE credit must not bank success"
    assert cell.failure == 0.0, "TRACE credit must not bank failure mass"

    fail_store = q_cells.InMemoryStore([
        _q_row("sig1", "dynamic-trace", 0.0)])
    fcell = q_cells.fold(fail_store, gamma=1.0).cells[("sig1",
                                                       "dynamic-trace")]
    assert fcell.success == 0.0
    assert fcell.failure == 1.0, "a genuine 0.0 still trains failure"

    full_store = q_cells.InMemoryStore([
        _q_row("sig1", "dynamic-trace", 1.0)])
    scell = q_cells.fold(full_store, gamma=1.0).cells[("sig1",
                                                       "dynamic-trace")]
    assert scell.success == 1.0
    assert scell.failure == 0.0


def test_observation_band_edges_are_pinned(tmp_path):
    """The band top (the TRACE rail ceiling) is INSIDE the observation
    band; one tick above it folds as a normal credit."""
    top_store = q_cells.InMemoryStore([
        _q_row("sig1", "dynamic-trace", q_cells.OBSERVATION_BAND_CEIL)])
    top = q_cells.fold(top_store, gamma=1.0).cells[("sig1",
                                                    "dynamic-trace")]
    assert (top.success, top.failure) == (0.0, 0.0)

    above_store = q_cells.InMemoryStore([
        _q_row("sig1", "dynamic-trace",
               q_cells.OBSERVATION_BAND_CEIL + 0.01)])
    above = q_cells.fold(above_store, gamma=1.0).cells[("sig1",
                                                        "dynamic-trace")]
    assert above.success == pytest.approx(0.06)
    assert above.failure == pytest.approx(0.94)


# ---------- 6. D-678.5: Φ non-degeneracy -----------------------------------

def test_phi_has_intermediate_values_with_graded_facts(tmp_path):
    """A workspace whose facts are all grammar-clean substantive
    non-terminal (INFERRED) has Φ strictly between 0 and 1: the binary
    verified-count read this as 0.0 — a fully non-terminal fact base
    looked IDENTICAL to an empty one."""
    ws = _ws(tmp_path)
    for i in range(3):
        _grammar_fact(ws, f"F5{i:02d}", "INFERRED", claim_id="C-001")
    face = rl_state.fact_face(ws)
    assert face["count"] == 3
    assert face["verified"] == 0, "INFERRED is not a credit terminal"
    assert face["weighted_fraction"] == 0.5

    phi = ir.potential(ws)
    assert 0.0 < phi < 1.0
    assert abs(phi - 0.5) < 1e-9


def test_phi_partial_certification_is_strictly_intermediate(tmp_path):
    """1 certified terminal + 1 substantive non-terminal: the graded
    fraction lands at 0.75 — intermediate values exist BEFORE every
    fact certifies."""
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-001", "status": "PROVEN",
                    "answers_question": None, "question": "q"}])
    _grammar_fact(ws, "F600", "PROVEN", claim_id="C-001")
    _grammar_fact(ws, "F601", "INFERRED", claim_id="C-001")
    face = rl_state.fact_face(ws)
    assert face["verified"] == 1
    assert abs(face["weighted_fraction"] - 0.75) < 1e-9
    phi = ir.potential(ws)
    assert 0.5 < phi < 1.0


def test_phi_draft_and_junk_tiers(tmp_path):
    """The outer rungs: a grammar-clean OPEN draft grades 0.25; a
    malformed junk file grades 0.0 (the #651 farm wall — junk never
    lifts Φ)."""
    draft_ws = _ws(tmp_path, "draft-ws")
    _grammar_fact(draft_ws, "F700", "OPEN", claim_id="C-001", bare=True)
    face = rl_state.fact_face(draft_ws)
    assert face["verified"] == 0
    assert face["weighted_fraction"] == 0.25

    junk_ws = _ws(tmp_path, "junk-ws")
    (junk_ws / "facts").mkdir(exist_ok=True)
    (junk_ws / "facts" / "F701.md").write_text(
        "junk prose, no frontmatter\n", encoding="utf-8")
    junk = rl_state.fact_face(junk_ws)
    assert junk["count"] == 1
    assert junk["weighted_fraction"] == 0.0


def test_transition_row_carries_phi_delta_and_claim_ref(tmp_path):
    """The transition row gains the EXPLICIT phi_delta column (the
    #548 tiebreaker raw material was previously only derivable by
    subtraction) plus claim_ref/action_key provenance from the launch
    stash."""
    ws = _ws(tmp_path)
    ir.record_launch(ws, "C-777", action_key="dyn-trace", phi=0.2)
    row = ir.append_transition(ws, "C-777", "DISPATCHED", r_settle=1.0)
    assert row is not None
    assert row["phi_before"] == 0.2
    assert row["s_prime_phi"] == 0.0  # no faces: honest-absence 0.0
    assert row["phi_delta"] == round(0.0 - 0.2, 6)
    assert row["claim_ref"] == "C-777"
    assert row["action_key"] == "dyn-trace"


# ---------- 7. T5: the oracle arm ------------------------------------------

def _armed_case(ws: Path, cid: str, pq: str) -> None:
    cdir = ws / "oracle" / "cases"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / f"{cid}.yaml").write_text(yaml.safe_dump({
        "id": cid,
        "channel": "probe",
        "target_pq": pq,
        "hypothesis_ref": "H-001",
        "update_map": {"red_up": ["H-002"]},
        "expected": [{"field": "probe", "value": "observed",
                      "evidence_refs": ["E-001"]}],
        "mutations": [{"kind": "omit", "target": "E-001"}],
    }), encoding="utf-8")


def test_armed_case_settlement_writes_posteriors(tmp_path):
    """An ARMED case (all five arming fields filled) whose target_pq is
    answered by a banked PROVEN claim drives record_case_settlements
    into runs/posteriors.yaml — the ledger that never existed live."""
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-001", "status": "PROVEN",
                    "answers_question": "pq-main", "question": "q"}])
    _armed_case(ws, "case-probe-1", "pq-main")

    assert src.armed_case_ids(ws) == {"case-probe-1"}

    out = src.record_case_settlements(ws, ["C-001"])
    assert out["case_observations"] == 1
    assert out["cases_passed"] == 1
    led_path = ws / "runs" / "posteriors.yaml"
    assert led_path.is_file()
    doc = yaml.safe_load(led_path.read_text(encoding="utf-8"))
    assert doc["cases"]["case-probe-1"]["alpha"] == 2.0  # Beta(1,1)+pass
    assert doc["cases"]["case-probe-1"]["beta"] == 1.0


def test_unarmed_case_is_not_armed(tmp_path):
    """A case doc missing its arming fields is NOT armed — the count
    that makes the silent gap loud never over-reports."""
    ws = _ws(tmp_path)
    cdir = ws / "oracle" / "cases"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "case-thin.yaml").write_text(yaml.safe_dump({
        "id": "case-thin", "target_pq": "pq-main",
    }), encoding="utf-8")
    assert src.armed_case_ids(ws) == set()
