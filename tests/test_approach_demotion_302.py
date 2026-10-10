# -*- coding: utf-8 -*-
"""Tests for issue 302 — D1 approach-class demotion on failure-signature clusters.

Fast tier (tests/_tiers.py FAST_MODULES): pure unit over the synthetic
16-round fixture (tests/fixtures/approach_demotion/synthetic_matrix.json)
plus tmp_path workspace faces. No process spawns, no network, no nested
pytest.

Fixture provenance (privacy red line): the fixture is SYNTHESIZED — it
mirrors the EXP-C dry-run matrix's STRUCTURE only (round shape, fine
instrumentation class taxonomy, 6-channel signature schema, cluster /
recurrence pattern, demotion-math pins). Identifiers, target facts,
mechanisms and values are fictional; the real engagement matrix never
enters the repo.

Contract (issue 302, RED first):

- clause_a: N DISTINCT signature clusters inside one approach class demote
  the class; clustering is by EXACT signature tuple — the same signature
  counts once.
- clause_b: a SINGLE post-patch recurrence of one cluster demotes
  (K_rec=1) — the patch fixed the symptom, not the class. An invest
  (infrastructure change) never triggers clause_b.
- while demoted: in-class patching FORBIDDEN from the demotion round
  onward; an invest re-arms the class for exactly one attempt (its own
  execution row); discovery rounds stay allowed (the protected rounds of
  the sensitivity analysis).
- N sensitivity pinned on the fixture: N=1 unsafe (forbids the discovery
  round), N=2+clause_b RECOMMENDED (12->4 failure attempts under full-D1
  attempt accounting), N=3 too lax, N=4 vacuous.
- the demotion unit is the FINE approach-class granularity (the ladder's
  mechanism families), never a coarse strategy cluster (binding EXP-C
  constraint: coarse keying is vacuous — the fixture's S/M/P/H classes map
  1:1 onto the interception family pool).
- target_ladder integration: the attempt-record ingestion point validates /
  normalizes signature tuples; rungs carry demotion state; a demoted class
  is skipped in generation (fail-open to the fallback axis — never
  unwalkable); in-class patching after demotion is a walked-validity
  defect; the gate emits approach_demoted through kunglao_log.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

import approach_demotion as ad  # noqa: E402
import target_ladder as tl  # noqa: E402
from kunglao_log import tail  # noqa: E402

FIXTURE = (Path(__file__).resolve().parent / "fixtures" /
           "approach_demotion" / "synthetic_matrix.json")
MATRIX = json.loads(FIXTURE.read_text(encoding="utf-8"))
ROUNDS = MATRIX["rounds"]
PIN = MATRIX["pinned_expectations"]

# The fixture's fine instrumentation classes map 1:1 onto the interception
# family pool — the same granularity (4 distinct approaches per goal). The
# demotion unit in the ladder is the FAMILY.
CLASS_TO_FAMILY = {"S": "hooking", "M": "repackaging",
                   "P": "ca-install", "H": "proxy-interposition"}
FAMILY_TO_CLASS = {v: k for k, v in CLASS_TO_FAMILY.items()}


# ---------- helpers ----------

def _as_classes(d: dict) -> dict:
    """Family-keyed state -> fixture-class-keyed (S/M/P/H) for pin diffing."""
    return {FAMILY_TO_CLASS[f]: v for f, v in d.items()}


_DEFECT_RE = re.compile(
    r"demotion: in-class patch on family '([^']+)' at round (\d+)")


def _demotion_defects(defects: list[str]) -> list[tuple[str, int]]:
    """(family, offending round) pairs from a ladder_defects list."""
    return [(m.group(1), int(m.group(2)))
            for d in defects for m in [_DEFECT_RE.match(d)] if m]

def _history(rounds: list[dict] | None = None,
             families: dict | None = None) -> list[dict]:
    """Fixture rounds -> D1 attempt history (the normalized record shape)."""
    cmap = families if families is not None else CLASS_TO_FAMILY
    return [{"round": r["round"],
             "family": cmap[r["approach_class"]],
             "signature": r["signature"],
             "outcome": r["outcome"],
             "change_kind": r["change_kind"]}
            for r in (rounds if rounds is not None else ROUNDS)]


def _demoted_at(history: list[dict], **kw) -> dict[str, int | None]:
    state = ad.demotion_state(history, **kw)
    return {f: st["demoted_at"] for f, st in state.items()}


def _forbidden(history: list[dict], **kw) -> list[int]:
    return ad.forbidden_rounds(history, **kw)


def _sig(**over) -> dict:
    base = {ch: None for ch in ad.SIGNATURE_CHANNELS}
    base["rewritten_flag"] = False
    base.update(over)
    return base


def _ws_with_ladder(tmp_path: Path, ladder: dict | None,
                    claim_id: str = "C-302") -> Path:
    ws = tmp_path
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [
            {"id": claim_id, "status": "OPEN", "origin": "failure-obstacle",
             "obstacle_for": "C-001", "obstacle_class": "interception"}]},
            allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    if ladder is not None:
        runs = ws / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        (runs / f"target-ladder-{claim_id}.yaml").write_text(
            yaml.safe_dump(ladder, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    return ws


def _rows(ws: Path, actor: str, action: str) -> list[dict]:
    return [r for r in tail(ws, 1000)
            if r.get("actor") == actor and r.get("action") == action]


def _ladder_with_history(history: list[dict],
                         obstacle_class: str = "interception") -> dict:
    return {
        "obstacle_class": obstacle_class,
        "attempts": [
            {"level": f"T{(i % 3) + 1}", "family": h["family"],
             "action": f"d1 attempt {h['round']}", "outcome": h["outcome"],
             "signature": h["signature"],
             "change_kind": h["change_kind"],
             "round": h["round"]}
            for i, h in enumerate(history)
        ],
        "inventory": [{"family": history[0]["family"],
                       "tried": "the first rung",
                       "failed_because": "cluster demotion"}],
    }


# ---------- clause_a: N distinct signature clusters ----------

def test_clause_a_two_distinct_clusters_demote_at_the_right_rounds():
    """Fixture-driven: clusters-only N=2 demotes S@4, P@9, M@11, H@15 (the
    fixture classes, keyed on the ladder-family granularity)."""
    assert _as_classes(_demoted_at(_history(), n=2, clause_b=False)) == \
        PIN["clusters_only_n2"]["demoted_at"]


def test_clause_a_identical_signature_counts_once():
    """Same failure signature counts once — exact-tuple clustering. Two
    fails with the IDENTICAL tuple are one cluster; the second DISTINCT
    tuple is what reaches N=2."""
    hist = [
        {"round": 1, "family": "hooking", "outcome": "fail",
         "change_kind": "none",
         "signature": _sig(process_state="host gone")},
        {"round": 2, "family": "hooking", "outcome": "fail",
         "change_kind": "none",
         "signature": _sig(process_state="host gone")},  # identical tuple
    ]
    assert ad.demote(hist, "hooking", n=2, clause_b=False) == ad.ACTIVE
    hist.append({"round": 3, "family": "hooking", "outcome": "fail",
                 "change_kind": "none",
                 "signature": _sig(process_state="ui stall")})
    assert ad.demote(hist, "hooking", n=2, clause_b=False) == ad.DEMOTED
    assert ad.demotion_round(hist, "hooking", n=2, clause_b=False) == 3


def test_clause_a_is_class_scoped():
    """Clusters do not leak across approach classes: one cluster in family A
    and one in family B never demote either."""
    hist = [
        {"round": 1, "family": "hooking", "outcome": "fail",
         "change_kind": "none", "signature": _sig(process_state="host gone")},
        {"round": 2, "family": "repackaging", "outcome": "fail",
         "change_kind": "none", "signature": _sig(process_state="ui stall")},
    ]
    assert ad.demote(hist, "hooking", n=2, clause_b=False) == ad.ACTIVE
    assert ad.demote(hist, "repackaging", n=2, clause_b=False) == ad.ACTIVE


# ---------- clause_b: single post-patch recurrence (K_rec=1) ----------

def test_clause_b_fires_at_the_right_rounds_on_the_fixture():
    """Full rule (N=2 + clause_b): S demotes at round 2 via clause_b (the
    identical-tuple patch retry), P@9 / M@11 / H@15 via clause_a."""
    assert _demoted_at(_history()) == {
        CLASS_TO_FAMILY[c]: r for c, r in
        PIN["full_rule_n2_clause_b"]["demoted_at"].items()}
    state = ad.demotion_state(_history())
    assert {f: st["clause"] for f, st in state.items()} == {
        CLASS_TO_FAMILY[c]: r for c, r in
        PIN["full_rule_n2_clause_b"]["clause"].items()}


def test_clause_b_identical_tuple_recurring_after_patch_demotes():
    """Two different bugs with an IDENTICAL surface signature cannot be told
    apart by clustering — patch, recur with the same tuple -> demote."""
    tup = _sig(process_state="tracer abort during symbol detour")
    hist = [
        {"round": 1, "family": "hooking", "outcome": "fail",
         "change_kind": "none", "signature": tup},
        {"round": 2, "family": "hooking", "outcome": "fail",
         "change_kind": "patch", "signature": tup},
    ]
    assert ad.demotion_round(hist, "hooking") == 2
    st = ad.demotion_state(hist)["hooking"]
    assert st["clause"] == "clause_b" and st["recurrences"] >= 1


def test_clause_b_invest_never_triggers():
    """An invest/infrastructure change does NOT count as a patch — invest
    outputs (fixture rounds 13 / 16) never demote via clause_b."""
    tup = _sig(process_state="tracer abort during symbol detour")
    hist = [
        {"round": 1, "family": "hooking", "outcome": "fail",
         "change_kind": "none", "signature": tup},
        {"round": 2, "family": "hooking", "outcome": "fail",
         "change_kind": "invest", "signature": tup},
    ]
    assert ad.demotion_round(hist, "hooking") is None


def test_clause_b_first_occurrence_after_patch_is_not_a_recurrence():
    """A patch landing before a FIRST occurrence of a cluster is not a
    recurrence (fixture round 4: a new tuple after a patch — no clause_b)."""
    hist = [
        {"round": 1, "family": "hooking", "outcome": "fail",
         "change_kind": "patch",
         "signature": _sig(process_state="host gone")},
    ]
    assert ad.demotion_round(hist, "hooking") is None


def test_patch_forbidden_forward_gate_face():
    """The forward-looking pure face: while demoted, an in-class patch (or
    an unchanged retry) is forbidden and an invest is the re-arm carve-out;
    an active family forbids nothing."""
    demoted = {"demoted_at": 2, "clause": "clause_b"}
    assert ad.patch_forbidden(demoted, "patch") is True
    assert ad.patch_forbidden(demoted, "none") is True
    assert ad.patch_forbidden(demoted, "invest") is False
    assert ad.patch_forbidden({"demoted_at": None}, "patch") is False
    assert ad.patch_forbidden(None, "patch") is False


def test_clause_b_k_recurrence_is_configurable():
    """K_rec=1 is the recommended default; K_rec=2 pins the count semantics
    (a single recurrence no longer suffices)."""
    tup = _sig(process_state="tracer abort")
    hist = [
        {"round": 1, "family": "hooking", "outcome": "fail",
         "change_kind": "none", "signature": tup},
        {"round": 2, "family": "hooking", "outcome": "fail",
         "change_kind": "patch", "signature": tup},
    ]
    assert ad.demotion_round(hist, "hooking", k_recurrence=2) is None
    hist.append({"round": 3, "family": "hooking", "outcome": "fail",
                 "change_kind": "patch", "signature": tup})
    assert ad.demotion_round(hist, "hooking", k_recurrence=2) == 3


# ---------- while demoted: forbidden / re-arm / protected rounds ----------

def test_inclass_patch_forbidden_from_demotion_round_onward():
    """The forbidden set of the full rule on the fixture: rounds 4, 5, 6, 7,
    10 (S, post clause_b demotion at 2) and 12 (P, post clause_a at 9)."""
    assert _forbidden(_history()) == PIN["full_rule_n2_clause_b"]["forbidden"]


def test_invest_rearms_for_exactly_one_attempt():
    """While demoted, an invest is allowed and its execution is the one
    re-armed attempt; the next in-class patch is forbidden again."""
    assert 13 in PIN["full_rule_n2_clause_b"]["protected_rounds_allowed"]
    tup = _sig(process_state="host gone")
    hist = [
        {"round": 1, "family": "hooking", "outcome": "fail",
         "change_kind": "none", "signature": tup},
        {"round": 2, "family": "hooking", "outcome": "fail",
         "change_kind": "patch", "signature": tup},  # demote
        {"round": 3, "family": "hooking", "outcome": "fail",
         "change_kind": "invest", "signature": tup},  # re-arm: allowed
        {"round": 4, "family": "hooking", "outcome": "fail",
         "change_kind": "patch", "signature": tup},  # forbidden again
    ]
    assert _forbidden(hist) == [4]
    st = ad.demotion_state(hist)["hooking"]
    assert st["demoted_at"] == 2, "re-arm must not reset the demotion"


def test_discovery_rounds_are_never_forbidden():
    """The protected rounds of the sensitivity analysis stay allowed under
    the recommended rule: r3 (first-contact learning), r8/r9 (legitimate
    invest work), r11 (the root-cause discovery round), r13 (invest output
    = the actual fix shape), r14 (first H failure), r15 (the re-exposure
    round, H's demoting round), r16 (invest output)."""
    forbidden = set(_forbidden(_history()))
    for protected in PIN["full_rule_n2_clause_b"]["protected_rounds_allowed"]:
        assert protected not in forbidden, protected


def test_full_d1_attempt_counterfactual_is_four():
    """Enforced replay: forbidden attempts never happen, invest work is
    absorbed (not a demotion-relevant failure attempt), stop at the first
    success -> exactly 4 failure attempts (12 -> 4)."""
    assert PIN["full_rule_n2_clause_b"]["attempt_counterfactual_full_d1"] == 4
    forbidden = set(_forbidden(_history()))
    attempts = 0
    for r in _history():
        if r["outcome"] == "success":
            break
        if r["round"] in forbidden or r["change_kind"] == "invest":
            continue
        attempts += 1
    assert attempts == 4


def test_deletion_only_counterfactual_is_six():
    """Naive deletion-only accounting: 12 canonical failures - 6 forbidden
    = 6 (the full-D1 attempt accounting is the one that meets 12 -> 4)."""
    assert PIN["full_rule_n2_clause_b"]["deletion_counterfactual"] == 6
    canonical = [r["round"] for r in _history() if r["round"] <= 12]
    assert len(canonical) == 12
    assert len(set(_forbidden(_history())) & set(canonical)) == 6


# ---------- N sensitivity (pinned) ----------

def test_n1_is_unsafe_it_blocks_the_discovery_round():
    """N=1 forbids round 11 — the round that exposed root cause 1. That is
    exactly why N=1 is REJECTED (it survives this case only via an
    invest-diagnostic exemption)."""
    assert _demoted_at(_history(), n=1)["hooking"] == \
        PIN["n1_unsafe"]["S_demotes_at"]
    assert 11 in _forbidden(_history(), n=1)


def test_n3_is_too_lax():
    """N=3 (clusters-only): S only demotes at 6 and P at 12 — it forbids
    just rounds 7 and 10, letting four in-class deaths through."""
    assert _as_classes(_demoted_at(_history(), n=3, clause_b=False)) == \
        PIN["clusters_only_n3"]["demoted_at"]
    assert _forbidden(_history(), n=3, clause_b=False) == \
        PIN["clusters_only_n3"]["forbidden"]


def test_n4_is_vacuous():
    """N=4 never fires on this data (max distinct clusters per class is 3)
    — the whole attempt log comes back allowed."""
    assert _as_classes(_demoted_at(_history(), n=4, clause_b=False)) == \
        PIN["n4_vacuous"]["demoted_at"]
    assert _forbidden(_history(), n=4, clause_b=False) == []


def test_coarse_strategy_cluster_keying_is_wrong_shaped_not_vacuous():
    """Binding EXP-C constraint, pinned by EXECUTION: the demotion unit must
    be the FINE instrumentation approach class (the fixture's S/M/P/H shape,
    mapped 1:1 onto the ladder family pool) — a coarse macro-class key is
    WRONG-SHAPED, not vacuous: all 16 rounds share one macro-class marker,
    so a macro-keyed replay has no cross-family discrimination. Pinned
    behavior of that replay: it demotes the whole track at round 2 and its
    forbidden set covers every class INCLUDING the root-cause discovery
    round 11 — the same unsafety shape that rejects N=1."""
    assert set(MATRIX["approach_class_taxonomy"]) == {"S", "M", "P", "H"}
    assert {r["approach_class"] for r in ROUNDS} == {"S", "M", "P", "H"}
    # the structural precondition: one shared macro-class marker
    assert {r["macro_class"] for r in ROUNDS} == {"device-refresh-track"}
    # executed behavior of the macro-keyed replay (family := macro_class)
    macro_hist = [{"round": r["round"], "family": r["macro_class"],
                   "signature": r["signature"], "outcome": r["outcome"],
                   "change_kind": r["change_kind"]} for r in ROUNDS]
    state = ad.demotion_state(macro_hist)["device-refresh-track"]
    assert state["demoted_at"] == 2 and state["clause"] == "clause_b"
    assert len(state["clusters"]) == 10
    assert ad.forbidden_rounds(macro_hist) == \
        [3, 4, 5, 6, 7, 10, 11, 12, 14, 15]
    assert 11 in ad.forbidden_rounds(macro_hist), \
        "the macro key cannot spare the discovery round — why it is rejected"


# ---------- record ingestion: validation / normalization ----------

def test_normalize_signature_rejects_unknown_channels_and_fills_missing():
    ok, err = ad.normalize_signature({"process_state": "alive",
                                      "not_a_channel": 1})
    assert ok is None and "not_a_channel" in err
    ok, err = ad.normalize_signature({"process_state": "alive"})
    assert err is None and ok["process_state"] == "alive"
    for ch in ad.SIGNATURE_CHANNELS:
        assert ch in ok, "missing channels normalize to explicit nulls"
    ok, err = ad.normalize_signature(None)
    assert ok is None and err is None, "success rows carry no signature"


def test_normalize_attempt_shape_and_errors():
    rec, err = ad.normalize_attempt({"round": 1, "family": "hooking",
                                     "signature": _sig(),
                                     "outcome": "fail",
                                     "change_kind": "patch"})
    assert err is None
    assert rec["change_kind"] == "patch"
    assert rec["signature"]["rewritten_flag"] is False
    bad, err = ad.normalize_attempt({"round": 1, "family": "hooking",
                                     "signature": {"bogus": 1},
                                     "outcome": "fail",
                                     "change_kind": "none"})
    assert bad is None and "bogus" in err
    bad, err = ad.normalize_attempt({"round": 1, "family": "",
                                     "signature": None,
                                     "outcome": "fail",
                                     "change_kind": "none"})
    assert bad is None and "family" in err
    bad, err = ad.normalize_attempt({"round": 1, "family": "hooking",
                                     "signature": None,
                                     "outcome": "fail",
                                     "change_kind": "surgical"})
    assert bad is None and "change_kind" in err


def test_inclass_patch_on_demoted_family_is_a_walk_defect():
    """The defect set is as-of scoped and EXACT: only the genuinely
    post-demotion in-class patches defect (hooking demoted at 2 → its
    patches at 4, 5, 10). Pre-demotion patches (H r14) and the demoting
    attempts themselves (S r2 clause_b, H r15 clause_a) do NOT defect."""
    ladder = _ladder_with_history(_history())
    defects = tl.ladder_defects(ladder, "interception")
    assert _demotion_defects(defects) == [("hooking", 4), ("hooking", 5),
                                          ("hooking", 10)], defects


def test_pre_demotion_patches_and_the_demoting_attempt_do_not_defect():
    """Reviewer repro (r2 HIGH): H r14 is a pre-demotion patch (H demotes
    at 15 via clause_a) and S r2 is the clause_b demoting attempt — neither
    may defect, or a rule-compliant walk becomes un-settleable."""
    ladder = _ladder_with_history(_history())
    pairs = _demotion_defects(tl.ladder_defects(ladder, "interception"))
    assert ("proxy-interposition", 14) not in pairs
    assert ("proxy-interposition", 15) not in pairs
    assert ("hooking", 2) not in pairs, \
        "the demoting attempt itself is an allowed row"


def test_compliant_walk_stays_settleable_no_demotion_defects():
    """A rule-compliant walk (patch retries stopped at demotion, then a
    switch to another family + an invest) carries ZERO demotion defects —
    enforcement never blocks settlement of an obeying walk."""
    hist = _history()[:2] + [
        {"round": 3, "family": "repackaging", "outcome": "fail",
         "change_kind": "none", "signature": _sig(process_state="alive")},
        {"round": 4, "family": "repackaging", "outcome": "success",
         "change_kind": "invest", "signature": None},
    ]
    assert _demotion_defects(tl.ladder_defects(
        _ladder_with_history(hist), "interception")) == []


def test_post_demotion_inclass_patch_still_defects():
    """The minimal violation shape: demote via clause_b at 2, then a further
    in-class patch at 4 — exactly one defect, naming the demotion round."""
    tup = _sig(process_state="host gone")
    hist = [
        {"round": 1, "family": "hooking", "outcome": "fail",
         "change_kind": "none", "signature": tup},
        {"round": 2, "family": "hooking", "outcome": "fail",
         "change_kind": "patch", "signature": tup},  # clause_b demote
        {"round": 4, "family": "hooking", "outcome": "fail",
         "change_kind": "patch", "signature": tup},  # post-demotion patch
    ]
    ladder = _ladder_with_history(hist)
    assert _demotion_defects(tl.ladder_defects(ladder, "interception")) == \
        [("hooking", 4)]


# ---------- target_ladder integration ----------

def test_attempt_records_ingestion_validates_signature_tuples():
    ladder = _ladder_with_history(_history())
    ladder["attempts"][0]["signature"] = {"nope": 1}  # unknown channel
    records, defects = tl.attempt_records(ladder)
    assert any("nope" in d for d in defects), defects
    clean, defects = tl.attempt_records(_ladder_with_history(_history()))
    assert defects == []
    assert len(clean) == 16
    assert all(ad.normalize_signature(r["signature"])[1] is None
               for r in clean if r["signature"] is not None)


def test_rungs_carry_demotion_state():
    annotated = tl.rungs_with_demotion(_ladder_with_history(_history()))
    by_round = {a["round"]: a for a in annotated}
    assert by_round[2]["demotion"]["state"] == ad.DEMOTED
    assert by_round[2]["demotion"]["clause"] == "clause_b"
    assert by_round[1]["demotion"]["state"] == ad.ACTIVE
    assert by_round[11]["demotion"]["state"] == ad.DEMOTED
    assert by_round[11]["demotion"]["clause"] == "clause_a"


def test_demoted_class_is_skipped_in_generation():
    history = _history()[:3]  # hooking demotes (clause_b at 2); the others stay active
    ladder = _ladder_with_history(history)
    state = tl.demotions(ladder)
    assert state["hooking"]["state"] == ad.DEMOTED
    assert state["repackaging"]["state"] == ad.ACTIVE
    pool = tl.generation_pool(ladder, "interception")
    assert "hooking" not in pool, "a demoted class is skipped in generation"
    assert "repackaging" in pool and "ca-install" in pool \
        and "proxy-interposition" in pool


def test_generation_pool_fails_open_when_everything_is_demoted():
    fams = tl.OBSTACLE_CLASS_FAMILIES["interception"]
    history = []
    # N distinct clusters for EVERY family -> all demoted
    for i, fam in enumerate(fams):
        for k in range(2):
            history.append({"round": i * 10 + k, "family": fam,
                            "outcome": "fail", "change_kind": "none",
                            "signature": _sig(
                                process_state=f"{fam}-failure-{k}")})
    pool = tl.generation_pool(_ladder_with_history(history), "interception")
    assert pool == tl.FAMILY_FALLBACK, \
        "an emptied pool falls back to the generic axis — never unwalkable"


def test_generation_pool_untouched_without_demotions():
    ladder = _ladder_with_history(_history()[:1])  # one attempt, no demotion
    assert tl.generation_pool(ladder, "interception") == \
        tl.family_ladder_for("interception")


def test_legacy_ladder_without_signature_records_stays_valid():
    """Pre-D1 artifacts (no signature / change_kind fields) never demote and
    never gain defects — the demotion replay is a no-op on them."""
    ladder = {
        "obstacle_class": "interception",
        "attempts": [
            {"level": "T1", "family": "hooking", "action": "a",
             "outcome": "blocked"},
            {"level": "T2", "family": "repackaging", "action": "b",
             "outcome": "blocked"},
            {"level": "T3", "family": "ca-install", "action": "c",
             "outcome": "blocked"},
        ],
        "inventory": [{"family": "hooking", "tried": "x",
                       "failed_because": "y"}],
    }
    assert tl.ladder_defects(ladder, "interception") == []
    state = tl.demotions(ladder)
    assert state and all(e["state"] == ad.ACTIVE
                         and e["demoted_at"] is None
                         and not e["forbidden"]
                         for e in state.values())


# ---------- emission: approach_demoted through kunglao_log ----------

def test_settlement_gate_emits_approach_demoted(tmp_path):
    ws = _ws_with_ladder(tmp_path, _ladder_with_history(_history()))
    blocker = tl.settlement_blocker(ws, "C-302")
    rows = _rows(ws, "target_ladder", "approach_demoted")
    assert rows, "the demotion decision must emit through kunglao_log"
    detail = json.loads(rows[0]["detail"])
    families = {d["family"] for d in detail["demoted"]}
    assert families == {"hooking", "repackaging", "ca-install",
                        "proxy-interposition"}
    assert any(d["family"] == "hooking" and d["clause"] == "clause_b"
               and d["demoted_at"] == 2 for d in detail["demoted"])
    # demotion is enforcement, not settlement refusal by itself: the gate
    # names whatever faces remain (here: the post-demotion in-class patches
    # are walk defects, so the gate blocks with the NAMED reason)
    assert blocker is None or "TARGET LADDER GATE" in blocker


def test_no_approach_demoted_row_without_signature_records(tmp_path):
    ws = _ws_with_ladder(tmp_path, {
        "obstacle_class": "interception",
        "attempts": [{"level": "T1", "family": "hooking", "action": "a",
                      "outcome": "blocked"}],
        "inventory": [],
    })
    tl.settlement_blocker(ws, "C-302")
    assert _rows(ws, "target_ladder", "approach_demoted") == []


# ---------- event vocabulary registration ----------

def test_approach_demoted_word_is_registered_sorted():
    import event_taxonomy as et
    words = et.EMIT_ACTIONS
    assert "approach_demoted" in words
    assert words == sorted(words), "the word table stays sorted"
    assert len(words) == len(set(words)), "the word table stays unique"


def test_pool_cli_face_prints_the_generation_pool(tmp_path, capsys,
                                                  monkeypatch):
    ws = _ws_with_ladder(tmp_path, _ladder_with_history(_history()[:3]))
    monkeypatch.setattr(sys, "argv",
                        ["target_ladder.py", str(ws), "--pool", "C-302"])
    assert tl.main() == 0
    out = capsys.readouterr().out
    pool_line = next(l for l in out.splitlines()
                     if l.startswith("generation pool"))
    assert "hooking" not in pool_line, \
        "demoted family skipped in the printed pool"
    assert "repackaging" in pool_line
    assert "hooking" in out, "the skipped family stays named (visible)"
