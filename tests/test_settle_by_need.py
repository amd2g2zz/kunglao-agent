# -*- coding: utf-8 -*-
"""Evidence settles by NEED (scripts/settle_by_need.py, #248 post2 piece
3): acceptance-side ``replay-observation`` evidence settles only
input-contract / param-sufficiency claims; generation-side propositions
admit ``reproduction`` evidence only; a replay observation cited by an
algorithm-class claim is re-routed to the input-contract claim and the
algorithm claim stays open; unknown classes fail closed."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import settle_by_need  # noqa: E402

ALGO_CLAIM = {"id": "C-algo", "answers_question": "Q1"}
CONTRACT_CLAIM = {"id": "C-contract", "answers_question": "Q2"}
QUESTIONS = {"Q1": "model_selection", "Q2": "yes_no_with_evidence"}
REPLAY_OBS = {"class": "replay-observation",
              "detail": "replay succeeded; endpoint returned 200"}
REPRO_EVIDENCE = {"class": "reproduction", "artifact": "evidence/replay-C-1.json"}


def test_replay_observation_does_not_settle_algorithm_claim():
    outcome = settle_by_need.settle_attempt(
        ALGO_CLAIM, REPLAY_OBS, QUESTIONS)
    assert outcome["settled"] is False
    assert outcome["claim_stays_open"] is True


def test_replay_observation_is_rerouted_to_input_contract():
    outcome = settle_by_need.settle_attempt(
        ALGO_CLAIM, REPLAY_OBS, QUESTIONS)
    assert outcome["reroute_to"] == "input-contract"


def test_reproduction_evidence_settles_algorithm_claim():
    outcome = settle_by_need.settle_attempt(
        ALGO_CLAIM, REPRO_EVIDENCE, QUESTIONS)
    assert outcome["settled"] is True
    assert outcome["claim_stays_open"] is False
    assert outcome["reroute_to"] is None


def test_replay_observation_settles_input_contract_claim():
    outcome = settle_by_need.settle_attempt(
        CONTRACT_CLAIM, REPLAY_OBS, QUESTIONS)
    assert outcome["settled"] is True
    assert outcome["reroute_to"] is None


def test_untyped_need_fails_closed():
    """A claim whose question has no need in the map gets no admissibility
    decision — nothing settles, nothing re-routes."""
    outcome = settle_by_need.settle_attempt(
        {"id": "C-x", "answers_question": "Q-missing"}, REPLAY_OBS,
        QUESTIONS)
    assert outcome["settled"] is False
    assert outcome["claim_stays_open"] is True
    assert outcome["reroute_to"] is None


def test_unknown_evidence_class_fails_closed():
    outcome = settle_by_need.settle_attempt(
        CONTRACT_CLAIM, {"class": "vibes"}, QUESTIONS)
    assert outcome["settled"] is False
    assert outcome["claim_stays_open"] is True
    assert outcome["reroute_to"] is None
