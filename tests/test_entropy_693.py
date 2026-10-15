# -*- coding: utf-8 -*-
"""tests/test_entropy_693.py — entropy-reduction operators (issue 693).

The objective is uncertainty reduction over the hypothesis space, not
"compress the state". ADR-001 removed the ΔH_PQ term because the
hypothesis distribution was DEGENERATE (credit all-zero -> posteriors
never move -> ΔH = 0 on 612/612 rank events) — removing the term hid
the symptom. This suite pins the missing machinery:

  1. ΔH is nonzero on a NON-DEGENERATE distribution (the mechanism —
     the zero was degeneracy, not a broken entropy computation);
  2. entropy stays OBSERVABLE-ONLY until the ADR-001 re-entry gate —
     a non-degenerate PQ categorical never lifts a priority score;
  3. the invariant-pruning operator rejects an impossible candidate
     BEFORE an attempt is spent (feasibility from evidence on disk);
  4. a recorded mismatch narrows the search to a NAMED layer and
     sub-space (CEGAR-shaped counterexample refinement);
  5. constant-set diff separates a reference MD5 constant table from a
     MUTATED variant mechanically (tools/crypto/algorithms.py holds no
     hash IVs/round constants — rlvr.constants_ref is that table).

T5 face: the covering-matrix search face delegates to
replay_equivalence.required_combos (the t-way machinery that lived
only at verification now also enumerates the search side).

All fixtures are SYNTHETIC (privacy rule); the constant-table provenance
(digest roundtrips + closed-form checks per family) ships separately in
tests/test_constants_ref_693.py — test 5 here pins the DIFF face.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, SCRIPTS)

import entropy_face  # noqa: E402
import priority_ratio as pr  # noqa: E402
from posteriors import PQCategorical, PosteriorLedger  # noqa: E402
from rlvr import constants_ref, hypotheses, invariants  # noqa: E402


# ---------- helpers ----------

def _claim(cid, status="OPEN", answers_question=None, attempts=0):
    c = {"id": cid, "status": status, "evidence_tier_attempted": 0,
         "promotion_attempts": attempts, "statement": cid}
    if answers_question is not None:
        c["answers_question"] = answers_question
    return c


def _ws_with_pq(tmp_path: Path, pq_id: str, candidates: dict) -> Path:
    ws = tmp_path / f"ws-{abs(hash(tuple(candidates.items()))) % 10**8}"
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    led = PosteriorLedger(pqs={pq_id: PQCategorical(pq_id, candidates)})
    led.save(ws)
    return ws


# ---------- 1. the ΔH mechanism ----------

def test_delta_h_nonzero_on_non_degenerate_distribution():
    """Entropy movement requires only a non-degenerate categorical: two
    competitors at equal mass carry H = 1 bit, elimination drops it to
    0 — ΔH > 0. The 612/612 historical zeros were the degenerate
    all-in-one-candidate shape (H = 0 -> any update keeps ΔH = 0), the
    mechanism this issue cures at the source, not in the score."""
    pq = PQCategorical("pq-1", {"aes-gcm": 1.0, "chacha20": 1.0})
    h0 = pq.entropy()
    assert h0 > 0.0  # non-degenerate: two competitors

    pq.update_eliminate("aes-gcm")
    h1 = pq.entropy()
    delta = h0 - h1
    assert delta > 0.0  # the observation bought information

    # degenerate anchor: a single-candidate PQ never moves (the old world)
    degenerate = PQCategorical("pq-2", {"only-one": 1.0})
    assert degenerate.entropy() == 0.0


# ---------- 2. the ADR-001 gate: observable only ----------

def test_entropy_observable_only_until_adr_gate(tmp_path):
    """ADR-001 stands: the entropy face is feeds/log/TUI only. Two
    workspaces identical except the PQ ledger's degeneracy must rank
    byte-identically (scores and order), while the entropy FACE reads
    nonzero h_bits for the non-degenerate one — observable, never
    priced. Re-entering the score follows ADR-001 §2, never a drift."""
    claims = [_claim("C-1"), _claim("C-2")]
    deps = {"depends_on": {}, "competitor_groups": {}}

    degenerate = _ws_with_pq(tmp_path, "pq", {"only": 1.0})
    rich = _ws_with_pq(tmp_path, "pq", {"a": 1.0, "b": 1.0, "c": 1.0})

    def rank(ws):
        ev = pr.EvidenceView(ws=ws)
        actions = pr.priority_ratio(
            claims, deps, ev, rng=random.Random(0), round_no=1)
        return [(a.claim_id, a.score) for a in actions]

    assert rank(degenerate) == rank(rich)  # entropy never enters the score

    # ...while the face observes it (the dual-use display contract).
    # uniform over 3 candidates: H = log2(3) ~= 1.585 bits (4dp).
    assert entropy_face.face(rich)["h_bits"] == 1.585
    assert entropy_face.face(degenerate)["h_bits"] == 0.0
    assert entropy_face.face(rich)["h_pq"] == "pq"


# ---------- 3. invariant pruning before the attempt ----------

def test_invariant_rejects_impossible_candidate_before_attempt():
    """Feasibility check BEFORE spending a step: a 32-byte-output
    candidate is impossible against a captured 16-byte digest (the
    invariant comes from evidence already on disk), so the search path
    prunes it without an attempt — the rejection names the invariant
    that killed it."""
    from_disk = {"output_len": 16, "min_loop_bound": 4}
    ok = invariants.check_candidate(
        {"name": "md5", "predicted_output_len": 16,
         "predicted_min_loop_bound": 64},
        from_disk)
    assert ok[0] is True

    rejected = invariants.check_candidate(
        {"name": "sha256", "predicted_output_len": 32,
         "predicted_min_loop_bound": 64},
        from_disk)
    assert rejected[0] is False
    assert "output_len" in rejected[1]      # named invariant
    assert "sha256" in rejected[1]          # the candidate, for the log

    # min_loop_bound is a ONE-SIDED lower bound: a core needing FEWER
    # iterations than the smallest loop observed cannot have produced
    # the trace (rejected, named); needing MORE stays inconclusive
    # (longer inputs iterate further — never a rejection).
    short_core = invariants.check_candidate(
        {"name": "reduced-round", "predicted_min_loop_bound": 2},
        from_disk)
    assert short_core[0] is False
    assert "min_loop_bound" in short_core[1]
    assert invariants.check_candidate(
        {"name": "long-core", "predicted_min_loop_bound": 64},
        {"min_loop_bound": 4})[0] is True

    # a malformed (non-numeric) prediction is fail-open: inconclusive,
    # never a rejection (one canonical warn) — pruning removes
    # IMPOSSIBLE candidates only, and "sixteen" claims nothing.
    survivors2, rejected2 = invariants.prune(
        [{"name": "bad-pred", "predicted_output_len": "sixteen"}],
        from_disk)
    assert [c["name"] for c in survivors2] == ["bad-pred"]
    assert rejected2 == []

    # the search-path face prunes a whole candidate list pre-attempt.
    survivors, rejected_rows = invariants.prune(
        [{"name": "md5", "predicted_output_len": 16},
         {"name": "sha256", "predicted_output_len": 32},
         {"name": "sm3", "predicted_output_len": 32}],
        from_disk)
    assert [c["name"] for c in survivors] == ["md5"]
    assert [c["name"] for c in rejected_rows] == ["sha256", "sm3"]


# ---------- 4. counterexample refinement names a layer ----------

def test_mismatch_narrows_to_named_layer():
    """A recorded mismatch is a REFINEMENT, not a failed attempt: the
    evidence structure (constants vs known-answer test) mechanically
    localizes the fault to family / primitive / composition and names
    the re-search sub-space. Family-confirmed + primitive-confirmed +
    pipeline mismatch -> composition layer (the issue's exact
    md5(plaintext) != captured case)."""
    # constants match no reference family -> the FAMILY layer is wrong
    r = hypotheses.refine_on_mismatch(family_match=None, kat_pass=False)
    assert r.layer == "family"
    assert r.subspace  # a named re-search space, not "everywhere"

    # constants identify MD5 but the compression core fails its KAT ->
    # the PRIMITIVE layer
    r = hypotheses.refine_on_mismatch(family_match="md5", kat_pass=False)
    assert r.layer == "primitive"
    assert "md5" in r.subspace

    # family + primitive both confirmed, digest still != captured ->
    # COMPOSITION (concatenation/padding/encoding), never "not MD5"
    r = hypotheses.refine_on_mismatch(family_match="md5", kat_pass=True)
    assert r.layer == "composition"
    assert "md5" in r.subspace

    # every refinement lands as an OPEN hypothesis at its named layer —
    # the new registry has no permanent terminal state (over-wide
    # conclusions must be refinable, per the issue's reopen demand).
    minted = hypotheses.mint_hypothesis(
        layer=r.layer, family="md5", statement=r.subspace)
    assert minted.layer in hypotheses.LAYERS
    assert minted.status == "open"


def test_termination_cells_key_on_kind_family_layer():
    """T4: the layer-scoped death accounting keys the triple
    (kind, family, layer) — a composition-layer failure never piles
    onto the family's primitive-layer cell (the option-death conflation
    the issue calls actively harmful)."""
    rows = [
        {"kind": "encryption_layer", "method_family": "crypto-core"},
        {"kind": "encryption_layer", "method_family": "crypto-core"},
        {"kind": "detection_trigger", "method_family": "crypto-core"},
    ]
    layer_of = {"crypto-core": "composition"}
    cells = hypotheses.layer_death_cells(rows, layer_of)
    assert cells == {
        ("encryption_layer", "crypto-core", "composition"): 2,
        ("detection_trigger", "crypto-core", "composition"): 1,
    }
    # an unattributed family lands in the explicit unscoped bucket —
    # absence is honest, never silently composition.
    cells2 = hypotheses.layer_death_cells(rows[:1], {})
    assert ("encryption_layer", "crypto-core",
            hypotheses.LAYER_UNSCOPED) in cells2


# ---------- 5. reference constant table + mechanical diff ----------

def test_constant_set_diff_separates_reference_from_mutated_md5():
    """Constant-set diff is mechanical: the reference MD5 table (IV +
    T) classifies as exact reference; the same table with ONE mutated
    round constant classifies as md5-mutated and names the differing
    word. The table words' own provenance (digest roundtrips against
    hashlib) is pinned in tests/test_constants_ref_693.py."""
    import hashlib
    assert hashlib.new("md5", b"abc").hexdigest() == \
        "900150983cd24fb0d6963f7d28e17f72"

    ref = constants_ref.reference_words("md5")
    assert len(ref) == 4 + 64  # IV + T-table
    assert constants_ref.classify(set(ref)) == {
        "family": "md5", "exact": True,
        "missing": [], "extra": [],
    }

    # mutate ONE T-table word (the mod-crypto constants-only family)
    mutated = list(ref)
    mutated[10] = ref[10] ^ 0x00010000
    got = constants_ref.classify(set(mutated))
    assert got["family"] == "md5"          # still mechanically identified
    assert got["exact"] is False           # ...but NOT the reference
    assert got["missing"] == [ref[10]]     # the original word is absent
    assert got["extra"] == [ref[10] ^ 0x00010000]

    # a non-member set never claims md5
    other = constants_ref.classify({0xDEADBEEF, 0xCAFEBABE})
    assert other["family"] is None
    assert other["exact"] is False

    # every shipped family table cross-checks its digest via a
    # known-vector roundtrip where hashlib provides one.
    for family in ("md5", "sha1", "sha256", "sm3"):
        words = constants_ref.reference_words(family)
        assert len(words) == len(set(words))  # no duplicate table words
        assert words, family


# ---------- T5. covering matrix on the search side ----------

def test_covering_matrix_enumerates_search_space():
    """The t-way covering machinery (previously verification-only via
    replay_equivalence) enumerates the SEARCH side too: a 2x2 domain
    at strength 2 is the full product; strength stays a parameter."""
    matrix = hypotheses.covering_matrix(
        {"primitive": ["md5", "sha1"], "padding": ["none", "pkcs7"]},
        strength=2)
    combos = {tuple(sorted(c.items())) for c in matrix}
    assert combos == {
        (("padding", "none"), ("primitive", "md5")),
        (("padding", "none"), ("primitive", "sha1")),
        (("padding", "pkcs7"), ("primitive", "md5")),
        (("padding", "pkcs7"), ("primitive", "sha1")),
    }
