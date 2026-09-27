# -*- coding: utf-8 -*-
"""tests/test_action_space_12.py — the action registry + the
byte-equivalence pin.

Scope ruling (2026-09-20 comment on the action-space issue):
"vocabulary + operator metadata first; composition can follow" — the minimal slice is

  1. the action registry (operator / orchestration / strategic vocabulary,
     each entry carrying cost / precondition / proof-power / consumer /
     a Delta-value estimator SIGNATURE stub — nothing implemented);
  2. the strategic layer as ROUTE-LEVEL metadata: FIGHT / BYPASS / INVEST.
     BYPASS reuses the negative-exit machinery (infeasible_proposal
     DEFERRED + wake_condition) — referenced, never rebuilt;
  3. priority_ratio's ``action`` field becomes registry-sourced
     (the claim-category table moves verbatim into the registry) with
     BYTE-EQUIVALENT rank output under default weights — the zero-behavior-
     change baseline is pinned by a frozen capture;
  4. value-weights.yaml grows the per-action weights SECTION (``actions:``)
     with defaults that reproduce current behavior (identity 1.0).

NO argmax controller, NO BYPASS/INVEST execution semantics (the v0.1.7
card), NO estimator implementation (the v0.2 controller).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import action_space as aspace  # noqa: E402
import priority_ratio as pr  # noqa: E402


# ---------- 1. registry completeness ----------

EXPECTED_OPERATORS = {"observe", "trace", "hook", "emulate", "derive",
                      "verify", "search", "ask", "plan_segment"}
EXPECTED_ORCHESTRATION = {"dispatch", "verify", "deepen", "replan",
                          "osint", "expand"}
EXPECTED_STRATEGIC = {"fight", "bypass", "invest"}


def test_registry_holds_exactly_the_issue_vocabulary():
    def _bare(level):
        return {s.name.split(".", 1)[1]
                for s in aspace.actions_of(level)}
    assert _bare(aspace.OPERATOR) == EXPECTED_OPERATORS
    assert _bare(aspace.ORCHESTRATION) == EXPECTED_ORCHESTRATION
    assert _bare(aspace.STRATEGIC) == EXPECTED_STRATEGIC
    # keys are level-namespaced: both vocabularies carry a verify
    assert "operator.verify" in aspace.ACTIONS
    assert "orchestration.verify" in aspace.ACTIONS


@pytest.mark.parametrize("name", sorted(aspace.ACTIONS))
def test_every_action_carries_full_metadata(name):
    spec = aspace.ACTIONS[name]
    # cost constant: strictly positive number
    assert isinstance(spec.cost, (int, float)) and spec.cost > 0
    # precondition: non-empty statement
    assert isinstance(spec.precondition, str) and spec.precondition.strip()
    # proof-power metadata: non-empty statement
    assert isinstance(spec.proof_power, str) and spec.proof_power.strip()
    # consumer field: non-empty statement
    assert isinstance(spec.consumer, str) and spec.consumer.strip()
    # Δ-value estimator SIGNATURE stub: declared, documented, NOT implemented
    est = spec.delta_estimator
    assert isinstance(est, aspace.DeltaEstimator)
    assert est.name.strip() and est.signature.strip()
    assert est.implemented is False, (
        "v0.1.6 lands the signature only — an implemented estimator is a "
        "v0.2 controller feature (#12 scope annotation)")
    # the estimator reads the signal stream, not the orchestrator's memory
    assert any("signals.jsonl" in src for src in est.inputs)


def test_estimator_signature_shape():
    """The documented estimator signature: per-round ΔV from the signal
    stream + persisted history (the orchestrator consumes the history,
    not the raw signal)."""
    sig = aspace.DeltaEstimator.SIGNATURE
    assert "estimate_delta_v" in sig
    assert "signals" in sig and "history" in sig


# ---------- 2. strategic layer ----------

def test_bypass_references_the_deferred_machinery():
    """BYPASS = defer: DEFERRED + wake_condition via the negative-exit
    machinery (scripts/infeasible_proposal.py file_proposal/wake). The
    registry REFERENCES it; it does NOT build new semantics."""
    spec = aspace.ACTIONS["strategic.bypass"]
    text = " ".join([spec.precondition, spec.proof_power, spec.consumer]
                    + list(spec.references))
    assert "DEFERRED" in text
    assert "wake_condition" in text
    assert "infeasible_proposal" in text


def test_invest_references_tool_creation():
    """INVEST = build capability first (rule-14 tool creation), then
    return — referenced as precondition metadata."""
    spec = aspace.ACTIONS["strategic.invest"]
    text = " ".join([spec.precondition, spec.proof_power, spec.consumer]
                    + list(spec.references))
    assert "tools/_INDEX" in text or "rule 14" in text.lower()


def test_fight_is_push_through():
    spec = aspace.ACTIONS["strategic.fight"]
    text = " ".join([spec.precondition, spec.proof_power, spec.consumer])
    assert "obstacle" in text.lower()


# ---------- 3. byte-equivalence: the zero-behavior-change baseline ----------

def _fixture_claims():
    return [
        {"id": "C-1", "status": "OPEN",
         "statement": "extract the c2 配置 endpoints",
         "answers_question": "q1", "evidence_tier_attempted": 0,
         "promotion_attempts": 0},
        {"id": "C-2", "status": "OPEN",
         "statement": "family vidar 归属 attribution",
         "answers_question": "q2", "evidence_tier_attempted": 1,
         "promotion_attempts": 1, "value_class": "c2_extract"},
        {"id": "C-3", "status": "OPEN",
         "statement": "persistence autorun 注册表 key",
         "answers_question": "q3", "evidence_tier_attempted": 2,
         "promotion_attempts": 0},
        {"id": "C-4", "status": "OPEN", "statement": "plain open question",
         "answers_question": "q4", "evidence_tier_attempted": 0,
         "promotion_attempts": 2},
        {"id": "C-5", "status": "OPEN", "statement": "blocked by parent",
         "answers_question": "q5", "depends_on": ["C-9"],
         "evidence_tier_attempted": 0, "promotion_attempts": 0},
        {"id": "C-6", "status": "PROVEN", "statement": "terminal already",
         "evidence_tier_attempted": 0, "promotion_attempts": 0},
        {"id": "C-7", "status": "OPEN", "statement": "exhausted",
         "evidence_tier_attempted": 0, "promotion_attempts": 3},
    ]


_FIXTURE_DEPS = {"depends_on": {}, "competitor_groups": {}}

# Frozen PRE-CHANGE capture (scripts/priority_ratio.py at base 8fcb264,
# rng-seeded + default-rng faces). Any diff = behavior change = REJECT.
_FROZEN = {
    "seed42": [
        {"claim_id": "C-2", "action": "family_attribution", "score": 0.682,
         "skill": None, "weight": 1.0},
        {"claim_id": "C-3", "action": "persistence", "score": 0.441,
         "skill": None, "weight": 1.0},
        {"claim_id": "C-1", "action": "c2_config_extract", "score": 0.329,
         "skill": None, "weight": 1.0},
        {"claim_id": "C-4", "action": "evidence_collection", "score": 0.328,
         "skill": None, "weight": 1.0},
    ],
    "default": [
        {"claim_id": "C-4", "action": "evidence_collection", "score": 0.924,
         "skill": None, "weight": 1.0},
        {"claim_id": "C-3", "action": "persistence", "score": 0.338,
         "skill": None, "weight": 1.0},
        {"claim_id": "C-1", "action": "c2_config_extract", "score": 0.21,
         "skill": None, "weight": 1.0},
        {"claim_id": "C-2", "action": "family_attribution", "score": 0.016,
         "skill": None, "weight": 1.0},
    ],
}


def test_rank_output_byte_equivalent_to_pre_change_baseline():
    import random
    claims = _fixture_claims()
    ev = pr.EvidenceView()
    seeded = [x.to_dict() for x in pr.priority_ratio(
        claims, _FIXTURE_DEPS, ev, rng=random.Random(42))]
    default = [x.to_dict() for x in pr.priority_ratio(claims, _FIXTURE_DEPS, ev)]
    assert seeded == _FROZEN["seed42"]
    assert default == _FROZEN["default"]


def test_action_field_is_registry_sourced():
    """The claim-category table lives in the registry; priority_ratio
    consumes it (the field is registry-sourced, not a local literal)."""
    assert pr.DEFAULT_ACTION == aspace.DEFAULT_CLAIM_ACTION
    assert pr.DEFAULT_ACTION == "evidence_collection"
    # the keyword table is THE SAME OBJECT (verbatim move, no drift)
    assert pr._KEYWORD_MAP == aspace.CLAIM_ACTION_KEYWORDS
    # every producible label is a registered claim category
    for _, cat in aspace.CLAIM_ACTION_KEYWORDS:
        assert cat in aspace.CLAIM_CATEGORIES
    assert aspace.DEFAULT_CLAIM_ACTION in aspace.CLAIM_CATEGORIES


def test_classify_action_delegation_unchanged():
    c_hit = {"statement": "reflective createremotethread 注入", "answers_question": ""}
    c_def = {"statement": "nothing special", "answers_question": ""}
    assert pr.classify_action(c_hit) == "injection"
    assert pr.classify_action(c_def) == "evidence_collection"
    assert aspace.classify_claim_action(c_hit) == "injection"


# ---------- 4. value-weights.yaml per-action weights section ----------

def test_load_action_weights_parses_actions_section(tmp_path):
    ws = tmp_path
    (ws / "runs").mkdir()
    (ws / "runs" / "value-weights.yaml").write_text(
        "claim_classes:\n  c2_extract: 2.0\n"
        "actions:\n  operator.derive: 1.5\n  strategic.fight: \"0.5\"\n"
        "  strategic.bypass: not-a-number\n  bad: -2\n",
        encoding="utf-8")
    weights = aspace.load_action_weights(ws)
    assert weights == {"operator.derive": 1.5, "strategic.fight": 0.5}


def test_load_action_weights_absent_is_empty(tmp_path):
    assert aspace.load_action_weights(tmp_path) == {}
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "value-weights.yaml").write_text(
        "claim_classes:\n  rce: 3.0\n", encoding="utf-8")
    assert aspace.load_action_weights(tmp_path) == {}


def test_default_action_weights_reproduce_current_behavior():
    """Defaults are identity (1.0) for every registered action: the
    per-action section is DATA in this slice — the ranker does not consume
    it, so default weights reproduce today's ranking exactly."""
    for name in aspace.ACTIONS:
        assert aspace.DEFAULT_ACTION_WEIGHTS[name] == 1.0


def test_actions_section_does_not_perturb_the_rank(tmp_path):
    """A weights file carrying an actions: section ranks identically to
    the same file without it (composition is v0.2; the section lands as
    data)."""
    import random
    base = "claim_classes:\n  c2_extract: 2.0\n"
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "value-weights.yaml").write_text(
        base + "actions:\n  operator.derive: 1.5\n", encoding="utf-8")
    a = [x.to_dict() for x in pr.priority_ratio(
        _fixture_claims(), _FIXTURE_DEPS, pr.EvidenceView(ws=tmp_path),
        rng=random.Random(42))]
    (tmp_path / "runs" / "value-weights.yaml").write_text(base, encoding="utf-8")
    b = [x.to_dict() for x in pr.priority_ratio(
        _fixture_claims(), _FIXTURE_DEPS, pr.EvidenceView(ws=tmp_path),
        rng=random.Random(42))]
    assert a == b
