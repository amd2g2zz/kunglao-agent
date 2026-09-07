# -*- coding: utf-8 -*-
"""tests/test_value_rebuild_107.py — #107 demolition guard (RED-first).

Owner ruling (issue #107, "探索和价值网络需要完全重构，之前的不要了"):
the weighted VoI-proxy ranker and the explore/exploit dual path are
DISCARDED, not adapted. The rebuild lands one ranker:

    action value = sampled_beta(case posteriors) + LAMBDA_DH · ΔH_PQ
    ranked per Thompson sample, stable tie-break claim_id

This suite is the mechanical half of the acceptance criteria: the deleted
symbols are greppable NOWHERE under scripts/ or hooks/ (mission_ledger.py
keeps its V_m data face — only its consumption died), and the surviving
Action/dataclass surface carries the new semantics. Historical mentions in
docs/, specs/, openspec/ archives are out of scope (records, not code).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# ---------- raw-source sweep helpers ----------

_BANNED_EXACT = (
    "EXPLORE_THRESHOLD",       # the count-cliff gate constant (#101 face too)
    "explore_gate",            # the deleted module + its function
    "explore_mode",            # the deleted DecideOutput field
    "_cheapness_order",        # the deleted DECIDE explore ranker
    "explore-cheapness",       # the deleted #101 authority tag
    "gap_bucket",              # the deleted #823-P3 lexicographic sort head
    "NOVELTY_BASE",            # the deleted novelty saturation constant
    "_explore_cheapness_rank",  # the deleted hook-side explore rank mirror
)

_PY_TREES = ("scripts", "hooks")


def _py_sources():
    for tree in _PY_TREES:
        for p in sorted((ROOT / tree).rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            yield p


def test_banned_symbols_greppable_nowhere_in_scripts_and_hooks():
    """Issue acceptance: the deleted ranking layer leaves ZERO residue in
    scripts/ and hooks/. mission_ledger.py stays (V_m data face) — its
    consumption by the ranker is what died, so its source must not name the
    dead sort key either."""
    hits: list[str] = []
    for p in _py_sources():
        text = p.read_text(encoding="utf-8", errors="replace")
        for needle in _BANNED_EXACT:
            if needle in text:
                hits.append(f"{p.relative_to(ROOT)}: {needle}")
    assert hits == [], f"deleted ranking-layer residue left behind: {hits}"


def test_explore_gate_module_deleted():
    """The whole module was the threshold cliff — deleted, not stubbed."""
    assert not (SCRIPTS / "explore_gate.py").exists()


def test_no_dangling_explore_gate_imports():
    """No consumer still imports the deleted module."""
    hits = [str(p.relative_to(ROOT)) for p in _py_sources()
            if "import explore_gate" in p.read_text(encoding="utf-8",
                                                    errors="replace")]
    assert hits == [], f"dangling explore_gate imports: {hits}"


# ---------- surviving module surface ----------


def test_priority_ratio_module_surface_is_thompson():
    """The ranker module carries the rebuilt semantics: no weighted-era
    constants, the Thompson DOF constant present, and the public API shape
    priority_ratio(claims, deps, evidence[, rng]) preserved."""
    import priority_ratio as pr

    for dead in ("WEIGHTS", "NOVELTY_BASE", "CAPABILITY_BONUS", "cheapness",
                 "TIER_COST"):
        assert not hasattr(pr, dead), \
            f"priority_ratio.{dead} survived the #107 demolition"
    assert hasattr(pr, "LAMBDA_DH"), "the Thompson rebuild must pin LAMBDA_DH"
    assert pr.LAMBDA_DH == 0.25, "#107 ruling: LAMBDA_DH = 0.25 (the only DOF)"
    assert hasattr(pr, "FLIP_POTENTIAL_BASE")
    assert pr.FLIP_POTENTIAL_BASE == 0.5
    assert hasattr(pr, "FLIP_POTENTIAL_FALLBACK")
    assert pr.FLIP_POTENTIAL_FALLBACK == 0.3


def test_action_shape_rebuilt():
    """Action keeps the dispatch-facing fields + the new diagnostic feeds;
    the weighted-era term fields are gone."""
    import priority_ratio as pr

    fields = pr.Action.__dataclass_fields__
    for keep in ("claim_id", "action", "score", "skill", "tier", "attempts",
                 "cost", "weight", "feeds"):
        assert keep in fields, f"Action.{keep} missing after rebuild"
    for dead in ("leverage", "discriminator", "novelty", "gap_bucket"):
        assert dead not in fields, \
            f"Action.{dead} is weighted-era surface — must be deleted"


def test_evidence_view_feeds_slimmed():
    """EvidenceView keeps the externally consumed record faces (capability
    cards, terminal facts, #759 worth weights) and drops the weighted-era
    scoring feeds (mission dynamics, difficulty multiplier, novelty proxies,
    cost-inflation prior)."""
    import priority_ratio as pr

    fields = pr.EvidenceView.__dataclass_fields__
    for keep in ("terminal_fact_claims", "verified_fact_count",
                 "fact_count_by_category", "validated_capabilities",
                 "identified_obstacles", "value_class_weights",
                 "value_claim_overrides", "ws"):
        assert keep in fields, f"EvidenceView.{keep} missing after rebuild"
    for dead in ("mission_gap", "mission_active", "mission_v_norm",
                 "mission_d_slope_norm", "difficulty_score", "difficulty_tier",
                 "strategy_failures", "claim_strategy",
                 "claim_dispatch_repeats", "prior_p_complete"):
        assert dead not in fields, \
            f"EvidenceView.{dead} fed the deleted formula — must be deleted"


def test_ranker_signature_rng_injection():
    """priority_ratio(claims, deps, evidence, rng=None) — deterministic by
    default (Random(0)), Thompson via injected rng."""
    import inspect
    import priority_ratio as pr

    sig = inspect.signature(pr.priority_ratio)
    assert list(sig.parameters) == ["claims", "deps", "evidence", "rng"]
    assert sig.parameters["rng"].default is None


def test_smoke_rank_is_deterministic_under_default_rng():
    """Same inputs -> byte-identical to_dict() output twice (seeded rng,
    no hidden state)."""
    import priority_ratio as pr

    claims = [{"id": "C-1", "status": "OPEN", "statement": "c2 config",
               "evidence_tier_attempted": 0, "promotion_attempts": 0},
              {"id": "C-2", "status": "OPEN", "statement": "family vidar",
               "evidence_tier_attempted": 1, "promotion_attempts": 0}]
    deps = {"depends_on": {}, "competitor_groups": {}}
    ev = pr.EvidenceView()
    a = [x.to_dict() for x in pr.priority_ratio(claims, deps, ev)]
    b = [x.to_dict() for x in pr.priority_ratio(claims, deps, ev)]
    assert a == b and len(a) == 2


@pytest.mark.parametrize("seed", [0, 7, 12345])
def test_smoke_rank_is_seed_sensitive(seed):
    """Different tick seeds may reorder Thompson samples (intrinsic
    exploration exists — no threshold gate); each seed is self-consistent."""
    import random

    import priority_ratio as pr

    claims = [{"id": f"C-{i}", "status": "OPEN", "statement": "work",
               "evidence_tier_attempted": 0, "promotion_attempts": 0}
              for i in range(1, 7)]
    deps = {"depends_on": {}, "competitor_groups": {}}
    ev = pr.EvidenceView()
    once = [a.to_dict() for a in pr.priority_ratio(claims, deps, ev,
                                                   rng=random.Random(seed))]
    twice = [a.to_dict() for a in pr.priority_ratio(claims, deps, ev,
                                                    rng=random.Random(seed))]
    assert once == twice
    assert sorted(a["claim_id"] for a in once) == [c["id"] for c in claims]
